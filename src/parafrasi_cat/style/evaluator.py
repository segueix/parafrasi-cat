"""Distància entre un text i un perfil d'estil."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from parafrasi_cat.analyzer.analysis import Analyzer
from parafrasi_cat.core.text import phrase_pattern
from parafrasi_cat.style.metrics import StyleMetrics, compute_style_metrics
from parafrasi_cat.style.profile import StyleProfile


@dataclass(frozen=True, slots=True)
class StyleDistance:
    """Distància (0 = coincideix amb el perfil, 1 = màximament allunyat)."""

    total: float
    components: dict[str, float]
    metrics: StyleMetrics

    def to_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "components": dict(self.components),
            "metrics": self.metrics.to_dict(),
        }


class StyleEvaluator:
    """Calcula la distància estilística d'un text respecte d'un perfil."""

    def __init__(
        self,
        profile: StyleProfile,
        analyzer: Analyzer,
        connectors: Iterable[str] = (),
    ) -> None:
        self._profile = profile
        self._analyzer = analyzer
        self._connectors = tuple(connectors)
        self._avoided = [phrase_pattern(w) for w in profile.avoided_words if w.strip()]
        self._preferred = [phrase_pattern(c) for c in profile.preferred_connectors if c.strip()]

    @property
    def profile(self) -> StyleProfile:
        return self._profile

    def distance(self, text: str) -> StyleDistance:
        metrics = compute_style_metrics(text, self._analyzer, self._connectors)
        components: dict[str, float] = {}

        deviation = abs(metrics.mean_sentence_length - self._profile.target_sentence_length)
        components["longitud_frase"] = _clip(deviation / self._profile.sentence_length_tolerance)

        if self._avoided:
            hits = sum(len(p.findall(text)) for p in self._avoided)
            components["mots_evitats"] = _clip(hits / max(metrics.n_words, 1) * 10)

        if self._preferred:
            hits = sum(len(p.findall(text)) for p in self._preferred)
            components["connectors_preferits"] = 0.0 if hits else 0.5

        total = sum(components.values()) / len(components) if components else 0.0
        return StyleDistance(total=total, components=components, metrics=metrics)


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))
