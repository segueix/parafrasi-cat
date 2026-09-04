"""Observacions estilomètriques d'un document.

Aquest mòdul recorre l'anàlisi lingüística d'un text (paràgrafs, frases,
tokens, pronoms febles, expressions multiparaula) i en treu recomptes i
exemples: longituds, puntuació, connectors i posició, expressions
recurrents, estructures impersonals, primera persona, passiva, repetició
lèxica, densitat aproximada de noms i verbs i variants equivalents. Tot és
determinista i basat en regles i llistes editables
(``resources/ca/style/*.yaml``); no s'hi fa servir cap model.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from parafrasi_cat.analyzer.analysis import Analysis
from parafrasi_cat.analyzer.clitics import Certainty, PronounAttachment
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon, WordClass, normalize_form
from parafrasi_cat.analyzer.sentences import Sentence
from parafrasi_cat.analyzer.tokens import Token, TokenKind, TokenSubkind
from parafrasi_cat.core.errors import ResourceError
from parafrasi_cat.core.text import LETTER, phrase_pattern
from parafrasi_cat.morphology.guesser import guess
from parafrasi_cat.resources import (
    ProjectPaths,
    as_int,
    as_mapping,
    as_mapping_list,
    as_str,
    as_str_list,
    load_mapping,
)
from parafrasi_cat.style.syntax_profile import SentenceSyntaxStats, observe_sentence_syntax
from parafrasi_cat.syntax.analysis import SyntaxProvider

if TYPE_CHECKING:
    from parafrasi_cat.rules.patterns import GrammarHints

VARIANTS_FILE = "style/variants.yaml"
SETTINGS_FILE = "style/estilometria.yaml"
FINITE_VERBS_FILE = "transformations/verbs_finits_frequents.yaml"

_CONNECTOR_CLASSES = (WordClass.CONNECTOR, WordClass.DISCOURSE_MARKER)
_CONTENT_WORD_RE = re.compile(rf"^{LETTER}(?:{LETTER}|·|-)*$")
#: Participis amb dièresi (construït, conduïda) que el patró general no cobreix.
_DIAERESIS_PARTICIPLE_RE = re.compile(rf"^{LETTER}{{2,}}(?:ït|ïda|ïts|ïdes)$")
_FOLLOWED_BY_OPTIONS = ("", "determiner", "infinitive", "que")


# --- Recursos ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VariantSpec:
    id: str
    patterns: tuple[re.Pattern[str], ...]
    regex: re.Pattern[str] | None = None
    followed_by: str = ""
    not_followed_by: tuple[re.Pattern[str], ...] = ()


@dataclass(frozen=True, slots=True)
class VariantGroup:
    id: str
    description: str
    variants: tuple[VariantSpec, ...]

    @property
    def variant_ids(self) -> tuple[str, ...]:
        return tuple(v.id for v in self.variants)


@dataclass(frozen=True, slots=True)
class StyleSettings:
    """Paràmetres i llistes de ``resources/ca/style/estilometria.yaml``."""

    sentence_length_bins: tuple[tuple[int, int | None], ...]
    example_max_chars: int
    examples_per_feature: int
    ngram_min_count: int
    ngram_min_documents: int
    ngram_max_items: int
    ngram_sizes: tuple[int, ...]
    segment_size: int
    near_window: int
    top_words: int
    min_word_length: int
    cal_forms: frozenset[str]
    hi_ha_forms: frozenset[str]
    copula_forms: frozenset[str]
    copula_adjectives: frozenset[str]
    sembla_forms: frozenset[str]
    first_sg_pronouns: frozenset[str]
    first_sg_possessives: frozenset[str]
    first_sg_weak: str
    first_sg_o_stoplist: frozenset[str]
    first_pl_pronouns: frozenset[str]
    first_pl_possessives: frozenset[str]
    first_pl_weak: str
    first_pl_stoplist: frozenset[str]
    first_pl_suffix_stoplist: tuple[str, ...]
    passive_present: frozenset[str]
    passive_other: frozenset[str]
    passive_after_haver: frozenset[str]
    haver_forms: frozenset[str]
    agent_prepositions: frozenset[str]
    passive_adjective_stoplist: frozenset[str]
    skippable_adverbs: frozenset[str]
    noun_introducers: frozenset[str]

    @classmethod
    def from_mapping(cls, data: dict[str, object]) -> StyleSettings:
        bins: list[tuple[int, int | None]] = []
        raw_bins = data.get("sentence_length_bins", [])
        if isinstance(raw_bins, Sequence) and not isinstance(raw_bins, str):
            for item in raw_bins:
                if not isinstance(item, Sequence) or len(item) != 2:
                    raise ResourceError(
                        "sentence_length_bins ha de contenir parells [mínim, màxim]"
                    )
                low, high = item
                bins.append((int(low), None if high is None else int(high)))
        if not bins:
            bins = [(1, 10), (11, 20), (21, 30), (31, None)]
        ngrams = as_mapping(data, "recurrent_expressions")
        lexical = as_mapping(data, "lexical_repetition")
        impersonal = as_mapping(data, "impersonal")
        first = as_mapping(data, "first_person")
        first_sg = as_mapping(first, "singular")
        first_pl = as_mapping(first, "plural")
        passive = as_mapping(data, "passive")
        classes = as_mapping(data, "word_classes")

        def forms(mapping: dict[str, object], key: str) -> frozenset[str]:
            return frozenset(normalize_form(f) for f in as_str_list(mapping, key))

        return cls(
            sentence_length_bins=tuple(bins),
            example_max_chars=as_int(data, "example_max_chars", 110),
            examples_per_feature=as_int(data, "examples_per_feature", 3),
            ngram_min_count=as_int(ngrams, "min_count", 3),
            ngram_min_documents=as_int(ngrams, "min_documents", 2),
            ngram_max_items=as_int(ngrams, "max_items", 20),
            ngram_sizes=tuple(int(n) for n in as_str_list(ngrams, "ngram_sizes")) or (2, 3, 4),
            segment_size=as_int(lexical, "segment_size", 100),
            near_window=as_int(lexical, "near_window", 25),
            top_words=as_int(lexical, "top_words", 15),
            min_word_length=as_int(lexical, "min_word_length", 3),
            cal_forms=forms(impersonal, "cal_forms"),
            hi_ha_forms=forms(impersonal, "hi_ha_forms"),
            copula_forms=forms(impersonal, "copula_forms"),
            copula_adjectives=forms(impersonal, "copula_adjectives"),
            sembla_forms=forms(impersonal, "sembla_forms"),
            first_sg_pronouns=forms(first_sg, "pronouns"),
            first_sg_possessives=forms(first_sg, "possessives"),
            first_sg_weak=as_str(first_sg, "weak_pronoun", "em"),
            first_sg_o_stoplist=forms(first_sg, "verb_o_stoplist"),
            first_pl_pronouns=forms(first_pl, "pronouns"),
            first_pl_possessives=forms(first_pl, "possessives"),
            first_pl_weak=as_str(first_pl, "weak_pronoun", "ens"),
            first_pl_stoplist=forms(first_pl, "verb_em_stoplist"),
            first_pl_suffix_stoplist=tuple(as_str_list(first_pl, "verb_em_suffix_stoplist")),
            passive_present=forms(passive, "present_forms"),
            passive_other=forms(passive, "other_forms"),
            passive_after_haver=forms(passive, "participle_after_haver"),
            haver_forms=forms(passive, "haver_forms"),
            agent_prepositions=forms(passive, "agent_prepositions"),
            passive_adjective_stoplist=forms(passive, "adjective_stoplist"),
            skippable_adverbs=forms(passive, "skippable_adverbs"),
            noun_introducers=forms(classes, "noun_introducers"),
        )


def parse_variant_groups(data: dict[str, object]) -> tuple[VariantGroup, ...]:
    groups: list[VariantGroup] = []
    for group in as_mapping_list(data, "groups"):
        group_id = as_str(group, "id").strip()
        variants: list[VariantSpec] = []
        for item in as_mapping_list(group, "variants"):
            followed_by = as_str(item, "followed_by", "").strip()
            if followed_by not in _FOLLOWED_BY_OPTIONS:
                raise ResourceError(
                    f"followed_by desconegut «{followed_by}» al grup de variants «{group_id}»"
                )
            regex_text = as_str(item, "regex", "").strip()
            try:
                regex = re.compile(regex_text) if regex_text else None
            except re.error as exc:
                raise ResourceError(f"Expressió regular invàlida a «{group_id}»: {exc}") from exc
            variants.append(
                VariantSpec(
                    id=as_str(item, "id").strip(),
                    patterns=tuple(phrase_pattern(f) for f in as_str_list(item, "forms")),
                    regex=regex,
                    followed_by=followed_by,
                    not_followed_by=tuple(
                        re.compile(r"\s*" + re.escape(p.strip()) + rf"(?!{LETTER})", re.IGNORECASE)
                        for p in as_str_list(item, "not_followed_by")
                    ),
                )
            )
        if not variants:
            raise ResourceError(f"El grup de variants «{group_id}» no té variants")
        groups.append(VariantGroup(group_id, as_str(group, "description", ""), tuple(variants)))
    return tuple(groups)


@dataclass(frozen=True)
class StyleResources:
    """Lexicó, pistes gramaticals i llistes que necessita l'anàlisi estilomètrica."""

    lexicon: ClosedClassLexicon
    hints: GrammarHints
    settings: StyleSettings
    variant_groups: tuple[VariantGroup, ...]
    connector_info: dict[str, tuple[str, str]]

    @classmethod
    def load(
        cls,
        paths: ProjectPaths,
        language: str = "ca",
        *,
        lexicon: ClosedClassLexicon | None = None,
    ) -> StyleResources:
        from parafrasi_cat.rules.patterns import GrammarHints

        lang = paths.language(language)
        lexicon = lexicon if lexicon is not None else ClosedClassLexicon.load(lang)
        finite_file = lang / FINITE_VERBS_FILE
        finite = as_str_list(load_mapping(finite_file), "forms") if finite_file.is_file() else ()
        hints = GrammarHints.from_lexicon(lexicon, finite)
        settings_file = lang / SETTINGS_FILE
        settings = StyleSettings.from_mapping(
            load_mapping(settings_file) if settings_file.is_file() else {}
        )
        variants_file = lang / VARIANTS_FILE
        groups = (
            parse_variant_groups(load_mapping(variants_file)) if variants_file.is_file() else ()
        )
        info: dict[str, tuple[str, str]] = {}
        for entry in lexicon.entries:
            if entry.word_class in _CONNECTOR_CLASSES:
                info.setdefault(normalize_form(entry.form), (entry.function, entry.register))
        return cls(lexicon, hints, settings, groups, info)

    def variant_group(self, group_id: str) -> VariantGroup | None:
        return next((g for g in self.variant_groups if g.id == group_id), None)


# --- Observacions -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Hit:
    """Una ocurrència observada: tipus, text coincident i exemple curt."""

    kind: str
    text: str
    example: str
    extra: str = ""


@dataclass(frozen=True, slots=True)
class ConnectorHit:
    form: str
    function: str
    register: str
    position: str
    with_comma: bool
    example: str


@dataclass
class DocumentObservations:
    """Recomptes i exemples d'un document (sense el text sencer)."""

    name: str
    n_words: int = 0
    n_sentences: int = 0
    n_paragraphs: int = 0
    sentence_lengths: list[int] = field(default_factory=list)
    sentence_tokens: list[int] = field(default_factory=list)
    """Tokens lingüístics per frase (paraules, clítics i xifres), per al ritme."""
    paragraph_sentences: list[int] = field(default_factory=list)
    paragraph_words: list[int] = field(default_factory=list)
    paragraph_token_sequences: list[list[int]] = field(default_factory=list)
    """Seqüència de tokens per frase de cada paràgraf, si el document en conserva."""
    syntax: list[SentenceSyntaxStats] = field(default_factory=list)
    """Recomptes sintàctics de les frases amb una anàlisi fiable (buit sense parser)."""
    syntax_skipped: int = 0
    """Frases que el parser no ha pogut analitzar amb prou fiabilitat."""
    punctuation: Counter[str] = field(default_factory=Counter)
    commas_per_sentence: list[int] = field(default_factory=list)
    sentence_endings: Counter[str] = field(default_factory=Counter)
    connectors: list[ConnectorHit] = field(default_factory=list)
    ngrams: Counter[str] = field(default_factory=Counter)
    ngram_examples: dict[str, str] = field(default_factory=dict)
    content_tokens: list[str] = field(default_factory=list)
    impersonal: list[Hit] = field(default_factory=list)
    first_person: list[Hit] = field(default_factory=list)
    passive: list[Hit] = field(default_factory=list)
    word_classes: Counter[str] = field(default_factory=Counter)
    variants: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    @property
    def n_content_words(self) -> int:
        return len(self.content_tokens)


def snippet(text: str, start: int, end: int, max_chars: int = 110) -> str:
    """Fragment curt del text al voltant de ``[start, end)``, sense salts de línia."""
    if len(text) <= max_chars:
        return " ".join(text.split())
    room = max(0, max_chars - (end - start))
    left = max(0, start - room // 2)
    right = min(len(text), end + room - (start - left))
    if left > 0:
        space = text.find(" ", left, min(start, left + 20) + 1)
        left = space + 1 if space >= 0 else left
    if right < len(text):
        space = text.rfind(" ", max(end, right - 20), right + 1)
        right = space if space >= 0 else right
    left, right = min(left, start), max(right, end)
    piece = " ".join(text[left:right].split())
    return ("…" if left > 0 else "") + piece + ("…" if right < len(text) else "")


def _is_countable_word(token: Token) -> bool:
    return token.kind in (TokenKind.WORD, TokenKind.NUMBER)


def _first_lexical_index(tokens: Sequence[Token]) -> int:
    return next((i for i, t in enumerate(tokens) if t.is_lexical), -1)


def _last_lexical_index(tokens: Sequence[Token]) -> int:
    return next((i for i in range(len(tokens) - 1, -1, -1) if tokens[i].is_lexical), -1)


def _next_word_index(tokens: Sequence[Token], index: int, *, skip_clitics: bool = True) -> int:
    for j in range(index + 1, len(tokens)):
        token = tokens[j]
        if token.kind is TokenKind.WORD:
            return j
        if token.is_clitic and skip_clitics:
            continue
        return -1
    return -1


def _previous_word(tokens: Sequence[Token], index: int) -> Token | None:
    for j in range(index - 1, -1, -1):
        token = tokens[j]
        if token.is_lexical:
            return token
        return None
    return None


def _join_forms(forms: Sequence[str]) -> str:
    text = ""
    for form in forms:
        if text and not text.endswith(("'", "’")):
            text += " "
        text += form
    return text


class DocumentObserver:
    """Extreu :class:`DocumentObservations` d'una anàlisi lingüística."""

    def __init__(self, resources: StyleResources) -> None:
        self._r = resources
        self._s = resources.settings
        self._hints = resources.hints
        self._lexicon = resources.lexicon

    # -- entrada ----------------------------------------------------------------------

    def observe(
        self,
        analysis: Analysis,
        name: str = "text",
        *,
        syntax: SyntaxProvider | None = None,
    ) -> DocumentObservations:
        """Observa un document; amb ``syntax`` també en recompta l'estructura sintàctica."""
        obs = DocumentObservations(name=name)
        obs.n_sentences = analysis.n_sentences
        obs.n_paragraphs = analysis.n_paragraphs
        for paragraph in analysis.paragraphs:
            sentences = analysis.sentences_of(paragraph)
            obs.paragraph_sentences.append(len(sentences))
            obs.paragraph_words.append(
                sum(1 for s in sentences for t in s.tokens if _is_countable_word(t))
            )
            obs.paragraph_token_sequences.append(
                [sum(1 for t in s.tokens if t.is_lexical) for s in sentences]
            )
        for sentence in analysis.sentences:
            self._observe_sentence(sentence, obs)
            if syntax is not None and syntax.available:
                stats = observe_sentence_syntax(syntax.parse(sentence.text))
                if stats is None:
                    obs.syntax_skipped += 1
                else:
                    obs.syntax.append(stats)
        obs.n_words = sum(obs.sentence_lengths)
        return obs

    def _observe_sentence(self, sentence: Sentence, obs: DocumentObservations) -> None:
        tokens = sentence.tokens
        n_words = sum(1 for t in tokens if _is_countable_word(t))
        obs.sentence_lengths.append(n_words)
        obs.sentence_tokens.append(sum(1 for t in tokens if t.is_lexical))
        self._punctuation(sentence, obs)
        self._connectors(sentence, obs)
        self._ngrams_and_content(sentence, obs)
        self._impersonal(sentence, obs)
        first_person_verbs = self._first_person(sentence, obs)
        self._passive(sentence, obs)
        self._word_classes(sentence, obs, first_person_verbs)
        self._variants(sentence, obs)

    def _example(self, sentence: Sentence, start: int, end: int) -> str:
        return snippet(sentence.text, start, end, self._s.example_max_chars)

    # -- puntuació ----------------------------------------------------------------------

    def _punctuation(self, sentence: Sentence, obs: DocumentObservations) -> None:
        tokens = sentence.tokens
        commas = 0
        for token in tokens:
            if not token.is_punct:
                continue
            text = token.text
            if text == ",":
                commas += 1
                obs.punctuation["comma"] += 1
            elif text == ";":
                obs.punctuation["semicolon"] += 1
            elif text == ":":
                obs.punctuation["colon"] += 1
            elif token.subkind is TokenSubkind.BRACKET_OPEN:
                obs.punctuation["parenthesis"] += 1
            elif token.subkind is TokenSubkind.DASH or (
                token.subkind is TokenSubkind.HYPHEN and _spaced(sentence.text, token)
            ):
                obs.punctuation["dash"] += 1
            elif token.subkind is TokenSubkind.QUOTE_OPEN:
                obs.punctuation["quote"] += 1
            elif text == "?":
                obs.punctuation["question"] += 1
            elif text == "!":
                obs.punctuation["exclamation"] += 1
            elif text.startswith(("…", "...")):
                obs.punctuation["ellipsis"] += 1
        obs.commas_per_sentence.append(commas)
        last = tokens[-1] if tokens else None
        if last is not None and last.subkind is TokenSubkind.SENTENCE_END:
            key = {".": "period", "?": "question", "!": "exclamation"}.get(last.text[0], "ellipsis")
        else:
            key = "none"
        obs.sentence_endings[key] += 1

    # -- connectors -----------------------------------------------------------------------

    def _connectors(self, sentence: Sentence, obs: DocumentObservations) -> None:
        tokens = sentence.tokens
        first = _first_lexical_index(tokens)
        last = _last_lexical_index(tokens)
        covered: set[int] = set()

        def position(start: int, end: int) -> str:
            if start == first:
                return "initial"
            if end == last:
                return "final"
            return "medial"

        def with_comma(end: int) -> bool:
            return end + 1 < len(tokens) and tokens[end + 1].text == ","

        for expression in sentence.expressions:
            if expression.word_class not in _CONNECTOR_CLASSES or not expression.token_indices:
                continue
            start, end = min(expression.token_indices), max(expression.token_indices)
            covered.update(expression.token_indices)
            form = normalize_form(expression.lemma or expression.text)
            function, register = self._r.connector_info.get(form, (expression.function, ""))
            obs.connectors.append(
                ConnectorHit(
                    form=form,
                    function=function or expression.function,
                    register=register,
                    position=position(start, end),
                    with_comma=with_comma(end),
                    example=self._example(sentence, expression.span.start, expression.span.end),
                )
            )
        for index, token in enumerate(tokens):
            if index in covered or token.kind is not TokenKind.WORD:
                continue
            form = normalize_form(token.text)
            info = self._r.connector_info.get(form)
            if info is None:
                continue
            obs.connectors.append(
                ConnectorHit(
                    form=form,
                    function=info[0],
                    register=info[1],
                    position=position(index, index),
                    with_comma=with_comma(index),
                    example=self._example(sentence, token.span.start, token.span.end),
                )
            )

    # -- expressions recurrents i repetició lèxica ------------------------------------------

    def _is_closed(self, token: Token) -> bool:
        return token.is_clitic or self._hints.is_closed_class(token.text)

    def _ngrams_and_content(self, sentence: Sentence, obs: DocumentObservations) -> None:
        tokens = sentence.tokens
        first = _first_lexical_index(tokens)
        runs: list[list[tuple[str, bool, Token]]] = [[]]
        for index, token in enumerate(tokens):
            proper = token.text[:1].isupper() and index != first
            if token.is_word and not proper:
                low = normalize_form(token.text)
                closed = self._is_closed(token)
                runs[-1].append((low, closed, token))
                if (
                    token.kind is TokenKind.WORD
                    and not closed
                    and len(low) >= self._s.min_word_length
                    and _CONTENT_WORD_RE.match(low)
                ):
                    obs.content_tokens.append(low)
            elif runs[-1]:
                runs.append([])
        for run in runs:
            for size in self._s.ngram_sizes:
                for start in range(0, len(run) - size + 1):
                    window = run[start : start + size]
                    if all(closed for _, closed, _ in window):
                        continue
                    text = _join_forms([form for form, _, _ in window])
                    obs.ngrams[text] += 1
                    if text not in obs.ngram_examples:
                        obs.ngram_examples[text] = self._example(
                            sentence, window[0][2].span.start, window[-1][2].span.end
                        )

    # -- estructures impersonals --------------------------------------------------------------

    def _impersonal(self, sentence: Sentence, obs: DocumentObservations) -> None:
        tokens = sentence.tokens
        settings = self._s
        seen: set[int] = set()
        for pronoun in sentence.pronouns:
            if pronoun.canonical != "es" or pronoun.certainty is not Certainty.SURE:
                continue
            if pronoun.attachment not in (PronounAttachment.FREE, PronounAttachment.PROCLITIC):
                continue
            verb_index = _next_word_index(tokens, pronoun.token_index)
            if verb_index < 0:
                continue
            verb = tokens[verb_index]
            seen.add(verb_index)
            obs.impersonal.append(
                Hit(
                    "es + verb",
                    f"{pronoun.text} {verb.text}".replace("' ", "'"),
                    self._example(sentence, pronoun.span.start, verb.span.end),
                )
            )
        for index, token in enumerate(tokens):
            if token.kind is not TokenKind.WORD or index in seen:
                continue
            low = normalize_form(token.text)
            nxt = _next_word_index(tokens, index, skip_clitics=False)
            next_low = normalize_form(tokens[nxt].text) if nxt >= 0 else ""
            if low == "hom":
                kind = "hom"
                end = token.span.end
            elif low in settings.cal_forms:
                kind = "cal"
                end = token.span.end
            elif low == "hi" and next_low in settings.hi_ha_forms:
                kind = "hi ha"
                end = tokens[nxt].span.end
            elif low in settings.sembla_forms and next_low == "que":
                kind = "sembla que"
                end = tokens[nxt].span.end
            elif low in settings.copula_forms and next_low in settings.copula_adjectives:
                after = _next_word_index(tokens, nxt, skip_clitics=False)
                after_token = tokens[after] if after >= 0 else None
                if after_token is None:
                    continue
                after_low = normalize_form(after_token.text)
                if after_low in ("que", "de", "d'") or self._hints.is_infinitive(after_token):
                    kind = "és + adjectiu + que/infinitiu"
                    end = after_token.span.end
                else:
                    continue
            else:
                continue
            obs.impersonal.append(
                Hit(
                    kind,
                    sentence.text[token.span.start : end],
                    self._example(sentence, token.span.start, end),
                )
            )

    # -- primera persona ------------------------------------------------------------------------

    def _first_person(self, sentence: Sentence, obs: DocumentObservations) -> set[int]:
        tokens = sentence.tokens
        settings = self._s
        first = _first_lexical_index(tokens)
        verb_indices: set[int] = set()

        def add(kind: str, token: Token, sure: bool) -> None:
            obs.first_person.append(
                Hit(
                    kind,
                    token.text,
                    self._example(sentence, token.span.start, token.span.end),
                    "sure" if sure else "approximate",
                )
            )

        pronoun_indices: set[int] = set()
        for pronoun in sentence.pronouns:
            if pronoun.certainty is not Certainty.SURE:
                continue
            if pronoun.canonical == settings.first_sg_weak:
                add("singular", tokens[pronoun.token_index], True)
                pronoun_indices.add(pronoun.token_index)
            elif pronoun.canonical == settings.first_pl_weak:
                add("plural", tokens[pronoun.token_index], True)
                pronoun_indices.add(pronoun.token_index)
        for index, token in enumerate(tokens):
            if token.kind is not TokenKind.WORD or index in pronoun_indices:
                continue
            low = normalize_form(token.text)
            if low in settings.first_sg_pronouns or low in settings.first_sg_possessives:
                add("singular", token, True)
                continue
            if low in settings.first_pl_pronouns or low in settings.first_pl_possessives:
                add("plural", token, True)
                continue
            if self._hints.is_closed_class(low) or (token.text[:1].isupper() and index != first):
                continue
            if self._looks_first_singular_verb(tokens, index, low):
                add("singular", token, False)
                verb_indices.add(index)
            elif self._looks_first_plural_verb(low):
                add("plural", token, False)
                verb_indices.add(index)
        return verb_indices

    def _looks_first_singular_verb(self, tokens: Sequence[Token], index: int, low: str) -> bool:
        settings = self._s
        if len(low) < 4 or not low.endswith("o") or low in settings.first_sg_o_stoplist:
            return False
        if not _CONTENT_WORD_RE.match(low):
            return False
        previous = _previous_word(tokens, index)
        if previous is not None:
            plow = normalize_form(previous.text)
            if (
                self._hints.is_determiner(previous)
                or plow in self._hints.prepositions
                or plow in settings.noun_introducers
                or previous.kind is TokenKind.NUMBER
            ):
                return False
        return True

    def _looks_first_plural_verb(self, low: str) -> bool:
        settings = self._s
        if low in settings.first_pl_stoplist or low.endswith(settings.first_pl_suffix_stoplist):
            return False
        for entry in guess(low):
            features = entry.features
            if (
                features.pos == "verb"
                and features.person == "1"
                and features.number == "pl"
                and entry.confidence >= 0.3
            ):
                return True
        return False

    # -- passiva ----------------------------------------------------------------------------------

    def _passive(self, sentence: Sentence, obs: DocumentObservations) -> None:
        tokens = sentence.tokens
        settings = self._s
        for index, token in enumerate(tokens):
            if token.kind is not TokenKind.WORD:
                continue
            low = normalize_form(token.text)
            if low in settings.passive_adjective_stoplist or not _participle(low):
                continue
            if self._hints.is_closed_class(low) and low not in settings.passive_after_haver:
                continue
            j = index - 1
            if j >= 0 and normalize_form(tokens[j].text) in settings.skippable_adverbs:
                j -= 1
            if j < 0 or not tokens[j].is_word:
                continue
            aux_low = normalize_form(tokens[j].text)
            if aux_low in settings.passive_present:
                tier = "ambiguous"
            elif aux_low in settings.passive_other:
                tier = "sure"
            elif (
                aux_low in settings.passive_after_haver
                and j - 1 >= 0
                and normalize_form(tokens[j - 1].text) in settings.haver_forms
            ):
                tier = "sure"
                j -= 1
            else:
                continue
            agent = self._has_agent(tokens, index)
            if agent:
                tier = "sure"
            start = tokens[j].span.start
            obs.passive.append(
                Hit(
                    tier,
                    sentence.text[start : token.span.end],
                    self._example(sentence, start, token.span.end),
                    "agent" if agent else "",
                )
            )

    def _has_agent(self, tokens: Sequence[Token], participle_index: int) -> bool:
        settings = self._s
        for k in range(participle_index + 1, min(participle_index + 5, len(tokens))):
            token = tokens[k]
            if token.is_punct and token.text in ";.:":
                return False
            if normalize_form(token.text) in settings.agent_prepositions:
                following = normalize_form(tokens[k + 1].text) if k + 1 < len(tokens) else ""
                return following not in ("a", "tal", "què", "això", "tant")
        return False

    # -- densitat aproximada de classes de mots --------------------------------------------------

    def _word_classes(
        self, sentence: Sentence, obs: DocumentObservations, first_person_verbs: set[int]
    ) -> None:
        tokens = sentence.tokens
        first = _first_lexical_index(tokens)
        verb_precursors = self._hints.auxiliary_all | {"va", "van", "ser", "estat", "sigut"}
        for index, token in enumerate(tokens):
            if token.kind is not TokenKind.WORD:
                continue
            low = normalize_form(token.text)
            if self._hints.is_closed_class(low) or self._lexicon.has(low):
                obs.word_classes["function"] += 1
                continue
            previous = tokens[index - 1] if index > 0 else None
            prev_low = (
                normalize_form(previous.text) if previous is not None and previous.is_word else ""
            )
            if _participle(low):
                kind = "verb" if prev_low in verb_precursors else "other"
            elif (
                index in first_person_verbs
                or self._hints.is_finite_verb(token)
                or self._hints.is_infinitive(token)
                or _is_gerund(low)
            ):
                kind = "verb"
            elif self._looks_noun(previous, prev_low, token, index == first):
                kind = "noun"
            else:
                kind = "other"
            obs.word_classes[kind] += 1

    def _looks_noun(
        self, previous: Token | None, prev_low: str, token: Token, sentence_initial: bool
    ) -> bool:
        if previous is not None and (
            self._hints.is_determiner(previous)
            or prev_low in self._s.noun_introducers
            or previous.kind is TokenKind.NUMBER
        ):
            return True
        return token.text[:1].isupper() and not sentence_initial

    # -- variants equivalents ---------------------------------------------------------------------

    def _variants(self, sentence: Sentence, obs: DocumentObservations) -> None:
        tokens = sentence.tokens
        first = _first_lexical_index(tokens)
        for group in self._r.variant_groups:
            matches: list[tuple[int, int, str]] = []
            for variant in group.variants:
                for pattern in variant.patterns:
                    for match in pattern.finditer(sentence.text):
                        if self._variant_conditions_ok(sentence, variant, match.end()):
                            matches.append((match.start(), match.end(), variant.id))
                if variant.regex is None:
                    continue
                for index, token in enumerate(tokens):
                    if token.kind is not TokenKind.WORD:
                        continue
                    if token.text[:1].isupper() and index != first:
                        continue
                    low = normalize_form(token.text)
                    if self._hints.is_closed_class(low) or not variant.regex.match(low):
                        continue
                    matches.append((token.span.start, token.span.end, variant.id))
            if not matches:
                continue
            matches.sort(key=lambda m: (m[0], -(m[1] - m[0])))
            cursor = -1
            for start, end, variant_id in matches:
                if start < cursor:
                    continue
                cursor = end
                obs.variants.setdefault(group.id, {}).setdefault(variant_id, []).append(
                    self._example(sentence, start, end)
                )

    def _variant_conditions_ok(self, sentence: Sentence, variant: VariantSpec, end: int) -> bool:
        rest = sentence.text[end:]
        if any(p.match(rest) for p in variant.not_followed_by):
            return False
        if not variant.followed_by:
            return True
        following = next((t for t in sentence.tokens if t.span.start >= end), None)
        if following is None or following.is_punct:
            return False
        if variant.followed_by == "determiner":
            return self._hints.is_determiner(following) or following.kind is TokenKind.NUMBER
        if variant.followed_by == "infinitive":
            return self._hints.is_infinitive(following)
        return normalize_form(following.text) == "que"


def _participle(low: str) -> bool:
    from parafrasi_cat.rules.patterns import is_participle

    return is_participle(low) or _DIAERESIS_PARTICIPLE_RE.match(low) is not None


def _spaced(text: str, token: Token) -> bool:
    before = text[token.span.start - 1] if token.span.start > 0 else " "
    after = text[token.span.end] if token.span.end < len(text) else " "
    return before.isspace() and after.isspace()


def _is_gerund(low: str) -> bool:
    return any(
        entry.features.pos == "verb" and entry.features.mood == "ger" and entry.confidence >= 0.3
        for entry in guess(low)
    )
