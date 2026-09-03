"""Interfície base de les regles i context d'aplicació."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field

from parafrasi_cat.analyzer.sentences import Sentence
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import Transformation, TransformationType
from parafrasi_cat.morphology.provider import MorphologyProvider, NullMorphology
from parafrasi_cat.protected.spans import ProtectedSpan
from parafrasi_cat.style.profile import StyleProfile


@dataclass(frozen=True, slots=True)
class RuleContext:
    """Tot el que una regla pot consultar per proposar transformacions.

    Els intervals de ``protected_spans`` i dels tokens de ``sentence`` són
    relatius al text de la frase.
    """

    sentence: Sentence
    protected_spans: tuple[ProtectedSpan, ...] = ()
    document_text: str = ""
    style_profile: StyleProfile | None = None
    morphology: MorphologyProvider = field(default_factory=NullMorphology)

    @property
    def text(self) -> str:
        return self.sentence.text

    def overlapping_protected(self, span: Span) -> tuple[ProtectedSpan, ...]:
        return tuple(p for p in self.protected_spans if p.overlaps(span))

    def is_protected(self, span: Span) -> bool:
        """Cert si l'interval toca algun fragment protegit."""
        return any(p.overlaps(span) for p in self.protected_spans)


class Rule(ABC):
    """Una regla proposa transformacions sobre una frase; mai no les aplica.

    Contracte:

    - Cada transformació proposada ha de ser aplicable a ``ctx.text``.
    - Cap transformació no pot solapar-se amb un fragment protegit
      (la canonada ho comprova igualment, però la regla ha d'evitar-ho).
    - Cada transformació ha de portar una explicació en llenguatge natural.
    """

    def __init__(
        self,
        rule_id: str,
        *,
        transformation_type: TransformationType,
        description: str = "",
    ) -> None:
        if not rule_id:
            raise ValueError("Una regla necessita un identificador")
        self._rule_id = rule_id
        self._transformation_type = transformation_type
        self._description = description

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def transformation_type(self) -> TransformationType:
        return self._transformation_type

    @property
    def description(self) -> str:
        return self._description

    @abstractmethod
    def propose(self, ctx: RuleContext) -> Iterable[Transformation]:
        """Retorna les transformacions que la regla proposa per a la frase."""

    def __repr__(self) -> str:
        return f"{type(self).__name__}(rule_id={self._rule_id!r})"
