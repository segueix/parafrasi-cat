"""Formes amb guionet: verbs amb enclítics, compostos, intervals i separadors."""

from __future__ import annotations

from parafrasi_cat.analyzer import HyphenKind, RuleBasedAnalyzer, Tokenizer, TokenSubkind


def tokens(text: str) -> list[tuple[str, str, str | None]]:
    return [
        (t.text, t.kind.value, t.subkind.value if t.subkind else None)
        for t in Tokenizer().tokenize(text)
    ]


def forms(text: str) -> list[tuple[str, HyphenKind, tuple[str, ...]]]:
    sentence = RuleBasedAnalyzer().analyze(text).sentences[0]
    result = []
    for form in sentence.hyphenated_forms:
        assert form.span.slice(sentence.text) == form.text
        result.append((form.text, form.kind, form.parts))
    return result


def test_verb_with_hyphenated_enclitics_is_split() -> None:
    assert tokens("porta-ho") == [("porta", "word", None), ("-ho", "clitic", "enclitic")]
    assert tokens("vés-te'n") == [
        ("vés", "word", None),
        ("-te", "clitic", "enclitic"),
        ("'n", "clitic", "enclitic"),
    ]
    assert tokens("dona-m'ho") == [
        ("dona", "word", None),
        ("-m'", "clitic", "enclitic"),
        ("ho", "clitic", "enclitic"),
    ]
    assert tokens("anem-nos-en") == [
        ("anem", "word", None),
        ("-nos", "clitic", "enclitic"),
        ("-en", "clitic", "enclitic"),
    ]
    assert tokens("digues-li-ho porta'ls-hi emporta-te'ls") == [
        ("digues", "word", None),
        ("-li", "clitic", "enclitic"),
        ("-ho", "clitic", "enclitic"),
        ("porta", "word", None),
        ("'ls", "clitic", "enclitic"),
        ("-hi", "clitic", "enclitic"),
        ("emporta", "word", None),
        ("-te", "clitic", "enclitic"),
        ("'ls", "clitic", "enclitic"),
    ]


def test_compounds_stay_whole() -> None:
    for word in (
        "sud-oest",
        "pèl-roig",
        "Vila-seca",
        "ex-president",
        "no-res",
        "cul-de-sac",
        "Jean-Pierre",
    ):
        assert tokens(word) == [(word, "word", "compound")], word
    # «-en» i «-el» només poden seguir un altre pronom: no descomponen compostos.
    assert tokens("Sant-en") == [("Sant-en", "word", "compound")]


def test_hyphenated_forms_annotation() -> None:
    assert forms("Porta-ho a Vila-seca, entre 1507-1516, i vés-te'n - ara.") == [
        ("Porta-ho", HyphenKind.ENCLITIC_PRONOUNS, ("Porta", "-ho")),
        ("Vila-seca", HyphenKind.COMPOUND, ("Vila", "seca")),
        ("1507-1516", HyphenKind.NUMERIC_RANGE, ("1507", "1516")),
        ("vés-te'n", HyphenKind.ENCLITIC_PRONOUNS, ("vés", "-te", "'n")),
        ("-", HyphenKind.SEPARATOR, ("-",)),
    ]


def test_dashes_are_not_hyphens() -> None:
    result = Tokenizer().tokenize("Va venir — i va marxar – de pressa.")
    assert [t.subkind for t in result if t.text in ("—", "–")] == [
        TokenSubkind.DASH,
        TokenSubkind.DASH,
    ]
    assert forms("Va venir — i va marxar.") == []
