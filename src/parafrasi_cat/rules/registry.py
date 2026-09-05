"""Registre de motors de regla.

Un *motor* és la implementació que interpreta una definició de regla. Les
regles es declaren a les dades (``resources/ca/transformations/*.yaml``) i el
registre les instancia pel nom del motor:

- ``pattern``: patró de tokens + plantilles (la majoria de regles);
- ``lexical``: substitució lèxica basada en diccionari;
- ``connector``: classes de connectors equivalents;
- ``periphrastic_past``: passat perifràstic ↔ passat simple;
- ``nominalization``: verb ↔ construcció nominal amb verb lleuger;
- ``fusion``: fusió de frases (regla de paràgraf);
- ``copular_fusion``: fusió de frases copulatives amb el mateix subjecte.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.resources import ProjectPaths, as_str, as_str_list
from parafrasi_cat.rules.base import AnyRule
from parafrasi_cat.rules.blocks import BlockMoveRule
from parafrasi_cat.rules.connectors import ConnectorEquivalenceRule
from parafrasi_cat.rules.definition import RuleDefinition, definition_from_params
from parafrasi_cat.rules.fusion import CopularFusionRule, SentenceFusionRule
from parafrasi_cat.rules.lexical import LexicalSubstitutionRule
from parafrasi_cat.rules.nominal import nominalization_rule_from_params
from parafrasi_cat.rules.pattern_rule import HintsCache, PatternRule
from parafrasi_cat.rules.verbal import periphrastic_rule_from_params

RuleFactory = Callable[[str, Mapping[str, object], ProjectPaths], AnyRule]
"""Crea una regla a partir de (rule_id, paràmetres, rutes del projecte).

Quan la regla prové d'una definició declarativa, ``params`` inclou la clau
``definition`` amb la :class:`RuleDefinition` sencera.
"""

FINITE_VERBS_FILE = "resources/ca/transformations/verbs_finits_frequents.yaml"


@dataclass(frozen=True, slots=True)
class _Registration:
    factory: RuleFactory
    description: str


class RuleRegistry:
    """Associa un *tipus* (motor) de regla amb la funció que la construeix."""

    def __init__(self) -> None:
        self._types: dict[str, _Registration] = {}

    def register(self, rule_type: str, factory: RuleFactory, *, description: str = "") -> None:
        if rule_type in self._types:
            raise ConfigError(f"El tipus de regla «{rule_type}» ja està registrat")
        self._types[rule_type] = _Registration(factory, description)

    def available(self) -> tuple[str, ...]:
        return tuple(sorted(self._types))

    def describe(self, rule_type: str) -> str:
        return self._registration(rule_type).description

    def create(
        self,
        rule_type: str,
        rule_id: str,
        params: Mapping[str, object],
        paths: ProjectPaths,
    ) -> AnyRule:
        return self._registration(rule_type).factory(rule_id, params, paths)

    def create_from_definition(self, definition: RuleDefinition, paths: ProjectPaths) -> AnyRule:
        params = {**definition.params, "definition": definition}
        return self.create(definition.engine, definition.rule_id, params, paths)

    def _registration(self, rule_type: str) -> _Registration:
        try:
            return self._types[rule_type]
        except KeyError:
            valid = ", ".join(self.available()) or "(cap)"
            raise ConfigError(
                f"Tipus de regla desconegut: «{rule_type}». Disponibles: {valid}"
            ) from None


class _Hints:
    """Cau de pistes gramaticals compartit per totes les regles de patrons del procés."""

    cache: HintsCache | None = None
    root: str = ""

    @classmethod
    def for_paths(cls, paths: ProjectPaths) -> HintsCache:
        root = str(paths.root)
        if cls.cache is None or cls.root != root:
            file = paths.optional(FINITE_VERBS_FILE)
            finite: tuple[str, ...] = ()
            if file is not None:
                from parafrasi_cat.resources import load_mapping

                finite = as_str_list(load_mapping(file), "forms")
            cls.cache = HintsCache(finite)
            cls.root = root
        return cls.cache


def _lexical_factory(rule_id: str, params: Mapping[str, object], paths: ProjectPaths) -> AnyRule:
    definition = params.get("definition")
    source = as_str(params, "source", "")
    if not source and isinstance(definition, RuleDefinition):
        source = as_str(definition.params, "source", "") or definition.source
    if not source:
        raise ConfigError(f"La regla «{rule_id}» necessita el paràmetre «source»")
    category = definition.category if isinstance(definition, RuleDefinition) else "lexic"
    level = definition.level if isinstance(definition, RuleDefinition) else 1
    return LexicalSubstitutionRule.from_file(
        paths.resolve(source), rule_id=rule_id, category=category or "lexic", level=level
    )


def _pattern_factory(rule_id: str, params: Mapping[str, object], paths: ProjectPaths) -> AnyRule:
    return PatternRule(definition_from_params(params, rule_id), hints=_Hints.for_paths(paths))


def _connector_factory(rule_id: str, params: Mapping[str, object], paths: ProjectPaths) -> AnyRule:
    return ConnectorEquivalenceRule(definition_from_params(params, rule_id))


def _periphrastic_factory(
    rule_id: str, params: Mapping[str, object], paths: ProjectPaths
) -> AnyRule:
    definition = definition_from_params(params, rule_id)
    return periphrastic_rule_from_params(definition, params, paths.root)


def _nominalization_factory(
    rule_id: str, params: Mapping[str, object], paths: ProjectPaths
) -> AnyRule:
    definition = definition_from_params(params, rule_id)
    return nominalization_rule_from_params(definition, params, paths.root)


def _fusion_factory(rule_id: str, params: Mapping[str, object], paths: ProjectPaths) -> AnyRule:
    return SentenceFusionRule(
        definition_from_params(params, rule_id), hints=_Hints.for_paths(paths)
    )


def _block_move_factory(rule_id: str, params: Mapping[str, object], paths: ProjectPaths) -> AnyRule:
    return BlockMoveRule(definition_from_params(params, rule_id))


def _copular_fusion_factory(
    rule_id: str, params: Mapping[str, object], paths: ProjectPaths
) -> AnyRule:
    return CopularFusionRule(definition_from_params(params, rule_id), hints=_Hints.for_paths(paths))


def default_registry() -> RuleRegistry:
    """Registre amb tots els motors implementats."""
    registry = RuleRegistry()
    registry.register(
        "lexical.substitution",
        _lexical_factory,
        description=(
            "Substitució de paraules o locucions per equivalents d'un diccionari "
            "(paràmetre «source»: ruta del diccionari YAML/JSON)"
        ),
    )
    registry.register("lexical", _lexical_factory, description="Àlies de lexical.substitution")
    registry.register(
        "pattern",
        _pattern_factory,
        description="Patró de tokens amb plantilles de transformació (regles declaratives)",
    )
    registry.register(
        "connector",
        _connector_factory,
        description="Classes de connectors equivalents (paràmetre «classes»)",
    )
    registry.register(
        "periphrastic_past",
        _periphrastic_factory,
        description="Passat perifràstic ↔ passat simple (paràmetres «direction», «irregulars»)",
    )
    registry.register(
        "nominalization",
        _nominalization_factory,
        description="Verb ↔ construcció nominal amb verb lleuger (paràmetres «direction», «pairs»)",
    )
    registry.register(
        "fusion",
        _fusion_factory,
        description="Fusió de frases consecutives compatibles (regla de paràgraf)",
    )
    registry.register(
        "block_move",
        _block_move_factory,
        description=(
            "Moviment de blocs sintàctics tancats amb analitzador fiable "
            "(paràmetres «kind», «markers», «prepositions»)"
        ),
    )
    registry.register(
        "copular_fusion",
        _copular_fusion_factory,
        description=(
            "Fusió de dues frases copulatives amb el mateix subjecte "
            "(«no és només A. És B.» → «no és només A, sinó també B.»; regla de paràgraf)"
        ),
    )
    return registry
