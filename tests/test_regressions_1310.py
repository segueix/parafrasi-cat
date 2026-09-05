"""Regressions específiques de la v1.3.10."""

from __future__ import annotations

from collections.abc import Mapping

from parafrasi_cat.analyzer import RuleBasedAnalyzer
from parafrasi_cat.protected import default_protector
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.rules import ConnectorEquivalenceRule, load_rule_definitions
from parafrasi_cat.rules.examples import outputs_for


def test_puix_que_is_recognised_but_never_generated(
    paths: ProjectPaths, catalan_analyzer: RuleBasedAnalyzer
) -> None:
    definition = next(
        d
        for d in load_rule_definitions(
            paths.language() / "transformations" / "connectors_equivalents.yaml"
        )
        if d.rule_id == "connector.equivalents"
    )
    rule = ConnectorEquivalenceRule(definition)
    causal = next(group for group in rule.classes if group.class_id == "causal")

    assert {member.form for member in causal.members} == {"ja que", "atès que", "puix que"}
    assert {member.form for member in causal.targets} == {"ja que", "atès que"}

    protector = default_protector(catalan_analyzer)

    def outputs(text: str) -> list[str]:
        return list(outputs_for(rule, text, catalan_analyzer, protector))

    generated_from_ja_que = outputs("Sortirem ja que plou.")
    assert generated_from_ja_que == ["Sortirem atès que plou."]
    assert all("puix que" not in text for text in generated_from_ja_que)

    # Si l'original ja el conté, sí que es pot modernitzar: el que es prohibeix
    # és introduir-lo com a ornament formal en un text que no el tenia.
    assert set(outputs("Sortirem puix que plou.")) == {
        "Sortirem ja que plou.",
        "Sortirem atès que plou.",
    }


def test_colon_split_requires_a_finite_verb_immediately_after_colon(
    paths: ProjectPaths,
) -> None:
    definition = next(
        d
        for d in load_rule_definitions(
            paths.language() / "transformations" / "cobertura_profunda.yaml"
        )
        if d.rule_id == "cobertura.dos_punts_explicatius_a_dues_frases"
    )
    pattern = list(definition.pattern)
    colon_index = next(
        index
        for index, item in enumerate(pattern)
        if isinstance(item, Mapping) and item.get("text") == ":"
    )
    first_after_colon = pattern[colon_index + 1]
    assert isinstance(first_after_colon, Mapping)
    assert first_after_colon.get("finite_verb") is True
    assert first_after_colon.get("group") == "b"

    negatives = {example.input for example in definition.negative_examples}
    assert (
        "La frase només té sentit si arfil designa una categoria política: "
        "un home pròxim al rei, útil al poder, però ja no sobirà."
    ) in negatives
