from __future__ import annotations

import pytest

from parafrasi_cat.core import (
    SemanticRisk,
    Span,
    Transformation,
    TransformationError,
    TransformationType,
    apply_transformations,
)


def make(before: str, after: str, start: int, rule_id: str = "test.rule") -> Transformation:
    return Transformation(
        rule_id=rule_id,
        text_before=before,
        text_after=after,
        changed_span=Span(start, start + len(before)),
        transformation_type=TransformationType.LEXICAL,
        confidence=0.9,
        semantic_risk=SemanticRisk.LOW,
        explanation=f"canvia «{before}» per «{after}»",
    )


def test_apply_single() -> None:
    t = make("gairebé", "quasi", 0)
    assert t.can_apply_to("gairebé tot")
    assert t.apply("gairebé tot") == "quasi tot"
    assert t.result_span == Span(0, 5)
    assert not t.is_identity


def test_apply_mismatch_raises() -> None:
    t = make("gairebé", "quasi", 0)
    with pytest.raises(TransformationError):
        t.apply("sempre tot")


def test_validation_of_fields() -> None:
    lexical = TransformationType.LEXICAL
    with pytest.raises(ValueError):
        Transformation("", "a", "b", Span(0, 1), lexical, 0.5, SemanticRisk.LOW, "x")
    with pytest.raises(ValueError):
        Transformation("r", "a", "b", Span(0, 1), lexical, 1.5, SemanticRisk.LOW, "x")
    with pytest.raises(ValueError):
        Transformation("r", "ab", "b", Span(0, 1), lexical, 0.5, SemanticRisk.LOW, "x")


def test_describe_and_to_dict() -> None:
    t = make("gairebé", "quasi", 4)
    description = t.describe()
    assert "test.rule" in description
    assert "«gairebé» → «quasi»" in description
    data = t.to_dict()
    assert data["rule_id"] == "test.rule"
    assert data["changed_span"] == {"start": 4, "end": 11}
    assert data["semantic_risk"] == "low"
    assert data["transformation_type"] == "lexical"


def test_apply_transformations_right_to_left() -> None:
    text = "gairebé sempre i sovint"
    t1 = make("gairebé", "quasi", 0)
    t2 = make("sovint", "freqüentment", 17)
    assert apply_transformations(text, [t2, t1]) == "quasi sempre i freqüentment"


def test_apply_transformations_rejects_overlap() -> None:
    text = "gairebé sempre"
    t1 = make("gairebé", "quasi", 0)
    t2 = make("bé sempre", "prou", 5)
    with pytest.raises(TransformationError):
        apply_transformations(text, [t1, t2])


def test_semantic_risk_ordering_and_parse() -> None:
    assert SemanticRisk.parse("Medium") is SemanticRisk.MEDIUM
    assert SemanticRisk.parse(SemanticRisk.HIGH) is SemanticRisk.HIGH
    assert SemanticRisk.HIGH.exceeds(SemanticRisk.LOW)
    assert not SemanticRisk.LOW.exceeds(SemanticRisk.LOW)
    assert SemanticRisk.NONE.weight == 0.0
    assert SemanticRisk.HIGH.weight == 1.0
    with pytest.raises(ValueError):
        SemanticRisk.parse("extrem")
