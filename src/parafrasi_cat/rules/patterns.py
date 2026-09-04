"""Motor de patrons sobre tokens per a les regles declarades en YAML.

Un patró és una seqüència d'elements que es comparen amb els tokens d'una
frase (sense espais), amb retrocés com en una expressió regular:

- **elements de token**: ``{text: és}``, ``{text: [és, són], group: cop}``,
  ``{regex: ".*ar$"}``, ``{class: preposition}``, ``{lemma: ser}``,
  ``{participle: true}``, ``{finite_verb: true}``, ``{infinitive: true}``,
  ``{determiner: true}``, ``{capitalized: true}``, ``{kind: number}``,
  ``{subkind: pause}``, ``{protected: false}``, ``{optional: true}``;
  una cadena sola («és») equival a ``{text: és}``;
- **trossos**: ``{np: true, group: subj}`` (sintagma nominal),
  ``{seq: true, group: rest}`` (seqüència lliure amb retrocés),
  ``{temporal: true, group: t}`` (complement temporal);
- **ancoratges**: ``{start: true}``, ``{end: true}``, ``{sentence_end: true}``
  (davant del signe final o al final), ``{boundary: true}`` (davant de coma,
  punt i coma o final).

Les plantilles referencien els grups: ``"{subj} constitueix {pred}"``. Filtres:
``{x|cap}``, ``{x|lower}``, ``{x|de}`` (contracció amb «de»), ``{x|a}``,
``{np|agree(apareix,apareixen)}`` (concordança de nombre),
``{p|map(fet=realitzat,feta=realitzada)}``,
``{cop|inflect(constituir,és=constitueix,són=constitueixen)}`` (canvi de verb
conservant persona, nombre i gènere: primer amb el recurs morfològic i, si no
en sap prou, amb el mapatge explícit que ve a continuació).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field

from parafrasi_cat.analyzer.clitics import DEFAULT_AUXILIARY_FORMS
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon, WordClass, normalize_form
from parafrasi_cat.analyzer.tokens import Token, TokenKind, TokenSubkind
from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.text import LETTER, match_casing, phrase_pattern
from parafrasi_cat.morphology.guesser import guess
from parafrasi_cat.morphology.provider import MorphologyProvider, NullMorphology, inflect_like
from parafrasi_cat.protected.spans import ProtectedSpan
from parafrasi_cat.syntax.analysis import SentenceSyntax, empty

# --- Coneixement gramatical mínim -----------------------------------------------

_SINGULAR_DETERMINERS = frozenset(
    {
        "el", "la", "l'", "un", "una", "aquest", "aquesta", "aquell", "aquella", "aqueix",
        "aqueixa", "cada", "cap", "algun", "alguna", "tot", "tota", "qualsevol", "el mateix",
        "la mateixa", "un altre", "una altra", "cert", "certa", "dit", "dita", "1",
    }
)  # fmt: skip
_PLURAL_DETERMINERS = frozenset(
    {
        "els", "les", "uns", "unes", "aquests", "aquestes", "aquells", "aquelles", "aqueixos",
        "aqueixes", "dos", "dues", "tres", "quatre", "cinc", "sis", "set", "vuit", "nou", "deu",
        "onze", "dotze", "tretze", "catorze", "quinze", "setze", "disset", "divuit", "dinou",
        "vint", "trenta", "quaranta", "cinquanta", "seixanta", "setanta", "vuitanta", "noranta",
        "cent", "mil", "ambdós", "ambdues", "diversos", "diverses", "nombrosos", "nombroses",
        "múltiples", "diferents", "tots", "totes", "alguns", "algunes", "molts", "moltes",
        "pocs", "poques", "altres", "sengles",
    }
)  # fmt: skip
_DEFINITE = frozenset(
    {
        "el", "la", "l'", "els", "les", "aquest", "aquesta", "aquests", "aquestes", "aquell",
        "aquella", "aquells", "aquelles", "aqueix", "aqueixa", "aqueixos", "aqueixes",
    }
)  # fmt: skip
_DEFAULT_PREPOSITIONS = frozenset(
    {"a", "amb", "de", "d'", "en", "per", "contra", "entre", "fins", "malgrat", "segons", "sense",
     "sobre", "sota", "vers", "envers", "durant", "mitjançant", "cap", "des"}
)  # fmt: skip
_DEFAULT_CONJUNCTIONS = frozenset(
    {"i", "o", "ni", "però", "sinó", "que", "si", "perquè", "com", "quan", "mentre", "doncs", "car"}
)
_DEFAULT_PRONOUNS = frozenset(
    {"em", "et", "es", "el", "la", "els", "les", "li", "ho", "hi", "en", "ens", "us", "me", "te",
     "se", "ne", "jo", "tu", "ell", "ella", "nosaltres", "vosaltres", "ells", "elles", "que",
     "qui", "què", "on", "això", "allò", "res", "algú", "ningú", "tothom"}
)  # fmt: skip
_DEGREE_ADVERBS = frozenset(
    {"molt", "poc", "més", "menys", "tan", "força", "ben", "bastant", "gairebé", "quasi", "prou",
     "massa", "completament", "totalment", "especialment", "particularment", "relativament",
     "extremadament", "lleugerament", "clarament"}
)  # fmt: skip
_NP_PREPOSITIONS = frozenset({"de", "d'", "del", "dels"})
RELATIVE_MARKERS = frozenset({"que", "qui", "on", "quan", "perquè", "mentre", "si"})

_INFINITIVE_RE = re.compile(r"^[^\W\d_]{2,}(?:ar|er|ir|re)$")
_PARTICIPLE_RE = re.compile(r"^[^\W\d_]{2,}(?:[aiu]t|[aiu]da|[aiu]ts|[aiu]des)$")


def is_participle(text: str) -> bool:
    """Cert si la forma sembla un participi (regular o irregular conegut)."""
    lowered = text.lower()
    if _PARTICIPLE_RE.match(lowered):
        return True
    return any(entry.features.mood == "part" for entry in guess(lowered))


def participle_number(text: str) -> str:
    """Nombre d'un participi a partir de la desinència (-s → plural)."""
    return "pl" if text.lower().endswith("s") else "sg"


@dataclass(frozen=True)
class GrammarHints:
    """Conjunts de formes gramaticals que necessiten els patrons.

    Es construeixen a partir del lexicó de classes tancades (si n'hi ha) i
    d'uns valors mínims incorporats, perquè els patrons funcionin també sense
    recursos carregats.
    """

    lexicon: ClosedClassLexicon | None = None
    auxiliary_finite: frozenset[str] = DEFAULT_AUXILIARY_FORMS
    auxiliary_all: frozenset[str] = DEFAULT_AUXILIARY_FORMS
    determiners: frozenset[str] = _SINGULAR_DETERMINERS | _PLURAL_DETERMINERS
    definite: frozenset[str] = _DEFINITE
    prepositions: frozenset[str] = _DEFAULT_PREPOSITIONS
    conjunctions: frozenset[str] = _DEFAULT_CONJUNCTIONS
    pronouns: frozenset[str] = _DEFAULT_PRONOUNS
    adverbs: frozenset[str] = frozenset()
    finite_verbs: frozenset[str] = frozenset()
    closed_class: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_lexicon(
        cls, lexicon: ClosedClassLexicon | None, finite_verbs: Sequence[str] = ()
    ) -> GrammarHints:
        if lexicon is None:
            return cls(finite_verbs=frozenset(normalize_form(f) for f in finite_verbs))
        aux_entries = lexicon.of_class(WordClass.AUXILIARY)
        aux_finite = frozenset(
            normalize_form(e.form)
            for e in aux_entries
            if e.feature("mood") in ("ind", "subj", "imp")
        )
        pronoun_entries = lexicon.of_class(WordClass.PRONOUN)
        adverb_forms = lexicon.forms_of(WordClass.ADVERB)
        determiner_like = frozenset(
            normalize_form(e.form)
            for e in pronoun_entries
            if e.subtype.startswith(("demostratiu", "possessiu", "indefinit"))
            and e.feature("number") is not None
            and normalize_form(e.form) not in adverb_forms  # «molt», «poc»: adverbis de grau
        )
        return cls(
            lexicon=lexicon,
            auxiliary_finite=aux_finite | DEFAULT_AUXILIARY_FORMS,
            auxiliary_all=lexicon.forms_of(WordClass.AUXILIARY) | DEFAULT_AUXILIARY_FORMS,
            determiners=_SINGULAR_DETERMINERS
            | _PLURAL_DETERMINERS
            | lexicon.forms_of(WordClass.ARTICLE)
            | determiner_like,
            definite=_DEFINITE,
            prepositions=lexicon.forms_of(WordClass.PREPOSITION) | _DEFAULT_PREPOSITIONS,
            conjunctions=lexicon.forms_of(WordClass.CONJUNCTION) | _DEFAULT_CONJUNCTIONS,
            pronouns=lexicon.forms_of(WordClass.PRONOUN) | _DEFAULT_PRONOUNS,
            adverbs=lexicon.forms_of(WordClass.ADVERB),
            finite_verbs=frozenset(normalize_form(f) for f in finite_verbs),
            closed_class=lexicon.single_word_forms,
        )

    def classes_of(self, form: str) -> frozenset[WordClass]:
        if self.lexicon is None:
            return frozenset()
        return self.lexicon.classes_of(form)

    def is_closed_class(self, form: str) -> bool:
        low = normalize_form(form)
        return (
            low in self.closed_class
            or low in self.determiners
            or low in self.prepositions
            or low in self.conjunctions
            or low in self.pronouns
            or low in self.auxiliary_all
        )

    def is_finite_verb(self, token: Token) -> bool:
        if not token.is_word:
            return False
        low = normalize_form(token.text)
        if low in self.auxiliary_finite or low in self.finite_verbs:
            return True
        if self.is_closed_class(low):
            return False
        for entry in guess(token.text):
            if (
                entry.features.pos == "verb"
                and entry.features.mood in ("ind", "subj")
                and entry.confidence >= 0.45
            ):
                return True
        return False

    def is_infinitive(self, token: Token) -> bool:
        if token.kind is not TokenKind.WORD:
            return False
        low = normalize_form(token.text)
        if self.is_closed_class(low) or low in self.finite_verbs:
            return False
        return _INFINITIVE_RE.match(low) is not None and not is_participle(low)

    def is_determiner(self, token: Token) -> bool:
        return normalize_form(token.text) in self.determiners

    def number_of(self, tokens: Sequence[Token]) -> str | None:
        """Nombre (sg/pl) d'un sintagma nominal a partir del seu primer element."""
        if not tokens:
            return None
        first = tokens[0]
        low = normalize_form(first.text)
        if first.kind is TokenKind.NUMBER:
            digits = re.sub(r"[^\d]", "", first.text)
            if not digits:
                return None
            return "sg" if int(digits) == 1 else "pl"
        if low in _PLURAL_DETERMINERS:
            return "pl"
        if low in _SINGULAR_DETERMINERS:
            return "sg"
        if first.text[:1].isupper():
            return "sg"
        return None

    def is_np_stop(self, token: Token) -> bool:
        """Cert si el token no pot formar part d'un sintagma nominal."""
        if token.kind is TokenKind.PUNCT:
            return True
        low = normalize_form(token.text)
        if low in _NP_PREPOSITIONS or low in self.determiners:
            return False
        if low in _DEGREE_ADVERBS:
            return False
        if low in self.auxiliary_all or low in self.conjunctions or low in RELATIVE_MARKERS:
            return True
        if low in self.pronouns or low in self.prepositions or low in self.adverbs:
            return True
        return token.kind is TokenKind.CLITIC and low not in ("l'", "d'")


# --- Estat de comparació ------------------------------------------------------------


@dataclass(frozen=True)
class MatchState:
    text: str
    tokens: tuple[Token, ...]
    protected: tuple[ProtectedSpan, ...]
    hints: GrammarHints
    morphology: MorphologyProvider = field(default_factory=NullMorphology)
    """Recurs morfològic per a les plantilles. Sense recurs, els mapatges manen."""

    syntax: SentenceSyntax = field(default_factory=empty)
    """Anàlisi sintàctica de la frase. Només la consulten les regles que la demanen."""

    def is_protected_token(self, index: int) -> bool:
        span = self.tokens[index].span
        return any(p.overlaps(span) for p in self.protected)

    def same_protected_as_previous(self, index: int) -> bool:
        """Cert si el token i l'anterior són dins del mateix fragment protegit."""
        if index == 0:
            return False
        current = self.tokens[index].span
        previous = self.tokens[index - 1].span
        return any(p.overlaps(current) and p.overlaps(previous) for p in self.protected)

    def is_final_punct(self, index: int) -> bool:
        token = self.tokens[index]
        return (
            index == len(self.tokens) - 1
            and token.kind is TokenKind.PUNCT
            and token.subkind is TokenSubkind.SENTENCE_END
        )


Captures = dict[str, tuple[int, int]]


def _merge(groups: Captures, name: str | None, start: int, end: int) -> Captures:
    if name is None or end <= start:
        return groups
    merged = dict(groups)
    previous = merged.get(name)
    if previous is not None and previous[1] == start:
        merged[name] = (previous[0], end)
    else:
        merged[name] = (start, end)
    return merged


# --- Elements ----------------------------------------------------------------------------


class Element:
    """Un element de patró: proposa posicions finals a partir d'una posició inicial."""

    consumes = True

    def candidates(self, state: MatchState, pos: int) -> Iterator[tuple[int, Captures]]:
        raise NotImplementedError


@dataclass(frozen=True)
class TokenElement(Element):
    texts: frozenset[str] = frozenset()
    not_texts: frozenset[str] = frozenset()
    regex: re.Pattern[str] | None = None
    kinds: frozenset[TokenKind] = frozenset()
    subkinds: frozenset[TokenSubkind] = frozenset()
    word_class: WordClass | None = None
    lemma: str | None = None
    participle: bool | None = None
    finite_verb: bool | None = None
    infinitive: bool | None = None
    determiner: bool | None = None
    definite: bool | None = None
    capitalized: bool | None = None
    protected: bool | None = None
    optional: bool = False
    group: str | None = None

    def matches(self, state: MatchState, index: int) -> bool:
        token = state.tokens[index]
        low = normalize_form(token.text)
        hints = state.hints
        if self.texts and low not in self.texts:
            return False
        if self.not_texts and low in self.not_texts:
            return False
        if self.regex is not None and self.regex.fullmatch(token.text) is None:
            return False
        if self.kinds and token.kind not in self.kinds:
            return False
        if self.subkinds and (token.subkind is None or token.subkind not in self.subkinds):
            return False
        if self.word_class is not None and self.word_class not in hints.classes_of(low):
            return False
        if self.lemma is not None:
            entries = hints.lexicon.lookup(low) if hints.lexicon is not None else ()
            if not any(normalize_form(e.lemma) == normalize_form(self.lemma) for e in entries):
                return False
        if self.participle is not None and is_participle(token.text) != self.participle:
            return False
        if self.finite_verb is not None and hints.is_finite_verb(token) != self.finite_verb:
            return False
        if self.infinitive is not None and hints.is_infinitive(token) != self.infinitive:
            return False
        if self.determiner is not None and hints.is_determiner(token) != self.determiner:
            return False
        if self.definite is not None and (low in hints.definite) != self.definite:
            return False
        if self.capitalized is not None and token.text[:1].isupper() != self.capitalized:
            return False
        return not (
            self.protected is not None and state.is_protected_token(index) != self.protected
        )

    def candidates(self, state: MatchState, pos: int) -> Iterator[tuple[int, Captures]]:
        if pos < len(state.tokens) and self.matches(state, pos):
            yield pos + 1, _merge({}, self.group, pos, pos + 1)
        if self.optional:
            yield pos, {}


@dataclass(frozen=True)
class NounPhraseElement(Element):
    group: str | None = None
    bare: bool = False
    preps: frozenset[str] = _NP_PREPOSITIONS
    min_tokens: int = 1
    max_tokens: int = 12

    def starts_np(self, state: MatchState, index: int, bare: bool) -> bool:
        token = state.tokens[index]
        if token.kind is TokenKind.PUNCT:
            return False
        low = normalize_form(token.text)
        hints = state.hints
        if low in hints.determiners or token.kind is TokenKind.NUMBER:
            return True
        if token.text[:1].isupper() and not hints.is_closed_class(low):
            return True
        return bool(
            bare
            and token.kind is TokenKind.WORD
            and not hints.is_closed_class(low)
            and not hints.is_finite_verb(token)
            and low not in RELATIVE_MARKERS
        )

    def ends(self, state: MatchState, pos: int) -> list[int]:
        tokens = state.tokens
        n = len(tokens)
        if pos >= n or not self.starts_np(state, pos, self.bare):
            return []
        j = pos + 1
        boundaries: list[int] = []
        while j < n and j - pos < self.max_tokens:
            token = tokens[j]
            low = normalize_form(token.text)
            if state.same_protected_as_previous(j):
                j += 1
                continue
            if token.kind is TokenKind.PUNCT:
                break
            if low in self.preps:
                if j + 1 < n and (
                    self.starts_np(state, j + 1, True) or tokens[j + 1].kind is TokenKind.NUMBER
                ):
                    boundaries.append(j)
                    j += 1
                    continue
                break
            if state.hints.is_np_stop(token) or state.hints.is_finite_verb(token):
                break
            j += 1
        ends = [j, *reversed(boundaries)]
        return [end for end in ends if end - pos >= self.min_tokens]

    def candidates(self, state: MatchState, pos: int) -> Iterator[tuple[int, Captures]]:
        for end in self.ends(state, pos):
            yield end, _merge({}, self.group, pos, end)


@dataclass(frozen=True)
class SequenceElement(Element):
    group: str | None = None
    min_tokens: int = 1
    max_tokens: int = 60
    greedy: bool = False
    no_comma: bool = False
    no_semicolon: bool = True
    no_punct: bool = False

    def _forbidden(self, state: MatchState, index: int) -> bool:
        token = state.tokens[index]
        if token.kind is not TokenKind.PUNCT:
            return False
        if state.is_final_punct(index):
            return True
        if self.no_punct:
            return True
        if self.no_comma and token.text == ",":
            return True
        return self.no_semicolon and token.text == ";"

    def candidates(self, state: MatchState, pos: int) -> Iterator[tuple[int, Captures]]:
        n = len(state.tokens)
        limit = min(n, pos + self.max_tokens)
        ends: list[int] = []
        index = pos
        while index < limit:
            if self._forbidden(state, index):
                break
            index += 1
            if index - pos >= self.min_tokens:
                ends.append(index)
        if self.greedy:
            ends.reverse()
        for end in ends:
            yield end, _merge({}, self.group, pos, end)


_MONTHS = "gener|febrer|març|abril|maig|juny|juliol|agost|setembre|octubre|novembre|desembre"
_ROMAN = r"[IVXLCDM]+"
_ERA = r"(?:\s?(?:aC|dC))?"
_INTRO = (
    r"(?:l'any\s+|el\s+|els\s+anys\s+|a\s+l'any\s+|al\s+|a\s+la\s+|a\s+les\s+|als\s+|en\s+|"
    r"durant\s+(?:el\s+|la\s+|els\s+|l')?|des\s+de\s+(?:l'|el\s+|la\s+)?|des\s+del\s+|"
    r"fins\s+a\s+(?:l'|el\s+|la\s+)?|fins\s+al\s+|a\s+partir\s+de\s+(?:l'|la\s+)?|a\s+partir\s+del\s+|"
    r"abans\s+de\s+(?:l'|la\s+)?|abans\s+del\s+|després\s+de\s+(?:l'|la\s+)?|després\s+del\s+|"
    r"entre\s+|cap\s+a\s+(?:l'|el\s+)?|cap\s+al\s+|vers\s+(?:el\s+|l')?|pels\s+volts\s+de\s+(?:l'|la\s+)?|"
    r"pels\s+volts\s+del\s+|"
    r"a\s+(?:principis|començaments|mitjan|mitjans|finals|final|les\s+acaballes)\s+(?:de\s+(?:l'|la\s+)?|del\s+))?"
)
_CORE = (
    rf"(?:\d{{3,4}}{_ERA}(?:\s+i\s+(?:el\s+)?\d{{3,4}}{_ERA})?"
    rf"|segle\s+{_ROMAN}{_ERA}|segles\s+{_ROMAN}(?:\s*(?:,|i)\s*{_ROMAN})*{_ERA}"
    rf"|(?:{_MONTHS})(?:\s+(?:de|del)\s+\d{{4}})?"
    rf"|\d{{1,2}}\s+(?:de\s+|d')(?:{_MONTHS})(?:\s+(?:de|del)\s+\d{{4}})?"
    r"|any\s+\d{3,4}|dècada\s+(?:de\s+|dels\s+)\d{4}|anys\s+\d{2,4}"
    r"|(?:tardor|estiu|hivern|primavera)\s+(?:de|del)\s+\d{4}"
    r"|(?:aquell|aquest|el\s+mateix)\s+(?:any|dia|mes|segle|estiu|hivern|període|moment|matí|vespre)"
    r"|ahir|avui|demà|aleshores|llavors|actualment|antigament|posteriorment|anteriorment"
    r"|(?:dilluns|dimarts|dimecres|dijous|divendres|dissabte|diumenge))"
)
TEMPORAL_RE = re.compile(rf"(?P<intro>{_INTRO}){_CORE}(?!{LETTER})", re.IGNORECASE)


@dataclass(frozen=True)
class TemporalElement(Element):
    group: str | None = None
    require_intro: bool = False
    """Exigeix un introductor (preposició o article: «el 1507», «al segle XIX»)."""

    def end_token(self, state: MatchState, pos: int) -> int | None:
        if pos >= len(state.tokens):
            return None
        match = TEMPORAL_RE.match(state.text, state.tokens[pos].span.start)
        if match is None:
            return None
        if self.require_intro and not match.group("intro"):
            return None
        for index in range(pos, len(state.tokens)):
            if state.tokens[index].span.end == match.end():
                return index + 1
            if state.tokens[index].span.end > match.end():
                break
        return None

    def candidates(self, state: MatchState, pos: int) -> Iterator[tuple[int, Captures]]:
        end = self.end_token(state, pos)
        if end is not None:
            yield end, _merge({}, self.group, pos, end)


def contains_temporal(text: str) -> bool:
    return TEMPORAL_RE.search(text) is not None


@dataclass(frozen=True)
class AnchorElement(Element):
    kind: str = "start"
    consumes = False

    def candidates(self, state: MatchState, pos: int) -> Iterator[tuple[int, Captures]]:
        n = len(state.tokens)
        if self.kind == "start":
            ok = pos == 0
        elif self.kind == "end":
            ok = pos == n
        elif self.kind == "sentence_end":
            ok = pos == n or (pos == n - 1 and state.is_final_punct(pos))
        elif self.kind == "boundary":
            ok = pos == n or (
                state.tokens[pos].kind is TokenKind.PUNCT
                and (state.tokens[pos].text in (",", ";") or state.is_final_punct(pos))
            )
        else:  # pragma: no cover - validat en compilar
            ok = False
        if ok:
            yield pos, {}


# --- Compilació d'un patró ---------------------------------------------------------------


def _as_str_set(value: object) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        return frozenset({normalize_form(value)})
    if isinstance(value, Sequence):
        return frozenset(normalize_form(str(v)) for v in value)
    raise ConfigError(f"Valor de patró invàlid: {value!r}")


def _as_bool_or_none(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ConfigError(f"S'esperava cert/fals, no {value!r}")


def _as_int(value: object, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"S'esperava un enter, no {value!r}")
    return value


def compile_element(spec: object) -> Element:
    if isinstance(spec, str):
        return TokenElement(texts=_as_str_set(spec))
    if not isinstance(spec, Mapping):
        raise ConfigError(f"Element de patró invàlid: {spec!r}")
    data: dict[str, object] = {str(k): v for k, v in spec.items()}
    group = data.get("group")
    group_name = None if group is None else str(group)
    for anchor in ("start", "end", "sentence_end", "boundary"):
        if data.get(anchor) is True:
            return AnchorElement(anchor)
    if data.get("np") is True:
        preps = _as_str_set(data.get("preps")) or _NP_PREPOSITIONS
        return NounPhraseElement(
            group=group_name,
            bare=bool(data.get("bare", False)),
            preps=preps,
            min_tokens=_as_int(data.get("min_tokens"), 1),
            max_tokens=_as_int(data.get("max_tokens"), 12),
        )
    if data.get("seq") is True:
        return SequenceElement(
            group=group_name,
            min_tokens=_as_int(data.get("min_tokens"), 1),
            max_tokens=_as_int(data.get("max_tokens"), 60),
            greedy=bool(data.get("greedy", False)),
            no_comma=bool(data.get("no_comma", False)),
            no_semicolon=bool(data.get("no_semicolon", True)),
            no_punct=bool(data.get("no_punct", False)),
        )
    if data.get("temporal") is True:
        return TemporalElement(group=group_name, require_intro=bool(data.get("intro", False)))
    regex_value = data.get("regex")
    regex = None
    if regex_value is not None:
        flags = 0 if data.get("case") is True else re.IGNORECASE
        regex = re.compile(str(regex_value), flags)
    kinds = frozenset(TokenKind(str(k)) for k in _as_str_set(data.get("kind")))
    subkinds = frozenset(TokenSubkind(str(k)) for k in _as_str_set(data.get("subkind")))
    class_value = data.get("class")
    word_class = None if class_value is None else WordClass(str(class_value))
    lemma = data.get("lemma")
    return TokenElement(
        texts=_as_str_set(data.get("text")),
        not_texts=_as_str_set(data.get("not_text")),
        regex=regex,
        kinds=kinds,
        subkinds=subkinds,
        word_class=word_class,
        lemma=None if lemma is None else str(lemma),
        participle=_as_bool_or_none(data.get("participle")),
        finite_verb=_as_bool_or_none(data.get("finite_verb")),
        infinitive=_as_bool_or_none(data.get("infinitive")),
        determiner=_as_bool_or_none(data.get("determiner")),
        definite=_as_bool_or_none(data.get("definite")),
        capitalized=_as_bool_or_none(data.get("capitalized")),
        protected=_as_bool_or_none(data.get("protected")),
        optional=bool(data.get("optional", False)),
        group=group_name,
    )


@dataclass(frozen=True)
class Match:
    start: int
    end: int
    groups: Mapping[str, tuple[int, int]]

    def span(self, state: MatchState) -> Span:
        return Span(state.tokens[self.start].span.start, state.tokens[self.end - 1].span.end)

    def group_tokens(self, state: MatchState, name: str) -> tuple[Token, ...]:
        bounds = self.groups.get(name)
        return () if bounds is None else state.tokens[bounds[0] : bounds[1]]

    def group_span(self, state: MatchState, name: str) -> Span | None:
        bounds = self.groups.get(name)
        if bounds is None:
            return None
        return Span(state.tokens[bounds[0]].span.start, state.tokens[bounds[1] - 1].span.end)

    def group_text(self, state: MatchState, name: str) -> str:
        span = self.group_span(state, name)
        return "" if span is None else span.slice(state.text)


Accept = Callable[[Match], bool]


class PatternMatcher:
    """Compara un patró amb els tokens d'una frase, amb retrocés."""

    def __init__(self, specs: Sequence[object]) -> None:
        if not specs:
            raise ConfigError("Un patró necessita almenys un element")
        self._elements = tuple(compile_element(spec) for spec in specs)
        if not any(e.consumes for e in self._elements):
            raise ConfigError("Un patró ha de consumir almenys un token")

    @property
    def elements(self) -> tuple[Element, ...]:
        return self._elements

    def matches_at(self, state: MatchState, pos: int) -> Iterator[Match]:
        yield from self._match(state, 0, pos, pos, {})

    def _match(
        self, state: MatchState, index: int, start: int, pos: int, groups: Captures
    ) -> Iterator[Match]:
        if index == len(self._elements):
            if pos > start:
                yield Match(start, pos, groups)
            return
        element = self._elements[index]
        for end, captured in element.candidates(state, pos):
            merged = groups
            for name, (s, e) in captured.items():
                merged = _merge(merged, name, s, e)
            yield from self._match(state, index + 1, start, end, merged)

    def find_all(self, state: MatchState, accept: Accept | None = None) -> list[Match]:
        """Primer encaix acceptat a cada posició; les cerques no se solapen."""
        found: list[Match] = []
        pos = 0
        n = len(state.tokens)
        while pos < n:
            chosen: Match | None = None
            for match in self.matches_at(state, pos):
                if accept is None or accept(match):
                    chosen = match
                    break
            if chosen is None:
                pos += 1
                continue
            found.append(chosen)
            pos = max(chosen.end, pos + 1)
        return found


# --- Plantilles ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{(\w+)((?:\|[^{}|]+)*)\}")
_VOWEL_START_RE = re.compile(r"^[haeiouàèéíòóúïü]", re.IGNORECASE)


def contract_de(text: str) -> str:
    """«de» + sintagma amb contracció: del, dels, de l', d'aigua."""
    low = normalize_form(text)
    if low.startswith("el ") or low == "el":
        return "del" + text[2:]
    if low.startswith("els ") or low == "els":
        return "dels" + text[3:]
    if low.startswith("l'") or low.startswith("l’"):
        return "de " + text
    first = text.split(maxsplit=1)[0] if text.strip() else ""
    if _VOWEL_START_RE.match(first) and normalize_form(first) not in ("un", "una", "uns", "unes"):
        return "d'" + text
    return "de " + text


def contract_a(text: str) -> str:
    """«a» + sintagma amb contracció: al, als."""
    low = normalize_form(text)
    if low.startswith("el ") or low == "el":
        return "al" + text[2:]
    if low.startswith("els ") or low == "els":
        return "als" + text[3:]
    return "a " + text


def number_of(state: MatchState, tokens: Sequence[Token]) -> str | None:
    """Nombre d'un sintagma: primer pel determinant i, si no n'hi ha, per morfologia.

    L'heurística del determinant falla amb sintagmes sense article («cranis
    humans»); aleshores es demana el nombre del primer nom que el recurs
    morfològic conegui.
    """
    number = state.hints.number_of(tokens)
    if number is not None:
        return number
    for token in tokens:
        for entry in state.morphology.analyze(token.text):
            if entry.features.pos in ("noun", "adj") and entry.features.number is not None:
                return entry.features.number
    return None


def _apply_filter(
    name: str, text: str, tokens: Sequence[Token], state: MatchState, protected_first: bool
) -> str | None:
    if name == "cap":
        return text[:1].upper() + text[1:]
    if name == "lower":
        if protected_first or (tokens and tokens[0].text.isupper() and len(tokens[0].text) > 1):
            return text
        return text[:1].lower() + text[1:]
    if name == "de":
        return contract_de(text)
    if name == "a":
        return contract_a(text)
    if name == "strip":
        return text.strip()
    if name == "nocomma":
        return text.rstrip(", ")
    inflect = re.fullmatch(r"inflect\((.*)\)", name)
    if inflect:
        return _inflect(inflect.group(1), text, state)
    agree = re.fullmatch(r"agree\(([^,()]+),([^,()]+)\)", name)
    if agree:
        number = number_of(state, tokens)
        if number is None and len(tokens) == 1 and is_participle(tokens[0].text):
            number = participle_number(tokens[0].text)
        if number is None:
            return None
        return agree.group(1).strip() if number == "sg" else agree.group(2).strip()
    mapping = re.fullmatch(r"map\((.*)\)", name)
    if mapping:
        table: dict[str, str] = {}
        for pair in mapping.group(1).split(","):
            key, _, value = pair.partition("=")
            table[normalize_form(key)] = value.strip()
        replacement = table.get(normalize_form(text))
        if replacement is None:
            return None
        return match_casing(text, replacement)
    raise ConfigError(f"Filtre de plantilla desconegut: «{name}»")


def _inflect(arguments: str, text: str, state: MatchState) -> str | None:
    """Filtre ``inflect(lema, forma=reserva, ...)``.

    Prioritat explícita: primer el recurs morfològic, que conjuga el lema amb
    els trets de la forma trobada; si no en sap prou, el mapatge de reserva que
    la mateixa regla declara; si tampoc no hi és, no es proposa res.
    """
    lemma = ""
    fallback: dict[str, str] = {}
    for argument in arguments.split(","):
        key, separator, value = argument.partition("=")
        if separator:
            fallback[normalize_form(key)] = value.strip()
        elif not lemma:
            lemma = key.strip()
    if not lemma:
        raise ConfigError(f"El filtre «inflect({arguments})» necessita un lema")
    generated = inflect_like(state.morphology, text, lemma)
    if generated is None:
        generated = fallback.get(normalize_form(text))
    if generated is None:
        return None
    return match_casing(text, generated)


def render_template(template: str, match: Match, state: MatchState) -> str | None:
    """Omple una plantilla amb els grups de l'encaix. ``None`` si un filtre no és aplicable."""
    failed = False

    def substitute(placeholder: re.Match[str]) -> str:
        nonlocal failed
        name = placeholder.group(1)
        filters = [f for f in placeholder.group(2).split("|") if f]
        tokens = match.group_tokens(state, name)
        if not tokens and name not in match.groups:
            failed = True
            return ""
        text = match.group_text(state, name)
        bounds = match.groups[name]
        protected_first = state.is_protected_token(bounds[0])
        for name_ in filters:
            result = _apply_filter(name_, text, tokens, state, protected_first)
            if result is None:
                failed = True
                return ""
            text = result
        return text

    rendered = _PLACEHOLDER_RE.sub(substitute, template)
    return None if failed else rendered


def phrase_in(text: str, phrases: Sequence[str]) -> bool:
    return any(phrase_pattern(p).search(text) for p in phrases if p.strip())
