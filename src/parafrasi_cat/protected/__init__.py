"""Detecció i protecció de fragments que el motor no pot modificar mai.

Els fragments protegits (noms propis, dates, xifres, números romans,
citacions, text entre cometes i termes definits per l'usuari) es detecten
abans d'aplicar cap regla i es comproven de nou en la validació final.
"""

from parafrasi_cat.protected.detectors import (
    CitationDetector,
    DateDetector,
    Detector,
    NumberDetector,
    ProperNounDetector,
    QuotedTextDetector,
    RegexDetector,
    RomanNumeralDetector,
    UserTermDetector,
)
from parafrasi_cat.protected.protector import Protector, default_protector
from parafrasi_cat.protected.spans import ProtectedSpan, ProtectionKind

__all__ = [
    "CitationDetector",
    "DateDetector",
    "Detector",
    "NumberDetector",
    "ProperNounDetector",
    "ProtectedSpan",
    "ProtectionKind",
    "Protector",
    "QuotedTextDetector",
    "RegexDetector",
    "RomanNumeralDetector",
    "UserTermDetector",
    "default_protector",
]
