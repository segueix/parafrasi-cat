"""Regla declarativa basada en patrons de tokens (motor «pattern»)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon
from parafrasi_cat.analyzer.tokens import Token, TokenKind
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import Transformation
from parafrasi_cat.resources import as_mapping, as_str_list
from parafrasi_cat.rules.base import Rule, RuleContext
from parafrasi_cat.rules.definition import RuleDefinition
from parafrasi_cat.rules.patterns import (
    RELATIVE_MARKERS,
    GrammarHints,
    Match,
    MatchState,
    PatternMatcher,
    contains_temporal,
    is_participle,
    phrase_in,
    render_template,
)

_LEADING_PUNCT = ",;.:)»”"


class HintsCache:
    """Reutilitza els :class:`GrammarHints` d'un mateix lexicó entre regles."""

    def __init__(self, finite_verbs: Sequence[str] = ()) -> None:
        self._finite_verbs = tuple(finite_verbs)
        self._cache: dict[int, GrammarHints] = {}

    def for_lexicon(self, lexicon: ClosedClassLexicon | None) -> GrammarHints:
        key = id(lexicon)
        hints = self._cache.get(key)
        if hints is None:
            hints = GrammarHints.from_lexicon(lexicon, self._finite_verbs)
            self._cache[key] = hints
        return hints


_DEFAULT_HINTS = HintsCache()


class PatternRule(Rule):
    """Regla que encaixa un patró de tokens i el reescriu amb una o més plantilles.

    Cada plantilla genera un candidat diferent. Les condicions i les excepcions
    de la definició filtren els encaixos; els fragments protegits que quedin
    dins de l'encaix s'han de conservar intactes.
    """

    def __init__(self, definition: RuleDefinition, *, hints: HintsCache | None = None) -> None:
        super().__init__(
            definition.rule_id,
            transformation_type=definition.transformation_type,
            description=definition.description,
            category=definition.category,
            level=definition.level,
        )
        if not definition.transformations:
            raise ValueError(f"La regla «{definition.rule_id}» no té cap plantilla")
        self._definition = definition
        self._matcher = PatternMatcher(definition.pattern)
        self._hints = hints or _DEFAULT_HINTS

    @property
    def definition(self) -> RuleDefinition:
        return self._definition

    def propose(self, ctx: RuleContext) -> Iterable[Transformation]:
        tokens = tuple(t for t in ctx.sentence.tokens if t.kind is not TokenKind.SPACE)
        if not tokens:
            return
        state = MatchState(
            ctx.text, tokens, ctx.protected_spans, self._hints.for_lexicon(ctx.lexicon)
        )
        definition = self._definition

        def accept(match: Match) -> bool:
            return check_conditions(definition.conditions, definition.exceptions, match, state)

        for match in self._matcher.find_all(state, accept):
            span = match.span(state)
            before = span.slice(ctx.text)
            for index, template in enumerate(definition.transformations):
                after = render_template(template, match, state)
                if after is None or after == before:
                    continue
                adjusted_span, adjusted_before = _absorb_leading_space(ctx.text, span, after)
                if ctx.protected_conflict(adjusted_span, after) is not None:
                    continue
                yield Transformation(
                    rule_id=self.rule_id,
                    text_before=adjusted_before,
                    text_after=after,
                    changed_span=adjusted_span,
                    transformation_type=definition.transformation_type,
                    confidence=definition.confidence,
                    semantic_risk=definition.semantic_risk,
                    explanation=f"{definition.description} — «{adjusted_before}» → «{after}»",
                    metadata={
                        "category": definition.category,
                        "level": str(definition.level),
                        "template": str(index),
                    },
                )


def _absorb_leading_space(text: str, span: Span, after: str) -> tuple[Span, str]:
    """Si el text nou comença per puntuació, absorbeix l'espai anterior («X (Y)» → «X, Y»)."""
    if after[:1] in _LEADING_PUNCT and span.start > 0 and text[span.start - 1] == " ":
        span = Span(span.start - 1, span.end)
    return span, span.slice(text)


# --- Condicions -------------------------------------------------------------------------------


def _first_low(tokens: Sequence[Token]) -> str:
    return tokens[0].lower.replace("’", "'") if tokens else ""


def _starts_with(tokens: Sequence[Token], options: Sequence[str], state: MatchState) -> bool:
    if not tokens:
        return False
    first = tokens[0]
    low = _first_low(tokens)
    for option in options:
        if option == "@determiner" and state.hints.is_determiner(first):
            return True
        if option == "@definite" and low in state.hints.definite:
            return True
        if (
            option == "@capitalized"
            and first.text[:1].isupper()
            and not state.hints.is_closed_class(low)
        ):
            return True
        if option == "@number" and first.kind is TokenKind.NUMBER:
            return True
        if option == "@participle" and is_participle(first.text):
            return True
        if option.startswith("@"):
            continue
        if low == option.lower().replace("’", "'"):
            return True
    return False


def _group_ok(
    spec: Mapping[str, object], tokens: Sequence[Token], text: str, state: MatchState
) -> bool:
    hints = state.hints
    starts = as_str_list(spec, "starts_with")
    if starts and not _starts_with(tokens, starts, state):
        return False
    not_starts = as_str_list(spec, "not_starts_with")
    if not_starts and _starts_with(tokens, not_starts, state):
        return False
    if spec.get("definite") is True and not _starts_with(
        tokens, ["@definite", "@capitalized"], state
    ):
        return False
    number = spec.get("number")
    if number is not None:
        actual = hints.number_of(tokens)
        if actual is None or (number != "known" and actual != number):
            return False
    max_tokens = spec.get("max_tokens")
    if isinstance(max_tokens, int) and len(tokens) > max_tokens:
        return False
    min_tokens = spec.get("min_tokens")
    if isinstance(min_tokens, int) and len(tokens) < min_tokens:
        return False
    finite = [t for t in tokens if hints.is_finite_verb(t)]
    if spec.get("has_finite_verb") is True and not finite:
        return False
    if spec.get("no_finite_verb") is True and finite:
        return False
    if spec.get("no_relative") is True and any(t.lower in RELATIVE_MARKERS for t in tokens):
        return False
    if spec.get("no_comma") is True and any(t.text == "," for t in tokens):
        return False
    if spec.get("no_punct") is True and any(t.kind is TokenKind.PUNCT for t in tokens):
        return False
    if spec.get("ends_with_participle") is True and not (tokens and is_participle(tokens[-1].text)):
        return False
    if spec.get("not_ends_with_participle") is True and tokens and is_participle(tokens[-1].text):
        return False
    not_ends = [w.lower().replace("’", "'") for w in as_str_list(spec, "not_ends_with")]
    if not_ends and tokens and tokens[-1].lower.replace("’", "'") in not_ends:
        return False
    if spec.get("not_protected") is True:
        span = Span(tokens[0].span.start, tokens[-1].span.end) if tokens else None
        if span is not None and any(p.overlaps(span) for p in state.protected):
            return False
    not_contains = as_str_list(spec, "not_contains")
    if not_contains and _contains_any(text, tokens, not_contains, state):
        return False
    contains_any = as_str_list(spec, "contains_any")
    return not (contains_any and not _contains_any(text, tokens, contains_any, state))


def _contains_any(
    text: str, tokens: Sequence[Token], options: Sequence[str], state: MatchState
) -> bool:
    for option in options:
        if option == "@temporal":
            if contains_temporal(text):
                return True
        elif option == "@participle":
            if any(is_participle(t.text) for t in tokens):
                return True
        elif option == "@finite_verb":
            if any(state.hints.is_finite_verb(t) for t in tokens):
                return True
        elif phrase_in(text, [option]):
            return True
    return False


def _context_ok(spec: Mapping[str, object], match: Match, state: MatchState) -> bool:
    before = state.tokens[match.start - 1] if match.start > 0 else None
    after = state.tokens[match.end] if match.end < len(state.tokens) else None
    for key, token in (("preceded_by", before), ("followed_by", after)):
        options = as_str_list(spec, key)
        if options and not _token_in(token, options, state, at_edge=key):
            return False
        negated = as_str_list(spec, "not_" + key)
        if negated and _token_in(token, negated, state, at_edge=key):
            return False
    return True


def _token_in(
    token: Token | None, options: Sequence[str], state: MatchState, *, at_edge: str
) -> bool:
    for option in options:
        if token is None:
            if option in ("@start", "@end"):
                return True
            continue
        low = token.lower.replace("’", "'")
        if option == "@punct" and token.kind is TokenKind.PUNCT:
            return True
        if option == "@word" and token.kind is TokenKind.WORD:
            return True
        if option == "@aux" and low in state.hints.auxiliary_all:
            return True
        if option == "@determiner" and state.hints.is_determiner(token):
            return True
        if option == "@finite_verb" and state.hints.is_finite_verb(token):
            return True
        if not option.startswith("@") and low == option.lower().replace("’", "'"):
            return True
    return False


def _sentence_ok(spec: Mapping[str, object], match: Match, state: MatchState) -> bool:
    tokens = state.tokens
    max_tokens = spec.get("max_tokens")
    if isinstance(max_tokens, int) and len(tokens) > max_tokens:
        return False
    min_tokens = spec.get("min_tokens")
    if isinstance(min_tokens, int) and len(tokens) < min_tokens:
        return False
    before = tokens[: match.start]
    if spec.get("no_relative_before") is True and any(t.lower in RELATIVE_MARKERS for t in before):
        return False
    if spec.get("no_comma_before") is True and any(t.text == "," for t in before):
        return False
    max_finite = spec.get("max_finite_verbs")
    if isinstance(max_finite, int) and (
        sum(1 for t in tokens if state.hints.is_finite_verb(t)) > max_finite
    ):
        return False
    not_contains = as_str_list(spec, "not_contains")
    return not (not_contains and phrase_in(state.text, not_contains))


def check_conditions(
    conditions: Mapping[str, object],
    exceptions: Sequence[str],
    match: Match,
    state: MatchState,
) -> bool:
    """Avalua les condicions declaratives d'una regla sobre un encaix."""
    span = match.span(state)
    if exceptions:
        for phrase in exceptions:
            for found in re.finditer(_phrase_regex(phrase), state.text, re.IGNORECASE):
                if Span(found.start(), found.end()).overlaps(span):
                    return False
    groups = as_mapping(conditions, "groups")
    for name, raw in groups.items():
        if not isinstance(raw, Mapping):
            continue
        spec = {str(k): v for k, v in raw.items()}
        tokens = match.group_tokens(state, name)
        if not tokens:
            if spec.get("required") is True:
                return False
            continue
        if not _group_ok(spec, tokens, match.group_text(state, name), state):
            return False
    if not _context_ok(as_mapping(conditions, "context"), match, state):
        return False
    return _sentence_ok(as_mapping(conditions, "sentence"), match, state)


def _phrase_regex(phrase: str) -> str:
    parts = [re.escape(p) for p in phrase.split()]
    body = r"\s+".join(parts).replace("'", "['’]")
    return rf"(?<![^\W\d_]){body}(?![^\W\d_])"
