"""Totes les regles declarades: metadades completes i exemples que es compleixen."""

from __future__ import annotations

import pytest

from parafrasi_cat.analyzer import RuleBasedAnalyzer
from parafrasi_cat.core import SemanticRisk
from parafrasi_cat.protected import default_protector
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.rules import RuleSet, RuleSetConfig, build_rule_set, default_registry
from parafrasi_cat.rules.examples import verify_examples

REQUIRED_CATEGORIES = {
    "lexic", "connector", "verbal", "nominalitzacio", "copula", "agent", "presencia", "ordre",
    "temporal", "subordinada", "fusio", "divisio", "puntuacio",
}  # fmt: skip


@pytest.fixture(scope="module")
def rule_set(paths: ProjectPaths) -> RuleSet:
    config = RuleSetConfig.load(paths.rules / "parafrasi.yaml")
    return build_rule_set(config, default_registry(), paths)


def test_rule_set_covers_all_families(rule_set: RuleSet) -> None:
    assert 25 <= len(rule_set.rules) <= 45
    assert {d.category for d in rule_set.definitions} == REQUIRED_CATEGORIES
    assert {d.level for d in rule_set.definitions} == {1, 2, 3, 4}
    assert len(rule_set.paragraph_rules) == 1
    assert len(rule_set.sentence_rules) == len(rule_set.rules) - 1


def test_every_rule_has_complete_metadata(rule_set: RuleSet) -> None:
    for definition in rule_set.definitions:
        assert definition.language == "ca", definition.rule_id
        assert definition.category and definition.description, definition.rule_id
        assert isinstance(definition.semantic_risk, SemanticRisk)
        assert 0.5 <= definition.confidence <= 1.0, definition.rule_id
        assert definition.positive_examples, f"{definition.rule_id}: cal un exemple positiu"
        assert definition.negative_examples, f"{definition.rule_id}: cal un exemple negatiu"
        if definition.engine == "pattern":
            assert definition.pattern and definition.transformations, definition.rule_id
        rule = rule_set.rule(definition.rule_id)
        assert rule.category == definition.category and rule.level == definition.level


def test_rule_ids_are_unique_and_namespaced(rule_set: RuleSet) -> None:
    ids = rule_set.rule_ids
    assert len(ids) == len(set(ids))
    assert all("." in rule_id for rule_id in ids)


@pytest.fixture(scope="module")
def example_checker(catalan_analyzer: RuleBasedAnalyzer):  # type: ignore[no-untyped-def]
    protector = default_protector(catalan_analyzer)

    def check(rule_set: RuleSet, rule_id: str) -> list[str]:
        definition = next(d for d in rule_set.definitions if d.rule_id == rule_id)
        rule = rule_set.rule(rule_id)
        return [
            f.describe() for f in verify_examples(rule, definition, catalan_analyzer, protector)
        ]

    return check


RULE_IDS = [
    "lexical.substitution", "connector.equivalents", "connector.aixi_com_a_i_tambe",
    "verbal.perifrastic_a_simple", "verbal.simple_a_perifrastic", "verbal.cal_inf_a_es_necessari",
    "verbal.cal_que_a_es_necessari_que", "verbal.es_necessari_inf_a_cal",
    "verbal.es_necessari_que_a_cal_que", "nominal.verb_a_nom", "nominal.nom_a_verb",
    "copula.es_a_constitueix", "copula.constitueix_a_es", "copula.es_a_correspon_a",
    "agent.fet_per_a_realitzat_per", "agent.realitzat_per_a_fet_per", "agent.fet_per_a_obra_de",
    "presencia.hi_ha_la_presencia_de_a_hi_ha", "presencia.hi_ha_la_presencia_de_a_apareix",
    "presencia.en_loc_hi_ha_la_presencia_a_presenta", "presencia.en_loc_hi_ha_a_presenta",
    "ordre.inversio_copula", "ordre.inversio_copula_amb_aposicio", "ordre.segons_inicial_a_final",
    "ordre.segons_final_a_inicial", "temporal.inicial_a_final", "temporal.final_a_inicial",
    "subordinada.relativa_passiva_a_participi",
    "subordinada.relativa_passiva_perifrastica_a_participi",
    "subordinada.participi_a_relativa_passiva", "subordinada.quan_va_inf_a_en_inf",
    "fusio.frases_compatibles", "divisio.coordinada_i", "divisio.coordinada_pero",
    "puntuacio.punt_i_coma_a_punt", "puntuacio.parentesi_a_comes",
    "puntuacio.parentesi_final_a_coma", "puntuacio.guions_a_comes",
]  # fmt: skip


def test_rule_id_list_matches_rule_set(rule_set: RuleSet) -> None:
    assert sorted(RULE_IDS) == sorted(rule_set.rule_ids)


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_rule_examples(rule_set: RuleSet, example_checker, rule_id: str) -> None:  # type: ignore[no-untyped-def]
    failures = example_checker(rule_set, rule_id)
    assert not failures, "\n".join(failures)
