"""Registre de tipus de regla disponibles."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.resources import ProjectPaths, as_str
from parafrasi_cat.rules.base import Rule
from parafrasi_cat.rules.lexical import LexicalSubstitutionRule

RuleFactory = Callable[[str, Mapping[str, object], ProjectPaths], Rule]
"""Crea una regla a partir de (rule_id, paràmetres, rutes del projecte)."""


@dataclass(frozen=True, slots=True)
class _Registration:
    factory: RuleFactory
    description: str


class RuleRegistry:
    """Associa un *tipus* de regla amb la funció que la construeix."""

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
    ) -> Rule:
        return self._registration(rule_type).factory(rule_id, params, paths)

    def _registration(self, rule_type: str) -> _Registration:
        try:
            return self._types[rule_type]
        except KeyError:
            valid = ", ".join(self.available()) or "(cap)"
            raise ConfigError(
                f"Tipus de regla desconegut: «{rule_type}». Disponibles: {valid}"
            ) from None


def _lexical_factory(rule_id: str, params: Mapping[str, object], paths: ProjectPaths) -> Rule:
    source = as_str(params, "source")
    return LexicalSubstitutionRule.from_file(paths.resolve(source), rule_id=rule_id)


def default_registry() -> RuleRegistry:
    """Registre amb els tipus de regla implementats en aquesta fase."""
    registry = RuleRegistry()
    registry.register(
        "lexical.substitution",
        _lexical_factory,
        description=(
            "Substitució de paraules o locucions per equivalents d'un diccionari "
            "(paràmetre «source»: ruta del diccionari YAML/JSON)"
        ),
    )
    return registry
