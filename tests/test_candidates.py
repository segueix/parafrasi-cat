from __future__ import annotations

import pytest

from parafrasi_cat.candidates import Candidate, CandidateGenerator
from parafrasi_cat.core import ConfigError, SemanticRisk, Span, Transformation, TransformationType


def make(before: str, after: str, start: int, confidence: float = 0.8) -> Transformation:
    return Transformation(
        rule_id="t",
        text_before=before,
        text_after=after,
        changed_span=Span(start, start + len(before)),
        transformation_type=TransformationType.LEXICAL,
        confidence=confidence,
        semantic_risk=SemanticRisk.LOW,
        explanation="prova",
    )


TEXT = "gairebé sempre i sovint plou"


def test_identity_candidate() -> None:
    candidate = Candidate.identity(0, TEXT)
    assert candidate.is_identity
    assert candidate.change_ratio() == 0.0
    assert candidate.describe() == "sense canvis"


def test_from_transformations_orders_and_applies() -> None:
    t1 = make("gairebé", "quasi", 0)
    t2 = make("sovint", "freqüentment", 17)
    candidate = Candidate.from_transformations(0, TEXT, [t2, t1])
    assert candidate.text == "quasi sempre i freqüentment plou"
    assert candidate.transformations == (t1, t2)
    assert 0 < candidate.change_ratio() < 1
    transformations = candidate.to_dict()["transformations"]
    assert isinstance(transformations, list) and transformations[0]["text_after"] == "quasi"


def test_generator_without_proposals() -> None:
    candidates = CandidateGenerator().generate(0, TEXT, [])
    assert len(candidates) == 1 and candidates[0].is_identity


def test_generator_singles_and_combination() -> None:
    t1 = make("gairebé", "quasi", 0, confidence=0.7)
    t2 = make("sovint", "freqüentment", 17, confidence=0.9)
    candidates = CandidateGenerator().generate(0, TEXT, [t1, t2])
    texts = [c.text for c in candidates]
    assert texts[0] == TEXT
    assert texts[1] == "gairebé sempre i freqüentment plou"  # més confiança primer
    assert texts[2] == "quasi sempre i sovint plou"
    assert texts[3] == "quasi sempre i freqüentment plou"
    assert len(candidates) == 4


def test_generator_skips_overlapping_combination_and_duplicates() -> None:
    t1 = make("gairebé", "quasi", 0)
    t2 = make("gairebé sempre", "quasi sempre", 0)
    t3 = make("gairebé", "quasi", 0)
    candidates = CandidateGenerator().generate(0, TEXT, [t1, t2, t3])
    assert [c.text for c in candidates] == [TEXT, "quasi sempre i sovint plou"]


def test_generator_ignores_inapplicable_and_identity_proposals() -> None:
    wrong = make("sempre", "mai", 0)  # el fragment no és a la posició indicada
    same = make("gairebé", "gairebé", 0)
    candidates = CandidateGenerator().generate(0, TEXT, [wrong, same])
    assert len(candidates) == 1


def test_generator_limits() -> None:
    proposals = [make("gairebé", f"x{i}", 0) for i in range(10)]
    candidates = CandidateGenerator(max_candidates=3).generate(0, TEXT, proposals)
    assert len(candidates) == 3
    t1 = make("gairebé", "quasi", 0)
    t2 = make("sempre", "tothora", 8)
    t3 = make("sovint", "freqüentment", 17)
    candidates = CandidateGenerator(max_transformations=2).generate(0, TEXT, [t1, t2, t3])
    assert max(c.n_transformations for c in candidates) == 2
    with pytest.raises(ConfigError):
        CandidateGenerator(max_transformations=0)
