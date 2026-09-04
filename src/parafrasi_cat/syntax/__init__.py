"""Anàlisi sintàctica local i opcional.

El parser **només analitza**: no genera text, no reescriu i no decideix res.
Aporta dependències, subjecte, objecte, complements, subordinades i
coordinacions perquè les regles puguin demostrar que una transformació és
segura. Quan no en té prou confiança, o quan no està instal·lat, el motor
continua amb les heurístiques de sempre.
"""

from parafrasi_cat.syntax.analysis import (
    CLAUSE_DEPS,
    NEGATIONS,
    OBJECT_DEPS,
    SUBJECT_DEPS,
    CachedSyntax,
    NullSyntax,
    SentenceSyntax,
    SyntaxConfidence,
    SyntaxProvider,
    SyntaxToken,
    agree,
    assess_confidence,
    empty,
    token_features,
)
from parafrasi_cat.syntax.spacy_parser import DEFAULT_MODEL, SpacySyntax, discover

__all__ = [
    "CLAUSE_DEPS",
    "DEFAULT_MODEL",
    "NEGATIONS",
    "OBJECT_DEPS",
    "SUBJECT_DEPS",
    "CachedSyntax",
    "NullSyntax",
    "SentenceSyntax",
    "SpacySyntax",
    "SyntaxConfidence",
    "SyntaxProvider",
    "SyntaxToken",
    "agree",
    "assess_confidence",
    "discover",
    "empty",
    "token_features",
]
