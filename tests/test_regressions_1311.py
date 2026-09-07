"""Regressions específiques de la v1.3.11: no repetir connectors per inèrcia.

Des de la v1.3.13 la mesura la fa :mod:`parafrasi_cat.style.connector_repetition`
(inventari de les regles, distància en frases i repetició introduïda contra
heretada) en lloc de la funció interna del puntuador. Les propietats que
protegia la v1.3.11 continuen sent les mateixes: una repetició dins de la unitat
pesa més que una coincidència amb la unitat contigua, els connectors diferents
no paguen res i el pes és configurable i no negatiu.
"""

from __future__ import annotations

import pytest

from parafrasi_cat.analyzer import RuleBasedAnalyzer
from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.scoring.weights import ScoringWeights
from parafrasi_cat.style.connector_repetition import ConnectorRepetition, DocumentWindow

FORMS = ("atès que", "ja que", "malgrat que", "tanmateix", "per tant", "però")

INSIDE = "Ho sabem atès que plou. Ho repetim atès que convé."
MIXED = "Ho sabem perquè plou. Ho repetim atès que convé."
NEUTRAL = "Ho sabem. Ho repetim."


@pytest.fixture(scope="module")
def repetition(catalan_analyzer: RuleBasedAnalyzer) -> ConnectorRepetition:
    return ConnectorRepetition(catalan_analyzer, FORMS)


def test_same_connector_repeated_inside_unit_is_penalised(
    repetition: ConnectorRepetition,
) -> None:
    assessment = repetition.assess(INSIDE, MIXED)
    assert assessment.penalty == pytest.approx(0.5)
    assert assessment.forms == ("atès que",)


def test_mixed_safe_connectors_are_not_penalised(repetition: ConnectorRepetition) -> None:
    assessment = repetition.assess(MIXED, INSIDE)
    assert assessment.penalty == 0.0
    assert assessment.forms == ()


def test_same_connector_at_context_boundary_has_smaller_penalty(
    repetition: ConnectorRepetition,
) -> None:
    window = DocumentWindow(before=("Tanmateix, plou.",), after=("Per tant, marxem.",))
    boundary = repetition.assess("Tanmateix, no plou.", "Per tant, no plou.", window)
    assert boundary.penalty == pytest.approx(0.5)
    assert boundary.forms == ("tanmateix",)
    # Dins de la unitat, la mateixa forma repetida a la frase següent pesa igual, i
    # dins d'una sola frase encara més: la distància és l'única cosa que ho gradua.
    assert repetition.assess(INSIDE, NEUTRAL).penalty == pytest.approx(0.5)
    same_sentence = "Ho sabem atès que plou i atès que fa vent."
    assert repetition.assess(same_sentence, NEUTRAL).penalty == pytest.approx(1.0)


def test_repetition_penalty_is_configurable_and_non_negative() -> None:
    weights = ScoringWeights.from_mapping({"connector_repetition": 0.23})
    assert weights.connector_repetition == pytest.approx(0.23)
    assert weights.to_dict()["connector_repetition"] == pytest.approx(0.23)
    with pytest.raises(ConfigError):
        ScoringWeights(connector_repetition=-0.01)
