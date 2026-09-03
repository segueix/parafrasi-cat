"""Lexicó de classes tancades i expressions multiparaula."""

from __future__ import annotations

from pathlib import Path

from parafrasi_cat.analyzer import (
    ClosedClassLexicon,
    RuleBasedAnalyzer,
    WordClass,
    find_multiword_expressions,
)
from parafrasi_cat.analyzer.lexicon import entries_from_mapping, normalize_form


def test_all_classes_are_loaded(lexicon: ClosedClassLexicon) -> None:
    for word_class in WordClass:
        assert lexicon.of_class(word_class), word_class
    assert len(lexicon) > 500


def test_lookup_is_case_and_apostrophe_insensitive(lexicon: ClosedClassLexicon) -> None:
    assert {e.word_class for e in lexicon.lookup("Dels")} == {WordClass.ARTICLE}
    assert lexicon.lookup("dels")[0].parts == ("de", "els")
    assert lexicon.lookup("L’")[0].word_class is WordClass.ARTICLE or lexicon.lookup("L’")
    assert {e.word_class for e in lexicon.lookup("l'")} == {WordClass.ARTICLE, WordClass.PRONOUN}
    assert lexicon.has("no obstant això")
    assert lexicon.classes_of("però") == {WordClass.CONJUNCTION, WordClass.CONNECTOR}
    assert not lexicon.has("documentació")
    assert normalize_form("  D’Altra   Banda ") == "d'altra banda"


def test_pronoun_entries_have_canonical_forms(lexicon: ClosedClassLexicon) -> None:
    weak = [e for e in lexicon.of_class(WordClass.PRONOUN) if e.subtype == "feble"]
    assert {e.canonical for e in weak} == {
        "em",
        "et",
        "es",
        "el",
        "la",
        "els",
        "les",
        "li",
        "ho",
        "hi",
        "en",
        "ens",
        "us",
    }
    assert {e.form for e in weak if e.canonical == "em"} == {"em", "'m", "m'", "-me", "me"}


def test_auxiliary_entries(lexicon: ClosedClassLexicon) -> None:
    forms = lexicon.forms_of(WordClass.AUXILIARY)
    for form in (
        "he",
        "ha",
        "han",
        "havia",
        "fou",
        "era",
        "és",
        "són",
        "va",
        "van",
        "pot",
        "poden",
        "podria",
        "cal",
        "sol",
    ):
        assert form in forms, form
    havia = lexicon.lookup("havia")
    assert {e.feature("person") for e in havia} == {"1", "3"}
    assert all(e.lemma == "haver" and e.feature("tense") == "impf" for e in havia)
    soc = lexicon.lookup("sóc")
    assert soc and soc[0].lemma == "ser"


def test_multiword_expressions_prefer_longest(lexicon: ClosedClassLexicon) -> None:
    analyzer = RuleBasedAnalyzer(lexicon=lexicon)
    text = "No obstant això, a partir de demà, tot i que plou, en primer lloc sortirem."
    sentence = analyzer.analyze(text).sentences[0]
    assert [e.text for e in sentence.expressions] == [
        "No obstant això",
        "a partir de",
        "tot i que",
        "en primer lloc",
    ]
    classes = [e.word_class for e in sentence.expressions]
    assert classes[:3] == [WordClass.CONNECTOR, WordClass.PREPOSITION, WordClass.CONJUNCTION]
    # «en primer lloc» és alhora connector i marcador discursiu.
    assert classes[3] in (WordClass.CONNECTOR, WordClass.DISCOURSE_MARKER)
    tokens = sentence.tokens
    assert find_multiword_expressions(text, tokens, ClosedClassLexicon.empty()) == ()


def test_entries_from_mapping_expands_variants_and_persons() -> None:
    data = {
        "pos": "aux",
        "entries": [
            {
                "form": "havia",
                "lemma": "haver",
                "persons": ["1", "3"],
                "number": "sg",
                "variants": ["havie"],
            },
            {"form": "sóc", "lemma": "ser", "person": 1, "number": "sg"},
        ],
    }
    entries = entries_from_mapping(data, WordClass.AUXILIARY)
    assert [(e.form, e.feature("person")) for e in entries] == [
        ("havia", "1"),
        ("havia", "3"),
        ("havie", "1"),
        ("havie", "3"),
        ("sóc", "1"),
    ]
    assert entries[0].pos == "aux" and entries[0].feature("number") == "sg"


def test_load_from_missing_directory_gives_empty_lexicon(tmp_path: Path) -> None:
    empty = ClosedClassLexicon.load(tmp_path)
    assert len(empty) == 0 and empty.multiword_patterns() == ()
