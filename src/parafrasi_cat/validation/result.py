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


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    validator_id: str
    severity: ValidationSeverity
    message: str

    def describe(self) -> str:
        return f"[{self.validator_id}] {self.severity.value}: {self.message}"

    def to_dict(self) -> dict[str, str]:
        return {
            "validator_id": self.validator_id,
            "severity": self.severity.value,
            "message": self.message,
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
    def error(cls, validator_id: str, message: str) -> ValidationResult:
        return cls((ValidationIssue(validator_id, ValidationSeverity.ERROR, message),))

    @classmethod
    def warning(cls, validator_id: str, message: str) -> ValidationResult:
        return cls((ValidationIssue(validator_id, ValidationSeverity.WARNING, message),))

    @classmethod
    def merge(cls, results: Iterable[ValidationResult]) -> ValidationResult:
        return cls(tuple(issue for result in results for issue in result.issues))

    def to_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "issues": [i.to_dict() for i in self.issues]}
