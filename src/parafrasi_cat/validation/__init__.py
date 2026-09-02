"""Validació de candidats: garanteix que el contingut original és intocable."""

from parafrasi_cat.validation.base import ValidationContext, Validator
from parafrasi_cat.validation.invariants import (
    HedgeValidator,
    LengthRatioValidator,
    NegationValidator,
    NumericInvariantValidator,
    ProtectedSpanValidator,
)
from parafrasi_cat.validation.markers import MarkerSet
from parafrasi_cat.validation.result import (
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)

__all__ = [
    "HedgeValidator",
    "LengthRatioValidator",
    "MarkerSet",
    "NegationValidator",
    "NumericInvariantValidator",
    "ProtectedSpanValidator",
    "ValidationContext",
    "ValidationIssue",
    "ValidationResult",
    "ValidationSeverity",
    "Validator",
]
