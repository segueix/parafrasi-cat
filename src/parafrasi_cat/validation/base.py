"""Protocol dels validadors i context de validació."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.protected.spans import ProtectedSpan
from parafrasi_cat.validation.result import ValidationResult


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """Informació sobre la frase original necessària per validar un candidat."""

    source_text: str
    protected_spans: tuple[ProtectedSpan, ...] = ()


@runtime_checkable
class Validator(Protocol):
    """Comprova que un candidat respecta un invariant del contingut original."""

    @property
    def validator_id(self) -> str: ...

    def validate(self, candidate: Candidate, ctx: ValidationContext) -> ValidationResult: ...
