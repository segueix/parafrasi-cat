"""Adaptadors d'analitzadors morfològics externs (execució local, opcionals).

Cap adaptador no s'activa per defecte. Només invoquen eines instal·lades a
l'ordinador de l'usuari com a processos locals; no envien res enlloc.
"""

from parafrasi_cat.morphology.adapters.apertium import ApertiumMorphology, parse_apertium_stream
from parafrasi_cat.morphology.adapters.base import ExternalToolAdapter, MorphologyUnavailableError
from parafrasi_cat.morphology.adapters.freeling import (
    FreeLingMorphology,
    decode_eagles,
    parse_freeling_morfo,
)

__all__ = [
    "ApertiumMorphology",
    "ExternalToolAdapter",
    "FreeLingMorphology",
    "MorphologyUnavailableError",
    "decode_eagles",
    "parse_apertium_stream",
    "parse_freeling_morfo",
]
