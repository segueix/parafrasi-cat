"""Categories epistemològiques: què expressa el text sobre la seva pròpia certesa.

Només es classifica la força *expressada pel text*; el motor no sap res del
món. Una afirmació en indicatiu sense cap marcador és ``UNKNOWN``: no és cap
evidència.
"""

from __future__ import annotations

from enum import StrEnum


class EpistemicCategory(StrEnum):
    EVIDENCE = "EVIDENCE"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    LIMITATION = "LIMITATION"
    UNKNOWN = "UNKNOWN"

    @property
    def rank(self) -> int | None:
        """Posició a l'escala de certesa (``None`` per a la forma no marcada)."""
        return _RANKS[self]

    @property
    def label(self) -> str:
        return _LABELS[self]

    @classmethod
    def parse(cls, value: object) -> EpistemicCategory:
        text = str(value or "").strip().upper()
        try:
            return cls(text)
        except ValueError:
            return cls.UNKNOWN


_RANKS: dict[EpistemicCategory, int | None] = {
    EpistemicCategory.LIMITATION: 0,
    EpistemicCategory.HYPOTHESIS: 1,
    EpistemicCategory.INFERENCE: 2,
    EpistemicCategory.EVIDENCE: 3,
    EpistemicCategory.UNKNOWN: None,
}

_LABELS: dict[EpistemicCategory, str] = {
    EpistemicCategory.EVIDENCE: "evidència",
    EpistemicCategory.INFERENCE: "inferència",
    EpistemicCategory.HYPOTHESIS: "hipòtesi",
    EpistemicCategory.LIMITATION: "limitació",
    EpistemicCategory.UNKNOWN: "indeterminada",
}

__all__ = ["EpistemicCategory"]
