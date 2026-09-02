"""Recompte de marcadors lèxics (negació, modalitat, certesa...)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from parafrasi_cat.core.text import phrase_pattern


class MarkerSet:
    """Conjunt de paraules o locucions que es compten com a paraula sencera.

    Les ``exceptions`` són locucions que contenen un marcador però no en
    tenen el valor (p. ex. «no obstant això» conté «no» però no nega res):
    s'emmascaren abans de comptar.
    """

    def __init__(self, markers: Iterable[str], exceptions: Iterable[str] = ()) -> None:
        self._markers = tuple(dict.fromkeys(m.strip() for m in markers if m.strip()))
        self._patterns = tuple((m, phrase_pattern(m)) for m in self._markers)
        self._exceptions = tuple(dict.fromkeys(e.strip() for e in exceptions if e.strip()))
        self._exception_patterns = tuple(phrase_pattern(e) for e in self._exceptions)

    @property
    def markers(self) -> tuple[str, ...]:
        return self._markers

    @property
    def exceptions(self) -> tuple[str, ...]:
        return self._exceptions

    def __len__(self) -> int:
        return len(self._markers)

    def mask_exceptions(self, text: str) -> str:
        """Substitueix les excepcions per espais (conservant la longitud del text)."""
        for pattern in self._exception_patterns:
            text = pattern.sub(lambda m: " " * len(m.group(0)), text)
        return text

    def counts(self, text: str) -> Counter[str]:
        """Nombre d'ocurrències de cada marcador (en minúscules)."""
        masked = self.mask_exceptions(text)
        result: Counter[str] = Counter()
        for marker, pattern in self._patterns:
            n = len(pattern.findall(masked))
            if n:
                result[marker.lower()] = n
        return result

    def count(self, text: str) -> int:
        return sum(self.counts(text).values())
