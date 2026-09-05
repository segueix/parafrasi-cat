"""Fusió de frases compatibles (motor «fusion», regla de paràgraf).

Dues frases consecutives es fusionen només quan la segona comença per un
senyal declarat a les dades (connector, conjunció «però», anàfora
demostrativa) o quan totes dues són molt curtes. La transformació substitueix
el punt, l'espai i la primera paraula de la segona frase; el contingut de les
dues frases queda intacte.

Reestructurar en profunditat no vol dir escriure més llarg. Abans de fusionar
res es calcula la longitud de la frase resultant i es compara amb el que
l'autor acostuma a escriure: el seu màxim explícit, la distribució de la seva
empremta o la longitud que ha declarat preferir. Si la fusió se'n va, no es
proposa, i el motiu queda apuntat al resultat. Amb un autor de frase curta, la
reestructuració del nivell 5 recau en la divisió i la reordenació.

Quan hi ha parser instal·lat, tampoc no es fusiona res si l'anàlisi d'alguna
de les dues frases no és fiable: un fragment no s'ha de tocar.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from parafrasi_cat.analyzer.sentences import Sentence
from parafrasi_cat.analyzer.tokens import Token, TokenKind, TokenSubkind
from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import SemanticRisk, Transformation
from parafrasi_cat.resources import as_int, as_mapping_list, as_str, as_str_list
from parafrasi_cat.rules.base import ParagraphContext, ParagraphRule
from parafrasi_cat.rules.definition import RuleDefinition
from parafrasi_cat.rules.pattern_rule import HintsCache
from parafrasi_cat.rules.patterns import GrammarHints
from parafrasi_cat.syntax.analysis import COPULA_DEPS


@dataclass(frozen=True, slots=True)
class FusionStrategy:
    """Com fusionar dues frases quan la segona comença per un dels senyals."""

    strategy_id: str
    joiner: str
    triggers: tuple[str, ...] = ()
    """Inicis de la segona frase que activen l'estratègia (buit = qualsevol inici)."""
    max_words: int = 40
    max_words_each: int = 0
    semantic_risk: SemanticRisk | None = None
    lowercase: bool = True
    skip_if_second_starts_with: tuple[str, ...] = ()
    """Inicis de la segona frase que l'estratègia no toca (una còpula: «És B.»)."""
    nominal_fragment: bool = False
    """Cert si la segona frase ha de ser un fragment nominal anafòric (només amb analitzador)."""

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> FusionStrategy:
        risk = data.get("semantic_risk")
        return cls(
            strategy_id=as_str(data, "id"),
            joiner=as_str(data, "joiner"),
            triggers=tuple(t.lower() for t in as_str_list(data, "triggers")),
            max_words=as_int(data, "max_words", 40),
            max_words_each=as_int(data, "max_words_each", 0),
            semantic_risk=None if risk is None else SemanticRisk.parse(str(risk)),
            lowercase=bool(data.get("lowercase", True)),
            skip_if_second_starts_with=tuple(
                t.lower() for t in as_str_list(data, "skip_if_second_starts_with")
            ),
            nominal_fragment=data.get("nominal_fragment") is True,
        )


class SentenceFusionRule(ParagraphRule):
    """Fusiona parelles de frases consecutives segons les estratègies declarades."""

    def __init__(self, definition: RuleDefinition, *, hints: HintsCache | None = None) -> None:
        self._hints = hints or HintsCache()
        super().__init__(
            definition.rule_id,
            transformation_type=definition.transformation_type,
            description=definition.description,
            category=definition.category,
            level=definition.level,
        )
        self._definition = definition
        self._strategies = tuple(
            FusionStrategy.from_mapping(item)
            for item in as_mapping_list(definition.params, "strategies")
        )
        if not self._strategies:
            raise ConfigError(f"La regla «{definition.rule_id}» necessita «strategies»")

    @property
    def strategies(self) -> tuple[FusionStrategy, ...]:
        return self._strategies

    def propose(self, ctx: ParagraphContext) -> Iterable[Transformation]:
        sentences = ctx.sentences
        for first, second in zip(sentences, sentences[1:], strict=False):
            if not _fusable(first, second, ctx.text):
                continue
            first_token = second.tokens[0]
            start_text = second.text.lower()
            words_first = len(first.words)
            words_second = len(second.words)
            for strategy in self._strategies:
                if strategy.triggers and not any(
                    _starts_with_phrase(start_text, t) for t in strategy.triggers
                ):
                    continue
                if any(
                    _starts_with_phrase(start_text, t) for t in strategy.skip_if_second_starts_with
                ):
                    continue
                if strategy.max_words_each and (
                    words_first > strategy.max_words_each or words_second > strategy.max_words_each
                ):
                    continue
                if words_first + words_second > strategy.max_words:
                    continue
                # La longitud no depèn de l'estratègia: si una volia fusionar i no
                # pot, cap altra no ho arreglarà.
                if not ctx.length_allows(words_first + words_second, _describe(first, second)):
                    break
                if strategy.nominal_fragment:
                    # Un fragment nominal («Un fet que...») no supera mai el criteri
                    # de confiança: aquí és precisament el que es demana, i la
                    # primera frase ha de ser una oració fiable.
                    if not _anaphoric_fragment(ctx, first, second):
                        continue
                elif not ctx.syntax_confident(first, second):
                    ctx.note(
                        f"no s'han fusionat {_describe(first, second)}: l'analitzador sintàctic "
                        "no es refia de l'estructura d'alguna de les dues"
                    )
                    break
                period = first.span.end - 1
                span = Span(period, second.span.start + first_token.span.end)
                before = span.slice(ctx.text)
                head = first_token.text
                first_abs = Span(second.span.start, second.span.start + first_token.span.end)
                if strategy.lowercase and not _keep_case(head, first_abs, ctx):
                    if not self._known_word(first_token, strategy, ctx):
                        continue  # podria ser un nom propi no detectat: no fusionem
                    head = head[:1].lower() + head[1:]
                after = strategy.joiner + head
                if ctx.protected_conflict(span, after) is not None:
                    continue
                yield Transformation(
                    rule_id=self.rule_id,
                    text_before=before,
                    text_after=after,
                    changed_span=span,
                    transformation_type=self._definition.transformation_type,
                    confidence=self._definition.confidence,
                    semantic_risk=strategy.semantic_risk or self._definition.semantic_risk,
                    explanation=(
                        f"{self._definition.description} ({strategy.strategy_id}): "
                        f"«{first.text}» + «{second.text}»"
                    ),
                    metadata={
                        "category": self._definition.category,
                        "level": str(self._definition.level),
                        "strategy": strategy.strategy_id,
                        "family": "CLAUSE_MERGE",
                    },
                )
                break  # una sola estratègia per parella

    def _known_word(self, token: Token, strategy: FusionStrategy, ctx: ParagraphContext) -> bool:
        """Cert si la paraula inicial és coneguda (mot gramatical, senyal o verb conjugat)."""
        low = token.lower.replace("’", "'")
        if any(t.split()[0] == low for t in strategy.triggers if t):
            return True
        if ctx.lexicon is not None and ctx.lexicon.has(low):
            return True
        return self._hints.for_lexicon(ctx.lexicon).is_finite_verb(token)


#: Formes de còpula amb què pot començar la segona frase («És B.»).
COPULAS = frozenset({"és", "són", "era", "eren"})
#: Adverbis de restricció que, amb la negació, donen «no és només A, sinó també B».
ONLY_ADVERBS = frozenset({"només", "solament", "únicament"})
#: Predicats que no són atributs de debò («és a dir», «és clar», «és possible»...).
COPULAR_EXCEPTIONS: tuple[str, ...] = (
    "a dir", "clar", "possible", "probable", "evident", "cert", "necessari", "obvi",
    "veritat", "que", "si", "on", "quan", "com", "per", "més", "menys",
)  # fmt: skip
MAX_PREDICATE_WORDS = 8


class CopularFusionRule(ParagraphRule):
    """Fusiona dues frases copulatives amb el mateix subjecte (motor «copular_fusion»).

    Patrons que reconeix, amb la mateixa forma de còpula a totes dues frases i
    la segona sense subjecte propi:

    - «S no és només A. És B.» → «S no és només A, sinó també B.»;
    - «S no és A. És B.» → «S no és A, sinó B.» (risc mitjà: afirma el contrast);
    - «S és A. És B.» → «S és A i B.».

    Condicions: predicats curts, sense verb conjugat, sense coma ni «que»;
    la segona frase no pot començar per una locució com «és a dir» o «és
    clar»; i, amb analitzador, la còpula de la primera ha de ser la de l'oració
    principal i la segona no pot tenir cap subjecte explícit. La fusió
    respecta la longitud de frase de l'autor, com la resta de fusions.
    """

    def __init__(self, definition: RuleDefinition, *, hints: HintsCache | None = None) -> None:
        self._hints = hints or HintsCache()
        super().__init__(
            definition.rule_id,
            transformation_type=definition.transformation_type,
            description=definition.description,
            category=definition.category,
            level=definition.level,
        )
        self._definition = definition

    def propose(self, ctx: ParagraphContext) -> Iterable[Transformation]:
        sentences = ctx.sentences
        hints = self._hints.for_lexicon(ctx.lexicon)
        for first, second in zip(sentences, sentences[1:], strict=False):
            if not _fusable(first, second, ctx.text):
                continue
            head = second.tokens[0]
            copula = head.lower
            if copula not in COPULAS or head.kind is not TokenKind.WORD:
                continue
            predicate_b = _predicate(second.tokens[1:], hints)
            if predicate_b is None:
                continue
            found = _first_copula(first, copula, hints)
            if found is None:
                continue
            copula_index, negated, only = found
            words = len(first.words) + len(second.words) - 1
            if not ctx.length_allows(words, _describe(first, second)):
                continue
            if not self._syntax_allows(ctx, first, second, copula_index):
                continue
            risk = self._definition.semantic_risk
            if negated and only:
                joiner, strategy = ", sinó també", "no_nomes_sino_tambe"
            elif negated:
                joiner, strategy, risk = ", sinó", "no_sino", SemanticRisk.MEDIUM
            else:
                joiner, strategy = " i", "coordinacio_predicats"
            period = first.span.end - 1
            span = Span(period, second.span.start + head.span.end)
            before = span.slice(ctx.text)
            if ctx.protected_conflict(span, joiner) is not None:
                continue
            yield Transformation(
                rule_id=self.rule_id,
                text_before=before,
                text_after=joiner,
                changed_span=span,
                transformation_type=self._definition.transformation_type,
                confidence=self._definition.confidence,
                semantic_risk=risk,
                explanation=(
                    f"{self._definition.description} ({strategy}): «{first.text}» + «{second.text}»"
                ),
                metadata={
                    "category": self._definition.category,
                    "level": str(self._definition.level),
                    "strategy": strategy,
                    "family": "COPULAR_MERGE",
                },
            )

    def _syntax_allows(
        self, ctx: ParagraphContext, first: Sentence, second: Sentence, copula_index: int
    ) -> bool:
        """Amb analitzador: còpula principal a la primera i cap subjecte a la segona."""
        if not ctx.syntax.available:
            return True
        analysis_first = ctx.parse_sentence(first)
        analysis_second = ctx.parse_sentence(second)
        if not analysis_first.confident or not analysis_second.confident:
            ctx.note(
                f"no s'han fusionat {_describe(first, second)}: l'analitzador sintàctic "
                "no es refia de l'estructura d'alguna de les dues"
            )
            return False
        root = analysis_first.root
        copula_token = analysis_first.token_at(first.tokens[copula_index].span.start)
        if root is None or copula_token is None:
            return False
        if not (copula_token.dep == "cop" and copula_token.head == root.index):
            return False
        second_root = analysis_second.root
        if second_root is None:
            return False
        has_copula = any(
            t.head == second_root.index and t.dep == "cop" for t in analysis_second.tokens
        )
        has_subject = any(
            t.head == second_root.index and t.dep in ("nsubj", "csubj")
            for t in analysis_second.tokens
        )
        return has_copula and not has_subject


def _predicate(tokens: Sequence[Token], hints: GrammarHints) -> tuple[Token, ...] | None:
    """Predicat curt i simple (sense verb conjugat, coma ni «que»), o ``None``."""
    body = [t for t in tokens if not (t.kind is TokenKind.PUNCT and t.text == ".")]
    if not body or body != list(tokens[: len(body)]):
        return None
    words = [t for t in body if t.is_lexical]
    if not words or len(words) > MAX_PREDICATE_WORDS:
        return None
    low = " ".join(t.lower for t in body)
    if any(_starts_with_phrase(low, exception) for exception in COPULAR_EXCEPTIONS):
        return None
    for token in body:
        if token.kind is TokenKind.PUNCT and token.text not in ("'", "’"):
            return None
        if token.lower in ("que", "si", "no", "ni") or hints.is_finite_verb(token):
            return None
    return tuple(body)


def _first_copula(
    sentence: Sentence, copula: str, hints: GrammarHints
) -> tuple[int, bool, bool] | None:
    """Última còpula de la primera frase amb un predicat simple fins al punt final.

    Retorna l'índex del token de la còpula, si va negada i si duu «només».
    """
    tokens = sentence.tokens
    for index in range(len(tokens) - 2, 0, -1):
        token = tokens[index]
        if token.lower != copula or token.kind is not TokenKind.WORD:
            continue
        predicate = _predicate(tokens[index + 1 :], hints)
        if predicate is None:
            return None
        only = predicate[0].lower in ONLY_ADVERBS
        if only and len(predicate) < 2:
            return None
        negated = any(t.lower in ("no",) for t in tokens[max(0, index - 2) : index])
        return index, negated, only
    return None


#: Categories que poden ser nucli d'un fragment nominal anafòric.
NOMINAL_POS = frozenset({"NOUN", "PROPN", "PRON"})


def _anaphoric_fragment(ctx: ParagraphContext, first: Sentence, second: Sentence) -> bool:
    """Cert si la segona frase és un sintagma nominal amb relativa i la primera, fiable.

    Només amb analitzador: el nucli de la segona ha de ser un nom (no un verb ni
    un predicat amb còpula), amb una relativa que en depengui i sense cap altre
    verb principal; la primera ha de superar el criteri de confiança.
    """
    if not ctx.syntax.available:
        return False
    if not ctx.parse_sentence(first).confident:
        return False
    analysis = ctx.parse_sentence(second)
    root = analysis.root
    if root is None or root.pos not in NOMINAL_POS:
        return False
    if any(t.head == root.index and t.dep in COPULA_DEPS for t in analysis.tokens):
        return False
    return any(t.head == root.index and t.dep in ("acl", "acl:relcl") for t in analysis.tokens)


def _describe(first: Sentence, second: Sentence) -> str:
    """Les dues frases, retallades, per als missatges del resultat."""
    return f"«{_shorten(first.text)}» i «{_shorten(second.text)}»"


def _shorten(text: str, limit: int = 40) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _fusable(first: Sentence, second: Sentence, text: str) -> bool:
    if not first.tokens or not second.tokens:
        return False
    last = first.tokens[-1]
    if last.kind is not TokenKind.PUNCT or last.text != ".":
        return False
    if len(first.tokens) >= 2 and first.tokens[-2].subkind is TokenSubkind.ABBREVIATION:
        return False
    gap = text[first.span.end : second.span.start]
    if not gap or not gap.isspace() or "\n" in gap or "\r" in gap:
        return False
    if second.tokens[0].kind is TokenKind.PUNCT:
        return False
    return any(t.kind is TokenKind.PUNCT and t.text == "." for t in second.tokens[-1:])


def _starts_with_phrase(text: str, phrase: str) -> bool:
    if not text.startswith(phrase):
        return False
    rest = text[len(phrase) :]
    return rest == "" or not rest[0].isalpha()


def _keep_case(head: str, span: Span, ctx: ParagraphContext) -> bool:
    if ctx.is_protected(span):
        return True
    return head.isupper() and len(head) > 1
