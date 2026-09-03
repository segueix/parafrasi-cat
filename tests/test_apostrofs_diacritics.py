"""Apòstrofs, ela geminada i diacrítics."""

from __future__ import annotations

from parafrasi_cat.analyzer import (
    ApostropheKind,
    RuleBasedAnalyzer,
    Tokenizer,
    TokenKind,
    TokenSubkind,
)


def tokens(text: str) -> list[tuple[str, str, str | None]]:
    return [
        (t.text, t.kind.value, t.subkind.value if t.subkind else None)
        for t in Tokenizer().tokenize(text)
    ]


def apostrophes(analyzer: RuleBasedAnalyzer, text: str) -> list[tuple[str, ApostropheKind]]:
    sentence = analyzer.analyze(text).sentences[0]
    return [
        (sentence.text[a.span.start - 1 : a.span.end + 1], a.kind) for a in sentence.apostrophes
    ]


def test_proclitic_elisions() -> None:
    assert tokens("l'home d'aigua s'ha m'agrada t'estimo n'hi") == [
        ("l'", "clitic", "proclitic"),
        ("home", "word", None),
        ("d'", "clitic", "proclitic"),
        ("aigua", "word", None),
        ("s'", "clitic", "proclitic"),
        ("ha", "word", None),
        ("m'", "clitic", "proclitic"),
        ("agrada", "word", None),
        ("t'", "clitic", "proclitic"),
        ("estimo", "word", None),
        ("n'", "clitic", "proclitic"),
        ("hi", "word", None),
    ]
    assert tokens("L'Ajuntament D'Alcoi") == [
        ("L'", "clitic", "proclitic"),
        ("Ajuntament", "word", None),
        ("D'", "clitic", "proclitic"),
        ("Alcoi", "word", None),
    ]


def test_typographic_apostrophe_is_equivalent() -> None:
    assert tokens("l’home") == [("l’", "clitic", "proclitic"), ("home", "word", None)]
    assert tokens("menja’n") == [("menja", "word", None), ("’n", "clitic", "enclitic")]


def test_enclitic_apostrophes() -> None:
    assert tokens("menja'n porta'ls compra'l renta't posa'ns") == [
        ("menja", "word", None),
        ("'n", "clitic", "enclitic"),
        ("porta", "word", None),
        ("'ls", "clitic", "enclitic"),
        ("compra", "word", None),
        ("'l", "clitic", "enclitic"),
        ("renta", "word", None),
        ("'t", "clitic", "enclitic"),
        ("posa", "word", None),
        ("'ns", "clitic", "enclitic"),
    ]


def test_apostrophe_before_number_and_isolated() -> None:
    assert tokens("l'11 de setembre") == [
        ("l'", "clitic", "proclitic"),
        ("11", "number", None),
        ("de", "word", None),
        ("setembre", "word", None),
    ]
    assert tokens("menja' ") == [("menja", "word", None), ("'", "punct", "apostrophe")]
    assert tokens("O'Neill rock'n'roll") == [
        ("O'Neill", "word", None),
        ("rock'n'roll", "word", None),
    ]


def test_apostrophe_classification(catalan_analyzer: RuleBasedAnalyzer) -> None:
    text = "D'altra banda, l'home s'ho menja'n tot i n'hi ha; l'he vist."
    kinds = [kind for _, kind in apostrophes(catalan_analyzer, text)]
    assert kinds == [
        ApostropheKind.ELISION_PREPOSITION,  # D'
        ApostropheKind.ARTICLE_OR_PRONOUN,  # l'home
        ApostropheKind.PROCLITIC_PRONOUN,  # s'ho
        ApostropheKind.ENCLITIC_PRONOUN,  # menja'n
        ApostropheKind.PROCLITIC_PRONOUN,  # n'hi
        ApostropheKind.PROCLITIC_PRONOUN,  # l'he (resolt com a pronom per l'auxiliar)
    ]
    quoted = catalan_analyzer.analyze("Va dir ‘hola’ i ‘adeu’.").sentences[0]
    assert {a.kind for a in quoted.apostrophes} == {ApostropheKind.QUOTE}
    foreign = catalan_analyzer.analyze("O'Neill va venir.").sentences[0]
    assert [a.kind for a in foreign.apostrophes] == [ApostropheKind.OTHER]


def test_ela_geminada() -> None:
    for word in ("col·legi", "il·lusió", "novel·la", "paral·lel", "intel·ligent", "Il·lustre"):
        result = tokens(word)
        assert result == [(word, "word", None)], word
    # Forma antiga amb el caràcter ŀ (U+0140): també un sol mot.
    assert tokens("coŀlegi") == [("coŀlegi", "word", None)]
    # Amb punt ordinari no és ela geminada: el punt separa.
    assert [t[0] for t in tokens("col.legi")] == ["col", ".", "legi"]
    sentence = RuleBasedAnalyzer().analyze("El col·legi és a Sant Feliu. Hola.").sentences
    assert [s.text for s in sentence] == ["El col·legi és a Sant Feliu.", "Hola."]


def test_diacritics_are_preserved_and_distinguished(catalan_analyzer: RuleBasedAnalyzer) -> None:
    text = "És així: l'àguila vol, però l'ós dorm; qui sóc? Déu ho sap."
    sentences = catalan_analyzer.analyze(text).sentences
    assert [s.text for s in sentences] == [
        "És així: l'àguila vol, però l'ós dorm; qui sóc?",
        "Déu ho sap.",
    ]
    words = [t.text for s in sentences for t in s.tokens if t.kind is TokenKind.WORD]
    assert {"És", "àguila", "ós", "sóc", "Déu"} <= set(words)
    for sentence in sentences:
        for token in sentence.tokens:
            assert token.span.slice(sentence.text) == token.text
    lexicon = catalan_analyzer.lexicon
    assert lexicon is not None
    # «és» (verb) i «es» (pronom) són entrades diferents; els accents no es normalitzen.
    assert {e.word_class.value for e in lexicon.lookup("és")} == {"auxiliary"}
    assert {e.word_class.value for e in lexicon.lookup("es")} == {"pronoun"}
    assert lexicon.lookup("sí") and lexicon.lookup("si")
    assert {e.subtype for e in lexicon.lookup("sí")} == {"afirmació"}
    assert all(e.subtype != "afirmació" for e in lexicon.lookup("si"))
    assert tokens("ï ü ç Ç") == [
        ("ï", "word", None),
        ("ü", "word", None),
        ("ç", "word", None),
        ("Ç", "word", None),
    ]


def test_punctuation_subkinds() -> None:
    text = 'Va dir: «Hola», “adeu” i "prou" (sí) [no] — o bé - res... Fi?'
    result = [(t.text, t.subkind) for t in Tokenizer().tokenize(text) if t.kind is TokenKind.PUNCT]
    assert result == [
        (":", TokenSubkind.PAUSE),
        ("«", TokenSubkind.QUOTE_OPEN),
        ("»", TokenSubkind.QUOTE_CLOSE),
        (",", TokenSubkind.PAUSE),
        ("“", TokenSubkind.QUOTE_OPEN),
        ("”", TokenSubkind.QUOTE_CLOSE),
        ('"', TokenSubkind.QUOTE_OPEN),
        ('"', TokenSubkind.QUOTE_CLOSE),
        ("(", TokenSubkind.BRACKET_OPEN),
        (")", TokenSubkind.BRACKET_CLOSE),
        ("[", TokenSubkind.BRACKET_OPEN),
        ("]", TokenSubkind.BRACKET_CLOSE),
        ("—", TokenSubkind.DASH),
        ("-", TokenSubkind.HYPHEN),
        ("...", TokenSubkind.SENTENCE_END),
        ("?", TokenSubkind.SENTENCE_END),
    ]
    assert [t.subkind for t in Tokenizer().tokenize("45 % i 3 €") if t.kind is TokenKind.PUNCT] == [
        TokenSubkind.SYMBOL,
        TokenSubkind.SYMBOL,
    ]
