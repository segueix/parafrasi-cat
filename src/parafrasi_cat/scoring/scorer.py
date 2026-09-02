"""Puntuació de candidats."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.scoring.weights import ScoringWeights
from parafrasi_cat.style.evaluator import StyleEvaluator


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    """Puntuació total d'un candidat i desglossament per components."""

    total: float
    components: dict[str, float]
    explanation: str

    def to_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "components": dict(self.components),
            "explanation": self.explanation,
        }


@runtime_checkable
class Scorer(Protocol):
    def score(self, candidate: Candidate) -> ScoreBreakdown: ...


class CompositeScorer:
    """Puntuació composta: guany per transformacions segures menys distància d'estil.

    Un candidat idèntic a l'original té guany 0; un candidat amb canvis segurs
    (confiança alta, risc baix) obté un guany positiu, de manera que el motor
    prefereix reredactar quan pot fer-ho sense risc, i deixar el text intacte
    en cas contrari.
    """

    def __init__(
        self,
        weights: ScoringWeights | None = None,
        style_evaluator: StyleEvaluator | None = None,
    ) -> None:
        self._weights = weights or ScoringWeights()
        self._style = style_evaluator

    @property
    def weights(self) -> ScoringWeights:
        return self._weights

    def score(self, candidate: Candidate) -> ScoreBreakdown:
        w = self._weights
        gain = 0.0
        for t in candidate.transformations:
            gain += t.confidence * max(0.0, 1.0 - w.semantic_risk * t.semantic_risk.weight)
        gain = w.transformation_gain * gain / w.max_transformations

        components: dict[str, float] = {"transformacions": round(gain, 4)}
        parts = [f"guany per transformacions {gain:+.3f}"]

        style_penalty = 0.0
        if self._style is not None:
            distance = self._style.distance(candidate.text)
            style_penalty = w.style_distance * distance.total
            components["estil"] = round(-style_penalty, 4)
            parts.append(f"distància d'estil {-style_penalty:+.3f}")

        total = gain - style_penalty
        return ScoreBreakdown(
            total=round(total, 4),
            components=components,
            explanation="; ".join(parts),
        )
