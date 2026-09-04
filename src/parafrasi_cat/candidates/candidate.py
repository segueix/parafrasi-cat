"""Un candidat: una versió alternativa d'una frase amb les transformacions aplicades."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import (
    Transformation,
    TransformationFamily,
    apply_transformations,
)

MULTI_TRANSFORM = "MULTI_TRANSFORM"
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,;:.!?»)])")


@dataclass(frozen=True, slots=True)
class Candidate:
    """Versió alternativa d'una frase (o d'un paràgraf).

    Atributs:
        sentence_index: Índex de la frase (o del paràgraf) dins del document.
        source_text: Text original.
        text: Text del candidat (igual a ``source_text`` si és el candidat identitat).
        transformations: Transformacions aplicades, ordenades per posició i
            relatives a ``source_text``.
    """

    sentence_index: int
    source_text: str
    text: str
    transformations: tuple[Transformation, ...] = ()

    @property
    def is_identity(self) -> bool:
        return not self.transformations and self.text == self.source_text

    @property
    def n_transformations(self) -> int:
        return len(self.transformations)

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(t.rule_id for t in self.transformations)

    @property
    def families(self) -> tuple[TransformationFamily, ...]:
        """Famílies estructurals de les transformacions, sense repeticions ni reparacions."""
        seen: dict[TransformationFamily, None] = {}
        for transformation in self.transformations:
            family = transformation.family
            if family is not TransformationFamily.REPAIR:
                seen.setdefault(family, None)
        return tuple(seen)

    @property
    def signature(self) -> str:
        """Signatura abstracta: ``ORIGINAL``, una família, o ``MULTI_TRANSFORM(A+B)``."""
        families = self.families
        if not families:
            return TransformationFamily.ORIGINAL.value
        if len(families) == 1:
            return families[0].value
        return f"{MULTI_TRANSFORM}({'+'.join(sorted(f.value for f in families))})"

    def structural_degree(self) -> float:
        """Grau de reredacció estructural (0-1): pes de cada família per la seva confiança."""
        total = sum(t.family.weight * t.confidence for t in self.transformations)
        return round(min(1.0, total), 4)

    @property
    def is_structural(self) -> bool:
        """Cert si alguna transformació canvia l'arquitectura de la frase."""
        return any(t.family.structural for t in self.transformations)

    def normalized_text(self) -> str:
        """Text sense espais repetits ni espais davant de puntuació.

        Serveix per detectar candidats gairebé idèntics: dos textos que només
        difereixen en això no aporten cap alternativa real. Les majúscules sí
        que compten: canvien el text.
        """
        collapsed = " ".join(self.text.split())
        return _SPACE_BEFORE_PUNCT_RE.sub(r"\1", collapsed)

    def change_ratio(self) -> float:
        """Proporció de caràcters canviats (0 = idèntic, 1 = completament diferent)."""
        if self.source_text == self.text:
            return 0.0
        return 1.0 - SequenceMatcher(a=self.source_text, b=self.text, autojunk=False).ratio()

    def result_spans(self) -> tuple[Span, ...]:
        """Interval que ocupa el ``text_after`` de cada transformació dins de ``text``."""
        spans: list[Span] = []
        shift = 0
        for transformation in self.transformations:
            start = transformation.changed_span.start + shift
            spans.append(Span(start, start + len(transformation.text_after)))
            shift += len(transformation.text_after) - transformation.changed_span.length
        return tuple(spans)

    def source_offset(self, offset: int) -> int | None:
        """Posició equivalent al text original, o ``None`` si cau en un tros canviat.

        Serveix per tornar a projectar sobre l'original una posició trobada al
        text del candidat (p. ex. el verb que una reparació ha de flexionar).
        """
        shift = 0
        for transformation in self.transformations:
            start = transformation.changed_span.start + shift
            end = start + len(transformation.text_after)
            if offset < start:
                return offset - shift
            if offset < end:
                return None
            shift += len(transformation.text_after) - transformation.changed_span.length
        return offset - shift

    def rule_at(self, offset: int) -> str:
        """Regla que ha escrit el fragment on cau la posició (buit si no n'hi ha cap)."""
        for transformation, span in zip(self.transformations, self.result_spans(), strict=True):
            if span.start <= offset < span.end:
                return transformation.rule_id
        return ""

    @classmethod
    def identity(cls, sentence_index: int, source_text: str) -> Candidate:
        return cls(sentence_index, source_text, source_text, ())

    @classmethod
    def from_transformations(
        cls,
        sentence_index: int,
        source_text: str,
        transformations: Iterable[Transformation],
    ) -> Candidate:
        ordered = tuple(sorted(transformations, key=lambda t: t.changed_span.start))
        return cls(
            sentence_index, source_text, apply_transformations(source_text, ordered), ordered
        )

    def describe(self) -> str:
        if self.is_identity:
            return "sense canvis"
        return "; ".join(t.describe() for t in self.transformations)

    def to_dict(self) -> dict[str, object]:
        return {
            "sentence_index": self.sentence_index,
            "source_text": self.source_text,
            "text": self.text,
            "transformations": [t.to_dict() for t in self.transformations],
            "change_ratio": round(self.change_ratio(), 4),
            "signature": self.signature,
            "families": [f.value for f in self.families],
            "structural_degree": self.structural_degree(),
        }
