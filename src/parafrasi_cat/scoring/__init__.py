"""Puntuació i selecció de candidats."""

from parafrasi_cat.scoring.scorer import CompositeScorer, ScoreBreakdown, Scorer
from parafrasi_cat.scoring.selection import select_best
from parafrasi_cat.scoring.weights import ScoringWeights

__all__ = ["CompositeScorer", "ScoreBreakdown", "Scorer", "ScoringWeights", "select_best"]
