"""Distància entre un text i un perfil d'estil.

Amb un perfil senzill, la distància només depèn de la longitud de frase, dels
mots evitats i dels connectors preferits. Si el perfil porta les preferències
d'un autor (empremta), s'hi afegeixen components que mesuren si el text fa
servir les variants, els connectors i la densitat de comes de l'autor.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from parafrasi_cat.analyzer.analysis import Analyzer
from parafrasi_cat.core.text import phrase_pattern
from parafrasi_cat.style.metrics import StyleMetrics, compute_style_metrics
from parafrasi_cat.style.observations import DocumentObserver, StyleResources
from parafrasi_cat.style.preferences import StylePreferences
from parafrasi_cat.style.profile import StyleProfile
from parafrasi_cat.style.statistics import relative_difference

_MIN_WORDS_FOR_PUNCTUATION = 15


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
        *,
        resources: StyleResources | None = None,
        preferences: StylePreferences | None = None,
    ) -> None:
        self._profile = profile
        self._analyzer = analyzer
        self._connectors = tuple(connectors)
        self._avoided = [phrase_pattern(w) for w in profile.avoided_words if w.strip()]
        self._preferred = [phrase_pattern(c) for c in profile.preferred_connectors if c.strip()]
        self._preferences = preferences if preferences is not None else profile.preferences
        self._observer = DocumentObserver(resources) if resources is not None else None

    @property
    def profile(self) -> StyleProfile:
        return self._profile

    @property
    def preferences(self) -> StylePreferences | None:
        return self._preferences

    def distance(self, text: str) -> StyleDistance:
        analysis = self._analyzer.analyze(text)
        metrics = compute_style_metrics(analysis, self._analyzer, self._connectors)
        components: dict[str, float] = {}

        deviation = abs(metrics.mean_sentence_length - self._profile.target_sentence_length)
        components["longitud_frase"] = _clip(deviation / self._profile.sentence_length_tolerance)

        if self._avoided:
            hits = sum(len(p.findall(text)) for p in self._avoided)
            components["mots_evitats"] = _clip(hits / max(metrics.n_words, 1) * 10)

        if self._preferred:
            hits = sum(len(p.findall(text)) for p in self._preferred)
            components["connectors_preferits"] = 0.0 if hits else 0.5

        if self._preferences is not None:
            self._author_components(analysis, metrics, components)

        total = sum(components.values()) / len(components) if components else 0.0
        return StyleDistance(total=total, components=components, metrics=metrics)

    def _author_components(
        self, analysis: object, metrics: StyleMetrics, components: dict[str, float]
    ) -> None:
        """Components basats en l'empremta de l'autor (només si hi ha prou evidència)."""
        from parafrasi_cat.analyzer.analysis import Analysis

        assert isinstance(analysis, Analysis)
        preferences = self._preferences
        assert preferences is not None
        author_commas = preferences.rate("punctuation.comma.per_100_words")
        if author_commas is not None and metrics.n_words >= _MIN_WORDS_FOR_PUNCTUATION:
            commas = sum(1 for s in analysis.sentences for t in s.tokens if t.text == ",")
            rate = commas / metrics.n_words * 100
            components["comes_autor"] = _clip(relative_difference(author_commas, rate))
        if self._observer is None:
            return
        observations = self._observer.observe(analysis)
        variant_penalties: list[float] = []
        for group_id, variants in observations.variants.items():
            if not preferences.is_reliable(f"variant_preferences.{group_id}"):
                continue
            for variant_id, examples in variants.items():
                share = preferences.variant_share(group_id, variant_id)
                if share is not None:
                    variant_penalties.extend([1.0 - share] * len(examples))
        if variant_penalties:
            components["variants_autor"] = _clip(sum(variant_penalties) / len(variant_penalties))
        connector_penalties: list[float] = []
        for hit in observations.connectors:
            share = preferences.connector_share(hit.form)
            if share is not None:
                connector_penalties.append(1.0 - share)
        if connector_penalties:
            components["connectors_autor"] = _clip(
                sum(connector_penalties) / len(connector_penalties)
            )


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))
