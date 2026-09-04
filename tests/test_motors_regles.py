"""Motors de regla: connectors, passat perifràstic, nominalització, fusió, registre i conjunts."""

from __future__ import annotations

from pathlib import Path

import pytest

from parafrasi_cat.analyzer import RuleBasedAnalyzer
from parafrasi_cat.core import ConfigError, SemanticRisk
from parafrasi_cat.protected import default_protector
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.rules import (
    ConnectorEquivalenceRule,
    NominalizationRule,
    ParagraphRule,
    PeriphrasticPastRule,
    Rule,
    RuleDefinition,
    RuleSetConfig,
    SentenceFusionRule,
    build_rule_set,
    default_registry,
    load_rule_definitions,
)
from parafrasi_cat.rules.examples import outputs_for
from parafrasi_cat.rules.nominal import load_nominalization_pairs
from parafrasi_cat.rules.verbal import load_irregular_pasts


@pytest.fixture(scope="module")
def outputs(catalan_analyzer: RuleBasedAnalyzer):  # type: ignore[no-untyped-def]
    protector = default_protector(catalan_analyzer)

    def run(rule: Rule | ParagraphRule, text: str) -> list[str]:
        return list(outputs_for(rule, text, catalan_analyzer, protector))

    return run


def test_connector_classes_slots_and_registers(paths: ProjectPaths, outputs) -> None:  # type: ignore[no-untyped-def]
    definition = next(
        d
        for d in load_rule_definitions(
            paths.language() / "transformations" / "connectors_equivalents.yaml"
        )
        if d.rule_id == "connector.equivalents"
    )
    rule = ConnectorEquivalenceRule(definition)
    assert len(rule.classes) >= 10
    initial = outputs(rule, "No obstant això, plou.")
    assert set(initial) == {
        "Tanmateix, plou.",
        "Així i tot, plou.",
        "Amb tot, plou.",
        "Malgrat tot, plou.",
    }
    # Sense coma no és un connector d'inici de frase.
    assert outputs(rule, "No obstant això plou.") == []
    # El registre col·loquial queda exclòs dels objectius.
    assert "Ho farem, o sigui, ho intentarem." not in outputs(
        rule, "Ho farem, és a dir, ho intentarem."
    )
    # Un connector medial ha d'anar delimitat per puntuació.
    assert outputs(rule, "És a dir que no.") == []
    # Els fragments protegits es respecten.
    assert outputs(rule, "Sortirem tot i que plou") == [
        "Sortirem encara que plou",
        "Sortirem malgrat que plou",
    ]
    directed = ConnectorEquivalenceRule(
        RuleDefinition.from_mapping(
            {
                "rule_id": "c",
                "engine": "connector",
                "classes": [
                    {
                        "id": "x",
                        "slot": "medial",
                        "members": [{"form": "així com"}],
                        "targets": [{"form": "i també"}],
                    }
                ],
            }
        )
    )
    assert outputs(directed, "Cranis, així com serps.") == ["Cranis, i també serps."]
    assert outputs(directed, "Cranis, així com també serps.") == []  # evita «i també també»
    with pytest.raises(ValueError):
        ConnectorEquivalenceRule(
            RuleDefinition.from_mapping(
                {
                    "rule_id": "c",
                    "engine": "connector",
                    "classes": [{"id": "x", "slot": "enlloc", "members": [{"form": "a"}]}],
                }
            )
        )


def test_periphrastic_past_both_directions(paths: ProjectPaths, outputs) -> None:  # type: ignore[no-untyped-def]
    irregulars = load_irregular_pasts(
        paths.language() / "transformations" / "passat_simple_irregular.yaml"
    )
    assert any(i.infinitive == "ser" and i.singular == "fou" for i in irregulars)
    base = {"engine": "periphrastic_past", "category": "verbal", "level": 3}
    to_simple = PeriphrasticPastRule(
        RuleDefinition.from_mapping({"rule_id": "s", **base}), irregulars, direction="to_simple"
    )
    assert outputs(to_simple, "Va encarregar el monument.") == ["Encarregà el monument."]
    assert outputs(to_simple, "Van finalitzar el sarcòfag i van ser premiats.") == [
        "Finalitzaren el sarcòfag i van ser premiats.",
        "Van finalitzar el sarcòfag i foren premiats.",
    ]
    assert outputs(to_simple, "Vam dormir bé i vau veure el mar.") == [
        "Dormírem bé i vau veure el mar."
    ]
    assert outputs(to_simple, "Va a Roma.") == []
    assert outputs(to_simple, "Va veure'l ahir.") == []
    to_periphrastic = PeriphrasticPastRule(
        RuleDefinition.from_mapping({"rule_id": "p", **base}),
        irregulars,
        direction="to_periphrastic",
    )
    assert outputs(to_periphrastic, "El monument fou encarregat el 1507.") == [
        "El monument va ser encarregat el 1507."
    ]
    assert outputs(to_periphrastic, "Els mestres finalitzaren l'obra.") == [
        "Els mestres van finalitzar l'obra."
    ]
    # «-à» només amb un pronom feble segur al davant («ho pagà»); mai un nom com «sofà».
    assert outputs(to_periphrastic, "El sofà és nou i no ho pagà.") == [
        "El sofà és nou i no ho va pagar."
    ]
    # Abans, «no el X» bastava per prendre X per verb; però «el» pot ser article
    # («però no el germà») i la negació precedeix igualment un adjectiu («però ja
    # no sobirà»). Sense recurs morfològic ni analitzador, el dubte conserva l'original.
    assert outputs(to_periphrastic, "El sofà és nou i no el pagà.") == []
    assert outputs(to_periphrastic, "Va convidar el pare, però no el germà.") == []
    assert outputs(to_periphrastic, "Era un home poderós, però ja no sobirà.") == []
    with pytest.raises(ConfigError):
        PeriphrasticPastRule(
            RuleDefinition.from_mapping({"rule_id": "x", **base}), direction="enrere"
        )


def test_nominalization_both_directions(paths: ProjectPaths, outputs) -> None:  # type: ignore[no-untyped-def]
    pairs = load_nominalization_pairs(
        paths.language() / "transformations" / "nominalitzacions.yaml"
    )
    assert any(p.verb == "analitzar" and p.noun == "anàlisi" and p.article == "l'" for p in pairs)
    base = {"engine": "nominalization", "category": "nominalitzacio", "level": 3}
    to_noun = NominalizationRule(
        RuleDefinition.from_mapping({"rule_id": "n", **base}), pairs, direction="to_noun"
    )
    assert outputs(to_noun, "Van analitzar les dades del jaciment.") == [
        "Van fer l'anàlisi de les dades del jaciment.",
        "Van realitzar l'anàlisi de les dades del jaciment.",
        "Van dur a terme l'anàlisi de les dades del jaciment.",
    ]
    assert outputs(to_noun, "L'equip estudia el retaule.")[0] == "L'equip fa l'estudi del retaule."
    assert outputs(to_noun, "Van analitzar-les ahir.") == []
    assert outputs(to_noun, "Cal analitzar les dades.") == []  # infinitiu sense auxiliar del passat
    to_verb = NominalizationRule(
        RuleDefinition.from_mapping({"rule_id": "v", **base}), pairs, direction="to_verb"
    )
    assert outputs(to_verb, "Van fer l'anàlisi de les dades.") == ["Van analitzar les dades."]
    assert outputs(to_verb, "Van dur a terme l'excavació del jaciment.") == [
        "Van excavar el jaciment."
    ]
    assert outputs(to_verb, "Fan la revisió dels textos.") == ["Revisen els textos."]
    assert outputs(to_verb, "Van fer una casa de fusta.") == []


def test_fusion_strategies(paths: ProjectPaths, outputs) -> None:  # type: ignore[no-untyped-def]
    definition = load_rule_definitions(paths.language() / "transformations" / "fusio.yaml")[0]
    rule = default_registry().create_from_definition(definition, paths)
    assert isinstance(rule, ParagraphRule) and isinstance(rule, SentenceFusionRule)
    assert [s.strategy_id for s in rule.strategies] == [
        "contrast_pero",
        "connector_punt_i_coma",
        "anafora_demostrativa",
        "frases_curtes",
    ]
    assert outputs(rule, "Plou molt. Però sortirem.") == ["Plou molt, però sortirem."]
    assert outputs(rule, "Plou molt. A més, fa fred.") == ["Plou molt; a més, fa fred."]
    assert outputs(rule, "Plou. Fa fred. Sortirem.") == [
        "Plou i fa fred. Sortirem.",
        "Plou. Fa fred i sortirem.",
    ]
    # El nom propi inicial de la segona frase no es passa a minúscula.
    assert outputs(rule, "Plou. Benedetto surt.") == []
    assert outputs(rule, "Plou molt!\nSortirem.") == []
    clause = "és tan llarga que supera el límit de paraules de qualsevol estratègia"
    long_first = f"Aquesta frase {clause} i {clause} i {clause} i {clause}. Però sortirem."
    assert outputs(rule, long_first) == []
    with pytest.raises(ConfigError):
        SentenceFusionRule(RuleDefinition.from_mapping({"rule_id": "f", "engine": "fusion"}))


def test_registry_engines_and_rule_set_includes(paths: ProjectPaths, tmp_path: Path) -> None:
    registry = default_registry()
    assert set(registry.available()) >= {
        "pattern",
        "lexical",
        "lexical.substitution",
        "connector",
        "periphrastic_past",
        "nominalization",
        "fusion",
    }
    rule = registry.create(
        "pattern", "prova.x", {"pattern": [{"text": "hola"}], "transformation": "adeu"}, paths
    )
    assert rule.rule_id == "prova.x"
    with pytest.raises(ConfigError):
        registry.create("nominalization", "prova.n", {}, paths)
    # Un conjunt amb «include» i una regla desactivada per «rules».
    config_file = tmp_path / "conjunt.yaml"
    config_file.write_text(
        "name: prova\nmax_semantic_risk: medium\n"
        "include:\n  - resources/ca/transformations/copula.yaml\n"
        "rules:\n  - id: copula.es_a_correspon_a\n    enabled: false\n",
        encoding="utf-8",
    )
    rule_set = build_rule_set(RuleSetConfig.load(config_file), registry, paths)
    assert rule_set.rule_ids == (
        "copula.es_a_constitueix",
        "copula.es_a_constitueix_invertit",
        "copula.es_a_constitueix_invertit_amb_aposicio",
        "copula.constitueix_a_es",
    )
    assert rule_set.config.max_semantic_risk is SemanticRisk.MEDIUM
    with pytest.raises(KeyError):
        rule_set.rule("copula.es_a_correspon_a")
    # Un conjunt que inclou dues vegades la mateixa regla és un error.
    config_file.write_text(
        "name: prova\ninclude:\n"
        "  - resources/ca/transformations/copula.yaml\n"
        "  - resources/ca/transformations/copula.yaml\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        build_rule_set(RuleSetConfig.load(config_file), registry, paths)


def test_rule_definition_validation() -> None:
    with pytest.raises(ConfigError):
        RuleDefinition.from_mapping({"engine": "pattern"})
    with pytest.raises(ConfigError):
        RuleDefinition.from_mapping({"rule_id": "x", "engine": "pattern", "level": 9})
    definition = RuleDefinition.from_mapping(
        {
            "rule_id": "x",
            "engine": "pattern",
            "transformation": "a",
            "transformations": ["b"],
            "examples": {
                "positive": [{"input": "i", "output": "o"}],
                "negative": ["n", {"input": "m"}],
            },
            "extra": 1,
        }
    )
    assert definition.transformations == ("a", "b")
    assert [e.input for e in definition.positive_examples] == ["i"]
    assert [e.input for e in definition.negative_examples] == ["n", "m"]
    assert definition.params == {"extra": 1}
