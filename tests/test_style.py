from __future__ import annotations

import pytest

from parafrasi_cat.analyzer import RuleBasedAnalyzer
from parafrasi_cat.core import ConfigError
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.style import (
    StyleEvaluator,
    StyleProfile,
    compute_style_metrics,
    estimate_profile,
    load_style_profile,
)


def test_metrics(analyzer: RuleBasedAnalyzer) -> None:
    text = "Plou molt, però sortirem. A més, fa fred."
    metrics = compute_style_metrics(text, analyzer, connectors=["però", "a més"])
    assert metrics.n_sentences == 2
    assert metrics.n_words == 8
    assert metrics.mean_sentence_length == 4.0
    assert metrics.connector_density == 1.0
    assert 0 < metrics.type_token_ratio <= 1
    assert metrics.punctuation_density > 0
    assert metrics.to_dict()["n_chars"] == len(text)


def test_metrics_empty(analyzer: RuleBasedAnalyzer) -> None:
    metrics = compute_style_metrics("", analyzer)
    assert metrics.n_sentences == 0 and metrics.mean_sentence_length == 0.0


def test_profiles_load(paths: ProjectPaths) -> None:
    default = load_style_profile(paths.style / "default.yaml")
    assert default.name == "default"
    assert default.preferred_connectors == ()
    formal = load_style_profile(paths.style / "formal.yaml")
    assert "tanmateix" in formal.preferred_connectors
    assert formal.formality > default.formality
    sentence_length = formal.to_dict()["sentence_length"]
    assert isinstance(sentence_length, dict)
    assert sentence_length["target_mean"] == formal.target_sentence_length


def test_profile_validation() -> None:
    with pytest.raises(ConfigError):
        StyleProfile(name="x", sentence_length_tolerance=0)
    with pytest.raises(ConfigError):
        StyleProfile(name="x", formality=2)


def test_evaluator_distance(analyzer: RuleBasedAnalyzer) -> None:
    profile = StyleProfile(
        name="prova",
        target_sentence_length=4,
        sentence_length_tolerance=4,
        avoided_words=("o sigui",),
        preferred_connectors=("tanmateix",),
    )
    evaluator = StyleEvaluator(profile, analyzer)
    close = evaluator.distance("Plou molt avui, tanmateix.")
    far = evaluator.distance("O sigui, plou molt i molt i molt i molt i molt i molt i molt avui.")
    assert close.components["longitud_frase"] == 0.0
    assert close.components["mots_evitats"] == 0.0
    assert close.components["connectors_preferits"] == 0.0
    assert far.components["mots_evitats"] > 0
    assert far.components["longitud_frase"] > 0
    assert far.total > close.total
    assert 0.0 <= close.total <= 1.0
    metrics = far.to_dict()["metrics"]
    assert isinstance(metrics, dict) and metrics["n_sentences"] == 1


def test_estimate_profile(analyzer: RuleBasedAnalyzer) -> None:
    texts = ["Una frase de cinc mots. Una altra de cinc mots.", "Tres mots aquí."]
    profile = estimate_profile(texts, analyzer, name="autor")
    assert profile.name == "autor"
    assert profile.target_sentence_length == pytest.approx(4.0, abs=0.01)
    assert profile.sentence_length_tolerance >= 4.0
    assert estimate_profile([], analyzer).target_sentence_length == 20.0
