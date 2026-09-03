"""Conjunts de regles configurables en YAML/JSON."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.core.transformation import SemanticRisk
from parafrasi_cat.resources import (
    ProjectPaths,
    as_bool,
    as_float,
    as_mapping,
    as_mapping_list,
    as_str,
    load_mapping,
)
from parafrasi_cat.rules.base import Rule
from parafrasi_cat.rules.registry import RuleRegistry


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """Una regla dins d'un conjunt: identificador, tipus, estat i paràmetres."""

    rule_id: str
    rule_type: str
    enabled: bool = True
    params: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> RuleSpec:
        rule_id = as_str(data, "id")
        return cls(
            rule_id=rule_id,
            rule_type=as_str(data, "type", rule_id),
            enabled=as_bool(data, "enabled", True),
            params=as_mapping(data, "params"),
        )


@dataclass(frozen=True, slots=True)
class RuleSetConfig:
    """Configuració d'un conjunt de regles (contingut de ``rules/<nom>.yaml``)."""

    name: str
    description: str = ""
    max_semantic_risk: SemanticRisk = SemanticRisk.LOW
    min_confidence: float = 0.6
    rules: tuple[RuleSpec, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ConfigError("min_confidence ha d'estar entre 0 i 1")
        ids = [spec.rule_id for spec in self.rules]
        if len(ids) != len(set(ids)):
            raise ConfigError("Hi ha identificadors de regla repetits al conjunt")

    @property
    def enabled_rules(self) -> tuple[RuleSpec, ...]:
        return tuple(spec for spec in self.rules if spec.enabled)

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> RuleSetConfig:
        return cls(
            name=as_str(data, "name", "sense-nom"),
            description=as_str(data, "description", ""),
            max_semantic_risk=SemanticRisk.parse(as_str(data, "max_semantic_risk", "low")),
            min_confidence=as_float(data, "min_confidence", 0.6),
            rules=tuple(RuleSpec.from_mapping(item) for item in as_mapping_list(data, "rules")),
        )

    @classmethod
    def load(cls, path: str | Path) -> RuleSetConfig:
        return cls.from_mapping(load_mapping(path))

    @classmethod
    def empty(cls, name: str = "buit") -> RuleSetConfig:
        return cls(name=name, description="Cap regla activa: el text es retorna sense canvis")


@dataclass(frozen=True, slots=True)
class RuleSet:
    """Conjunt de regles instanciades i la configuració d'on provenen."""

    config: RuleSetConfig
    rules: tuple[Rule, ...]

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(rule.rule_id for rule in self.rules)


def build_rule_set(
    config: RuleSetConfig,
    registry: RuleRegistry,
    paths: ProjectPaths,
) -> RuleSet:
    """Instancia les regles actives d'un conjunt mitjançant el registre."""
    rules = [
        registry.create(spec.rule_type, spec.rule_id, spec.params, paths)
        for spec in config.enabled_rules
    ]
    return RuleSet(config=config, rules=tuple(rules))
