from __future__ import annotations

import pytest

from parafrasi_cat.analyzer import RuleBasedAnalyzer
from parafrasi_cat.candidates import Candidate
from parafrasi_cat.core import ConfigError, SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.scoring import CompositeScorer, ScoringWeights, select_best
from parafrasi_cat.style import StyleEvaluator, StyleProfile


def make(
    before: str, after: str, start: int, risk: SemanticRisk, confidence: float
) -> Transformation:
    return Transformation(
        rule_id="t",
        text_before=before,
        text_after=after,
        changed_span=Span(start, start + len(before)),
        transformation_type=TransformationType.LEXICAL,
        confidence=confidence,
        semantic_risk=risk,
        explanation="prova",
    )


TEXT = "gairebé sempre plou"


def test_identity_has_zero_gain() -> None:
    score = CompositeScorer().score(Candidate.identity(0, TEXT))
    assert score.total == 0.0
    assert score.components == {"transformacions": 0.0}


def test_safe_transformation_scores_positive() -> None:
    low = Candidate.from_transformations(
        0, TEXT, [make("gairebé", "quasi", 0, SemanticRisk.LOW, 0.9)]
    )
    high = Candidate.from_transformations(
        0, TEXT, [make("gairebé", "quasi", 0, SemanticRisk.HIGH, 0.9)]
    )
    scorer = CompositeScorer()
    assert scorer.score(low).total == pytest.approx(0.9 * 0.75 / 3, abs=1e-4)
    assert scorer.score(high).total == 0.0
    assert "guany" in scorer.score(low).explanation


def test_style_penalty(analyzer: RuleBasedAnalyzer) -> None:
    profile = StyleProfile(name="p", target_sentence_length=3, sentence_length_tolerance=1)
    scorer = CompositeScorer(ScoringWeights(style_distance=1.0), StyleEvaluator(profile, analyzer))
    short = scorer.score(Candidate.identity(0, "Plou molt avui."))
    long = scorer.score(Candidate.identity(0, "Plou molt avui i demà també plourà molt."))
    assert short.total == 0.0
    assert long.total < 0
    assert long.components["estil"] < 0


def test_select_best_tie_breaking() -> None:
    identity = Candidate.identity(0, TEXT)
    changed = Candidate.from_transformations(
        0, TEXT, [make("gairebé", "quasi", 0, SemanticRisk.LOW, 0.9)]
    )
    scorer = CompositeScorer(ScoringWeights(transformation_gain=0.0))
    items = [(changed, scorer.score(changed)), (identity, scorer.score(identity))]
    best = select_best(items, lambda i: i[0], lambda i: i[1])
    assert best is not None and best[0].is_identity
    scorer = CompositeScorer()
    items = [(identity, scorer.score(identity)), (changed, scorer.score(changed))]
    best = select_best(items, lambda i: i[0], lambda i: i[1])
    assert best is not None and best[0] is changed
    assert select_best([], lambda i: i[0], lambda i: i[1]) is None


def test_weights() -> None:
    weights = ScoringWeights.from_mapping({"style_distance": 0.2, "max_transformations": 5})
    assert weights.style_distance == 0.2 and weights.max_transformations == 5
    assert weights.transformation_gain == 1.0
    assert weights.to_dict()["semantic_risk"] == 1.0
    with pytest.raises(ConfigError):
        ScoringWeights(max_transformations=0)
    with pytest.raises(ConfigError):
        ScoringWeights(style_distance=-1)
