from __future__ import annotations

from parafrasi_cat.analyzer import ParagraphSplitter, RuleBasedAnalyzer


def test_blank_lines_separate_paragraphs() -> None:
    text = "Primer paràgraf. Segona frase.\n\nSegon paràgraf.\r\n\r\n  Tercer.  "
    paragraphs = ParagraphSplitter().split(text)
    assert [p.text for p in paragraphs] == [
        "Primer paràgraf. Segona frase.",
        "Segon paràgraf.",
        "Tercer.",
    ]
    assert [p.index for p in paragraphs] == [0, 1, 2]
    for paragraph in paragraphs:
        assert paragraph.span.slice(text) == paragraph.text


def test_single_newline_stays_in_paragraph_by_default() -> None:
    text = "Línia u.\nLínia dos.\n\nAltre."
    assert [p.text for p in ParagraphSplitter().split(text)] == ["Línia u.\nLínia dos.", "Altre."]
    assert [p.text for p in ParagraphSplitter(split_on_single_newline=True).split(text)] == [
        "Línia u.",
        "Línia dos.",
        "Altre.",
    ]


def test_empty_and_whitespace_only() -> None:
    assert ParagraphSplitter().split("") == ()
    assert ParagraphSplitter().split("\n\n   \n") == ()


def test_sentences_carry_paragraph_index_and_document_offsets() -> None:
    text = "Primer paràgraf. Segona frase.\n\nSegon paràgraf.\nLínia nova."
    analysis = RuleBasedAnalyzer().analyze(text)
    assert analysis.n_paragraphs == 2
    assert [(s.index, s.paragraph_index, s.text) for s in analysis.sentences] == [
        (0, 0, "Primer paràgraf."),
        (1, 0, "Segona frase."),
        (2, 1, "Segon paràgraf."),
        (3, 1, "Línia nova."),
    ]
    for sentence in analysis.sentences:
        assert sentence.span.slice(text) == sentence.text
    assert [s.text for s in analysis.sentences_of(1)] == ["Segon paràgraf.", "Línia nova."]
    assert [s.text for s in analysis.sentences_of(analysis.paragraphs[0])] == [
        "Primer paràgraf.",
        "Segona frase.",
    ]
    assert analysis.to_dict()["paragraphs"] == [p.to_dict() for p in analysis.paragraphs]
