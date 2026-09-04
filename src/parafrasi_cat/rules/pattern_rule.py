"""Regla declarativa basada en patrons de tokens (motor «pattern»)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from parafrasi_cat.analyzer.clitics import Certainty
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
from parafrasi_cat.syntax.analysis import SentenceSyntax, SyntaxToken, empty

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
        self._uses_syntax = uses_syntax(definition.conditions)

    @property
    def definition(self) -> RuleDefinition:
        return self._definition

    def propose(self, ctx: RuleContext) -> Iterable[Transformation]:
        tokens = tuple(t for t in ctx.sentence.tokens if t.kind is not TokenKind.SPACE)
        if not tokens:
            return
        definition = self._definition
        # L'anàlisi sintàctica només es demana si la regla la declara: la resta
        # de regles no paguen el cost del parser ni en canvien el comportament.
        syntax = ctx.parse() if self._uses_syntax else empty(ctx.text)
        state = MatchState(
            ctx.text,
            tokens,
            ctx.protected_spans,
            self._hints.for_lexicon(ctx.lexicon),
            ctx.morphology,
            syntax,
            frozenset(
                p.token_index for p in ctx.sentence.pronouns if p.certainty is Certainty.SURE
            ),
        )

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
        words = option.lower().replace("’", "'").split()
        if [t.lower.replace("’", "'") for t in tokens[: len(words)]] == words:
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
    finite = [t for t in tokens if state.is_finite(t)]
    if spec.get("has_finite_verb") is True and not finite:
        return False
    if spec.get("no_finite_verb") is True and finite:
        return False
    if not _structural_ok(spec, tokens, text, state, starts):
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


#: Condicions de grup que consulten l'estructura de la frase.
STRUCTURAL_KEYS = frozenset(
    {"is_subject", "is_adverbial_clause", "mood", "no_clitic", "single_clause", "exact",
     "is_apposition", "no_subject"}
)  # fmt: skip


def uses_syntax(conditions: Mapping[str, object]) -> bool:
    """Cert si alguna condició de la regla necessita l'anàlisi sintàctica."""
    if conditions.get("syntax"):
        return True
    groups = as_mapping(conditions, "groups")
    return any(
        isinstance(spec, Mapping) and any(key in STRUCTURAL_KEYS for key in spec)
        for spec in groups.values()
    )


def _structural_ok(
    spec: Mapping[str, object],
    tokens: Sequence[Token],
    text: str,
    state: MatchState,
    starts: Sequence[str],
) -> bool:
    """Condicions estructurals d'un grup.

    Amb una anàlisi sintàctica fiable són comprovacions sobre l'arbre de
    dependències; sense analitzador instal·lat, recorren a les heurístiques
    conservadores de sempre (i el motor, quan hi ha parser però no es refia de
    la frase, ja no arriba a provar cap regla estructural).
    """
    if not tokens:
        return True
    syntax = state.syntax
    start = tokens[0].span.start
    end = tokens[-1].span.end
    exact = as_str_list(spec, "exact")
    if exact and _normalized(text) not in {_normalized(option) for option in exact}:
        return False
    if spec.get("no_clitic") is True:
        first = state.tokens.index(tokens[0])
        if any(state.is_clitic(first + offset) for offset in range(len(tokens))):
            return False
    if spec.get("single_clause") is True and not _single_clause(tokens, state, starts):
        return False
    if spec.get("is_subject") is True:
        if syntax.confident:
            if not _is_subject_phrase(syntax, start, end):
                return False
        elif any(state.is_finite(t) for t in tokens):
            return False
    if spec.get("is_adverbial_clause") is True:
        if syntax.confident:
            if not _is_adverbial_clause(syntax, tokens, start, end):
                return False
        elif not any(state.is_finite(t) for t in tokens):
            return False
    mood = spec.get("mood")
    if isinstance(mood, str):
        if syntax.confident:
            finite = syntax.finite_tokens_in(start, end)
            if not finite or any(t.mood not in (mood, None) for t in finite):
                return False
        elif any(_guessed_mood(t) not in (mood, None) for t in tokens):
            return False
    if spec.get("is_apposition") is True:
        if not syntax.confident:
            return False
        head = _phrase_head(tokens, syntax)
        if head is None or head.dep != "appos":
            return False
        if not syntax.covers(head, start, end):
            return False
    if spec.get("no_subject") is True and syntax.confident:
        # Només un subjecte nominal fa personal la construcció: en «es considera
        # que X», la clàusula «que X» és el subjecte (csubj) i continua sent impersonal.
        for token in tokens:
            parsed = syntax.token_at(token.span.start)
            if parsed is None:
                continue
            if any(t.head == parsed.index and t.dep == "nsubj" for t in syntax.tokens):
                return False
    return True


#: Verbs que admeten una interrogativa indirecta amb «si» o «quan» com a complement
#: («no sap si vindrà», «pregunta quan acaba»): amb ells, una clàusula que
#: l'analitzador etiqueta com a complement no es pot tractar com a adverbial.
COMPLEMENT_TAKING_LEMMAS = frozenset(
    {
        "saber", "dir", "preguntar", "veure", "mirar", "comprovar", "decidir", "explicar",
        "entendre", "recordar", "ignorar", "dubtar", "pensar", "imaginar", "esbrinar",
        "determinar", "indicar", "especificar", "concretar", "demanar", "descobrir",
        "conèixer", "aclarir", "considerar", "avaluar", "valorar", "plantejar",
    }
)  # fmt: skip
#: Marcadors que també introdueixen interrogatives indirectes.
INTERROGATIVE_MARKERS = frozenset({"si", "quan", "on", "com"})


def _is_subject_phrase(syntax: SentenceSyntax, start: int, end: int) -> bool:
    """Cert si l'interval és el subjecte del nucli, o el seu començament.

    L'analitzador pot penjar una subordinada interposada del nom del subjecte
    («El roc, encara que tingui un nom menys evident, ...»); aleshores el
    subarbre del subjecte va més enllà del sintagma. Es demana que el subarbre
    comenci on comença el grup i que el nucli del subjecte hi sigui a dins.
    """
    subject = syntax.subject_of_root()
    if subject is None:
        return False
    first, _last = syntax.subtree_span(subject)
    return first == start and start <= subject.start < end


def _is_adverbial_clause(
    syntax: SentenceSyntax, tokens: Sequence[Token], start: int, end: int
) -> bool:
    """Cert si l'interval és exactament el subarbre d'una subordinada adverbial.

    S'accepta una clàusula ``advcl`` pengi d'on pengi (l'analitzador de vegades
    la penja del nom del subjecte en lloc del verb), una clàusula ``acl`` si
    comença per un marcador adverbial (el mateix cas, etiquetat com a adnominal)
    i una clàusula ``ccomp`` només si el seu marcador no pot obrir una
    interrogativa indirecta del verb principal: «no sap si vindrà» no és cap
    condicional.
    """
    root = syntax.root
    marker = tokens[0].lower.replace("’", "'") if tokens else ""
    for candidate in syntax.tokens:
        if candidate.dep not in ("advcl", "acl", "ccomp") or not syntax.covers(
            candidate, start, end
        ):
            continue
        if candidate.dep == "advcl":
            return True
        if candidate.dep == "acl":
            return marker not in ("que", "qui", "on")
        if marker not in INTERROGATIVE_MARKERS:
            return True
        head = next((t for t in syntax.tokens if t.index == candidate.head), None)
        lemma = (head.lemma.lower() if head is not None else "") or ""
        if root is not None and head is not None and head.index == root.index:
            return lemma not in COMPLEMENT_TAKING_LEMMAS
        return False
    return False


def _normalized(text: str) -> str:
    return " ".join(text.lower().replace("’", "'").split())


def _single_clause(tokens: Sequence[Token], state: MatchState, starts: Sequence[str]) -> bool:
    """Cert si, passat el marcador inicial, el grup no obre cap altra clàusula.

    Es busquen, a la resta del grup, els marcadors relatius i qualsevol de les
    locucions de ``starts`` senceres («encara que», «un cop»): un mot solt com
    «un» o «per» no compta.
    """
    low = [t.lower.replace("’", "'") for t in tokens]
    options = [o.lower().replace("’", "'").split() for o in starts if not o.startswith("@")]
    skip = 0
    for words in sorted(options, key=len, reverse=True):
        if low[: len(words)] == words:
            skip = len(words)
            break
    if skip == 0:
        return False
    rest = low[skip:]
    if any(word in RELATIVE_MARKERS for word in rest):
        return False
    return not any(
        rest[i : i + len(words)] == words
        for words in options
        for i in range(len(rest) - len(words) + 1)
    )


def _guessed_mood(token: Token) -> str | None:
    """Mode verbal segons l'endevinador, o ``None`` si no hi veu cap verb."""
    if not token.is_word:
        return None
    from parafrasi_cat.morphology.guesser import guess

    for entry in guess(token.text):
        if entry.features.pos == "verb" and entry.confidence >= 0.45:
            return entry.features.mood
    return None


def _phrase_head(tokens: Sequence[Token], syntax: SentenceSyntax) -> SyntaxToken | None:
    """Mot del grup del qual depenen tots els altres (el nucli del sintagma)."""
    parsed = [p for t in tokens if (p := syntax.token_at(t.span.start)) is not None]
    indices = {p.index for p in parsed}
    heads = [p for p in parsed if p.head not in indices or p.head == p.index]
    return heads[0] if len(heads) == 1 else None


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
            if any(state.is_finite(t) for t in tokens):
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
        if option == "@finite_verb" and state.is_finite(token):
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
    if isinstance(max_finite, int) and sum(1 for t in tokens if state.is_finite(t)) > max_finite:
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
    if not _syntax_ok(as_mapping(conditions, "syntax"), match, state):
        return False
    return _sentence_ok(as_mapping(conditions, "sentence"), match, state)


def _syntax_ok(spec: Mapping[str, object], match: Match, state: MatchState) -> bool:
    """Condicions que consulten l'analitzador sintàctic.

    Són **opt-in**: una regla que no declari un bloc ``syntax`` no les avalua
    mai i es comporta exactament com abans. Si el parser no està instal·lat i
    la regla n'exigeix un, la regla no s'aplica: davant del dubte, no es
    transforma.
    """
    if not spec:
        return True
    syntax = state.syntax
    if not syntax.confident:
        # Sense parser fiable, només passen les regles que no l'exigeixen.
        return spec.get("requires_parser") is not True
    span = match.span(state)
    if spec.get("no_clause_boundary") is True and syntax.crosses_clause_boundary(
        span.start, span.end
    ):
        return False
    wanted_number = spec.get("subject_number")
    if isinstance(wanted_number, str) and syntax.subject_number() != wanted_number:
        return False
    if spec.get("requires_subject") is True and syntax.main_subject() is None:
        return False
    max_clauses = spec.get("max_clauses")
    if isinstance(max_clauses, int) and len(syntax.clauses) > max_clauses:
        return False
    max_coordinations = spec.get("max_coordinations")
    if isinstance(max_coordinations, int) and len(syntax.coordinations) > max_coordinations:
        return False
    return not (spec.get("no_negation") is True and syntax.negations)


def _phrase_regex(phrase: str) -> str:
    parts = [re.escape(p) for p in phrase.split()]
    body = r"\s+".join(parts).replace("'", "['’]")
    return rf"(?<![^\W\d_]){body}(?![^\W\d_])"
