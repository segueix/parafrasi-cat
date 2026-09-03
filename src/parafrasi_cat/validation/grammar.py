"""Gramaticalitat heurística d'un candidat.

No hi ha cap analitzador sintàctic: es comproven símptomes superficials
d'una reescriptura mal formada, sempre en comparació amb l'original (un
defecte que ja tenia l'original no es penalitza). Els defectes greus són
errors (el candidat es descarta); els lleus, avisos que rebaixen la
puntuació de gramaticalitat.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.core.text import LETTER
from parafrasi_cat.validation.base import ValidationContext
from parafrasi_cat.validation.result import (
    ValidationDimension,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)

#: Penalització per avís en la puntuació de gramaticalitat (0-1).
WARNING_PENALTY = 0.15

_PAIRS = (("(", ")"), ("[", "]"), ("«", "»"), ("“", "”"))
_MANDATORY_CONTRACTIONS = re.compile(
    rf"(?<!{LETTER})(?:de|a|per|ca)\s+els?(?!{LETTER})", re.IGNORECASE
)
_DOUBLE_SPACE = re.compile(r"[^\S\n]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"\s[,;:.!?»)]")
_REPEATED_PUNCT = re.compile(r"[,;:]{2,}|\.{2}(?!\.)")
_REPEATED_WORD = re.compile(rf"(?<!{LETTER})({LETTER}{{2,}})\s+\1(?!{LETTER})", re.IGNORECASE)
_SPACE_AFTER_APOSTROPHE = re.compile(rf"{LETTER}['’]\s+{LETTER}")
_TERMINAL = ".!?…"


@dataclass(frozen=True, slots=True)
class GrammarAssessment:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def score(self) -> float:
        if self.errors:
            return 0.0
        return max(0.0, 1.0 - WARNING_PENALTY * len(self.warnings))


def assess_grammar(text: str, reference: str = "") -> GrammarAssessment:
    """Defectes de ``text`` que no tenia ``reference``."""
    errors: list[str] = []
    warnings: list[str] = []
    if not text.strip():
        return GrammarAssessment(("el text és buit",), ())
    for opener, closer in _PAIRS:
        if text.count(opener) != text.count(closer) and reference.count(opener) == reference.count(
            closer
        ):
            errors.append(f"signes «{opener}{closer}» desaparellats")
    if text.count('"') % 2 and not reference.count('"') % 2:
        errors.append('cometes rectes desaparellades (")')
    for problem in _new_matches(_MANDATORY_CONTRACTIONS, text, reference):
        errors.append(f"contracció obligatòria no feta: «{problem}»")
    if (
        reference.strip()
        and reference.strip()[-1] in _TERMINAL
        and text.strip()[-1] not in _TERMINAL
    ):
        errors.append("falta la puntuació final de la frase")
    for problem in _new_matches(_REPEATED_WORD, text, reference):
        warnings.append(f"paraula repetida: «{problem}»")
    for problem in _new_matches(_REPEATED_PUNCT, text, reference):
        warnings.append(f"puntuació repetida: «{problem}»")
    if _new_matches(_DOUBLE_SPACE, text, reference):
        warnings.append("espais dobles")
    if _new_matches(_SPACE_BEFORE_PUNCT, text, reference):
        warnings.append("espai abans d'un signe de puntuació")
    if _new_matches(_SPACE_AFTER_APOSTROPHE, text, reference):
        warnings.append("espai després d'un apòstrof")
    first = text.lstrip()[:1]
    reference_first = reference.lstrip()[:1]
    if first.islower() and (not reference_first or reference_first.isupper()):
        warnings.append("la frase comença en minúscula")
    return GrammarAssessment(tuple(errors), tuple(warnings))


def _new_matches(pattern: re.Pattern[str], text: str, reference: str) -> list[str]:
    """Coincidències del patró a ``text`` que no hi eren (mateix recompte) a ``reference``."""
    found = Counter(m.group(0).lower() for m in pattern.finditer(text))
    known = Counter(m.group(0).lower() for m in pattern.finditer(reference))
    return sorted((found - known).elements())


class GrammarHeuristicValidator:
    """Aplica :func:`assess_grammar` a un candidat respecte de l'original."""

    validator_id = "grammar"
    dimension = ValidationDimension.GRAMMAR

    def validate(self, candidate: Candidate, ctx: ValidationContext) -> ValidationResult:
        if candidate.is_identity:
            return ValidationResult.passed()
        assessment = assess_grammar(candidate.text, ctx.source_text)
        issues = [
            ValidationIssue(self.validator_id, ValidationSeverity.ERROR, message, self.dimension)
            for message in assessment.errors
        ]
        issues.extend(
            ValidationIssue(self.validator_id, ValidationSeverity.WARNING, message, self.dimension)
            for message in assessment.warnings
        )
        return ValidationResult(tuple(issues))
