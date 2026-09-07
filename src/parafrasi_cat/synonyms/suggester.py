"""Alternatives clicables d'un text: què pot triar qui edita, a cada fragment.

Aquest mòdul no reescriu res. Recorre un text, mira quins fragments tenen una
alternativa que el projecte conegui i la deixa a punt perquè una persona en
triï una. Les fonts són tres, totes locals:

- **connectors equivalents**: les classes d'equivalència de les regles actives,
  que és exactament el que el motor sap intercanviar tot sol;
- **diccionaris terminològics**: una forma a evitar porta a la preferida, i una
  forma conservada porta a la resta de formes conservades del mateix terme;
- **diccionari de sinònims** (component opcional), amb el sentit de cada grup.

Quatre regles fan que una proposta sigui segura de clicar:

1. **Res que trepitgi un fragment protegit.** Un nom, una data, una xifra o un
   terme protegit no ofereix cap alternativa.
2. **Res que canviï el que el text afirma.** Una negació, una atenuació o un
   marcador de certesa («no», «potser», «sens dubte») no té sinònims aquí:
   canviar-los no és canviar la forma, és canviar el contingut, i els
   validadors ho rebutjarien igualment.
3. **Concordança o res.** Una proposta del diccionari de sinònims s'ofereix
   flexionada com la forma que substitueix («sabem» → «coneixem», «cases» →
   «llars»). Si la morfologia no pot generar la forma que caldria —perquè el
   forma és desconeguda, per exemple— la proposta **no s'ofereix**. Amb parser
   fiable, els grups nominals simples es canvien sencers, ajustant determinants
   i adjectius al gènere del nou nom i conservant el nombre.
   Val més una llista curta que una llista que trenca el text.
4. **Cap antònim.** No són al recurs: l'importador no els hi posa.

El sentit no s'endevina mai. «Peça» és una part d'un conjunt i també una obra
musical; «cavall» és un animal i també una biga. Les propostes s'agrupen per
sentit, amb la glossa del diccionari, i qui edita tria el grup que volia dir.

Quan hi ha analitzador sintàctic i se'n fia, la categoria que dona **en aquesta
frase** decideix quins sentits s'ofereixen: «fan» com a nom (admirador) no té
res a veure amb «fan» com a verb, i oferir-lo seria soroll. Sense parser
—o amb una frase de la qual no se'n fia— s'ofereixen tots els sentits, perquè
llavors qui tria és l'única font de desambiguació que hi ha.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from parafrasi_cat.analyzer.analysis import Analyzer
from parafrasi_cat.analyzer.lexicon import normalize_form
from parafrasi_cat.analyzer.tokens import Token, TokenKind
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.text import match_casing
from parafrasi_cat.dictionaries.dictionary import DictionarySet, FormStatus, normalize_term
from parafrasi_cat.morphology.provider import MorphologyProvider, inflect_like
from parafrasi_cat.protected.spans import ProtectedSpan
from parafrasi_cat.synonyms.thesaurus import CatalanThesaurus, SynonymGroup, normalize
from parafrasi_cat.syntax.analysis import SentenceSyntax, SyntaxProvider
from parafrasi_cat.synonyms.agreement import nominal_span, replacement

MAX_PHRASE_TOKENS = 4
"""Paraules màximes d'un fragment clicable (les locucions llargues no s'hi busquen)."""

MAX_SENSES = 4
"""Sentits que s'ofereixen d'un fragment: prou per triar, no tants com per perdre-s'hi."""

MAX_OPTIONS_PER_SENSE = 8
"""Propostes de cada sentit: una llista que es pugui llegir d'un cop."""

#: Categories que no es flexionen: la forma del diccionari ja serveix tal qual.
INVARIABLE = frozenset({"adv", "loc", "conj", "adp", "intj"})

#: Categories del parser que no reben sinònims: canviar-les no és triar una
#: altra paraula, és canviar l'estructura de la frase (i d'això ja se n'ocupen
#: les redaccions alternatives) o tocar un nom propi o una xifra.
FUNCTIONAL_POS = frozenset({"DET", "PRON", "AUX", "ADP", "PART", "NUM", "PROPN", "PUNCT", "SYM"})

#: Categoria del parser (universal) → categoria del diccionari de sinònims.
PARSER_POS: Mapping[str, str] = {
    "NOUN": "noun",
    "VERB": "verb",
    "ADJ": "adj",
    "ADV": "adv",
    "CCONJ": "conj",
    "SCONJ": "conj",
    "INTJ": "intj",
}

SOURCE_CONNECTOR = "connector"
SOURCE_DICTIONARY = "diccionari"
SOURCE_THESAURUS = "sinònims"

_SOURCE_LABELS: Mapping[str, str] = {
    SOURCE_CONNECTOR: "connector equivalent",
    SOURCE_DICTIONARY: "diccionari del projecte",
    SOURCE_THESAURUS: "diccionari de sinònims",
}

#: Ordre dels grups: primer el que el motor sap fer sol, després el diccionari
#: obert. Dins de cada font, els sentits que encaixen amb la categoria de la
#: frase van al davant.
_SOURCE_ORDER: Mapping[str, int] = {
    SOURCE_CONNECTOR: 0,
    SOURCE_DICTIONARY: 1,
    SOURCE_THESAURUS: 2,
}


@dataclass(frozen=True, slots=True)
class SynonymOption:
    """Una alternativa a punt d'inserir: el text ja flexionat i d'on surt."""

    text: str
    """Text que substitueix el fragment, amb la caixa de l'original."""
    lemma: str
    """Forma tal com surt al diccionari, per si difereix de la flexionada."""
    source: str
    register: str = ""
    """``col·loquial``, ``antic``, ``dialectal``… o buit si és neutra."""
    note: str = ""

    @property
    def source_label(self) -> str:
        return _SOURCE_LABELS.get(self.source, self.source)

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "lemma": self.lemma,
            "source": self.source,
            "source_label": self.source_label,
            "register": self.register,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class OptionGroup:
    """Les alternatives d'un sentit concret, amb el nom del sentit."""

    label: str
    source: str
    options: tuple[SynonymOption, ...]
    expected: bool = False
    """Cert si la categoria d'aquest sentit és la que el parser dona a la frase."""

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "source": self.source,
            "source_label": _SOURCE_LABELS.get(self.source, self.source),
            "expected": self.expected,
            "options": [option.to_dict() for option in self.options],
        }


@dataclass(frozen=True, slots=True)
class TokenOptions:
    """Un fragment del text amb les alternatives que s'hi poden triar."""

    start: int
    end: int
    text: str
    groups: tuple[OptionGroup, ...] = field(default_factory=tuple)

    @property
    def options(self) -> tuple[SynonymOption, ...]:
        return tuple(option for group in self.groups for option in group.options)

    @property
    def clickable(self) -> bool:
        return bool(self.groups)

    def to_dict(self) -> dict[str, object]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "n_options": len(self.options),
            "groups": [group.to_dict() for group in self.groups],
        }


@dataclass(frozen=True, slots=True)
class ConnectorAlternative:
    """Una forma de connector amb la classe d'equivalència d'on surt."""

    form: str
    class_id: str
    function: str = ""


def connector_index(rules: Iterable[object]) -> dict[str, tuple[ConnectorAlternative, ...]]:
    """Per a cada connector, les formes de la seva classe que el poden substituir.

    Es llegeixen les classes de les regles actives. Si una classe declara
    ``targets``, les substitucions van només cap allà: és el mateix criteri que
    fa servir la regla, de manera que la interfície no ofereix mai res que el
    motor no pogués escriure sol.
    """
    index: dict[str, dict[str, ConnectorAlternative]] = {}
    for rule in rules:
        classes = getattr(rule, "classes", None)
        if not classes:
            continue
        for connector_class in classes:
            targets = connector_class.targets or connector_class.members
            for member in connector_class.members:
                key = normalize(member.form)
                bucket = index.setdefault(key, {})
                for target in targets:
                    form = target.form.strip()
                    if normalize(form) == key:
                        continue
                    bucket.setdefault(
                        normalize(form),
                        ConnectorAlternative(
                            form, connector_class.class_id, connector_class.function
                        ),
                    )
    return {form: tuple(bucket.values()) for form, bucket in index.items() if bucket}


class SynonymSuggester:
    """Recorre un text i diu quins fragments es poden canviar i per quines formes."""

    def __init__(
        self,
        analyzer: Analyzer,
        *,
        morphology: MorphologyProvider | None = None,
        thesaurus: CatalanThesaurus | None = None,
        connectors: Mapping[str, tuple[ConnectorAlternative, ...]] | None = None,
        dictionary: DictionarySet | None = None,
        syntax: SyntaxProvider | None = None,
        guarded: Iterable[str] = (),
    ) -> None:
        self._analyzer = analyzer
        self._morphology = morphology
        self._thesaurus = thesaurus
        self._connectors = dict(connectors or {})
        self._dictionary = dictionary
        self._syntax = syntax
        self._guarded = frozenset(normalize_form(form) for form in guarded if form.strip())
        self._cache: dict[str, tuple[TokenOptions, ...]] = {}

    @property
    def thesaurus(self) -> CatalanThesaurus | None:
        return self._thesaurus

    @property
    def available(self) -> bool:
        """Cert si hi ha alguna font d'alternatives."""
        return bool(self._connectors) or self._thesaurus is not None or self._dictionary is not None

    def describe(self) -> str:
        parts: list[str] = []
        if self._connectors:
            parts.append(f"{len(self._connectors)} connectors equivalents")
        if self._dictionary is not None:
            parts.append("diccionaris del projecte")
        parts.append(
            self._thesaurus.describe()
            if self._thesaurus is not None
            else "sense diccionari de sinònims"
        )
        return "; ".join(parts)

    # -- recorregut --------------------------------------------------------------------------

    def options(
        self, text: str, protected: Sequence[ProtectedSpan] = ()
    ) -> tuple[TokenOptions, ...]:
        """Fragments del text que tenen alternativa, en ordre d'aparició."""
        if not text.strip() or not self.available:
            return ()
        if not protected:
            cached = self._cache.get(text)
            if cached is not None:
                return cached
        tokens = self._words(text)
        parsed = self._parse(text)
        found: list[TokenOptions] = []
        position = 0
        while position < len(tokens):
            entry = self._at(text, tokens, position, protected, parsed)
            if entry is None:
                position += 1
                continue
            options, length = entry
            found.append(options)
            position += length
        if isinstance(parsed, SentenceSyntax) and self._morphology is not None:
            found = self._nominal_groups(text, parsed, protected, found)
        result = tuple(found)
        if not protected:
            self._cache[text] = result
        return result

    def _nominal_groups(
        self, text: str, parsed: SentenceSyntax,
        protected: Sequence[ProtectedSpan], found: list[TokenOptions],
    ) -> list[TokenOptions]:
        """El nom i la concordança formen un únic fragment editable/desfés."""
        assert self._morphology is not None
        for noun in parsed.tokens:
            if noun.pos != "NOUN":
                continue
            span = nominal_span(parsed, noun)
            # Never leave an isolated noun replacement bypassing agreement.
            found = [t for t in found if not (t.start <= noun.start < t.end)]
            if span is None:
                continue
            start, end = span
            if any(p.span.overlaps(Span(start, end)) for p in protected):
                continue
            if any(normalize_form(t.text) in self._guarded
                   for t in parsed.tokens_in(start, end)):
                continue
            groups = self._from_dictionary(noun.text)
            if self._thesaurus is not None:
                for group in self._groups_for(noun.text, noun.lemma):
                    if group.pos != "noun":
                        continue
                    groups.append(OptionGroup(group.label or "sinònims", SOURCE_THESAURUS,
                        tuple(SynonymOption(m.form, m.form, SOURCE_THESAURUS,
                            m.register, "equivalència més fluixa" if m.secondary else "")
                            for m in group.members), True))
            adjusted = []
            for group in groups:
                options = []
                seen = set()
                for option in group.options:
                    value = replacement(parsed, noun, option.lemma, self._morphology)
                    if value is None or normalize(value) == normalize(text[start:end]) or value in seen:
                        continue
                    seen.add(value)
                    options.append(replace(option, text=value))
                if options:
                    adjusted.append(replace(group, options=tuple(options[:MAX_OPTIONS_PER_SENSE])))
            if adjusted:
                found = [t for t in found if not (t.start < end and start < t.end)]
                found.append(TokenOptions(start, end, text[start:end],
                                          tuple(_numbered(adjusted)[:MAX_SENSES])))
        return sorted(found, key=lambda t: t.start)

    def _words(self, text: str) -> tuple[Token, ...]:
        """Paraules del text, amb la posició referida al text sencer."""
        words: list[Token] = []
        for sentence in self._analyzer.analyze(text).sentences:
            words.extend(token for token in sentence.tokens if token.kind is TokenKind.WORD)
        return tuple(words)

    def _parse(self, text: str) -> object | None:
        """Anàlisi sintàctica del text, si hi ha parser i se'n fia."""
        if self._syntax is None or not self._syntax.available:
            return None
        analysis = self._syntax.parse(text)
        return analysis if analysis is not None and analysis.confident else None

    def _at(
        self,
        text: str,
        tokens: Sequence[Token],
        position: int,
        protected: Sequence[ProtectedSpan],
        parsed: object | None,
    ) -> tuple[TokenOptions, int] | None:
        """El fragment més llarg que comença aquí i té alternativa, si n'hi ha cap."""
        limit = min(MAX_PHRASE_TOKENS, len(tokens) - position)
        for length in range(limit, 0, -1):
            start = tokens[position].span.start
            end = tokens[position + length - 1].span.end
            if any(p.span.overlaps(Span(start, end)) for p in protected):
                continue
            phrase = text[start:end]
            # La categoria del parser només val per a un sol mot: al primer mot
            # d'una locució («a causa de») diu «preposició», que no és el que
            # és la locució sencera.
            pos, lemma = self._parser_info(parsed, start) if length == 1 else (None, "")
            groups = self._for_phrase(phrase, pos, lemma)
            if groups:
                return TokenOptions(start, end, phrase, groups), length
        return None

    def _parser_info(self, parsed: object | None, offset: int) -> tuple[str | None, str]:
        """Categoria i lema que el parser dona al mot d'aquesta posició."""
        if parsed is None:
            return None, ""
        token = parsed.token_at(offset)  # type: ignore[attr-defined]
        if token is None:
            return None, ""
        return str(token.pos), str(token.lemma or "")

    # -- fonts -------------------------------------------------------------------------------

    def _for_phrase(
        self, phrase: str, parser_pos: str | None, parser_lemma: str = ""
    ) -> tuple[OptionGroup, ...]:
        """Grups d'alternatives d'un fragment, de la font més segura a la més oberta."""
        if normalize_form(phrase) in self._guarded:
            # Una negació o un marcador de modalitat no té sinònims: canviar-lo
            # canvia el que el text afirma, no com ho diu.
            return ()
        groups = [
            *self._from_connectors(phrase),
            *self._dictionary_without_agreement(phrase),
            *self._from_thesaurus(phrase, parser_pos, parser_lemma),
        ]
        ranked = sorted(
            groups, key=lambda g: (_SOURCE_ORDER.get(g.source, 9), not g.expected, g.label)
        )
        return tuple(ranked[:MAX_SENSES])

    def _from_connectors(self, phrase: str) -> list[OptionGroup]:
        alternatives = self._connectors.get(normalize(phrase))
        if not alternatives:
            return []
        function = next((a.function for a in alternatives if a.function), "")
        options = tuple(
            SynonymOption(
                text=match_casing(phrase, alternative.form),
                lemma=alternative.form,
                source=SOURCE_CONNECTOR,
                note="mateixa classe d'equivalència",
            )
            for alternative in alternatives
        )
        label = f"connector de {function}" if function else "connector equivalent"
        return [OptionGroup(label, SOURCE_CONNECTOR, options[:MAX_OPTIONS_PER_SENSE], True)]

    def _dictionary_without_agreement(self, phrase: str) -> list[OptionGroup]:
        """Sense ajust contextual, un nom no pot canviar de gènere o nombre."""
        groups = self._from_dictionary(phrase)
        if self._morphology is None:
            return groups
        nouns = [e for e in self._morphology.analyze(phrase) if e.features.pos == "noun"]
        if not nouns:
            return groups
        safe = []
        for group in groups:
            options = tuple(o for o in group.options if any(
                target.features.pos == "noun"
                and target.features.gender == original.features.gender
                and target.features.number == original.features.number
                for original in nouns for target in self._morphology.analyze(o.text)))
            if options:
                safe.append(replace(group, options=options))
        return safe

    def _from_dictionary(self, phrase: str) -> list[OptionGroup]:
        if self._dictionary is None:
            return []
        match = self._dictionary.lookup(phrase)
        if match is None:
            return []
        entry = match.entry
        key = normalize_term(phrase)
        if match.status is FormStatus.AVOID:
            # Una forma a evitar no té alternatives: té una substituta.
            preferred: tuple[SynonymOption, ...] = (
                SynonymOption(
                    text=match_casing(phrase, entry.preferred_form),
                    lemma=entry.preferred_form,
                    source=SOURCE_DICTIONARY,
                    note=entry.notes or "forma preferida del diccionari",
                ),
            )
            return [
                OptionGroup(f"forma preferida · {entry.term}", SOURCE_DICTIONARY, preferred, True)
            ]
        options = tuple(
            SynonymOption(
                text=match_casing(phrase, form),
                lemma=form,
                source=SOURCE_DICTIONARY,
                note=entry.notes,
            )
            for form in entry.kept_forms
            if normalize_term(form) != key
        )
        if not options:
            return []
        label = f"diccionari · {entry.term}"
        return [OptionGroup(label, SOURCE_DICTIONARY, options[:MAX_OPTIONS_PER_SENSE], True)]

    def _from_thesaurus(
        self, phrase: str, parser_pos: str | None, parser_lemma: str = ""
    ) -> list[OptionGroup]:
        if self._thesaurus is None:
            return []
        if parser_pos is not None and parser_pos in FUNCTIONAL_POS:
            return []
        expected = PARSER_POS.get(parser_pos or "")
        found: list[OptionGroup] = []
        for group in self._groups_for(phrase, parser_lemma):
            options = self._from_group(phrase, group)
            if not options:
                continue
            matches = expected is None or expected in group.pos.split("/")
            found.append(
                OptionGroup(
                    group.label or "sinònims",
                    SOURCE_THESAURUS,
                    options[:MAX_OPTIONS_PER_SENSE],
                    matches,
                )
            )
        # Amb parser fiable, un sentit d'una altra categoria és soroll: «fan» com
        # a nom (admirador) no té res a veure amb «fan» com a verb. Si el parser
        # ha dit de quina categoria és el mot, els sentits d'una altra no
        # s'ofereixen; si no n'hi ha cap que hi encaixi, no s'ofereix res.
        if expected is not None:
            found = [group for group in found if group.expected]
        return _numbered(found)

    def _groups_for(self, phrase: str, parser_lemma: str) -> tuple[SynonymGroup, ...]:
        """Grups de la forma i, si difereix, del seu lema.

        El diccionari està escrit amb formes de diccionari («saber», «casa») i
        el text porta formes flexionades («sabem», «cases»). Buscar només la
        forma tal com surt deixaria fora tot el que està conjugat o en plural.
        """
        assert self._thesaurus is not None
        keys: dict[str, None] = {normalize(phrase): None}
        for lemma in (parser_lemma, self._lemma_of(phrase)):
            key = normalize(lemma)
            if key:
                keys.setdefault(key, None)
        found: dict[tuple[str, str, tuple[str, ...]], SynonymGroup] = {}
        for key in keys:
            for group in self._thesaurus.groups(key):
                identity = (group.pos, group.sense, tuple(m.form for m in group.members))
                found.setdefault(identity, group)
        return tuple(found.values())

    def _lemma_of(self, phrase: str) -> str:
        """Lema de la forma segons la morfologia, o buit si no se sap."""
        if self._morphology is None or " " in phrase.strip():
            return ""
        for entry in self._morphology.analyze(phrase):
            if entry.lemma:
                return str(entry.lemma)
        return ""

    def _from_group(self, phrase: str, group: SynonymGroup) -> tuple[SynonymOption, ...]:
        invariable = all(part in INVARIABLE for part in group.pos.split("/") if part)
        found: list[SynonymOption] = []
        seen: set[str] = set()
        for member in group.members:
            text = self._inflected(phrase, member.form, group, invariable=invariable)
            if text is None:
                continue
            key = normalize(text)
            if key == normalize(phrase) or key in seen:
                continue
            seen.add(key)
            found.append(
                SynonymOption(
                    text=match_casing(phrase, text),
                    lemma=member.form,
                    source=SOURCE_THESAURUS,
                    register=member.register,
                    note="equivalència més fluixa" if member.secondary else "",
                )
            )
        return tuple(found)

    def _inflected(
        self, phrase: str, lemma: str, group: SynonymGroup, *, invariable: bool
    ) -> str | None:
        """La forma del lema que encaixa amb el fragment, o ``None`` si no se'n pot fer cap.

        Una locució o un adverbi no es flexionen: la forma del diccionari ja
        serveix. Un nom, un adjectiu o un verb sí, i sense morfologia
        instal·lada no es pot garantir la concordança: en aquest cas no
        s'ofereix res.
        """
        if invariable:
            return lemma
        if " " in lemma.strip() or self._morphology is None:
            return None
        if normalize(phrase) == normalize(lemma):
            return None
        pos = group.pos if "/" not in group.pos else None
        provider = self._morphology
        return inflect_like(provider, phrase, lemma, pos=pos) or inflect_like(
            provider, phrase, lemma
        )


def _numbered(groups: Sequence[OptionGroup]) -> list[OptionGroup]:
    """Distingeix els sentits que comparteixen etiqueta.

    El diccionari no glossa tots els grups: «fàcilment» en té quatre i tots es
    diuen «adverbi». Numerar-los deixa clar que són sentits diferents; qui
    tria els distingeix per les formes que hi ha a dins.
    """
    counts: dict[str, int] = {}
    for group in groups:
        counts[group.label] = counts.get(group.label, 0) + 1
    seen: dict[str, int] = {}
    numbered: list[OptionGroup] = []
    for group in groups:
        if counts[group.label] < 2:
            numbered.append(group)
            continue
        seen[group.label] = seen.get(group.label, 0) + 1
        numbered.append(replace(group, label=f"{group.label} · sentit {seen[group.label]}"))
    return numbered


__all__ = [
    "FUNCTIONAL_POS",
    "INVARIABLE",
    "MAX_OPTIONS_PER_SENSE",
    "MAX_PHRASE_TOKENS",
    "MAX_SENSES",
    "PARSER_POS",
    "SOURCE_CONNECTOR",
    "SOURCE_DICTIONARY",
    "SOURCE_THESAURUS",
    "ConnectorAlternative",
    "OptionGroup",
    "SynonymOption",
    "SynonymSuggester",
    "TokenOptions",
    "connector_index",
]
