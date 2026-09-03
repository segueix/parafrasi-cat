"""Generació de múltiples candidats a partir de les transformacions proposades."""

from __future__ import annotations

from collections.abc import Iterable

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.core.errors import ConfigError, TransformationError
from parafrasi_cat.core.transformation import Transformation


class CandidateGenerator:
    """Construeix candidats combinant transformacions compatibles.

    Estratègia (deliberadament senzilla en aquesta fase):

    1. Sempre s'inclou el candidat identitat (la frase sense canvis).
    2. Cada transformació proposada genera un candidat amb només aquest canvi.
    3. Les transformacions es combinen de manera voraç per ordre de confiança
       (i risc ascendent) mentre no se solapin, fins a ``max_transformations``,
       i la combinació resultant genera un candidat addicional.

    Els candidats amb text repetit es descarten.
    """

    def __init__(self, *, max_transformations: int = 3, max_candidates: int = 20) -> None:
        if max_transformations < 1 or max_candidates < 1:
            raise ConfigError("max_transformations i max_candidates han de ser almenys 1")
        self._max_transformations = max_transformations
        self._max_candidates = max_candidates

    @property
    def max_transformations(self) -> int:
        return self._max_transformations

    def generate(
        self,
        sentence_index: int,
        source_text: str,
        proposals: Iterable[Transformation],
    ) -> tuple[Candidate, ...]:
        candidates: list[Candidate] = [Candidate.identity(sentence_index, source_text)]
        seen: set[str] = {source_text}

        ordered = sorted(
            (p for p in proposals if not p.is_identity and p.can_apply_to(source_text)),
            key=lambda t: (-t.confidence, t.semantic_risk.level, t.changed_span.start),
        )

        for transformation in ordered:
            self._add(candidates, seen, sentence_index, source_text, (transformation,))

        chosen: list[Transformation] = []
        for transformation in ordered:
            if len(chosen) >= self._max_transformations:
                break
            if all(not transformation.changed_span.overlaps(c.changed_span) for c in chosen):
                chosen.append(transformation)
        if len(chosen) >= 2:
            self._add(candidates, seen, sentence_index, source_text, tuple(chosen))

        return tuple(candidates[: self._max_candidates])

    @staticmethod
    def _add(
        candidates: list[Candidate],
        seen: set[str],
        sentence_index: int,
        source_text: str,
        transformations: tuple[Transformation, ...],
    ) -> None:
        try:
            candidate = Candidate.from_transformations(sentence_index, source_text, transformations)
        except TransformationError:
            return
        if candidate.text in seen:
            return
        seen.add(candidate.text)
        candidates.append(candidate)
