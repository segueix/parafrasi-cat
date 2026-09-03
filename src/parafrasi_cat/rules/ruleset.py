"""Conjunts de regles configurables en YAML/JSON.

Un conjunt de regles pot:

- incloure fitxers de definicions declaratives (``include``), que aporten
  totes les regles que contenen;
- activar regles per tipus i paràmetres (``rules``), o desactivar-ne
  d'incloses (``{id: ..., enabled: false}``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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
    as_str_list,
    load_mapping,
)
from parafrasi_cat.rules.base import AnyRule, ParagraphRule, Rule
from parafrasi_cat.rules.definition import RuleDefinition, load_rule_definitions
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
    include: tuple[str, ...] = ()

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
            include=as_str_list(data, "include"),
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
    rules: tuple[AnyRule, ...]
    definitions: tuple[RuleDefinition, ...] = ()

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(rule.rule_id for rule in self.rules)

    @property
    def sentence_rules(self) -> tuple[Rule, ...]:
        return tuple(rule for rule in self.rules if isinstance(rule, Rule))

    @property
    def paragraph_rules(self) -> tuple[ParagraphRule, ...]:
        return tuple(rule for rule in self.rules if isinstance(rule, ParagraphRule))

    def rule(self, rule_id: str) -> AnyRule:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        raise KeyError(rule_id)

    @property
    def epistemic_rule_ids(self) -> tuple[str, ...]:
        """Regles autoritzades explícitament a canviar la força epistemològica."""
        return tuple(d.rule_id for d in self.definitions if d.allows_epistemic_change)

    def up_to_level(self, level: int | None) -> RuleSet:
        """Conjunt restringit a les regles de nivell ≤ ``level`` (``None`` = totes)."""
        if level is None:
            return self
        if level < 1:
            raise ConfigError("El nivell ha de ser almenys 1")
        rules = tuple(rule for rule in self.rules if rule.level <= level)
        kept = {rule.rule_id for rule in rules}
        definitions = tuple(d for d in self.definitions if d.rule_id in kept)
        return RuleSet(self.config, rules, definitions)

    def with_extra_rules(self, rules: Iterable[AnyRule]) -> RuleSet:
        """Conjunt ampliat amb regles construïdes en codi (p. ex. la dels diccionaris)."""
        extra = tuple(rules)
        ids = [*self.rule_ids, *(rule.rule_id for rule in extra)]
        if len(ids) != len(set(ids)):
            raise ConfigError("Hi ha identificadors de regla repetits en ampliar el conjunt")
        return RuleSet(self.config, (*self.rules, *extra), self.definitions)


def build_rule_set(
    config: RuleSetConfig,
    registry: RuleRegistry,
    paths: ProjectPaths,
) -> RuleSet:
    """Instancia les regles del conjunt: primer les incloses, després les explícites."""
    overrides = {spec.rule_id: spec for spec in config.rules}
    rules: list[AnyRule] = []
    definitions: list[RuleDefinition] = []
    seen: set[str] = set()
    for include in config.include:
        for definition in load_rule_definitions(paths.resolve(include)):
            if definition.rule_id in seen:
                raise ConfigError(f"La regla «{definition.rule_id}» s'inclou dues vegades")
            seen.add(definition.rule_id)
            override = overrides.get(definition.rule_id)
            enabled = definition.enabled if override is None else override.enabled
            if not enabled:
                continue
            merged = definition
            if override is not None and override.params:
                merged = RuleDefinition(
                    **{
                        **{f: getattr(definition, f) for f in RuleDefinition.__dataclass_fields__},
                        "params": {**definition.params, **override.params},
                    }
                )
            definitions.append(merged)
            rules.append(registry.create_from_definition(merged, paths))
    for spec in config.enabled_rules:
        if spec.rule_id in seen:
            continue  # només era una modificació d'una regla inclosa
        rules.append(registry.create(spec.rule_type, spec.rule_id, spec.params, paths))
    return RuleSet(config=config, rules=tuple(rules), definitions=tuple(definitions))
