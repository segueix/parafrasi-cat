"""Regressions d'abast lògic en reordenacions condicionals."""

from __future__ import annotations

from pathlib import Path

from parafrasi_cat import PipelineConfig, build_pipeline
from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.validation.base import ValidationContext
from parafrasi_cat.validation.conditional_scope import ConditionalScopeValidator
from parafrasi_cat.validation.result import ValidationDimension


def _validate(source: str, target: str):  # type: ignore[no-untyped-def]
    validator = ConditionalScopeValidator()
    candidate = Candidate(0, source, target, ())
    return validator.validate(candidate, ValidationContext(source))


def test_only_if_direction_cannot_be_reversed() -> None:
    source = (
        "La frase només té sentit si arfil designa una categoria política: "
        "un home pròxim al rei, útil al poder, però ja no sobirà."
    )
    target = (
        "Si arfil designa una categoria política: un home pròxim al rei, útil al poder, "
        "però ja no sobirà, la frase només té sentit."
    )
    result = _validate(source, target)
    assert not result.ok
    assert result.errors_in(ValidationDimension.EPISTEMIC)
    assert "condició necessària" in result.summary


def test_reverse_direction_is_protected_too() -> None:
    source = "Si el document és autèntic, la hipòtesi només és possible en aquest context."
    target = "La hipòtesi només és possible en aquest context si el document és autèntic."
    assert not _validate(source, target).ok


def test_ordinary_conditional_can_still_move() -> None:
    source = "La regla no funciona si el text és antic."
    target = "Si el text és antic, la regla no funciona."
    assert _validate(source, target).ok


def test_restrictor_without_conditional_is_not_blocked() -> None:
    source = "La frase només té una lectura plausible."
    target = "Només té una lectura plausible, la frase."
    assert _validate(source, target).ok


def test_validator_is_always_wired_into_the_pipeline(project_root: Path) -> None:
    pipeline = build_pipeline(
        PipelineConfig(home=project_root, level=3, languagetool=False, syntax="none")
    )
    assert "conditional_scope" in {validator.validator_id for validator in pipeline.validators}
