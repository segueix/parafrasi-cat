"""Observacions estilomètriques sobre frases construïdes a mà."""

from __future__ import annotations

import pytest

from parafrasi_cat.analyzer import ClosedClassLexicon, RuleBasedAnalyzer
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.style import DocumentObservations, DocumentObserver, StyleResources
from parafrasi_cat.style.observations import snippet


@pytest.fixture(scope="module")
def resources(paths: ProjectPaths, lexicon: ClosedClassLexicon) -> StyleResources:
    return StyleResources.load(paths, lexicon=lexicon)


@pytest.fixture(scope="module")
def observe(resources: StyleResources, catalan_analyzer: RuleBasedAnalyzer):  # type: ignore[no-untyped-def]
    observer = DocumentObserver(resources)

    def run(text: str) -> DocumentObservations:
        return observer.observe(catalan_analyzer.analyze(text), "prova")

    return run


def test_resources_loaded(resources: StyleResources) -> None:
    assert {g.id for g in resources.variant_groups} >= {"copula", "agent", "presencia", "passat"}
    copula = resources.variant_group("copula")
    assert copula is not None and copula.variant_ids == ("és", "constitueix", "correspon a")
    assert resources.connector_info["tanmateix"] == ("contrast", "formal")
    assert resources.settings.sentence_length_bins[0] == (1, 5)
    assert resources.settings.sentence_length_bins[-1][1] is None


def test_lengths_and_punctuation(observe) -> None:  # type: ignore[no-untyped-def]
    obs = observe("Plou molt; fa fred, però sortirem (potser). Vindràs?\n\nSí!")
    assert obs.n_sentences == 3 and obs.n_paragraphs == 2
    assert obs.sentence_lengths == [7, 1, 1]
    assert obs.n_words == 9
    assert obs.paragraph_sentences == [2, 1] and obs.paragraph_words == [8, 1]
    assert obs.punctuation["semicolon"] == 1
    assert obs.punctuation["comma"] == 1
    assert obs.punctuation["parenthesis"] == 1
    assert obs.punctuation["question"] == 1
    assert obs.punctuation["exclamation"] == 1
    assert obs.commas_per_sentence == [1, 0, 0]
    assert obs.sentence_endings == {"period": 1, "question": 1, "exclamation": 1}


def test_dashes_only_when_they_are_not_hyphens(observe) -> None:  # type: ignore[no-untyped-def]
    obs = observe("El pont —fet per un mestre— és al sud-oest. El pont - vell - cau. Vés-te'n.")
    assert obs.punctuation["dash"] == 4
    assert obs.punctuation["hyphen"] == 0


def test_connector_positions(observe) -> None:  # type: ignore[no-untyped-def]
    obs = observe("No obstant això, plou. Plou, però sortirem. Sortirem després.")
    hits = {hit.form: hit for hit in obs.connectors}
    assert hits["no obstant això"].position == "initial"
    assert hits["no obstant això"].with_comma is True
    assert hits["no obstant això"].function == "contrast"
    assert hits["no obstant això"].register == "formal"
    assert hits["però"].position == "medial"
    assert hits["després"].position == "final"
    assert all(len(hit.example) <= 112 for hit in obs.connectors)


def test_recurrent_ngrams_skip_names_and_pure_function_words(observe) -> None:  # type: ignore[no-untyped-def]
    obs = observe("Crec que plou. Crec que neva. Diu Benedetto que crec que sí. De la casa.")
    assert obs.ngrams["crec que"] == 3
    assert obs.ngrams["que plou"] == 1
    assert not any("benedetto" in key for key in obs.ngrams)
    assert "de la" not in obs.ngrams  # només mots de classe tancada
    assert "la casa" in obs.ngrams
    assert obs.content_tokens == ["crec", "plou", "crec", "neva", "diu", "crec", "casa"]
    assert obs.ngram_examples["crec que"] == "Crec que plou."


def test_impersonal_structures(observe) -> None:  # type: ignore[no-untyped-def]
    obs = observe(
        "Es considera que hi ha tres arcs. Cal anar-hi. Hom diu que és necessari que plogui. "
        "Sembla que sí. Ell es renta."
    )
    kinds = [hit.kind for hit in obs.impersonal]
    assert kinds.count("es + verb") == 2
    assert "hi ha" in kinds and "cal" in kinds and "hom" in kinds
    assert "és + adjectiu + que/infinitiu" in kinds and "sembla que" in kinds
    assert any(hit.text == "Es considera" for hit in obs.impersonal)


def test_first_person_sure_and_approximate(observe) -> None:  # type: ignore[no-untyped-def]
    obs = observe(
        "Jo crec que el meu poble és bonic. Nosaltres ens estimem la nostra terra. "
        "Compro pa i el ferro pesa. El mínim és clar."
    )
    singular = [hit for hit in obs.first_person if hit.kind == "singular"]
    plural = [hit for hit in obs.first_person if hit.kind == "plural"]
    assert sorted(h.text for h in singular if h.extra == "sure") == ["Jo", "meu"]
    assert [h.text for h in singular if h.extra == "approximate"] == ["Compro"]
    assert sorted(h.text for h in plural if h.extra == "sure") == ["Nosaltres", "ens", "nostra"]
    assert [h.text for h in plural if h.extra == "approximate"] == ["estimem"]


def test_passive_tiers(observe) -> None:  # type: ignore[no-untyped-def]
    obs = observe(
        "El pont fou bastit pel consell. El monument va ser encarregat el 1507. "
        "La casa és coneguda. La font ha estat restaurada. El projecte fou fet per a l'ocasió. "
        "El mur fou construït per un mestre. La sala és decorada per un pintor."
    )
    tiers = [(hit.kind, hit.extra) for hit in obs.passive]
    assert tiers == [
        ("sure", "agent"),
        ("sure", ""),
        ("ambiguous", ""),
        ("sure", ""),
        ("sure", ""),
        ("sure", "agent"),
        ("sure", "agent"),
    ]
    assert obs.passive[0].text == "fou bastit"
    assert obs.passive[3].text == "ha estat restaurada"


def test_word_classes_are_approximate_but_sensible(observe) -> None:  # type: ignore[no-untyped-def]
    obs = observe("El pont vell presenta tres arcs de pedra.")
    assert obs.word_classes == {"function": 3, "noun": 3, "verb": 1, "other": 1}


def test_variant_detection(observe) -> None:  # type: ignore[no-untyped-def]
    obs = observe(
        "La font és el cor de la plaça. És clar que plou. El pont fou fet per un mestre i "
        "finalitzat el 1742. Els veïns el van reparar. Els obrers acabaren l'obra. "
        "Hi ha la presència de dos cranis i hi ha un escut."
    )
    counts = {g: {v: len(x) for v, x in vs.items()} for g, vs in obs.variants.items()}
    assert counts["copula"] == {"és": 1}
    assert counts["agent"] == {"fet per": 1}
    assert counts["finalitzar_acabar"] == {"finalitzar": 1, "acabar": 1}
    assert counts["passat"] == {"simple": 2, "perifràstic": 1}
    assert counts["presencia"] == {"hi ha la presència de": 1, "hi ha": 1}
    assert obs.variants["copula"]["és"] == ["La font és el cor de la plaça."]


def test_snippet_is_short() -> None:
    assert snippet("Frase curta.", 0, 5) == "Frase curta."
    long = " ".join(f"mot{i}" for i in range(60))
    start = long.index("mot30")
    piece = snippet(long, start, start + 5, 60)
    assert "mot30" in piece and piece.startswith("…") and piece.endswith("…")
    assert len(piece) <= 70
