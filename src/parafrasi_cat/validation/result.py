"""Resultat d'una validació."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class ValidationSeverity(StrEnum):
    ERROR = "error"
    """El candidat s'ha de descartar."""

    WARNING = "warning"
    """El candidat és acceptable però convé revisar-lo."""


class ValidationDimension(StrEnum):
    """Dimensió que avalua un validador; la puntuació les reporta per separat."""

    FACTUAL = "factual"
    """Preservació del contingut: noms, dates, xifres, citacions, negació."""

    TERMINOLOGY = "terminology"
    """Terminologia protegida per l'usuari."""

    EPISTEMIC = "epistemic"
    """Força i funció epistemològica (hipòtesi, certesa, demostració...)."""

    GRAMMAR = "grammar"
    """Gramaticalitat heurística."""

    LENGTH = "length"
    """Marge de longitud."""

    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    validator_id: str
    severity: ValidationSeverity
    message: str
    dimension: ValidationDimension = ValidationDimension.OTHER

    def describe(self) -> str:
        return f"[{self.validator_id}] {self.severity.value}: {self.message}"

    def to_dict(self) -> dict[str, str]:
        return {
            "validator_id": self.validator_id,
            "severity": self.severity.value,
            "message": self.message,
            "dimension": self.dimension.value,
        }


@dataclass(frozen=True, slots=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        """Cert si no hi ha cap problema de severitat ``error``."""
        return not self.errors

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is ValidationSeverity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is ValidationSeverity.WARNING)

    @classmethod
    def passed(cls) -> ValidationResult:
        return cls(())

    @classmethod
    def error(
        cls,
        validator_id: str,
        message: str,
        dimension: ValidationDimension = ValidationDimension.OTHER,
    ) -> ValidationResult:
        return cls((ValidationIssue(validator_id, ValidationSeverity.ERROR, message, dimension),))

    @classmethod
    def warning(
        cls,
        validator_id: str,
        message: str,
        dimension: ValidationDimension = ValidationDimension.OTHER,
    ) -> ValidationResult:
        return cls((ValidationIssue(validator_id, ValidationSeverity.WARNING, message, dimension),))

    def in_dimension(self, dimension: ValidationDimension) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.dimension is dimension)

    def errors_in(self, dimension: ValidationDimension) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.errors if i.dimension is dimension)

    def warnings_in(self, dimension: ValidationDimension) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.warnings if i.dimension is dimension)

    @property
    def summary(self) -> str:
        """Motius dels errors en una línia (buit si no n'hi ha)."""
        return "; ".join(i.message for i in self.errors)

    @classmethod
    def merge(cls, results: Iterable[ValidationResult]) -> ValidationResult:
        return cls(tuple(issue for result in results for issue in result.issues))

    def to_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "issues": [i.to_dict() for i in self.issues]}
