from __future__ import annotations

import pytest

from parafrasi_cat.analyzer import RuleBasedAnalyzer
from parafrasi_cat.core import ConfigError, SemanticRisk, Span, TransformationType
from parafrasi_cat.protected import ProtectedSpan, ProtectionKind
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.rules import (
    LexicalSubstitutionRule,
    RuleContext,
    RuleSetConfig,
    SubstitutionEntry,
    build_rule_set,
    default_registry,
)


def context(text: str, protected: tuple[ProtectedSpan, ...] = ()) -> RuleContext:
    sentence = RuleBasedAnalyzer().analyze(text).sentences[0]
    return RuleContext(sentence=sentence, protected_spans=protected, document_text=text)


def test_lexical_rule_proposes_whole_words_with_casing() -> None:
    rule = LexicalSubstitutionRule([SubstitutionEntry("gairebé", "quasi", confidence=0.9)])
    proposals = list(rule.propose(context("Gairebé tothom ho sap, gairebé.")))
    assert [(t.text_before, t.text_after) for t in proposals] == [
        ("Gairebé", "Quasi"),
        ("gairebé", "quasi"),
    ]
    first = proposals[0]
    assert first.changed_span == Span(0, 7)
    assert first.rule_id == "lexical.substitution"
    assert first.confidence == 0.9
    assert first.semantic_risk is SemanticRisk.LOW
    assert "Gairebé" in first.explanation and "Quasi" in first.explanation
    assert first.metadata["source"] == "gairebé"


def test_lexical_rule_does_not_match_inside_words() -> None:
    rule = LexicalSubstitutionRule([SubstitutionEntry("cap", "cim")])
    assert list(rule.propose(context("El capital és al cap."))) != []
    proposals = list(rule.propose(context("El capital no té capçalera.")))
    assert proposals == []


def test_lexical_rule_respects_protected_spans() -> None:
    rule = LexicalSubstitutionRule([SubstitutionEntry("gairebé", "quasi")])
    protected = (ProtectedSpan(Span(0, 7), "Gairebé", ProtectionKind.USER_TERM, "test"),)
    assert list(rule.propose(context("Gairebé tothom.", protected))) == []


def test_multiword_entries_and_apostrophes() -> None:
    rule = LexicalSubstitutionRule(
        [
            SubstitutionEntry(
                "no obstant això", "tanmateix", transformation_type=TransformationType.CONNECTOR
            )
        ]
    )
    proposals = list(rule.propose(context("No obstant   això, plou.")))
    assert [(t.text_before, t.text_after) for t in proposals] == [
        ("No obstant   això", "Tanmateix")
    ]
    assert proposals[0].transformation_type is TransformationType.CONNECTOR

    rule = LexicalSubstitutionRule([SubstitutionEntry("d'acord", "conforme")])
    assert [t.text_before for t in rule.propose(context("Hi estem d’acord."))] == ["d’acord"]


def test_substitution_entry_validation() -> None:
    with pytest.raises(ValueError):
        SubstitutionEntry("igual", "Igual")
    with pytest.raises(ValueError):
        SubstitutionEntry("", "x")
    with pytest.raises(ValueError):
        SubstitutionEntry("a", "b", confidence=2)


def test_lexical_rule_from_file(paths: ProjectPaths) -> None:
    file = paths.language() / "transformations" / "substitucions_lexiques.yaml"
    rule = LexicalSubstitutionRule.from_file(file)
    assert rule.rule_id == "lexical.substitution"
    assert len(rule.entries) >= 5
    by_source = {e.source: e for e in rule.entries}
    assert by_source["no obstant això"].transformation_type is TransformationType.CONNECTOR
    assert by_source["començar"].semantic_risk is SemanticRisk.MEDIUM
    assert by_source["gairebé"].confidence == 0.9
    proposals = list(rule.propose(context("Gairebé sempre.")))
    assert proposals[0].metadata["dictionary"] == "substitucions_lexiques.yaml"


def test_registry(paths: ProjectPaths) -> None:
    registry = default_registry()
    assert registry.available() == ("lexical.substitution",)
    assert "diccionari" in registry.describe("lexical.substitution")
    rule = registry.create(
        "lexical.substitution",
        "meva.regla",
        {"source": "resources/ca/transformations/substitucions_lexiques.yaml"},
        paths,
    )
    assert rule.rule_id == "meva.regla"
    with pytest.raises(ConfigError):
        registry.create("inexistent", "x", {}, paths)
    with pytest.raises(ConfigError):
        registry.register("lexical.substitution", lambda *_: rule)


def test_rule_set_configs(paths: ProjectPaths) -> None:
    default = RuleSetConfig.load(paths.rules / "default.yaml")
    assert default.name == "default"
    assert default.enabled_rules == ()
    assert default.max_semantic_risk is SemanticRisk.LOW

    example = RuleSetConfig.load(paths.rules / "exemple-lexic.yaml")
    assert [s.rule_id for s in example.enabled_rules] == ["lexical.substitution"]
    rule_set = build_rule_set(example, default_registry(), paths)
    assert rule_set.rule_ids == ("lexical.substitution",)
    assert build_rule_set(default, default_registry(), paths).rules == ()


def test_rule_set_rejects_duplicates() -> None:
    with pytest.raises(ConfigError):
        RuleSetConfig.from_mapping(
            {"name": "x", "rules": [{"id": "a", "type": "lexical.substitution"}, {"id": "a"}]}
        )
    with pytest.raises(ConfigError):
        RuleSetConfig(name="x", min_confidence=3.0)
