"""Selecció determinista del millor candidat."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.scoring.scorer import ScoreBreakdown

T = TypeVar("T")


def select_best(
    items: Sequence[T],
    candidate_of: Callable[[T], Candidate],
    score_of: Callable[[T], ScoreBreakdown],
) -> T | None:
    """Tria l'element amb puntuació més alta.

    En cas d'empat guanya el candidat amb menys transformacions (el més
    conservador) i, si persisteix l'empat, el primer de la seqüència.
    """
    best: T | None = None
    best_key: tuple[float, int] | None = None
    for item in items:
        key = (score_of(item).total, -len(candidate_of(item).transformations))
        if best_key is None or key > best_key:
            best, best_key = item, key
    return best
