"""Empremta estilística: corpus, construcció, esquema, comparació i preferències."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from parafrasi_cat import PipelineConfig, build_pipeline
from parafrasi_cat.analyzer import ClosedClassLexicon, RuleBasedAnalyzer
from parafrasi_cat.core import ConfigError
from parafrasi_cat.core.errors import ResourceError
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.style import (
    CorpusRole,
    FeatureStat,
    StyleEvaluator,
    StyleFingerprint,
    StylePreferences,
    StyleProfile,
    StyleResources,
    build_fingerprint,
    compare_fingerprints,
    corpus_from_texts,
    load_corpus,
    load_style_profile,
)
from parafrasi_cat.style.schema import SCHEMA_FILE, load_schema, validate

STYLES = ("concis", "academic", "narratiu")


def _num(value: object) -> float:
    assert isinstance(value, int | float) and not isinstance(value, bool)
    return float(value)


def _items(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def resources(paths: ProjectPaths, lexicon: ClosedClassLexicon) -> StyleResources:
    return StyleResources.load(paths, lexicon=lexicon)


@pytest.fixture(scope="module")
def examples_dir(project_root: Path) -> Path:
    return project_root / "corpus" / "exemples"


@pytest.fixture(scope="module")
def fingerprints(
    examples_dir: Path, resources: StyleResources, catalan_analyzer: RuleBasedAnalyzer
) -> dict[str, StyleFingerprint]:
    result: dict[str, StyleFingerprint] = {}
    for style in STYLES:
        corpus = load_corpus(
            examples_dir / style, validation_dir=examples_dir / f"{style}-validacio"
        )
        result[style] = build_fingerprint(corpus, resources, catalan_analyzer, name=style)
        validation = load_corpus(examples_dir / f"{style}-validacio")
        result[f"{style}-val"] = build_fingerprint(
            validation, resources, catalan_analyzer, name=f"{style}-val"
        )
    return result


@pytest.fixture(scope="module")
def schema(project_root: Path) -> dict[str, object]:
    return load_schema(project_root / SCHEMA_FILE)


# --- corpus -------------------------------------------------------------------------


def test_load_corpus_roles_and_exclusions(tmp_path: Path) -> None:
    main = tmp_path / "principal"
    main.mkdir()
    (main / "a.txt").write_text("Primer text.\n", encoding="utf-8")
    (main / "b.md").write_text("Segon text.\n", encoding="utf-8")
    (main / "README.md").write_text("# no és corpus\n", encoding="utf-8")
    (main / "buit.txt").write_text("  \n", encoding="utf-8")
    (main / "esborrany-1.txt").write_text("Esborrany.\n", encoding="utf-8")
    (main / "exclosos.txt").write_text("# patrons\nesborrany*\n", encoding="utf-8")
    validation = tmp_path / "validacio"
    validation.mkdir()
    (validation / "v.txt").write_text("Text de validació.\n", encoding="utf-8")
    corpus = load_corpus(main, validation_dir=validation, exclude=[str(main / "b.md")])
    assert [d.name for d in corpus.documents] == ["a.txt", "validation/v.txt"]
    assert [d.role for d in corpus.documents] == [CorpusRole.MAIN, CorpusRole.VALIDATION]
    assert {e.name: e.reason for e in corpus.excluded} == {
        "b.md": "exclòs explícitament",
        "buit.txt": "document buit",
        "esborrany-1.txt": "coincideix amb el patró «esborrany*»",
    }
    assert len(corpus.main) == 1 and len(corpus.validation) == 1
    assert len(corpus.main[0].sha256) == 12
    with pytest.raises(ResourceError):
        load_corpus(tmp_path / "inexistent")
    memory = corpus_from_texts(["Hola.", "   ", "Adeu."])
    assert [d.name for d in memory.documents] == ["text-1", "text-3"]


# --- construcció i esquema -------------------------------------------------------------


def _examples(node: object) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("examples", "ambiguous_examples") and isinstance(value, list):
                found.extend(str(v) for v in value)
            elif key == "example" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_examples(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_examples(item))
    return found


def test_fingerprints_follow_schema_and_keep_examples_short(
    fingerprints: dict[str, StyleFingerprint], schema: dict[str, object]
) -> None:
    for style in STYLES:
        fingerprint = fingerprints[style]
        data = fingerprint.to_dict()
        assert validate(data, schema) == []
        assert fingerprint.corpus["n_documents"] == 4
        assert fingerprint.validation is not None
        assert fingerprint.validation["n_documents"] == 2
        assert fingerprint.generator["uses_models"] is False
        assert fingerprint.generator["deterministic"] is True
        examples = _examples(data)
        assert examples and max(len(e) for e in examples) <= 115
        assert set(_mapping(data["features"])) >= {
            "sentence_length",
            "punctuation",
            "connectors",
            "recurrent_expressions",
            "impersonal",
            "first_person",
            "passive",
            "lexical_repetition",
            "word_class_density",
            "variant_preferences",
        }


def test_fingerprint_is_deterministic_and_round_trips(
    examples_dir: Path,
    resources: StyleResources,
    catalan_analyzer: RuleBasedAnalyzer,
    fingerprints: dict[str, StyleFingerprint],
    tmp_path: Path,
) -> None:
    corpus = load_corpus(examples_dir / "concis")
    first = build_fingerprint(corpus, resources, catalan_analyzer, name="concis")
    second = build_fingerprint(corpus, resources, catalan_analyzer, name="concis")
    assert first.to_json() == second.to_json()
    assert first.generator["corpus_hash"] == second.generator["corpus_hash"]
    file = fingerprints["academic"].save(tmp_path / "academic.json")
    loaded = StyleFingerprint.load(file)
    assert loaded.to_dict() == fingerprints["academic"].to_dict()
    stat = loaded.stat("sentence_length")
    assert stat is not None and FeatureStat.from_dict(stat.to_dict()) == stat
    assert loaded.value("punctuation.comma.per_100_words") is not None
    assert loaded.get("no.existeix") is None and loaded.stat("connectors") is None
    with pytest.raises(ResourceError):
        StyleFingerprint.load(tmp_path / "no.json")
    with pytest.raises(ResourceError):
        StyleFingerprint.from_dict({"schema_version": "9.0", "name": "x", "features": {}})
    with pytest.raises(ResourceError):
        build_fingerprint(corpus_from_texts([]), resources, catalan_analyzer)


# --- els estils es distingeixen -------------------------------------------------------------


def test_styles_are_distinguished(fingerprints: dict[str, StyleFingerprint]) -> None:
    def distance(a: str, b: str) -> float:
        return compare_fingerprints(fingerprints[a], fingerprints[b]).distance

    for style in STYLES:
        within = distance(style, f"{style}-val")
        assert within < 0.25, (style, within)
        for other in STYLES:
            if other != style:
                assert within < distance(style, other), (style, other)
                assert within < distance(style, f"{other}-val"), (style, other)
    assert distance("concis", "academic") >= 0.4
    assert compare_fingerprints(fingerprints["concis"], fingerprints["academic"]).label == (
        "clarament diferents"
    )
    assert compare_fingerprints(fingerprints["concis"], fingerprints["concis"]).distance == 0.0


def test_detected_preferences_match_the_designed_styles(
    fingerprints: dict[str, StyleFingerprint],
) -> None:
    concis = StylePreferences(fingerprints["concis"])
    academic = StylePreferences(fingerprints["academic"])
    narratiu = StylePreferences(fingerprints["narratiu"])
    assert concis.preferred_variant("copula") == "és"
    assert concis.preferred_variant("agent") == "fet per"
    assert concis.preferred_variant("finalitzar_acabar") == "acabar"
    assert concis.preferred_variant("presencia") == "hi ha"
    assert concis.preferred_variant("passat") == "perifràstic"
    assert academic.preferred_variant("copula") == "constitueix"
    assert academic.preferred_variant("agent") == "obra de"
    assert academic.preferred_variant("finalitzar_acabar") == "finalitzar"
    assert academic.preferred_variant("presencia") == "presenta"
    assert academic.preferred_variant("passat") == "simple"
    assert academic.preferred_variant("contrast") == "tanmateix"
    assert narratiu.preferred_variant("agent") == "realitzat per"
    assert narratiu.preferred_variant("presencia") == "apareix"
    assert narratiu.preferred_variant("contrast") == "en canvi"
    assert narratiu.preferred_variant("causa") == "ja que"
    assert concis.preferred_variant("causa") is None  # una sola observació

    def value(style: str, path: str) -> float:
        result = fingerprints[style].value(path)
        assert result is not None
        return result

    assert value("concis", "sentence_length") < value("narratiu", "sentence_length")
    assert value("narratiu", "sentence_length") < value("academic", "sentence_length")
    assert value("concis", "punctuation.comma.per_100_words") < value(
        "academic", "punctuation.comma.per_100_words"
    )
    assert value("academic", "punctuation.semicolon.per_100_words") > 0
    assert value("concis", "punctuation.semicolon.per_100_words") == 0
    assert value("narratiu", "punctuation.dash.per_100_words") > 0
    assert value("narratiu", "punctuation.exclamation.per_100_words") > 0
    assert value("concis", "first_person.singular.per_100_sentences") > 20
    assert value("academic", "first_person.singular.per_100_sentences") < 2
    assert value("narratiu", "first_person.plural.per_100_sentences") > 50
    assert value("academic", "passive.per_100_sentences") > value(
        "concis", "passive.per_100_sentences"
    )
    assert value("academic", "impersonal.per_100_sentences") > value(
        "narratiu", "impersonal.per_100_sentences"
    )
    registers = _mapping(fingerprints["academic"].get("connectors.by_register_shares"))
    assert _num(registers["formal"]) > 0.8
    expressions = _items(fingerprints["concis"].get("recurrent_expressions.items"))
    assert "crec que" in {_mapping(item)["text"] for item in expressions}
    positions = _mapping(fingerprints["concis"].get("connectors.position_shares"))
    assert positions["initial"] == 1.0


def test_validation_section_and_comparison_report(
    fingerprints: dict[str, StyleFingerprint],
) -> None:
    validation = fingerprints["narratiu"].validation
    assert validation is not None
    assert 0.0 <= _num(validation["distance"]) < 0.25
    assert all(isinstance(f, str) for f in _items(validation["divergent_features"]))
    distances = _mapping(validation["feature_distances"])
    assert all(0.0 <= _num(v) <= 1.0 for v in distances.values())
    comparison = compare_fingerprints(fingerprints["concis"], fingerprints["academic"])
    report = comparison.report(top=5)
    assert "«concis»" in report and "«academic»" in report and "Distància global" in report
    data = comparison.to_dict()
    assert data["distance"] == comparison.distance
    kinds = {_mapping(item)["kind"] for item in _items(data["items"])}
    assert kinds >= {"stat", "shares", "list", "preferred"}
    divergent = comparison.divergent()
    assert divergent and divergent[0].distance >= divergent[-1].distance
    assert "variant_preferences.copula.preferred" in {i.path for i in divergent}


# --- preferències, perfil i avaluador ---------------------------------------------------


def test_preferences_api(fingerprints: dict[str, StyleFingerprint]) -> None:
    preferences = StylePreferences(fingerprints["concis"])
    assert preferences.name == "concis"
    assert preferences.sentence_length == fingerprints["concis"].value("sentence_length")
    assert 5.0 <= _num(preferences.sentence_length) <= 9.0
    assert preferences.sentence_length_spread is not None
    assert preferences.prefers("copula", "és") is True
    assert preferences.prefers("copula", "constitueix") is False
    assert preferences.prefers("causa", "perquè") is None
    assert preferences.variant_share("copula", "és") == 1.0
    assert preferences.variant_share("copula", "inexistent") is None
    assert preferences.connector_share("a més") == 1.0
    assert preferences.connector_share("tanmateix") == 0.0
    assert preferences.top_connectors(2) == ("a més", "per tant")
    assert preferences.rate("punctuation.comma.per_100_words") is not None
    assert preferences.rate("no.existeix") is None
    assert preferences.is_reliable("sentence_length")
    assert preferences.punctuation_rate("semicolon") == 0.0
    assert preferences.impersonal_rate is not None and preferences.passive_rate is not None
    assert preferences.first_person_rate("singular") is not None
    assert "prefereix «és»" in preferences.summary()
    assert "addició" in preferences.connector_function_shares()


def test_profile_from_fingerprint_and_loading(
    fingerprints: dict[str, StyleFingerprint], tmp_path: Path
) -> None:
    academic = fingerprints["academic"]
    profile = StyleProfile.from_fingerprint(academic, fingerprint_path="academic.json")
    assert profile.name == "academic"
    assert profile.target_sentence_length == pytest.approx(_num(academic.value("sentence_length")))
    assert profile.target_sentence_length > 25
    assert profile.sentence_length_tolerance >= 4.0
    assert profile.formality > 0.8
    assert "així mateix" in profile.preferred_connectors
    assert profile.preferences is not None
    assert profile.to_dict()["fingerprint"] == "academic.json"
    assert "fingerprint" not in StyleProfile(name="x").to_dict()

    academic.save(tmp_path / "academic.json")
    profile_file = tmp_path / "perfil.yaml"
    profile_file.write_text(yaml.safe_dump(profile.to_dict()), encoding="utf-8")
    loaded = load_style_profile(profile_file)
    assert loaded.preferences is not None and loaded.preferences.name == "academic"
    assert loaded == profile  # «preferences» no participa en la igualtat
    profile_file.write_text("name: buit\n", encoding="utf-8")
    assert load_style_profile(profile_file).preferences is None
    missing = tmp_path / "trencat.yaml"
    missing.write_text("name: x\nfingerprint: no-existeix.json\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_style_profile(missing)


def test_evaluator_uses_author_preferences(
    fingerprints: dict[str, StyleFingerprint],
    resources: StyleResources,
    catalan_analyzer: RuleBasedAnalyzer,
) -> None:
    profile = StyleProfile.from_fingerprint(fingerprints["academic"])
    evaluator = StyleEvaluator(profile, catalan_analyzer, resources=resources)
    assert evaluator.preferences is not None
    like_author = (
        "El pont constitueix el testimoni més antic de la comarca; tanmateix, la barana, "
        "que es considera moderna, fou finalitzada més tard per un altre mestre."
    )
    unlike_author = (
        "El pont és el testimoni més antic de la comarca. Però la barana va ser acabada "
        "més tard per un altre mestre."
    )
    close = evaluator.distance(like_author)
    far = evaluator.distance(unlike_author)
    assert close.components["variants_autor"] < 0.3
    assert far.components["variants_autor"] > 0.6
    assert close.components["connectors_autor"] < far.components["connectors_autor"]
    assert close.total < far.total
    plain = StyleEvaluator(StyleProfile(name="senzill"), catalan_analyzer)
    assert "variants_autor" not in plain.distance(like_author).components


def test_pipeline_builder_loads_fingerprint_profile(
    fingerprints: dict[str, StyleFingerprint], tmp_path: Path
) -> None:
    fingerprint_file = fingerprints["academic"].save(tmp_path / "academic.json")
    profile = StyleProfile.from_fingerprint(
        fingerprints["academic"], fingerprint_path=str(fingerprint_file)
    )
    profile_file = tmp_path / "academic.yaml"
    profile_file.write_text(yaml.safe_dump(profile.to_dict()), encoding="utf-8")
    pipeline = build_pipeline(PipelineConfig(rule_set="parafrasi", style_profile=str(profile_file)))
    assert pipeline.style_profile is not None
    assert pipeline.style_profile.preferences is not None
    text = "La primera referència itàlica és el monument funerari d'Oddo Altoviti."
    result = pipeline.run(text)
    scores = [c.score for c in result.sentences[0].candidates if c.score is not None]
    assert scores and all("estil" in score.components for score in scores)
    assert "1507" not in text or "1507" in result.output_text


# --- validador d'esquema --------------------------------------------------------------------


def test_schema_validator_reports_errors(schema: dict[str, object]) -> None:
    mini: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["n", "kind"],
        "properties": {
            "n": {"type": "integer", "minimum": 0, "maximum": 10},
            "kind": {"type": "string", "enum": ["a", "b"]},
            "items": {"type": "array", "items": {"$ref": "#/$defs/item"}, "minItems": 1},
            "maybe": {"anyOf": [{"type": "null"}, {"type": "number"}]},
        },
        "$defs": {
            "item": {"type": "object", "required": ["x"], "properties": {"x": {"type": "number"}}}
        },
    }
    assert validate({"n": 3, "kind": "a", "items": [{"x": 1.5}], "maybe": None}, mini) == []
    errors = validate(
        {"n": 11, "kind": "c", "items": [], "maybe": "text", "extra": 1, "n2": True}, mini
    )
    joined = "\n".join(errors)
    assert "$.n: 11 és més gran" in joined
    assert "fora de l'enumeració" in joined
    assert "almenys 1 elements" in joined
    assert "$.maybe: no compleix cap" in joined
    assert "$.extra: clau no permesa" in joined
    assert "falta la clau" in "\n".join(validate({"n": 1}, mini))
    assert "s'esperava el tipus" in "\n".join(validate({"n": "1", "kind": "a"}, mini))
    assert "$.items[0]: falta la clau obligatòria «x»" in "\n".join(
        validate({"n": 1, "kind": "a", "items": [{}]}, mini)
    )
    broken = json.loads(json.dumps({"schema_version": "1.0", "name": "x"}))
    assert validate(broken, schema)
