"""Representació explícita d'una transformació aplicada a un text.

Cada canvi que el motor fa sobre una frase queda registrat com una
:class:`Transformation`, amb prou informació per explicar-lo, revertir-lo i
avaluar-ne el risc semàntic.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from parafrasi_cat.core.errors import TransformationError
from parafrasi_cat.core.spans import Span


class TransformationType(StrEnum):
    """Tipus de transformació, segons el nivell lingüístic que afecta."""

    LEXICAL = "lexical"
    """Substitució d'una paraula o locució per una d'equivalent."""

    CONNECTOR = "connector"
    """Substitució d'un connector discursiu per un altre de la mateixa funció."""

    SYNTACTIC = "syntactic"
    """Reordenació o canvi d'estructura de la frase sense canviar-ne el contingut."""

    MORPHOLOGICAL = "morphological"
    """Canvi de forma flexiva (p. ex. perífrasi verbal equivalent)."""

    PUNCTUATION = "punctuation"
    """Canvi de puntuació."""

    SENTENCE_SPLIT = "sentence_split"
    """Divisió d'una frase llarga en dues."""

    SENTENCE_MERGE = "sentence_merge"
    """Fusió de dues frases curtes."""

    IDENTITY = "identity"
    """Cap canvi (es fa servir per a candidats de referència)."""


class SemanticRisk(StrEnum):
    """Risc que una transformació alteri el significat del text original."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def level(self) -> int:
        """Nivell ordinal (0 = cap risc, 3 = risc alt)."""
        return _RISK_LEVELS[self]

    @property
    def weight(self) -> float:
        """Pes numèric entre 0 i 1 que fan servir els mòduls de puntuació."""
        return _RISK_WEIGHTS[self]

    def exceeds(self, limit: SemanticRisk) -> bool:
        """Cert si aquest risc és estrictament superior a ``limit``."""
        return self.level > limit.level

    @classmethod
    def parse(cls, value: str | SemanticRisk) -> SemanticRisk:
        if isinstance(value, SemanticRisk):
            return value
        try:
            return cls(value.strip().lower())
        except ValueError as exc:
            valid = ", ".join(member.value for member in cls)
            raise ValueError(f"Risc semàntic desconegut: {value!r} (vàlids: {valid})") from exc


_RISK_LEVELS: dict[SemanticRisk, int] = {
    SemanticRisk.NONE: 0,
    SemanticRisk.LOW: 1,
    SemanticRisk.MEDIUM: 2,
    SemanticRisk.HIGH: 3,
}

_RISK_WEIGHTS: dict[SemanticRisk, float] = {
    SemanticRisk.NONE: 0.0,
    SemanticRisk.LOW: 0.25,
    SemanticRisk.MEDIUM: 0.6,
    SemanticRisk.HIGH: 1.0,
}


@dataclass(frozen=True, slots=True)
class Transformation:
    """Un canvi concret, localitzat i explicable sobre una frase.

    Atributs:
        rule_id: Identificador de la regla que ha proposat el canvi.
        text_before: Fragment original exacte que es reemplaça.
        text_after: Fragment que el substitueix.
        changed_span: Posició de ``text_before`` dins de la frase d'origen.
        transformation_type: Nivell lingüístic del canvi.
        confidence: Confiança de la regla en el canvi (entre 0 i 1).
        semantic_risk: Risc estimat d'alterar el significat.
        explanation: Explicació en llenguatge natural del que s'ha canviat i per què.
        metadata: Informació addicional lliure (p. ex. la font del diccionari).
    """

    rule_id: str
    text_before: str
    text_after: str
    changed_span: Span
    transformation_type: TransformationType
    confidence: float
    semantic_risk: SemanticRisk
    explanation: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise ValueError("Una transformació necessita un rule_id")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"La confiança ha d'estar entre 0 i 1: {self.confidence}")
        if self.changed_span.length != len(self.text_before):
            raise ValueError(
                "La longitud de changed_span no coincideix amb text_before: "
                f"{self.changed_span.length} != {len(self.text_before)}"
            )

    @property
    def is_identity(self) -> bool:
        return self.text_before == self.text_after

    @property
    def result_span(self) -> Span:
        """Interval que ocupa ``text_after`` un cop aplicada la transformació."""
        return Span(self.changed_span.start, self.changed_span.start + len(self.text_after))

    def can_apply_to(self, text: str) -> bool:
        """Cert si el fragment de ``text`` a ``changed_span`` és exactament ``text_before``."""
        return self.changed_span.slice(text) == self.text_before

    def apply(self, text: str) -> str:
        """Aplica la transformació a ``text`` i retorna el text resultant."""
        if not self.can_apply_to(text):
            raise TransformationError(
                f"La transformació {self.rule_id} esperava «{self.text_before}» a "
                f"{self.changed_span.start}-{self.changed_span.end} però ha trobat "
                f"«{self.changed_span.slice(text)}»"
            )
        return text[: self.changed_span.start] + self.text_after + text[self.changed_span.end :]

    def describe(self) -> str:
        """Descripció llegible en una línia."""
        return (
            f"[{self.rule_id}] «{self.text_before}» → «{self.text_after}» "
            f"({self.transformation_type.value}, confiança {self.confidence:.2f}, "
            f"risc {self.semantic_risk.value}): {self.explanation}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "text_before": self.text_before,
            "text_after": self.text_after,
            "changed_span": self.changed_span.to_dict(),
            "transformation_type": self.transformation_type.value,
            "confidence": self.confidence,
            "semantic_risk": self.semantic_risk.value,
            "explanation": self.explanation,
            "metadata": dict(self.metadata),
        }


def apply_transformations(text: str, transformations: Iterable[Transformation]) -> str:
    """Aplica un conjunt de transformacions no solapades sobre ``text``.

    Les transformacions s'apliquen de dreta a esquerra perquè els intervals
    (definits sobre el text original) es mantinguin vàlids.
    """
    ordered = sorted(transformations, key=lambda t: t.changed_span.start)
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if previous.changed_span.overlaps(current.changed_span):
            raise TransformationError(
                f"Les transformacions {previous.rule_id} i {current.rule_id} se solapen"
            )
    result = text
    for transformation in reversed(ordered):
        result = transformation.apply(result)
    return result
