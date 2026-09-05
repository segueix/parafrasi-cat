"""Regressions específiques de la v1.3.11: no repetir connectors per inèrcia."""

from __future__ import annotations

import pytest

from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.scoring.scorer import _connector_repetition_severity
from parafrasi_cat.scoring.weights import ScoringWeights
from parafrasi_cat.style.adaptation import AdaptationContext, UnitStats


def test_same_connector_repeated_inside_unit_is_penalised() -> None:
    severity, forms = _connector_repetition_severity(
        ("atès que", "atès que", "malgrat que", "tanmateix")
    )
    assert severity == pytest.approx(0.75)
    assert forms == ("atès que",)


def test_mixed_safe_connectors_are_not_penalised() -> None:
    severity, forms = _connector_repetition_severity(
        ("perquè", "atès que", "malgrat que", "tanmateix")
    )
    assert severity == 0.0
    assert forms == ()


def test_same_connector_at_context_boundary_has_smaller_penalty() -> None:
    context = AdaptationContext(
        before=UnitStats(connectors=("tanmateix",)),
        after=UnitStats(connectors=("per tant",)),
    )
    severity, forms = _connector_repetition_severity(("tanmateix", "atès que"), context)
    assert severity == pytest.approx(0.35)
    assert forms == ("tanmateix",)


def test_repetition_penalty_is_configurable_and_non_negative() -> None:
    weights = ScoringWeights.from_mapping({"connector_repetition": 0.23})
    assert weights.connector_repetition == pytest.approx(0.23)
    assert weights.to_dict()["connector_repetition"] == pytest.approx(0.23)
    with pytest.raises(ConfigError):
        ScoringWeights(connector_repetition=-0.01)
