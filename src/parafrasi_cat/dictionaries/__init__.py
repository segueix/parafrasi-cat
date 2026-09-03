"""Diccionaris terminològics editables per projecte.

Cada diccionari (``dictionaries/<nom>.yml``) declara, per a cada terme, les
formes preferides, les acceptades, les que cal evitar, si està protegit, la
categoria gramatical i notes. Se'n poden activar diversos alhora
(:class:`DictionarySet`); la protecció és acumulativa i, si dos diccionaris
discrepen, mana el primer de la llista d'activació. Tot és explícit i
determinista: no hi ha cap model ni cap ajust automàtic.
"""

from parafrasi_cat.dictionaries.dictionary import (
    DEFAULT_CONFIDENCE,
    DictionaryConflict,
    DictionaryEntry,
    DictionaryMatch,
    DictionarySet,
    FormStatus,
    Substitution,
    TermDictionary,
    normalize_term,
)

__all__ = [
    "DEFAULT_CONFIDENCE",
    "DictionaryConflict",
    "DictionaryEntry",
    "DictionaryMatch",
    "DictionarySet",
    "FormStatus",
    "Substitution",
    "TermDictionary",
    "normalize_term",
]
