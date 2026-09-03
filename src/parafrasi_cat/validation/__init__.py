"""Validació de candidats: garanteix que el contingut original és intocable.

Prioritat: preservació del contingut (noms, dates, xifres, romans,
citacions, negació) > terminologia protegida > gramaticalitat > estil >
quantitat de canvi. Qualsevol error de contingut invalida el candidat: és
millor retornar l'original que acceptar una transformació insegura.
"""

from parafrasi_cat.validation.base import ValidationContext, Validator
from parafrasi_cat.validation.epistemic import (
    EpistemicChange,
    EpistemicClass,
    EpistemicLexicon,
    EpistemicMatch,
    EpistemicProfile,
    EpistemicValidator,
    rule_ids_of,
)
from parafrasi_cat.validation.factual import (
    CitationValidator,
    DateValidator,
    DetectorInvariantValidator,
    ProperNounValidator,
    ProtectedTermValidator,
    QuotedTextValidator,
    RomanNumeralValidator,
    factual_validators,
)
from parafrasi_cat.validation.grammar import (
    GrammarAssessment,
    GrammarHeuristicValidator,
    assess_grammar,
)
from parafrasi_cat.validation.invariants import (
    HedgeValidator,
    LengthRatioValidator,
    NegationValidator,
    NumericInvariantValidator,
    ProtectedSpanValidator,
)
from parafrasi_cat.validation.markers import MarkerSet
from parafrasi_cat.validation.result import (
    ValidationDimension,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)

__all__ = [
    "CitationValidator",
    "DateValidator",
    "DetectorInvariantValidator",
    "EpistemicChange",
    "EpistemicClass",
    "EpistemicLexicon",
    "EpistemicMatch",
    "EpistemicProfile",
    "EpistemicValidator",
    "GrammarAssessment",
    "GrammarHeuristicValidator",
    "HedgeValidator",
    "LengthRatioValidator",
    "MarkerSet",
    "NegationValidator",
    "NumericInvariantValidator",
    "ProperNounValidator",
    "ProtectedSpanValidator",
    "ProtectedTermValidator",
    "QuotedTextValidator",
    "RomanNumeralValidator",
    "ValidationContext",
    "ValidationDimension",
    "ValidationIssue",
    "ValidationResult",
    "ValidationSeverity",
    "Validator",
    "assess_grammar",
    "factual_validators",
    "rule_ids_of",
]
