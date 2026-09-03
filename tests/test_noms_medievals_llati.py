"""Noms propis medievals (conservadors) i expressions llatines."""

from __future__ import annotations

from parafrasi_cat.analyzer import RuleBasedAnalyzer, TokenSubkind, WordClass
from parafrasi_cat.protected import ProtectionKind, default_protector


def protected(analyzer: RuleBasedAnalyzer, text: str) -> list[tuple[str, str]]:
    spans = default_protector(analyzer).protect(text)
    for span in spans:
        assert span.span.slice(text) == span.text
    return [(s.text, s.kind.value) for s in spans]


def names(analyzer: RuleBasedAnalyzer, text: str) -> list[str]:
    return [t for t, kind in protected(analyzer, text) if kind == ProtectionKind.PROPER_NOUN.value]


def test_medieval_names_with_numerals_and_epithets(catalan_analyzer: RuleBasedAnalyzer) -> None:
    assert names(catalan_analyzer, "Ramon Borrell podria haver conegut aquesta tradició.") == [
        "Ramon Borrell"
    ]
    assert names(catalan_analyzer, "El comte Borrell II va trencar amb els francs.") == [
        "Borrell II"
    ]
    assert names(catalan_analyzer, "Ramon Berenguer IV es casà amb Peronella.") == [
        "Ramon Berenguer IV",
        "Peronella",
    ]
    assert names(catalan_analyzer, "Guifré el Pilós va morir el 897.") == ["Guifré el Pilós"]
    assert names(catalan_analyzer, "Martí l'Humà fou l'últim rei.") == ["Martí l'Humà"]
    assert names(catalan_analyzer, "Ho va dir Jaume I el Conqueridor.") == [
        "Jaume I el Conqueridor"
    ]
    assert names(catalan_analyzer, "Ermessenda de Carcassona governà el comtat.") == [
        "Ermessenda de Carcassona"
    ]
    assert names(catalan_analyzer, "L'abat Oliba va fundar Montserrat.") == ["Oliba", "Montserrat"]
    assert names(catalan_analyzer, "Segons Guillem de Cabestany, l'amor és cec.") == [
        "Guillem de Cabestany"
    ]


def test_conservative_sentence_start(catalan_analyzer: RuleBasedAnalyzer) -> None:
    # Un verb inicial no s'arrossega dins del nom.
    assert names(catalan_analyzer, "Visitem el Museu Nacional.") == ["Museu Nacional"]
    assert names(catalan_analyzer, "Visitem l'Institut d'Estudis Catalans.") == [
        "Institut d'Estudis Catalans"
    ]
    # Un sol nom al començament de frase no es distingeix d'una paraula ordinària.
    assert names(catalan_analyzer, "Borrell va morir el 992.") == []
    # Els mots gramaticals inicials (pronoms, articles...) mai no comencen un nom.
    assert names(catalan_analyzer, "Se'n va anar a Ripoll.") == ["Ripoll"]
    assert names(catalan_analyzer, "Els comtes de Barcelona hi eren.") == ["Barcelona"]
    # Un número romà no comença un nom.
    assert names(catalan_analyzer, "Els segles XI i XII.") == []


def test_roman_numeral_inside_name_is_also_protected(catalan_analyzer: RuleBasedAnalyzer) -> None:
    assert protected(catalan_analyzer, "El comte Borrell II va trencar amb els francs.") == [
        ("Borrell II", "proper_noun"),
        ("II", "roman_numeral"),
    ]


def test_latin_bibliographic_expressions(catalan_analyzer: RuleBasedAnalyzer) -> None:
    text = "Fabra et al. van proposar una norma (vegeu op. cit., p. 34 i ibid.)."
    assert [s.text for s in catalan_analyzer.analyze(text).sentences] == [text]
    assert protected(catalan_analyzer, text) == [
        ("et al.", "citation"),
        ("op. cit.", "citation"),
        ("p. 34", "citation"),
        ("34", "number"),
        ("ibid.", "citation"),
    ]
    # Un parèntesi amb any és una citació sencera.
    assert ("(1918: 23)", "citation") in protected(catalan_analyzer, "Segons Fabra (1918: 23), no.")
    sentence = catalan_analyzer.analyze("Vegeu cf. Fabra, ca. 1918, i vs. Moll.").sentences[0]
    assert [t.text for t in sentence.tokens if t.subkind is TokenSubkind.ABBREVIATION] == [
        "cf",
        "ca",
        "vs",
    ]


def test_latin_adverbial_expressions_are_multiword_units(
    catalan_analyzer: RuleBasedAnalyzer,
) -> None:
    sentence = catalan_analyzer.analyze(
        "A priori, la decisió es va prendre in situ, ad hoc i grosso modo."
    ).sentences[0]
    assert [(e.text, e.word_class, e.origin) for e in sentence.expressions] == [
        ("A priori", WordClass.ADVERB, "llatí"),
        ("in situ", WordClass.ADVERB, "llatí"),
        ("ad hoc", WordClass.ADVERB, "llatí"),
        ("grosso modo", WordClass.ADVERB, "llatí"),
    ]
    for expression in sentence.expressions:
        assert expression.span.slice(sentence.text) == expression.text
        assert len(expression.token_indices) == 2


def test_dates_with_era_and_centuries(catalan_analyzer: RuleBasedAnalyzer) -> None:
    assert protected(catalan_analyzer, "Va passar el 218 aC i al segle II dC.") == [
        ("218 aC", "date"),
        ("218", "number"),
        ("segle II dC", "date"),
        ("II", "roman_numeral"),
    ]
