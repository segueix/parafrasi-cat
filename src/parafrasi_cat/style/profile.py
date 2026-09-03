"""Perfils d'estil configurables en YAML/JSON."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.resources import as_float, as_mapping, as_str, as_str_list, load_mapping


@dataclass(frozen=True, slots=True)
class StyleProfile:
    """Descripció de l'estil objectiu.

    Atributs:
        name: Nom del perfil.
        description: Text lliure.
        target_sentence_length: Longitud mitjana desitjada (paraules per frase).
        sentence_length_tolerance: Desviació a partir de la qual la distància és màxima.
        formality: Grau de formalitat entre 0 (col·loquial) i 1 (molt formal).
        preferred_connectors: Connectors que l'estil prefereix.
        avoided_words: Mots o locucions que l'estil evita.
        max_change_ratio: Proporció màxima de canvi acceptable respecte de l'original.
    """

    name: str
    description: str = ""
    target_sentence_length: float = 20.0
    sentence_length_tolerance: float = 8.0
    formality: float = 0.5
    preferred_connectors: tuple[str, ...] = field(default_factory=tuple)
    avoided_words: tuple[str, ...] = field(default_factory=tuple)
    max_change_ratio: float = 0.35

    def __post_init__(self) -> None:
        if self.sentence_length_tolerance <= 0:
            raise ConfigError("sentence_length_tolerance ha de ser positiu")
        if not 0.0 <= self.formality <= 1.0:
            raise ConfigError("formality ha d'estar entre 0 i 1")
        if not 0.0 <= self.max_change_ratio <= 1.0:
            raise ConfigError("max_change_ratio ha d'estar entre 0 i 1")

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> StyleProfile:
        length = as_mapping(data, "sentence_length")
        return cls(
            name=as_str(data, "name", "sense-nom"),
            description=as_str(data, "description", ""),
            target_sentence_length=as_float(length, "target_mean", 20.0),
            sentence_length_tolerance=as_float(length, "tolerance", 8.0),
            formality=as_float(data, "formality", 0.5),
            preferred_connectors=as_str_list(data, "preferred_connectors"),
            avoided_words=as_str_list(data, "avoided_words"),
            max_change_ratio=as_float(data, "max_change_ratio", 0.35),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "sentence_length": {
                "target_mean": self.target_sentence_length,
                "tolerance": self.sentence_length_tolerance,
            },
            "formality": self.formality,
            "preferred_connectors": list(self.preferred_connectors),
            "avoided_words": list(self.avoided_words),
            "max_change_ratio": self.max_change_ratio,
        }


def load_style_profile(path: str | Path) -> StyleProfile:
    return StyleProfile.from_mapping(load_mapping(path))
