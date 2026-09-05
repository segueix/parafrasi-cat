"""Preservació de l'abast lògic de condicionals restrictives.

Una reordenació aparentment innòcua pot invertir una implicació quan hi ha
marcadors com «només»: «P només ... si Q» expressa Q com a condició necessària,
mentre que «Si Q, P ...» presenta Q com a condició suficient. El motor no pot
intercanviar aquestes dues lectures.

El validador és deliberadament conservador. Només actua quan hi ha exactament
un «si» condicional i un restrictor clar («només», «solament», «únicament») a
la unitat; si l'ordre relatiu entre tots dos s'inverteix, el candidat es
rebutja. Amb estructures més complexes prefereix no inferir res.
"""

from __future__ import annotations

import re

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.validation.base import ValidationContext
from parafrasi_cat.validation.result import ValidationDimension, ValidationResult

_RESTRICTOR_RE = re.compile(r"\b(?:només|solament|únicament)\b", re.IGNORECASE)
# «si bé» és concessiu, no una condició d'aquest tipus.
_CONDITIONAL_SI_RE = re.compile(r"\bsi\b(?!\s+bé\b)", re.IGNORECASE)


class ConditionalScopeValidator:
    """Impedeix invertir l'abast entre un restrictor i una clàusula amb «si»."""

    validator_id = "conditional_scope"
    dimension = ValidationDimension.EPISTEMIC

    def validate(self, candidate: Candidate, ctx: ValidationContext) -> ValidationResult:
        before = _scope_order(ctx.source_text)
        after = _scope_order(candidate.text)
        if before is None or after is None or before == after:
            return ValidationResult.passed()
        return ValidationResult.error(
            self.validator_id,
            "La reordenació inverteix l'abast de «només/solament/únicament» respecte "
            "de «si» i podria convertir una condició necessària en suficient o a l'inrevés",
            self.dimension,
        )


def _scope_order(text: str) -> str | None:
    restrictors = tuple(_RESTRICTOR_RE.finditer(text))
    conditionals = tuple(_CONDITIONAL_SI_RE.finditer(text))
    if len(restrictors) != 1 or len(conditionals) != 1:
        return None
    return (
        "restrictor_before_si"
        if restrictors[0].start() < conditionals[0].start()
        else "si_before_restrictor"
    )


__all__ = ["ConditionalScopeValidator"]
