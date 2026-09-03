"""Pesos configurables de la funció de puntuació."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.resources import as_float, as_int


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    """Pesos de la puntuació global.

    - ``transformation_gain``: pes del guany per transformacions aplicades.
      Cada transformació aporta ``confiança × (1 − semantic_risk × pes_del_risc)``.
    - ``semantic_risk``: multiplicador del risc semàntic dins del guany.
    - ``style_distance``: penalització per distància respecte del perfil d'estil.
    - ``grammar``: penalització per defectes heurístics de gramaticalitat.
    - ``preferences``: pes de les preferències explícites (diccionaris del projecte,
      fitxer de preferències de l'autor i feedback manual).
    - ``max_transformations``: nombre de transformacions que normalitza el guany.

    Les dimensions de preservació (factual, epistemològica, terminològica) no
    tenen pes: qualsevol error hi invalida el candidat.
    """

    transformation_gain: float = 1.0
    semantic_risk: float = 1.0
    style_distance: float = 0.5
    grammar: float = 0.5
    preferences: float = 0.5
    max_transformations: int = 3

    def __post_init__(self) -> None:
        if self.max_transformations < 1:
            raise ConfigError("max_transformations ha de ser almenys 1")
        for name in (
            "transformation_gain",
            "semantic_risk",
            "style_distance",
            "grammar",
            "preferences",
        ):
            if getattr(self, name) < 0:
                raise ConfigError(f"El pes «{name}» no pot ser negatiu")

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> ScoringWeights:
        defaults = cls()
        return cls(
            transformation_gain=as_float(data, "transformation_gain", defaults.transformation_gain),
            semantic_risk=as_float(data, "semantic_risk", defaults.semantic_risk),
            style_distance=as_float(data, "style_distance", defaults.style_distance),
            grammar=as_float(data, "grammar", defaults.grammar),
            preferences=as_float(data, "preferences", defaults.preferences),
            max_transformations=as_int(data, "max_transformations", defaults.max_transformations),
        )

    def to_dict(self) -> dict[str, float | int]:
        return {
            "transformation_gain": self.transformation_gain,
            "semantic_risk": self.semantic_risk,
            "style_distance": self.style_distance,
            "grammar": self.grammar,
            "preferences": self.preferences,
            "max_transformations": self.max_transformations,
        }
