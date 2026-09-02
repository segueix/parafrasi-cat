from __future__ import annotations

from parafrasi_cat.analyzer import Tokenizer, TokenKind


def kinds(text: str) -> list[tuple[str, TokenKind]]:
    return [(t.text, t.kind) for t in Tokenizer().tokenize(text)]


def test_elided_articles_are_clitics() -> None:
    assert kinds("l'home") == [("l'", TokenKind.CLITIC), ("home", TokenKind.WORD)]
    assert kinds("D'aquesta manera") == [
        ("D'", TokenKind.CLITIC),
        ("aquesta", TokenKind.WORD),
        ("manera", TokenKind.WORD),
    ]
    assert kinds("l’home")[0] == ("l’", TokenKind.CLITIC)


def test_enclitics() -> None:
    assert kinds("menja'n") == [("menja", TokenKind.WORD), ("'n", TokenKind.CLITIC)]
    assert kinds("porta-ho") == [("porta-ho", TokenKind.WORD)]


def test_special_catalan_characters() -> None:
    assert kinds("col·legi") == [("col·legi", TokenKind.WORD)]
    assert kinds("sud-oest") == [("sud-oest", TokenKind.WORD)]
    assert kinds("pel·lícula") == [("pel·lícula", TokenKind.WORD)]


def test_numbers_and_punctuation() -> None:
    assert kinds("1.000,50 €") == [("1.000,50", TokenKind.NUMBER), ("€", TokenKind.PUNCT)]
    assert kinds("Hola, món!") == [
        ("Hola", TokenKind.WORD),
        (",", TokenKind.PUNCT),
        ("món", TokenKind.WORD),
        ("!", TokenKind.PUNCT),
    ]


def test_spans_match_source() -> None:
    text = "Hola, món! Ens veiem l'any 2020."
    for token in Tokenizer().tokenize(text):
        assert token.span.slice(text) == token.text


def test_keep_spaces() -> None:
    tokens = Tokenizer(keep_spaces=True).tokenize("a b")
    assert [t.kind for t in tokens] == [TokenKind.WORD, TokenKind.SPACE, TokenKind.WORD]


def test_word_properties() -> None:
    tokens = Tokenizer().tokenize("l'any 2020,")
    assert [t.is_word for t in tokens] == [True, True, False, False]
    assert [t.is_lexical for t in tokens] == [True, True, True, False]
    assert tokens[-1].is_punct
