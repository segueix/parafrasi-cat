"""Puntuació i selecció de candidats.

La puntuació és multidimensional (preservació factual, epistemològica,
terminològica, gramaticalitat, semblança d'estil, grau de canvi) i qualsevol
error de preservació invalida el candidat.
"""

from parafrasi_cat.scoring.scorer import (
    DIMENSIONS,
    CompositeScorer,
    ScoreBreakdown,
    Scorer,
    ScoringContext,
)
from parafrasi_cat.scoring.selection import rank, select_best
from parafrasi_cat.scoring.weights import ScoringWeights

__all__ = [
    "DIMENSIONS",
    "CompositeScorer",
    "ScoreBreakdown",
    "Scorer",
    "ScoringContext",
    "ScoringWeights",
    "rank",
    "select_best",
]
