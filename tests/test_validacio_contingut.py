"""Validació obligatòria de contingut: noms, dates, nombres, romans, citacions, termes."""

from __future__ import annotations

from parafrasi_cat.analyzer import RuleBasedAnalyzer
from parafrasi_cat.candidates import Candidate
from parafrasi_cat.core import Span
from parafrasi_cat.protected import ProtectedSpan, ProtectionKind
from parafrasi_cat.validation import (
    CitationValidator,
    DateValidator,
    NegationValidator,
    NumericInvariantValidator,
    ProperNounValidator,
    ProtectedSpanValidator,
    ProtectedTermValidator,
    QuotedTextValidator,
    RomanNumeralValidator,
    ValidationContext,
    ValidationDimension,
    ValidationResult,
    factual_validators,
)


def candidate(source: str, text: str) -> Candidate:
    return Candidate(0, source, text)


def check(validator: object, source: str, text: str) -> ValidationResult:
    result = validator.validate(candidate(source, text), ValidationContext(source))  # type: ignore[attr-defined]
    assert isinstance(result, ValidationResult)
    return result


def test_proper_nouns_must_survive(catalan_analyzer: RuleBasedAnalyzer) -> None:
    v = ProperNounValidator(catalan_analyzer, lexicon=catalan_analyzer.lexicon)
    source = "Va néixer Jacint Verdaguer a Folgueroles el 1877."
    assert check(v, source, "Jacint Verdaguer va néixer a Folgueroles el 1877.").ok
    broken = check(v, source, "Va néixer Jacint Verdager a Folgueroles el 1877.")
    assert not broken.ok
    assert "Jacint Verdaguer" in broken.errors[0].message
    assert broken.errors[0].dimension is ValidationDimension.FACTUAL
    assert broken.errors[0].validator_id == "proper_nouns"
    assert not check(v, source, "Va néixer Jacint Verdaguer a folgueroles el 1877.").ok


def test_dates_exact_and_not_duplicated() -> None:
    v = DateValidator()
    source = "El 12 de gener de 2020 va ploure a Girona, com el 3/4/1999."
    assert check(v, source, "Va ploure a Girona el 12 de gener de 2020, com el 3/4/1999.").ok
    assert not check(v, source, "El 13 de gener de 2020 va ploure a Girona, com el 3/4/1999.").ok
    assert not check(v, source, "El 12 de gener de 2020 va ploure a Girona, com el 3/4/1998.").ok
    duplicated = check(
        v, source, "El 12 de gener de 2020 i el 12 de gener de 2020 va ploure, com el 3/4/1999."
    )
    assert not duplicated.ok and "duplicat" in duplicated.errors[0].message
    assert check(v, "Sense cap data.", "Cap data, sense.").ok


def test_numbers_and_roman_numerals() -> None:
    numbers = NumericInvariantValidator()
    source = "El capítol IV parla de 3,5 % dels 120 casos del segle XIV."
    assert check(numbers, source, "Dels 120 casos del segle XIV, el capítol IV parla de 3,5 %.").ok
    lost = check(numbers, source, "El capítol IV parla de 3,5 % dels 121 casos del segle XIV.")
    assert not lost.ok and lost.errors[0].dimension is ValidationDimension.FACTUAL
    assert not check(
        numbers, source, "El capítol IV parla de 3,5 % dels 120 casos del segle XV."
    ).ok
    romans = RomanNumeralValidator()
    assert check(romans, source, "El segle XIV i el capítol IV.").ok
    assert not check(romans, source, "El capítol V parla de 3,5 % dels 120 casos del segle XIV.").ok
    assert not check(romans, source, "El capítol IV i IV parla dels 120 casos del segle XIV.").ok


def test_citations_and_quoted_text() -> None:
    citations = CitationValidator()
    source = "Segons (Puig, 2019) i [12], vegeu p. 34."
    assert check(citations, source, "Vegeu p. 34, segons [12] i (Puig, 2019).").ok
    assert not check(citations, source, "Segons (Puig, 2018) i [12], vegeu p. 34.").ok
    assert not check(citations, source, "Segons (Puig, 2019) i [13], vegeu p. 34.").ok
    assert not check(citations, source, "Segons (Puig, 2019) i [12], vegeu p. 35.").ok
    quoted = QuotedTextValidator()
    source = "Va dir «Hola, món» i “adeu”."
    assert check(quoted, source, "“adeu” i «Hola, món», va dir.").ok
    assert not check(quoted, source, "Va dir «Hola món» i “adeu”.").ok
    assert not check(quoted, source, "Va dir «Hola, món» i “Adeu”.").ok


def test_protected_terms_keep_their_form() -> None:
    v = ProtectedTermValidator(["capital circulant", "Pla d'Acció"])
    assert v.terms == ("capital circulant", "Pla d'Acció")
    source = "El Capital Circulant del Pla d’Acció puja."
    assert check(v, source, "Puja el Capital Circulant del Pla d’Acció.").ok
    changed = check(v, source, "El capital circulant del Pla d’Acció puja.")
    assert not changed.ok
    assert changed.errors[0].dimension is ValidationDimension.TERMINOLOGY
    assert "canviat de forma" in changed.errors[0].message
    lost = check(v, source, "El capital del Pla d’Acció puja.")
    assert "desaparegut" in lost.errors[0].message
    assert check(v, "Sense termes.", "Res.").ok


def test_protected_spans_report_dimension_by_kind() -> None:
    source = "El capital circulant del 2020."
    ctx = ValidationContext(
        source,
        (
            ProtectedSpan(Span(3, 20), "capital circulant", ProtectionKind.USER_TERM, "u"),
            ProtectedSpan(Span(25, 29), "2020", ProtectionKind.NUMBER, "n"),
        ),
    )
    v = ProtectedSpanValidator()
    result = v.validate(candidate(source, "El capital del 2021."), ctx)
    assert {i.dimension for i in result.errors} == {
        ValidationDimension.FACTUAL,
        ValidationDimension.TERMINOLOGY,
    }
    assert result.errors_in(ValidationDimension.TERMINOLOGY)[0].message.count("«") == 1
    assert "xifra" in result.errors_in(ValidationDimension.FACTUAL)[0].message
    assert result.summary
    assert result.to_dict()["issues"][0]["dimension"] in ("factual", "terminology")  # type: ignore[index]


def test_negation_is_content(modality: dict[str, tuple[str, ...]]) -> None:
    v = NegationValidator(modality["negation"], modality["negation_exceptions"])
    result = check(v, "No es pot demostrar mai.", "Es pot demostrar mai.")
    assert not result.ok and result.errors[0].dimension is ValidationDimension.FACTUAL
    assert check(v, "No obstant això, no plou.", "Tanmateix, no plou.").ok


def test_factual_validator_bundle(catalan_analyzer: RuleBasedAnalyzer) -> None:
    validators = factual_validators(catalan_analyzer, lexicon=catalan_analyzer.lexicon)
    assert [v.validator_id for v in validators] == [
        "proper_nouns",
        "dates",
        "roman_numerals",
        "citations",
        "quoted_text",
    ]
    source = "El 1507 Oddo Altoviti encarregà «el monument» (Vasari, 1568) al capítol IV."
    ok = "Oddo Altoviti encarregà «el monument» (Vasari, 1568) al capítol IV el 1507."
    assert all(check(v, source, ok).ok for v in validators)
    bad = "El 1507 Oddo Altoviti encarregà «el monuments» (Vasari, 1568) al capítol IV."
    assert not all(check(v, source, bad).ok for v in validators)
