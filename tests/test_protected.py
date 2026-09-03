from __future__ import annotations

import pytest

from parafrasi_cat.analyzer import RuleBasedAnalyzer
from parafrasi_cat.core import Span
from parafrasi_cat.protected import (
    CitationDetector,
    DateDetector,
    Detector,
    NumberDetector,
    ProperNounDetector,
    ProtectedSpan,
    ProtectionKind,
    Protector,
    QuotedTextDetector,
    RomanNumeralDetector,
    UserTermDetector,
    default_protector,
)


def found(detector: Detector, text: str) -> list[str]:
    spans = list(detector.detect(text))
    for span in spans:
        assert span.span.slice(text) == span.text
    return [s.text for s in spans]


def test_dates() -> None:
    d = DateDetector()
    assert found(d, "Va passar el 12/03/2021 i el 2021-03-12.") == ["12/03/2021", "2021-03-12"]
    assert found(d, "El 12 de març de 2021 i l'1 d'abril del 2020.") == [
        "12 de març de 2021",
        "1 d'abril del 2020",
    ]
    assert found(d, "Al març de 2021 i el 3 de maig.") == ["març de 2021", "3 de maig"]
    assert found(d, "El 2012 de gener no és cap data.") == []


def test_numbers() -> None:
    d = NumberDetector()
    text = "Un 45 % dels 1.000,50 € els van rebre els 3r i 4t classificats el 2020."
    assert found(d, text) == ["45 %", "1.000,50 €", "3r", "4t", "2020"]
    assert found(d, "Temperatura de -3 graus i 2,5 km.") == ["-3", "2,5"]
    assert found(d, "Cap xifra aquí.") == []


def test_roman_numerals() -> None:
    d = RomanNumeralDetector()
    assert found(d, "Al segle XX i al capítol V, Jaume I i Pere III.") == ["XX", "V", "I", "III"]
    assert found(d, "I després van marxar.") == []
    assert found(d, "Els nombres i, v, x no compten.") == []
    assert found(d, "MCMXCII va ser un any.") == ["MCMXCII"]
    assert found(d, "La paraula CIVIL no és un numeral.") == []


def test_quoted_text() -> None:
    d = QuotedTextDetector()
    assert found(d, 'Va dir «hola» i “adeu” i "fins ara".') == ["«hola»", "“adeu”", '"fins ara"']
    assert found(d, "l'home i l'anell") == []


def test_citations() -> None:
    d = CitationDetector()
    assert found(d, "Segons (Fabra, 1918) i (vegeu Solà 1994: 23), vegeu [12] i [3, 4].") == [
        "(Fabra, 1918)",
        "(vegeu Solà 1994: 23)",
        "[12]",
        "[3, 4]",
    ]
    assert found(d, "Vegeu p. 34 i pp. 12-15, ibid. i op. cit.") == [
        "p. 34",
        "pp. 12-15",
        "ibid.",
        "op. cit.",
    ]
    assert found(d, "(vegeu el capítol tres)") == []


def test_proper_nouns() -> None:
    d = ProperNounDetector(RuleBasedAnalyzer())
    assert found(d, "La Universitat de Barcelona és gran.") == ["Universitat de Barcelona"]
    assert found(d, "Joan Maragall va néixer a Barcelona.") == ["Joan Maragall", "Barcelona"]
    assert found(d, "Visitem l'Institut d'Estudis Catalans.") == ["Institut d'Estudis Catalans"]
    assert found(d, "Universitat de Barcelona és gran.") == ["Universitat de Barcelona"]
    assert found(d, "Consell de l'Audiovisual de Catalunya.") == [
        "Consell de l'Audiovisual de Catalunya"
    ]
    assert found(d, "Vam anar a Barcelona, Madrid i Girona.") == ["Barcelona", "Madrid i Girona"]
    assert found(d, "Pompeu Fabra i Poch va néixer a Gràcia.") == ["Pompeu Fabra i Poch", "Gràcia"]
    assert found(d, "Segons Fabra, la norma és clara.") == ["Fabra"]
    assert found(d, "ONU és una sigla.") == ["ONU"]
    # Limitació coneguda: una sola paraula amb majúscula al començament de frase
    # no es distingeix d'una paraula ordinària; cal el diccionari de noms propis.
    assert found(d, "Barcelona és gran.") == []
    assert found(d, "Després va ploure.") == []


def test_user_terms() -> None:
    d = UserTermDetector(["capital circulant", "Pla d'Acció"])
    spans = list(d.detect("El Capital Circulant del pla d’acció puja."))
    assert [s.text for s in spans] == ["Capital Circulant", "pla d’acció"]
    assert spans[0].note == "capital circulant"
    assert spans[0].kind is ProtectionKind.USER_TERM
    assert found(UserTermDetector(["cap"]), "El capital no és cap problema.") == ["cap"]


def test_protected_span_validation() -> None:
    with pytest.raises(ValueError):
        ProtectedSpan(Span(0, 3), "abcd", ProtectionKind.NUMBER, "x")
    span = ProtectedSpan(Span(2, 6), "2020", ProtectionKind.NUMBER, "number.regex")
    assert span.start == 2 and span.end == 6
    assert span.overlaps(Span(5, 9))
    assert span.shift(10).span == Span(12, 16)
    assert "xifra" in span.describe()
    assert span.to_dict()["kind"] == "number"


def test_protector_orders_and_deduplicates() -> None:
    protector = Protector([NumberDetector(), NumberDetector(), DateDetector()])
    spans = protector.protect("El 12 de gener de 2020.")
    assert [(s.text, s.kind.value) for s in spans] == [
        ("12 de gener de 2020", "date"),
        ("12", "number"),
        ("2020", "number"),
    ]


def test_protector_within_clips_and_shifts() -> None:
    text = "Va dir «Hola. Adeu». Prou."
    spans = Protector([QuotedTextDetector()]).protect(text)
    assert [s.text for s in spans] == ["«Hola. Adeu»"]
    first = Protector.within(spans, Span(0, 13))  # «Va dir «Hola.»
    assert [(s.text, s.span.start, s.span.end) for s in first] == [("«Hola.", 7, 13)]
    second = Protector.within(spans, Span(14, 20))  # «Adeu».
    assert [(s.text, s.span.start, s.span.end) for s in second] == [("Adeu»", 0, 5)]
    assert Protector.within(spans, Span(21, 26)) == ()


def test_default_protector_with_user_terms_and_names() -> None:
    protector = default_protector(
        RuleBasedAnalyzer(), user_terms=["capital circulant"], known_names=["Verdaguer"]
    )
    spans = protector.protect("Verdaguer parlava del capital circulant el 1877.")
    kinds = {(s.text, s.kind) for s in spans}
    assert ("Verdaguer", ProtectionKind.PROPER_NOUN) in kinds
    assert ("capital circulant", ProtectionKind.USER_TERM) in kinds
    assert ("1877", ProtectionKind.NUMBER) in kinds
