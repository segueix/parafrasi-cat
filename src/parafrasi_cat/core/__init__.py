"""Tipus de dades compartits per tots els mòduls del motor.

Aquest paquet no depèn de cap altre mòdul de ``parafrasi_cat``: conté els
conceptes bàsics (intervals, transformacions, errors, utilitats de text)
sobre els quals es construeix la resta de l'arquitectura.
"""

from parafrasi_cat.core.errors import (
    ConfigError,
    ParafrasiError,
    ResourceError,
    TransformationError,
)
from parafrasi_cat.core.spans import Span, spans_overlap
from parafrasi_cat.core.text import match_casing, phrase_pattern
from parafrasi_cat.core.transformation import (
    SemanticRisk,
    Transformation,
    TransformationType,
    apply_transformations,
)

__all__ = [
    "ConfigError",
    "ParafrasiError",
    "ResourceError",
    "SemanticRisk",
    "Span",
    "Transformation",
    "TransformationError",
    "TransformationType",
    "apply_transformations",
    "match_casing",
    "phrase_pattern",
    "spans_overlap",
]
