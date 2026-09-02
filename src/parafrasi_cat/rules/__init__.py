"""Regles de transformació: components que proposen canvis explicables."""

from parafrasi_cat.rules.base import Rule, RuleContext
from parafrasi_cat.rules.lexical import LexicalSubstitutionRule, SubstitutionEntry
from parafrasi_cat.rules.registry import RuleFactory, RuleRegistry, default_registry
from parafrasi_cat.rules.ruleset import RuleSet, RuleSetConfig, RuleSpec, build_rule_set

__all__ = [
    "LexicalSubstitutionRule",
    "Rule",
    "RuleContext",
    "RuleFactory",
    "RuleRegistry",
    "RuleSet",
    "RuleSetConfig",
    "RuleSpec",
    "SubstitutionEntry",
    "build_rule_set",
    "default_registry",
]
