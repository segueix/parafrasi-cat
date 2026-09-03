"""Números romans: reconeixement, valor, context i protecció."""

from __future__ import annotations

import pytest

from parafrasi_cat.analyzer import (
    RuleBasedAnalyzer,
    is_roman_numeral,
    looks_like_roman_numeral,
    roman_to_int,
)
from parafrasi_cat.protected import ProtectionKind, RomanNumeralDetector


def test_is_roman_numeral_and_value() -> None:
    for text, value in (
        ("I", 1),
        ("IV", 4),
        ("IX", 9),
        ("XI", 11),
        ("XIII", 13),
        ("XL", 40),
        ("XCIX", 99),
        ("MCMXCII", 1992),
        ("MMXXIV", 2024),
    ):
        assert is_roman_numeral(text)
        assert roman_to_int(text) == value
    assert roman_to_int("XXIè") == 21
    for text in ("IIII", "VX", "IC", "civil", "CIVIL", "MIXA", "", "X1"):
        assert not is_roman_numeral(text), text
    with pytest.raises(ValueError):
        roman_to_int("CIVIL")


def test_single_letters_need_context() -> None:
    assert looks_like_roman_numeral("XI")
    assert looks_like_roman_numeral("I", "El rei Jaume ")
    assert looks_like_roman_numeral("X", "al segle ")
    assert looks_like_roman_numeral("V", "vegeu el cap. ")
    assert looks_like_roman_numeral("XI", "s. ")
    assert not looks_like_roman_numeral("I", "")
    assert not looks_like_roman_numeral("I", "va venir ")
    assert not looks_like_roman_numeral("C", "la vitamina ")


def test_tokens_get_the_roman_subkind_in_context(catalan_analyzer: RuleBasedAnalyzer) -> None:
    sentence = catalan_analyzer.analyze(
        "Al segle XI, Jaume I i Pere III; I després res."
    ).sentences[0]
    assert [(r.text, r.value) for r in sentence.roman_numerals] == [
        ("XI", 11),
        ("I", 1),
        ("III", 3),
    ]
    sentence = catalan_analyzer.analyze("El XXIè Congrés i el segle XXIIè.").sentences[0]
    assert [(r.text, r.value, r.ordinal) for r in sentence.roman_numerals] == [
        ("XXIè", 21, True),
        ("XXIIè", 22, True),
    ]


def test_detector_protects_roman_numerals() -> None:
    detector = RomanNumeralDetector()
    text = "Els segles XI, XII i XIII; Ramon Berenguer IV; s. XX; CIVIL i I després."
    spans = list(detector.detect(text))
    assert [s.text for s in spans] == ["XI", "XII", "XIII", "IV", "XX"]
    assert all(s.kind is ProtectionKind.ROMAN_NUMERAL for s in spans)
    for span in spans:
        assert span.span.slice(text) == span.text
    assert [s.text for s in detector.detect("El XXIè Congrés.")] == ["XXIè"]
