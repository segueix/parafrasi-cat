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

from collections.abc import Iterable, Mapping
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
                if strategy.max_words_each and (
                    words_first > strategy.max_words_each or words_second > strategy.max_words_each
                ):
                    continue
                if words_first + words_second > strategy.max_words:
                    continue
                # Aquestes dues comprovacions no depenen de l'estratègia: si una
                # volia fusionar i no pot, cap altra no ho arreglarà.
                if not ctx.length_allows(words_first + words_second, _describe(first, second)):
                    break
                if not ctx.syntax_confident(first, second):
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
