"""Identificació conservadora dels pronoms febles."""

from __future__ import annotations

from parafrasi_cat.analyzer import (
    Certainty,
    PronounAttachment,
    RuleBasedAnalyzer,
    Tokenizer,
    canonical_form,
    find_weak_pronouns,
)


def pronouns(analyzer: RuleBasedAnalyzer, text: str) -> list[tuple[str, str, str, str]]:
    sentence = analyzer.analyze(text).sentences[0]
    result = []
    for pronoun in sentence.pronouns:
        assert sentence.text[pronoun.span.start : pronoun.span.end] == pronoun.text
        result.append(
            (pronoun.text, pronoun.canonical, pronoun.attachment.value, pronoun.certainty.value)
        )
    return result


def test_unambiguous_free_forms(catalan_analyzer: RuleBasedAnalyzer) -> None:
    assert pronouns(catalan_analyzer, "Em sembla que et veig i ho sé; hi anem i us ho dic.") == [
        ("Em", "em", "free", "sure"),
        ("et", "et", "free", "sure"),
        ("ho", "ho", "free", "sure"),
        ("hi", "hi", "free", "sure"),
        ("us", "us", "free", "sure"),
        ("ho", "ho", "free", "sure"),
    ]


def test_clusters_resolve_reinforced_and_ambiguous_forms(
    catalan_analyzer: RuleBasedAnalyzer,
) -> None:
    assert pronouns(catalan_analyzer, "Se'n poden extreure conclusions.") == [
        ("Se", "es", "free", "sure"),
        ("'n", "en", "enclitic", "sure"),
    ]
    assert pronouns(catalan_analyzer, "Me la va donar i se li va trencar.") == [
        ("Me", "em", "free", "sure"),
        ("la", "la", "free", "sure"),
        ("se", "es", "free", "sure"),
        ("li", "li", "free", "sure"),
    ]
    assert pronouns(catalan_analyzer, "Els hi portarem.") == [
        ("Els", "els", "free", "sure"),
        ("hi", "hi", "free", "sure"),
    ]


def test_articles_are_not_reported_as_pronouns(catalan_analyzer: RuleBasedAnalyzer) -> None:
    assert pronouns(catalan_analyzer, "El monument i la casa dels segles passats.") == []
    assert pronouns(catalan_analyzer, "Els textos presenten diferències.") == []
    # Davant d'una forma auxiliar sí que és pronom.
    assert pronouns(catalan_analyzer, "El va veure i la vaig llegir.") == [
        ("El", "el", "free", "sure"),
        ("la", "la", "free", "sure"),
    ]


def test_en_is_only_a_pronoun_with_evidence(catalan_analyzer: RuleBasedAnalyzer) -> None:
    assert pronouns(catalan_analyzer, "En aquest cas, en Joan parla en veu alta.") == []
    assert pronouns(catalan_analyzer, "En va parlar molt.") == [("En", "en", "free", "sure")]
    assert pronouns(catalan_analyzer, "N'hi ha molts.") == [
        ("N'", "en", "proclitic", "sure"),
        ("hi", "hi", "free", "sure"),
    ]


def test_elided_l_is_ambiguous_unless_confirmed(catalan_analyzer: RuleBasedAnalyzer) -> None:
    assert pronouns(catalan_analyzer, "L'home l'ha vist.") == [
        ("L'", "el", "proclitic", "ambiguous"),
        ("l'", "el", "proclitic", "sure"),
    ]
    assert pronouns(catalan_analyzer, "Se l'ha menjat.") == [
        ("Se", "es", "free", "sure"),
        ("l'", "el", "proclitic", "sure"),
    ]
    ambiguous = catalan_analyzer.analyze("L'home dorm.").sentences[0].pronouns
    assert ambiguous[0].certainty is Certainty.AMBIGUOUS and "article" in ambiguous[0].note


def test_proclitics_and_enclitics(catalan_analyzer: RuleBasedAnalyzer) -> None:
    assert pronouns(
        catalan_analyzer, "M'agrada, s'ho menja i t'ho dic: porta-m'ho i vés-te'n."
    ) == [
        ("M'", "em", "proclitic", "sure"),
        ("s'", "es", "proclitic", "sure"),
        ("ho", "ho", "free", "sure"),
        ("t'", "et", "proclitic", "sure"),
        ("ho", "ho", "free", "sure"),
        ("-m'", "em", "enclitic", "sure"),
        ("ho", "ho", "enclitic", "sure"),
        ("-te", "et", "enclitic", "sure"),
        ("'n", "en", "enclitic", "sure"),
    ]
    # «d'» és la preposició, mai un pronom.
    assert pronouns(catalan_analyzer, "D'altra banda, d'acord.") == []


def test_latin_et_al_is_not_a_pronoun(catalan_analyzer: RuleBasedAnalyzer) -> None:
    assert pronouns(catalan_analyzer, "Fabra et al. ho van dir.") == [("ho", "ho", "free", "sure")]


def test_canonical_forms() -> None:
    assert canonical_form("-me") == "em"
    assert canonical_form("'ls") == "els"
    assert canonical_form("’n") == "en"
    assert canonical_form("-nos") == "ens"
    assert canonical_form("vos") == "us"
    assert canonical_form("HO") == "ho"


def test_find_weak_pronouns_without_lexicon_uses_default_auxiliaries() -> None:
    tokens = Tokenizer().tokenize("La vaig veure i la casa.")
    found = find_weak_pronouns(tokens)
    assert [(p.text, p.attachment) for p in found] == [("La", PronounAttachment.FREE)]
