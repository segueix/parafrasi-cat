"""Definició declarativa d'una regla (metadades, patró, exemples).

Les regles es defineixen en fitxers YAML/JSON amb aquesta estructura::

    description: ...
    language: ca
    rules:
      - rule_id: copula.es_a_constitueix
        engine: pattern             # pattern | lexical | connector | periphrastic_past | ...
        category: copula
        level: 3
        transformation_type: syntactic
        semantic_risk: low
        confidence: 0.75
        description: ...
        pattern: [...]
        transformation: "..."       # o «transformations: [...]» per a diversos candidats
        conditions: {...}
        exceptions: [...]
        examples:
          positive: [{input: ..., output: ...}]
          negative: [...]

Cada motor interpreta ``pattern``, ``transformation`` i les claus pròpies
(``params``) a la seva manera; les metadades i els exemples són comuns.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.core.transformation import SemanticRisk, TransformationType
from parafrasi_cat.resources import (
    as_bool,
    as_float,
    as_int,
    as_mapping,
    as_mapping_list,
    as_str,
    as_str_list,
    load_mapping,
)

_KNOWN_KEYS = frozenset(
    {
        "rule_id", "id", "engine", "language", "category", "level", "description",
        "transformation_type", "semantic_risk", "confidence", "pattern", "transformation",
        "transformations", "conditions", "exceptions", "examples", "enabled",
        "allows_epistemic_change", "reduces_epistemic_redundancy", "option",
    }
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class RuleExample:
    """Un exemple positiu (entrada → sortida esperada) o negatiu (sense sortida)."""

    input: str
    output: str | None = None

    @property
    def is_positive(self) -> bool:
        return self.output is not None


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    """Una regla tal com es declara a les dades."""

    rule_id: str
    engine: str
    language: str = "ca"
    category: str = ""
    level: int = 1
    description: str = ""
    transformation_type: TransformationType = TransformationType.SYNTACTIC
    semantic_risk: SemanticRisk = SemanticRisk.LOW
    confidence: float = 0.7
    pattern: tuple[object, ...] = ()
    transformations: tuple[str, ...] = ()
    conditions: Mapping[str, object] = field(default_factory=dict)
    exceptions: tuple[str, ...] = ()
    examples: tuple[RuleExample, ...] = ()
    params: Mapping[str, object] = field(default_factory=dict)
    enabled: bool = True
    source: str = ""
    allows_epistemic_change: bool = False
    reduces_epistemic_redundancy: bool = False
    """Cert si la regla només elimina marcadors epistemològics redundants (mateixa força)."""
    option: str = ""
    """Opció de configuració que activa la regla (buit = sempre activa)."""
    """Cert si la regla està autoritzada a canviar la força o la funció epistemològica."""

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise ConfigError("Una definició de regla necessita rule_id")
        if not self.engine:
            raise ConfigError(f"La regla «{self.rule_id}» necessita un motor (engine)")
        if not 0.0 <= self.confidence <= 1.0:
            raise ConfigError(f"La confiança de «{self.rule_id}» ha d'estar entre 0 i 1")
        if self.level < 1 or self.level > 5:
            raise ConfigError(f"El nivell de «{self.rule_id}» ha d'estar entre 1 i 5")

    @property
    def positive_examples(self) -> tuple[RuleExample, ...]:
        return tuple(e for e in self.examples if e.is_positive)

    @property
    def negative_examples(self) -> tuple[RuleExample, ...]:
        return tuple(e for e in self.examples if not e.is_positive)

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, object],
        *,
        language: str = "ca",
        source: str = "",
    ) -> RuleDefinition:
        rule_id = as_str(data, "rule_id", "") or as_str(data, "id", "")
        transformations = as_str_list(data, "transformations")
        single = data.get("transformation")
        if single is not None:
            transformations = (as_str(data, "transformation"), *transformations)
        pattern_value = data.get("pattern", ())
        if isinstance(pattern_value, str | Mapping):
            pattern: tuple[object, ...] = (pattern_value,)
        elif isinstance(pattern_value, Sequence):
            pattern = tuple(pattern_value)
        else:
            raise ConfigError(f"El patró de «{rule_id}» ha de ser una llista")
        examples_data = as_mapping(data, "examples")
        examples: list[RuleExample] = []
        for item in as_mapping_list(examples_data, "positive"):
            examples.append(RuleExample(as_str(item, "input"), as_str(item, "output")))
        negatives = examples_data.get("negative")
        if isinstance(negatives, Sequence) and not isinstance(negatives, str):
            for negative in negatives:
                if isinstance(negative, Mapping):
                    examples.append(RuleExample(as_str(negative, "input")))
                else:
                    examples.append(RuleExample(str(negative)))
        params = {key: value for key, value in data.items() if key not in _KNOWN_KEYS}
        return cls(
            rule_id=rule_id,
            engine=as_str(data, "engine", "pattern"),
            language=as_str(data, "language", language),
            category=as_str(data, "category", ""),
            level=as_int(data, "level", 1),
            description=as_str(data, "description", "").strip(),
            transformation_type=TransformationType(
                as_str(data, "transformation_type", TransformationType.SYNTACTIC.value)
            ),
            semantic_risk=SemanticRisk.parse(as_str(data, "semantic_risk", "low")),
            confidence=as_float(data, "confidence", 0.7),
            pattern=pattern,
            transformations=transformations,
            conditions=as_mapping(data, "conditions"),
            exceptions=as_str_list(data, "exceptions"),
            examples=tuple(examples),
            params=params,
            enabled=as_bool(data, "enabled", True),
            source=source,
            allows_epistemic_change=as_bool(data, "allows_epistemic_change", False),
            reduces_epistemic_redundancy=as_bool(data, "reduces_epistemic_redundancy", False),
            option=as_str(data, "option", "").strip(),
        )


def load_rule_definitions(path: str | Path) -> tuple[RuleDefinition, ...]:
    """Llegeix les definicions d'un fitxer (clau ``rules``, o una sola regla a l'arrel)."""
    file = Path(path)
    data = load_mapping(file)
    language = as_str(data, "language", "ca")
    items = as_mapping_list(data, "rules") if "rules" in data else (dict(data),)
    definitions = [
        RuleDefinition.from_mapping(item, language=language, source=str(file)) for item in items
    ]
    ids = [d.rule_id for d in definitions]
    if len(ids) != len(set(ids)):
        raise ConfigError(f"Identificadors de regla repetits a «{file}»")
    return tuple(definitions)


def definition_from_params(params: Mapping[str, object], rule_id: str) -> RuleDefinition:
    """Recupera la definició passada per la fàbrica (clau ``definition``) o en crea una mínima."""
    definition = params.get("definition")
    if isinstance(definition, RuleDefinition):
        return definition
    data = {key: value for key, value in params.items() if key != "definition"}
    data.setdefault("rule_id", rule_id)
    data.setdefault("engine", "pattern")
    return RuleDefinition.from_mapping(data)
