from __future__ import annotations

from parafrasi_cat.analyzer import RuleBasedAnalyzer, SentenceSplitter


def texts(text: str) -> list[str]:
    return [s.text for s in SentenceSplitter().split(text)]


def test_basic_split() -> None:
    assert texts("Plou molt. Fa fred! Vindràs? Sí.") == [
        "Plou molt.",
        "Fa fred!",
        "Vindràs?",
        "Sí.",
    ]


def test_abbreviations_do_not_split() -> None:
    assert texts("El Sr. Puig va venir. Després va marxar.") == [
        "El Sr. Puig va venir.",
        "Després va marxar.",
    ]
    assert texts("Vegeu la pàg. 3 i el cap. II.") == ["Vegeu la pàg. 3 i el cap. II."]
    assert texts("Hi ha fruita, p. ex. pomes.") == ["Hi ha fruita, p. ex. pomes."]


def test_initials_do_not_split() -> None:
    assert texts("J. Verdaguer va néixer el 1845. Va morir el 1902.") == [
        "J. Verdaguer va néixer el 1845.",
        "Va morir el 1902.",
    ]


def test_etc_can_end_sentence() -> None:
    assert texts("Pomes, peres, etc. La resta no.") == ["Pomes, peres, etc.", "La resta no."]


def test_decimal_numbers_do_not_split() -> None:
    assert texts("Costa 3.5 euros. Sí.") == ["Costa 3.5 euros.", "Sí."]


def test_lowercase_after_period_does_not_split() -> None:
    assert texts("Va dir que sí. i després res") == ["Va dir que sí. i després res"]


def test_quotes_after_period() -> None:
    assert texts("Va dir «Hola.» Després res.") == ["Va dir «Hola.»", "Després res."]
    assert texts("Va dir: «Hola». Després res.") == ["Va dir: «Hola».", "Després res."]


def test_line_breaks_split() -> None:
    sentences = SentenceSplitter().split("Primera línia\nSegona línia")
    assert [s.text for s in sentences] == ["Primera línia", "Segona línia"]
    assert [(s.span.start, s.span.end) for s in sentences] == [(0, 13), (14, 26)]


def test_spans_and_indices() -> None:
    text = "  Hola.  Adeu. "
    sentences = SentenceSplitter().split(text)
    assert [(s.index, s.text) for s in sentences] == [(0, "Hola."), (1, "Adeu.")]
    for sentence in sentences:
        assert sentence.span.slice(text) == sentence.text
        for token in sentence.tokens:
            assert token.span.slice(sentence.text) == token.text
            assert sentence.absolute(token.span).slice(text) == token.text


def test_empty_and_whitespace() -> None:
    assert texts("") == []
    assert texts("   \n\n  ") == []


def test_custom_abbreviations() -> None:
    splitter = SentenceSplitter(abbreviations={"xyz."})
    assert splitter.abbreviations == frozenset({"xyz"})
    assert [s.text for s in splitter.split("Vegeu xyz. Després.")] == ["Vegeu xyz. Després."]


def test_analyzer() -> None:
    analysis = RuleBasedAnalyzer().analyze("Hola món. Adeu món.")
    assert analysis.n_sentences == 2
    assert [t.text for t in analysis.words] == ["Hola", "món", "Adeu", "món"]
    sentences = analysis.to_dict()["sentences"]
    assert isinstance(sentences, list) and sentences[1]["text"] == "Adeu món."
