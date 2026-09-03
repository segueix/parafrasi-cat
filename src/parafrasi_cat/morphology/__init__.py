"""Informació morfològica: lemes, trets flexius i generació de formes.

En aquesta fase només hi ha un proveïdor basat en diccionari (i un de nul).
Els analitzadors morfològics externs s'hi poden connectar implementant el
protocol :class:`MorphologyProvider`.
"""

from parafrasi_cat.morphology.features import LexicalEntry, MorphFeatures
from parafrasi_cat.morphology.provider import (
    DictionaryMorphology,
    MorphologyProvider,
    NullMorphology,
)

__all__ = [
    "DictionaryMorphology",
    "LexicalEntry",
    "MorphFeatures",
    "MorphologyProvider",
    "NullMorphology",
]
