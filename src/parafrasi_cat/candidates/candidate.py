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
#: Rendiments decreixents d'una mateixa família: la k-èsima aplicació val ``0.5^(k−1)``.
FAMILY_DECAY = 0.5
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
        """Famílies de les transformacions, sense repeticions ni reparacions."""
        seen: dict[TransformationFamily, None] = {}
        for transformation in self.transformations:
            family = transformation.family
            if family is not TransformationFamily.REPAIR:
                seen.setdefault(family, None)
        return tuple(seen)

    @property
    def structural_families(self) -> tuple[TransformationFamily, ...]:
        """Famílies estructurals presents (les que reorganitzen la frase o el paràgraf)."""
        return tuple(f for f in self.families if f.structural)

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
        """Grau de reredacció estructural (0-1): només l'arquitectura lingüística.

        Hi compten únicament les transformacions de famílies estructurals
        (reordenació, subordinació, canvi de construcció, divisió, fusió). Cap
        substitució lèxica, de connector, de puntuació ni de flexió verbal no hi
        suma res, per moltes que se n'apliquin: tres canvis «va gaudir» → «gaudí»
        donen exactament 0.

        Cada transformació estructural aporta ``pes de la regla × confiança ×
        abast``, on l'abast és la part de la frase que el canvi reorganitza
        (reordenar tota l'oració pesa més que tocar-ne un sintagma; un canvi
        entre frases compta sencer). Les aportacions es combinen com a
        probabilitats independents, ``1 − Π(1 − a_i)``: el resultat mai no passa
        d'1, dues famílies diferents pesen més que dues aplicacions de la
        mateixa, i les repeticions d'una família tenen rendiments decreixents
        (la segona val la meitat; la tercera, un quart).
        """
        return _combine(self._impacts(structural=True))

    def surface_degree(self) -> float:
        """Grau de canvi superficial (0-1): mots, connectors, puntuació i flexió.

        Mateixa agregació que el grau estructural, sobre les famílies no
        estructurals. Serveix per explicar què ha canviat, no per premiar-ho.
        """
        return _combine(self._impacts(structural=False))

    def _impacts(self, *, structural: bool) -> list[float]:
        by_family: dict[TransformationFamily, list[float]] = {}
        length = max(1, len(self.source_text))
        for transformation in self.transformations:
            family = transformation.family
            if family.structural is not structural or family is TransformationFamily.REPAIR:
                continue
            if structural:
                coverage = min(1.0, transformation.changed_span.length / length)
                reach = 1.0 if family.cross_sentence else 0.5 + 0.5 * coverage
                impact = transformation.structural_weight * transformation.confidence * reach
            else:
                impact = family.surface_weight * transformation.confidence
            if impact > 0:
                by_family.setdefault(family, []).append(impact)
        impacts: list[float] = []
        for values in by_family.values():
            for rank, value in enumerate(sorted(values, reverse=True)):
                impacts.append(value * FAMILY_DECAY**rank)
        return impacts

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
            "structural_families": [f.value for f in self.structural_families],
            "structural_degree": self.structural_degree(),
            "surface_degree": self.surface_degree(),
        }


def _combine(impacts: Iterable[float]) -> float:
    """Combina aportacions (0-1) com a probabilitats independents: ``1 − Π(1 − a)``."""
    remaining = 1.0
    for impact in impacts:
        remaining *= 1.0 - max(0.0, min(1.0, impact))
    return round(1.0 - remaining, 4)
