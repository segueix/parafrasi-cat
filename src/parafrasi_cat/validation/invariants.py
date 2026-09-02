"""Validadors dels invariants de contingut.

Cadascun comprova una faceta del principi fonamental: el motor pot canviar
la forma, però mai el contingut. Tots són independents de les regles que han
generat el candidat, de manera que actuen com a segona línia de defensa.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.validation.base import ValidationContext
from parafrasi_cat.validation.markers import MarkerSet
from parafrasi_cat.validation.result import ValidationResult

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_ROMAN_RE = re.compile(
    r"(?<![^\W\d_])(?=[MDCLXVI])M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})(?![^\W\d_])"
)


class ProtectedSpanValidator:
    """Cada fragment protegit ha d'aparèixer al candidat tantes vegades com a l'original."""

    validator_id = "protected_spans"

    def validate(self, candidate: Candidate, ctx: ValidationContext) -> ValidationResult:
        missing: list[str] = []
        for text in dict.fromkeys(p.text for p in ctx.protected_spans):
            if not text.strip():
                continue
            if candidate.text.count(text) < ctx.source_text.count(text):
                missing.append(text)
        if missing:
            listed = ", ".join(f"«{m}»" for m in missing)
            return ValidationResult.error(
                self.validator_id, f"El candidat ha alterat fragments protegits: {listed}"
            )
        return ValidationResult.passed()


class NumericInvariantValidator:
    """Les xifres i els números romans han de ser exactament els mateixos."""

    validator_id = "numeric_invariants"

    def validate(self, candidate: Candidate, ctx: ValidationContext) -> ValidationResult:
        before = Counter(_NUMBER_RE.findall(ctx.source_text))
        after = Counter(_NUMBER_RE.findall(candidate.text))
        if before != after:
            return ValidationResult.error(
                self.validator_id, f"Les xifres han canviat: {_diff(before, after)}"
            )
        before = Counter(_ROMAN_RE.findall(ctx.source_text))
        after = Counter(_ROMAN_RE.findall(candidate.text))
        if before != after:
            return ValidationResult.error(
                self.validator_id, f"Els números romans han canviat: {_diff(before, after)}"
            )
        return ValidationResult.passed()


class NegationValidator:
    """El nombre de marcadors de negació no pot variar.

    Les locucions indicades a ``exceptions`` («no obstant això», «si no»...)
    no compten com a negació encara que continguin un marcador.
    """

    validator_id = "negation"

    def __init__(
        self,
        negation_markers: Iterable[str],
        exceptions: Iterable[str] = (),
    ) -> None:
        self._markers = MarkerSet(negation_markers, exceptions)

    def validate(self, candidate: Candidate, ctx: ValidationContext) -> ValidationResult:
        before = self._markers.counts(ctx.source_text)
        after = self._markers.counts(candidate.text)
        if before != after:
            return ValidationResult.error(
                self.validator_id, f"La negació ha canviat: {_diff(before, after)}"
            )
        return ValidationResult.passed()


class HedgeValidator:
    """Una hipòtesi no es pot convertir en certesa.

    - Els marcadors d'atenuació (potser, probablement, sembla...) no poden
      disminuir.
    - Els marcadors de certesa (sens dubte, evidentment...) no poden augmentar.
    """

    validator_id = "modality"

    def __init__(self, hedge_markers: Iterable[str], certainty_markers: Iterable[str]) -> None:
        self._hedges = MarkerSet(hedge_markers)
        self._certainty = MarkerSet(certainty_markers)

    def validate(self, candidate: Candidate, ctx: ValidationContext) -> ValidationResult:
        hedges_before = self._hedges.count(ctx.source_text)
        hedges_after = self._hedges.count(candidate.text)
        if hedges_after < hedges_before:
            return ValidationResult.error(
                self.validator_id,
                f"S'han perdut marcadors d'atenuació ({hedges_before} → {hedges_after}): "
                "una hipòtesi podria haver-se convertit en afirmació",
            )
        certainty_before = self._certainty.count(ctx.source_text)
        certainty_after = self._certainty.count(candidate.text)
        if certainty_after > certainty_before:
            return ValidationResult.error(
                self.validator_id,
                f"S'han afegit marcadors de certesa ({certainty_before} → {certainty_after})",
            )
        return ValidationResult.passed()


class LengthRatioValidator:
    """La longitud del candidat ha de mantenir-se dins d'un marge raonable.

    Un candidat molt més curt probablement ha perdut contingut; un de molt
    més llarg probablement n'ha afegit.
    """

    validator_id = "length_ratio"

    def __init__(self, min_ratio: float = 0.6, max_ratio: float = 1.6) -> None:
        if not 0.0 < min_ratio <= 1.0 <= max_ratio:
            raise ConfigError("Cal 0 < min_ratio <= 1 <= max_ratio")
        self._min = min_ratio
        self._max = max_ratio

    def validate(self, candidate: Candidate, ctx: ValidationContext) -> ValidationResult:
        source_length = len(ctx.source_text.strip())
        if source_length == 0:
            return ValidationResult.passed()
        ratio = len(candidate.text.strip()) / source_length
        if ratio < self._min or ratio > self._max:
            return ValidationResult.error(
                self.validator_id,
                f"La longitud del candidat ({ratio:.2f}× l'original) surt del marge "
                f"[{self._min}, {self._max}]",
            )
        return ValidationResult.passed()


def _diff(before: Counter[str], after: Counter[str]) -> str:
    lost = before - after
    gained = after - before
    parts: list[str] = []
    if lost:
        parts.append("desaparegut " + ", ".join(f"«{k}»×{v}" for k, v in sorted(lost.items())))
    if gained:
        parts.append("aparegut " + ", ".join(f"«{k}»×{v}" for k, v in sorted(gained.items())))
    return "; ".join(parts) or "(sense detall)"
