"""Regles de transformació: components que proposen canvis explicables.

Les regles es declaren com a dades (``resources/ca/transformations/*.yaml``)
i s'interpreten amb motors registrats (:func:`default_registry`). Cada regla
té identificador, llengua, categoria, nivell, patró, transformació,
condicions, excepcions, risc semàntic i exemples positius i negatius
(:class:`RuleDefinition`).
"""

from parafrasi_cat.rules.base import (
    AnyRule,
    ParagraphContext,
    ParagraphRule,
    Rule,
    RuleContext,
    protected_conflict,
)
from parafrasi_cat.rules.connectors import ConnectorClass, ConnectorEquivalenceRule
from parafrasi_cat.rules.definition import RuleDefinition, RuleExample, load_rule_definitions
from parafrasi_cat.rules.fusion import FusionStrategy, SentenceFusionRule
from parafrasi_cat.rules.lexical import LexicalSubstitutionRule, SubstitutionEntry
from parafrasi_cat.rules.nominal import NominalizationPair, NominalizationRule
from parafrasi_cat.rules.pattern_rule import PatternRule
from parafrasi_cat.rules.patterns import GrammarHints, PatternMatcher, render_template
from parafrasi_cat.rules.registry import RuleFactory, RuleRegistry, default_registry
from parafrasi_cat.rules.ruleset import RuleSet, RuleSetConfig, RuleSpec, build_rule_set
from parafrasi_cat.rules.verbal import IrregularPast, PeriphrasticPastRule

__all__ = [
    "AnyRule",
    "ConnectorClass",
    "ConnectorEquivalenceRule",
    "FusionStrategy",
    "GrammarHints",
    "IrregularPast",
    "LexicalSubstitutionRule",
    "NominalizationPair",
    "NominalizationRule",
    "ParagraphContext",
    "ParagraphRule",
    "PatternMatcher",
    "PatternRule",
    "PeriphrasticPastRule",
    "Rule",
    "RuleContext",
    "RuleDefinition",
    "RuleExample",
    "RuleFactory",
    "RuleRegistry",
    "RuleSet",
    "RuleSetConfig",
    "RuleSpec",
    "SentenceFusionRule",
    "SubstitutionEntry",
    "build_rule_set",
    "default_registry",
    "load_rule_definitions",
    "protected_conflict",
    "render_template",
]
