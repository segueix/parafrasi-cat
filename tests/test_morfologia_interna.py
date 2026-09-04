"""Interfície morfològica desacoblada: analitzador intern, registre i adaptadors."""

from __future__ import annotations

from pathlib import Path

import pytest

from parafrasi_cat.analyzer import ClosedClassLexicon
from parafrasi_cat.core import ConfigError
from parafrasi_cat.morphology import (
    DictionaryMorphology,
    InternalMorphology,
    MorphFeatures,
    MorphologyContext,
    MorphologyProvider,
    NullMorphology,
    create_morphology_provider,
    default_morphology_registry,
    guess,
)
from parafrasi_cat.morphology.adapters import (
    ApertiumMorphology,
    FreeLingMorphology,
    MorphologyUnavailableError,
    decode_eagles,
    parse_apertium_stream,
    parse_freeling_morfo,
)
from parafrasi_cat.resources import ProjectPaths


def test_internal_provider_combines_sources(
    lexicon: ClosedClassLexicon, paths: ProjectPaths
) -> None:
    dictionary = DictionaryMorphology.from_file(
        Path(str(paths.language())) / "morphology" / "formes.yaml"
    )
    morphology = InternalMorphology(lexicon, dictionary)
    assert isinstance(morphology, MorphologyProvider)
    assert morphology.is_function_word("dels") and not morphology.is_function_word("monument")

    cases = morphology.analyze("cases")
    assert cases[0].source == "dictionary" and cases[0].lemma == "casa"

    fou = morphology.analyze("fou")
    assert fou[0].source == "lexicon:auxiliary" and fou[0].confidence == 1.0

    documentacio = morphology.analyze("documentació")
    assert documentacio[0].source == "guesser" and documentacio[0].confidence < 0.5

    assert morphology.generate(
        "haver", MorphFeatures(person="3", number="sg", tense="pres", mood="ind")
    ) == ("ha",)
    assert "cases" in morphology.generate("casa", MorphFeatures(number="pl"))
    assert InternalMorphology(lexicon, use_guesser=False).analyze("documentació") == ()


def test_guesser_rules() -> None:
    def one(form: str) -> tuple[str, dict[str, str], float]:
        entries = guess(form)
        assert len(entries) == 1, form
        entry = entries[0]
        return entry.lemma, entry.features.to_dict(), entry.confidence

    assert one("encarregat")[:2] == (
        "encarregar",
        {"pos": "verb", "gender": "m", "number": "sg", "mood": "part"},
    )
    assert one("finalitzades")[0] == "finalitzar"
    assert one("conegut")[0] == "conèixer"
    assert one("coneguda")[1]["gender"] == "f"
    assert one("entesos")[0] == "entendre"
    assert one("presenten")[:2] == (
        "presentar",
        {"pos": "verb", "number": "pl", "person": "3", "tense": "pres", "mood": "ind"},
    )
    assert one("extreuen")[0] == "extreure"
    assert one("plantejar")[1] == {"pos": "verb", "mood": "inf"}
    assert one("cantava")[0] == "cantar" and one("cantava")[1]["tense"] == "impf"
    assert one("dormirien")[:2] == (
        "dormir",
        {"pos": "verb", "number": "pl", "person": "3", "tense": "cond", "mood": "ind"},
    )
    assert one("gràcia")[1]["pos"] == "noun"  # esdrúixol: «-ia» no és desinència verbal
    assert one("creia")[0] == "creure" and one("creia")[1]["tense"] == "impf"
    assert one("permet")[1] == {"pos": "noun", "number": "sg"} and one("permet")[2] == 0.2
    assert guess("XI") == () and guess("12") == () and guess("a") == ()
    assert all(entry.source == "guesser" for entry in guess("cantaven"))


def test_registry_and_factory(project_root: Path, lexicon: ClosedClassLexicon) -> None:
    lang = project_root / "resources" / "ca"
    registry = default_morphology_registry()
    assert registry.available() == (
        "apertium",
        "catalan",
        "dictionary",
        "freeling",
        "internal",
        "null",
    )
    assert "Apertium" in registry.describe("apertium")
    assert isinstance(create_morphology_provider("null", lang), NullMorphology)
    assert isinstance(create_morphology_provider("dictionary", lang), DictionaryMorphology)
    internal = create_morphology_provider("internal", lang, lexicon=lexicon)
    assert isinstance(internal, InternalMorphology) and internal.lexicon is lexicon
    with pytest.raises(ConfigError):
        create_morphology_provider("inexistent", lang)
    with pytest.raises(ConfigError):
        registry.register("null", lambda ctx: NullMorphology())
    context = MorphologyContext(lang)
    assert context.load_dictionary() is not None and len(context.load_lexicon()) > 0


def test_external_adapters_are_unavailable_here_and_fail_clearly(project_root: Path) -> None:
    lang = project_root / "resources" / "ca"
    apertium = ApertiumMorphology(command="apertium-inexistent-xyz")
    assert not apertium.is_available()
    with pytest.raises(MorphologyUnavailableError):
        apertium.analyze("casa")
    with pytest.raises(MorphologyUnavailableError):
        create_morphology_provider("apertium", lang, options={"command": "apertium-inexistent-xyz"})
    with pytest.raises(MorphologyUnavailableError):
        create_morphology_provider("freeling", lang, options={"command": "analyze-inexistent-xyz"})
    assert apertium.arguments() == ["cat-morph"]
    assert ApertiumMorphology.from_options(
        {"mode": "cat-tagger", "data_dir": "/x"}
    ).arguments() == [
        "-d",
        "/x",
        "cat-tagger",
    ]
    assert FreeLingMorphology.from_options({"config": "ca.cfg"}).arguments()[:2] == ["-f", "ca.cfg"]


def test_apertium_stream_parser() -> None:
    output = (
        "^casa/casa<n><f><sg>/casar<vblex><pri><p3><sg>$ ^*documentaciooo$ "
        "^l'/el<det><def><mf><sg>/el<prn><pro><p3><m><sg>$\n"
    )
    units = parse_apertium_stream(output)
    assert [surface for surface, _ in units] == ["casa", "documentaciooo", "l'"]
    casa = units[0][1]
    assert [(r.lemma, r.tags) for r in casa] == [
        ("casa", ("n", "f", "sg")),
        ("casar", ("vblex", "pri", "p3", "sg")),
    ]
    assert casa[0].to_features().to_dict() == {"pos": "noun", "gender": "f", "number": "sg"}
    assert casa[1].to_features().to_dict() == {
        "pos": "verb",
        "number": "sg",
        "person": "3",
        "tense": "pres",
        "mood": "ind",
    }
    assert units[1][1] == ()
    adapter = ApertiumMorphology()
    entries = adapter.entries_from_output("Casa", output)
    assert [e.lemma for e in entries] == ["casa", "casar"] and entries[0].source == "apertium"
    assert parse_apertium_stream(r"^a\/b/a\/b<n>$")[0][0] == "a/b"


def test_freeling_parser_and_eagles() -> None:
    output = (
        "El el DA0MS0 1\nmonument monument NCMS000 1\nfou ser VSIS3S0 1\n"
        "encarregat encarregar VMP00SM 0.9\n\n"
    )
    units = parse_freeling_morfo(output)
    assert [surface for surface, _ in units] == ["El", "monument", "fou", "encarregat"]
    assert decode_eagles("DA0MS0").to_dict() == {"pos": "det", "gender": "m", "number": "sg"}
    assert decode_eagles("NCMS000").to_dict() == {"pos": "noun", "gender": "m", "number": "sg"}
    assert decode_eagles("VSIS3S0").to_dict() == {
        "pos": "aux",
        "number": "sg",
        "person": "3",
        "tense": "past",
        "mood": "ind",
    }
    assert decode_eagles("VMP00SM").to_dict() == {
        "pos": "verb",
        "gender": "m",
        "number": "sg",
        "mood": "part",
    }
    assert decode_eagles("NP00000").pos == "propn" and decode_eagles("").pos is None
    adapter = FreeLingMorphology()
    entries = adapter.entries_from_output("fou", output)
    assert (
        entries[0].lemma == "ser"
        and entries[0].source == "freeling"
        and entries[0].confidence == 1.0
    )


def test_pipeline_config_selects_the_provider_by_name(project_root: Path) -> None:
    from parafrasi_cat import PipelineConfig, build_pipeline

    config = PipelineConfig.from_mapping({"morphology": "null"})
    assert config.morphology == "null" and config.to_dict()["morphology"] == "null"
    pipeline = build_pipeline(config)
    assert pipeline.run("Se'n poden extreure diverses conclusions.").output_text == (
        "Se'n poden extreure diverses conclusions."
    )
