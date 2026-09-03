"""Casos de prova de la capa d'anàlisi lingüística (fase 2).

Cada frase passa per l'analitzador complet (paràgrafs, frases, tokens,
pronoms febles, expressions multiparaula), pel protector i per l'analitzador
morfològic intern. El text no es transforma mai.
"""

from __future__ import annotations

from pathlib import Path

from parafrasi_cat.analyzer import (
    ApostropheKind,
    Certainty,
    ClosedClassLexicon,
    PronounAttachment,
    RuleBasedAnalyzer,
    TokenKind,
    TokenSubkind,
    WordClass,
)
from parafrasi_cat.morphology import InternalMorphology, create_morphology_provider
from parafrasi_cat.protected import ProtectionKind, default_protector

CASES = (
    "D'altra banda, aquesta documentació permet plantejar una interpretació diferent.",
    "Se'n poden extreure diverses conclusions.",
    "El monument fou encarregat el 1507 i finalitzat el 1516.",
    "Els textos dels segles XI, XII i XIII presenten diferències importants.",
    "Ramon Borrell podria haver conegut aquesta tradició.",
)


def token_view(analyzer: RuleBasedAnalyzer, text: str) -> list[tuple[str, str, str | None]]:
    sentence = analyzer.analyze(text).sentences[0]
    return [(t.text, t.kind.value, t.subkind.value if t.subkind else None) for t in sentence.tokens]


def test_offsets_are_exact_for_every_case(catalan_analyzer: RuleBasedAnalyzer) -> None:
    for text in CASES:
        analysis = catalan_analyzer.analyze(text)
        assert analysis.n_paragraphs == 1 and analysis.n_sentences == 1
        sentence = analysis.sentences[0]
        assert sentence.span.slice(text) == sentence.text == text
        for token in sentence.tokens:
            assert token.span.slice(sentence.text) == token.text
        assert "".join(t.text for t in sentence.tokens).replace(" ", "") == text.replace(" ", "")


def test_case_1_discourse_marker_and_elision(catalan_analyzer: RuleBasedAnalyzer) -> None:
    text = CASES[0]
    sentence = catalan_analyzer.analyze(text).sentences[0]
    assert token_view(catalan_analyzer, text)[:4] == [
        ("D'", "clitic", "proclitic"),
        ("altra", "word", None),
        ("banda", "word", None),
        (",", "punct", "pause"),
    ]
    assert [(e.text, e.word_class, e.function) for e in sentence.expressions] == [
        ("D'altra banda", WordClass.DISCOURSE_MARKER, "estructuració")
    ]
    assert [a.kind for a in sentence.apostrophes] == [ApostropheKind.ELISION_PREPOSITION]
    assert sentence.pronouns == ()
    assert default_protector(catalan_analyzer).protect(text) == ()


def test_case_2_weak_pronoun_cluster(catalan_analyzer: RuleBasedAnalyzer) -> None:
    text = CASES[1]
    sentence = catalan_analyzer.analyze(text).sentences[0]
    assert token_view(catalan_analyzer, text)[:3] == [
        ("Se", "word", None),
        ("'n", "clitic", "enclitic"),
        ("poden", "word", None),
    ]
    assert [(p.text, p.canonical, p.attachment, p.certainty) for p in sentence.pronouns] == [
        ("Se", "es", PronounAttachment.FREE, Certainty.SURE),
        ("'n", "en", PronounAttachment.ENCLITIC, Certainty.SURE),
    ]
    assert [a.kind for a in sentence.apostrophes] == [ApostropheKind.ENCLITIC_PRONOUN]
    assert default_protector(catalan_analyzer).protect(text) == ()


def test_case_3_years_are_protected_and_ser_is_auxiliary(
    catalan_analyzer: RuleBasedAnalyzer, lexicon: ClosedClassLexicon
) -> None:
    text = CASES[2]
    spans = default_protector(catalan_analyzer).protect(text)
    assert [(s.text, s.kind) for s in spans] == [
        ("1507", ProtectionKind.NUMBER),
        ("1516", ProtectionKind.NUMBER),
    ]
    numbers = catalan_analyzer.analyze(text).sentences[0].numbers
    assert [n.text for n in numbers] == ["1507", "1516"]
    morphology = InternalMorphology(lexicon)
    fou = morphology.analyze("fou")
    assert len(fou) == 1
    assert fou[0].lemma == "ser" and fou[0].source == "lexicon:auxiliary"
    assert fou[0].features.to_dict() == {
        "pos": "aux",
        "number": "sg",
        "person": "3",
        "tense": "past",
        "mood": "ind",
    }
    encarregat = morphology.analyze("encarregat")
    assert encarregat[0].lemma == "encarregar" and encarregat[0].features.mood == "part"
    assert encarregat[0].source == "guesser" and encarregat[0].confidence < 1.0


def test_case_4_roman_centuries(catalan_analyzer: RuleBasedAnalyzer) -> None:
    text = CASES[3]
    sentence = catalan_analyzer.analyze(text).sentences[0]
    assert [(r.text, r.value) for r in sentence.roman_numerals] == [
        ("XI", 11),
        ("XII", 12),
        ("XIII", 13),
    ]
    romans = [t for t in sentence.tokens if t.subkind is TokenSubkind.ROMAN_NUMERAL]
    assert [t.text for t in romans] == ["XI", "XII", "XIII"]
    spans = default_protector(catalan_analyzer).protect(text)
    assert [(s.text, s.kind) for s in spans] == [
        ("XI", ProtectionKind.ROMAN_NUMERAL),
        ("XII", ProtectionKind.ROMAN_NUMERAL),
        ("XIII", ProtectionKind.ROMAN_NUMERAL),
    ]
    # «dels» és una contracció registrada al lexicó.
    dels = [t for t in sentence.tokens if t.text == "dels"][0]
    assert dels.kind is TokenKind.WORD
    entry = catalan_analyzer.lexicon.lookup("dels")[0] if catalan_analyzer.lexicon else None
    assert entry is not None and entry.parts == ("de", "els")


def test_case_5_medieval_name_and_modal_periphrasis(
    catalan_analyzer: RuleBasedAnalyzer, lexicon: ClosedClassLexicon
) -> None:
    text = CASES[4]
    spans = default_protector(catalan_analyzer).protect(text)
    assert [(s.text, s.kind) for s in spans] == [("Ramon Borrell", ProtectionKind.PROPER_NOUN)]
    morphology = InternalMorphology(lexicon)
    podria = morphology.analyze("podria")
    assert {e.lemma for e in podria} == {"poder"}
    assert {e.features.person for e in podria} == {"1", "3"}
    assert all(e.features.tense == "cond" for e in podria)
    haver = morphology.analyze("haver")
    assert haver[0].lemma == "haver" and haver[0].features.mood == "inf"
    conegut = morphology.analyze("conegut")
    assert conegut[0].lemma == "conèixer" and conegut[0].features.mood == "part"


def test_pipeline_uses_the_analysis_layer_without_transforming(project_root: Path) -> None:
    from parafrasi_cat import PipelineConfig, build_pipeline

    pipeline = build_pipeline(PipelineConfig(morphology="internal"))
    text = "\n".join(CASES)
    result = pipeline.run(text)
    assert result.output_text == text
    assert [s.text for s in result.protected_spans] == [
        "1507",
        "1516",
        "XI",
        "XII",
        "XIII",
        "Ramon Borrell",
    ]
    provider = create_morphology_provider("internal", project_root / "resources" / "ca")
    assert isinstance(provider, InternalMorphology)
