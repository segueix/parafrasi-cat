"""Intervals de caràcters dins d'un text."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class Span:
    """Interval semiobert ``[start, end)`` expressat en posicions de caràcter.

    Els intervals són immutables i es poden comparar i ordenar (primer per
    ``start`` i després per ``end``).
    """

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"Interval invàlid: start={self.start}, end={self.end}")

    @property
    def length(self) -> int:
        """Nombre de caràcters de l'interval."""
        return self.end - self.start

    @property
    def is_empty(self) -> bool:
        return self.length == 0

    def overlaps(self, other: Span) -> bool:
        """Cert si els dos intervals comparteixen almenys un caràcter."""
        return self.start < other.end and other.start < self.end

    def contains(self, other: Span) -> bool:
        """Cert si ``other`` queda completament dins d'aquest interval."""
        return self.start <= other.start and other.end <= self.end

    def contains_index(self, index: int) -> bool:
        return self.start <= index < self.end

    def shift(self, offset: int) -> Span:
        """Retorna l'interval desplaçat ``offset`` posicions."""
        return Span(self.start + offset, self.end + offset)

    def clip(self, bounds: Span) -> Span | None:
        """Retorna la intersecció amb ``bounds`` o ``None`` si és buida."""
        start = max(self.start, bounds.start)
        end = min(self.end, bounds.end)
        if start >= end:
            return None
        return Span(start, end)

    def slice(self, text: str) -> str:
        """Retorna el fragment de ``text`` cobert per l'interval."""
        return text[self.start : self.end]

    def to_dict(self) -> dict[str, int]:
        return {"start": self.start, "end": self.end}


def spans_overlap(spans: Iterable[Span]) -> bool:
    """Cert si algun parell d'intervals de la col·lecció se solapa."""
    ordered = sorted(spans)
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if previous.overlaps(current):
            return True
    return False
