"""Anàlisi estilomètrica i perfils d'estil.

Un :class:`StyleProfile` descriu l'estil objectiu (longitud de frase,
connectors preferits, mots a evitar...). Les :class:`StyleMetrics` es
calculen sobre qualsevol text i el :class:`StyleEvaluator` mesura la
distància entre les mètriques d'un candidat i el perfil.
"""

from parafrasi_cat.style.estimate import estimate_profile
from parafrasi_cat.style.evaluator import StyleDistance, StyleEvaluator
from parafrasi_cat.style.metrics import StyleMetrics, compute_style_metrics
from parafrasi_cat.style.profile import StyleProfile, load_style_profile

__all__ = [
    "StyleDistance",
    "StyleEvaluator",
    "StyleMetrics",
    "StyleProfile",
    "compute_style_metrics",
    "estimate_profile",
    "load_style_profile",
]
