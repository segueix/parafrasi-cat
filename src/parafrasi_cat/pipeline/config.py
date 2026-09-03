"""Configuració de la canonada (editable en YAML o JSON)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.core.transformation import SemanticRisk
from parafrasi_cat.resources import (
    as_bool,
    as_float,
    as_int,
    as_mapping,
    as_str,
    as_str_list,
    load_mapping,
)
from parafrasi_cat.scoring.weights import ScoringWeights


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Paràmetres de construcció de la canonada.

    Atributs:
        home: Directori arrel amb ``resources/``, ``rules/`` i ``dictionaries/``
            (``None`` = detecció automàtica).
        language: Codi de llengua dels recursos (només ``ca`` en aquesta fase).
        rule_set: Nom (``rules/<nom>.yaml``) o ruta del conjunt de regles.
        style_profile: Nom (``resources/style/<nom>.yaml``) o ruta del perfil d'estil.
        morphology: Nom del proveïdor morfològic (``internal``, ``dictionary``, ``null``,
            ``apertium``, ``freeling``); vegeu ``parafrasi_cat.morphology.registry``.
        protected_terms: Termes addicionals que cap regla pot tocar.
        protected_terms_files: Fitxers amb termes protegits (un per línia).
        max_semantic_risk: Risc màxim acceptat; ``None`` = el del conjunt de regles.
        min_confidence: Confiança mínima acceptada; ``None`` = la del conjunt de regles.
        scoring: Pesos de la puntuació.
        max_transformations_per_sentence: Límit de transformacions combinades per frase.
        max_candidates_per_sentence: Límit de candidats avaluats per frase.
        candidate_depth: Nivells de reaplicació de regles sobre els candidats (1 = cap).
        length_ratio: Marge de longitud (mínim, màxim) acceptat respecte de l'original.
        use_style: Si és fals, no es calcula la distància d'estil.
    """

    home: Path | None = None
    language: str = "ca"
    rule_set: str = "default"
    style_profile: str = "default"
    morphology: str = "internal"
    protected_terms: tuple[str, ...] = ()
    protected_terms_files: tuple[Path, ...] = ()
    max_semantic_risk: SemanticRisk | None = None
    min_confidence: float | None = None
    scoring: ScoringWeights = field(default_factory=ScoringWeights)
    max_transformations_per_sentence: int = 3
    max_candidates_per_sentence: int = 20
    candidate_depth: int = 2
    length_ratio: tuple[float, float] = (0.6, 1.6)
    use_style: bool = True

    def __post_init__(self) -> None:
        if self.min_confidence is not None and not 0.0 <= self.min_confidence <= 1.0:
            raise ConfigError("min_confidence ha d'estar entre 0 i 1")
        if self.candidate_depth < 1:
            raise ConfigError("candidate_depth ha de ser almenys 1")
        if self.max_transformations_per_sentence < 1 or self.max_candidates_per_sentence < 1:
            raise ConfigError("Els límits de transformacions i candidats han de ser almenys 1")
        low, high = self.length_ratio
        if not 0.0 < low <= 1.0 <= high:
            raise ConfigError("length_ratio ha de complir 0 < mínim <= 1 <= màxim")

    def with_overrides(self, **changes: Any) -> PipelineConfig:
        """Retorna una còpia amb els camps indicats modificats."""
        return replace(self, **changes)

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, object],
        *,
        base_dir: Path | None = None,
    ) -> PipelineConfig:
        """Construeix la configuració a partir d'un diccionari (contingut d'un YAML/JSON).

        Les rutes relatives es resolen respecte de ``base_dir`` (normalment el
        directori del fitxer de configuració).
        """
        defaults = cls()
        home_value = data.get("home")
        home = _resolve_path(as_str(data, "home"), base_dir) if home_value is not None else None
        risk_value = data.get("max_semantic_risk")
        risk = (
            SemanticRisk.parse(as_str(data, "max_semantic_risk"))
            if risk_value is not None
            else None
        )
        confidence = (
            as_float(data, "min_confidence") if data.get("min_confidence") is not None else None
        )
        ratio = as_mapping(data, "length_ratio")
        return cls(
            home=home,
            language=as_str(data, "language", defaults.language),
            rule_set=_maybe_path(as_str(data, "rule_set", defaults.rule_set), base_dir),
            style_profile=_maybe_path(
                as_str(data, "style_profile", defaults.style_profile), base_dir
            ),
            morphology=as_str(data, "morphology", defaults.morphology),
            protected_terms=as_str_list(data, "protected_terms"),
            protected_terms_files=tuple(
                _resolve_path(f, base_dir) for f in as_str_list(data, "protected_terms_files")
            ),
            max_semantic_risk=risk,
            min_confidence=confidence,
            scoring=ScoringWeights.from_mapping(as_mapping(data, "scoring")),
            max_transformations_per_sentence=as_int(
                data, "max_transformations_per_sentence", defaults.max_transformations_per_sentence
            ),
            max_candidates_per_sentence=as_int(
                data, "max_candidates_per_sentence", defaults.max_candidates_per_sentence
            ),
            candidate_depth=as_int(data, "candidate_depth", defaults.candidate_depth),
            length_ratio=(
                as_float(ratio, "min", defaults.length_ratio[0]),
                as_float(ratio, "max", defaults.length_ratio[1]),
            ),
            use_style=as_bool(data, "use_style", defaults.use_style),
        )

    @classmethod
    def load(cls, path: str | Path) -> PipelineConfig:
        file = Path(path)
        return cls.from_mapping(load_mapping(file), base_dir=file.resolve().parent)

    def to_dict(self) -> dict[str, object]:
        return {
            "home": None if self.home is None else str(self.home),
            "language": self.language,
            "rule_set": self.rule_set,
            "style_profile": self.style_profile,
            "morphology": self.morphology,
            "protected_terms": list(self.protected_terms),
            "protected_terms_files": [str(f) for f in self.protected_terms_files],
            "max_semantic_risk": None
            if self.max_semantic_risk is None
            else self.max_semantic_risk.value,
            "min_confidence": self.min_confidence,
            "scoring": self.scoring.to_dict(),
            "max_transformations_per_sentence": self.max_transformations_per_sentence,
            "max_candidates_per_sentence": self.max_candidates_per_sentence,
            "candidate_depth": self.candidate_depth,
            "length_ratio": {"min": self.length_ratio[0], "max": self.length_ratio[1]},
            "use_style": self.use_style,
        }


def _resolve_path(value: str, base_dir: Path | None) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute() or base_dir is None:
        return path
    return base_dir / path


def _maybe_path(value: str, base_dir: Path | None) -> str:
    """Si el valor sembla una ruta (conté separadors o extensió), la resol; si no, és un nom."""
    if "/" in value or value.endswith((".yaml", ".yml", ".json")):
        return str(_resolve_path(value, base_dir))
    return value
