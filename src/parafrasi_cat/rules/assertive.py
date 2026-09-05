"""Normalització determinista de piles de modalització epistemològica.

Aquest motor no genera llenguatge lliurement: reconeix combinacions redundants
ja presents al text (p. ex. «potser podria ser possible que») i les redueix a
una sola formulació de possibilitat. La categoria epistemològica es conserva i
el validador continua tenint l'última paraula.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import Transformation
from parafrasi_cat.rules.base import Rule, RuleContext
from parafrasi_cat.rules.definition import RuleDefinition


_LEADING_STACKS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"^(?P<prefix>(?:potser|possiblement|tal vegada)\s+)"
            r"(?P<modal>podria)\s+ser\s+possible\s+que\b",
            re.IGNORECASE,
        ),
        "{modal} ser que",
    ),
    (
        re.compile(
            r"^(?P<prefix>sembla\s+que\s+)"
            r"(?P<modal>podria)\s+ser\s+possible\s+que\b",
            re.IGNORECASE,
        ),
        "{modal} ser que",
    ),
    (
        re.compile(
            r"^(?P<prefix>(?:potser|possiblement|tal vegada)\s+)"
            r"(?P<modal>podria|podrien)\b",
            re.IGNORECASE,
        ),
        "{modal}",
    ),
    (
        re.compile(
            r"^(?P<prefix>sembla\s+que\s+)"
            r"(?P<modal>podria|podrien)\b",
            re.IGNORECASE,
        ),
        "{modal}",
    ),
    (
        re.compile(r"^(?P<modal>podria)\s+ser\s+possible\s+que\b", re.IGNORECASE),
        "{modal} ser que",
    ),
)


class AssertiveNormalizationRule(Rule):
    """Redueix piles redundants de dubte/possibilitat sense pujar la certesa."""

    def __init__(self, definition: RuleDefinition) -> None:
        super().__init__(
            definition.rule_id,
            transformation_type=definition.transformation_type,
            description=definition.description,
            category=definition.category,
            level=definition.level,
        )
        self._definition = definition

    def propose(self, ctx: RuleContext) -> Iterable[Transformation]:
        text = ctx.text
        for pattern, template in _LEADING_STACKS:
            match = pattern.search(text)
            if match is None:
                continue
            modal = match.group("modal")
            replacement = template.format(modal=modal)
            if match.start() == 0 and text[:1].isupper():
                replacement = replacement[:1].upper() + replacement[1:]
            span = Span(match.start(), match.end())
            before = span.slice(text)
            if before == replacement or ctx.protected_conflict(span, replacement) is not None:
                continue
            yield Transformation(
                rule_id=self.rule_id,
                text_before=before,
                text_after=replacement,
                changed_span=span,
                transformation_type=self._definition.transformation_type,
                confidence=self._definition.confidence,
                semantic_risk=self._definition.semantic_risk,
                explanation=(
                    f"{self._definition.description} — «{before}» → «{replacement}»"
                ),
                metadata={
                    "category": self._definition.category,
                    "level": str(self._definition.level),
                    "family": "EPISTEMIC",
                    "assertive_priority": "redundancy",
                },
            )
            # Les expressions estan ancorades a l'inici i són alternatives entre si:
            # un sol candidat normalitzat per regla és suficient i evita duplicats.
            break


__all__ = ["AssertiveNormalizationRule"]
