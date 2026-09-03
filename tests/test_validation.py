from __future__ import annotations

import pytest

from parafrasi_cat.candidates import Candidate
from parafrasi_cat.core import ConfigError, Span
from parafrasi_cat.protected import ProtectedSpan, ProtectionKind
from parafrasi_cat.validation import (
    HedgeValidator,
    LengthRatioValidator,
    MarkerSet,
    NegationValidator,
    NumericInvariantValidator,
    ProtectedSpanValidator,
    ValidationContext,
    ValidationResult,
    ValidationSeverity,
)


def candidate(source: str, text: str) -> Candidate:
    return Candidate(0, source, text)


def test_protected_span_validator() -> None:
    source = "Va néixer el 1877 a Folgueroles."
    ctx = ValidationContext(
        source,
        (
            ProtectedSpan(Span(13, 17), "1877", ProtectionKind.NUMBER, "n"),
            ProtectedSpan(Span(20, 31), "Folgueroles", ProtectionKind.PROPER_NOUN, "p"),
        ),
    )
    v = ProtectedSpanValidator()
    assert v.validate(candidate(source, "Nasqué el 1877 a Folgueroles."), ctx).ok
    result = v.validate(candidate(source, "Nasqué el 1878 a Folgueroles."), ctx)
    assert not result.ok
    assert "1877" in result.errors[0].message
    assert not v.validate(candidate(source, "Nasqué el 1877 a folgueroles."), ctx).ok


def test_numeric_invariants() -> None:
    v = NumericInvariantValidator()
    ctx = ValidationContext("El 2020 va ser el segle XXI amb 3,5 %.")
    assert v.validate(candidate(ctx.source_text, "El segle XXI, el 2020, amb 3,5 %."), ctx).ok
    assert not v.validate(
        candidate(ctx.source_text, "El 2021 va ser el segle XXI amb 3,5 %."), ctx
    ).ok
    assert not v.validate(
        candidate(ctx.source_text, "El 2020 va ser el segle XX amb 3,5 %."), ctx
    ).ok
    assert not v.validate(
        candidate(ctx.source_text, "El 2020 va ser el segle XXI amb 3.5 %."), ctx
    ).ok


def test_negation_validator(modality: dict[str, tuple[str, ...]]) -> None:
    v = NegationValidator(modality["negation"], modality["negation_exceptions"])
    ctx = ValidationContext("No ho sé, mai no hi vaig.")
    assert v.validate(candidate(ctx.source_text, "No ho sé, no hi vaig mai."), ctx).ok
    assert not v.validate(candidate(ctx.source_text, "Ho sé, no hi vaig mai."), ctx).ok
    assert not v.validate(candidate(ctx.source_text, "No ho sé, mai no hi vaig, ni tu."), ctx).ok

    ctx = ValidationContext("No obstant això, vindrà.")
    assert v.validate(candidate(ctx.source_text, "Tanmateix, vindrà."), ctx).ok
    assert not v.validate(candidate(ctx.source_text, "Tanmateix, no vindrà."), ctx).ok


def test_hedge_validator(modality: dict[str, tuple[str, ...]]) -> None:
    v = HedgeValidator(modality["hedges"], modality["certainty"])
    ctx = ValidationContext("Potser plourà demà.")
    assert v.validate(candidate(ctx.source_text, "Demà potser plourà."), ctx).ok
    assert v.validate(candidate(ctx.source_text, "Probablement potser plourà demà."), ctx).ok
    lost = v.validate(candidate(ctx.source_text, "Plourà demà."), ctx)
    assert not lost.ok and "atenuació" in lost.errors[0].message
    ctx = ValidationContext("Plourà demà.")
    gained = v.validate(candidate(ctx.source_text, "Sens dubte plourà demà."), ctx)
    assert not gained.ok and "certesa" in gained.errors[0].message


def test_length_ratio_validator() -> None:
    v = LengthRatioValidator(0.5, 2.0)
    ctx = ValidationContext("Una frase de prova.")
    assert v.validate(candidate(ctx.source_text, "Una frase de prova!"), ctx).ok
    assert not v.validate(candidate(ctx.source_text, "Una."), ctx).ok
    assert not v.validate(candidate(ctx.source_text, "Una frase de prova " * 4), ctx).ok
    assert v.validate(candidate("", "qualsevol"), ValidationContext("")).ok
    with pytest.raises(ConfigError):
        LengthRatioValidator(1.5, 2.0)


def test_marker_set() -> None:
    markers = MarkerSet(["no", "ni tan sols"], exceptions=["no obstant això"])
    assert markers.count("No, no obstant això, ni tan sols ell.") == 2
    assert markers.counts("no i NO") == {"no": 2}
    assert markers.mask_exceptions("a no obstant això b") == "a                 b"
    assert len(markers) == 2


def test_validation_result_helpers() -> None:
    ok = ValidationResult.passed()
    assert ok.ok and ok.issues == ()
    warning = ValidationResult.warning("v", "compte")
    assert warning.ok and warning.warnings[0].severity is ValidationSeverity.WARNING
    error = ValidationResult.error("v", "malament")
    merged = ValidationResult.merge([ok, warning, error])
    assert not merged.ok
    assert len(merged.issues) == 2
    assert merged.to_dict()["ok"] is False
    assert "malament" in error.errors[0].describe()
