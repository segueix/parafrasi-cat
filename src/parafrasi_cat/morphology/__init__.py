"""Informació morfològica: lemes, trets flexius i generació de formes.

Interfície desacoblada:

- :class:`MorphologyProvider` és el protocol que fa servir la canonada.
- :func:`create_morphology_provider` crea el proveïdor pel nom («internal»,
  «dictionary», «null», «apertium», «freeling»), de manera que la canonada no
  depèn de cap implementació concreta.
- :class:`InternalMorphology` és l'analitzador intern mínim (lexicó de classes
  tancades + diccionari de formes + endevinador per sufixos).
- Els adaptadors d'Apertium i FreeLing són opcionals i s'executen localment.
"""

from parafrasi_cat.morphology.features import LexicalEntry, MorphFeatures
from parafrasi_cat.morphology.guesser import guess
from parafrasi_cat.morphology.internal import InternalMorphology
from parafrasi_cat.morphology.provider import (
    DictionaryMorphology,
    MorphologyProvider,
    NullMorphology,
)
from parafrasi_cat.morphology.registry import (
    MorphologyContext,
    MorphologyRegistry,
    create_morphology_provider,
    default_morphology_registry,
)

__all__ = [
    "DictionaryMorphology",
    "InternalMorphology",
    "LexicalEntry",
    "MorphFeatures",
    "MorphologyContext",
    "MorphologyProvider",
    "MorphologyRegistry",
    "NullMorphology",
    "create_morphology_provider",
    "default_morphology_registry",
    "guess",
]
