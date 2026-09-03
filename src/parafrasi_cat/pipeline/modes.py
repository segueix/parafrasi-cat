"""Modes de reescriptura: conservador i reredacció profunda.

Un mode és un *envoltant de seguretat* sobre :class:`PipelineConfig`: fixa
el risc semàntic màxim, la confiança mínima, quantes transformacions es
poden combinar en un candidat i fins a quin nivell arriben les regles.

- ``conservador``: només transformacions de risc baix i confiança alta, una
  sola transformació per candidat, sense reaplicar regles i sense
  reestructurar entre frases (nivell màxim 3). Si cap alternativa no és
  clarament segura, la puntuació deixa guanyar el text original.
- ``profund``: fins al nivell 5 (paràgraf), amb el risc i la confiança que
  declari el conjunt de regles i fins a tres transformacions combinades.

Cap dels dos modes no toca les proteccions: els termes protegits, els
diccionaris, les preferències i la llista de validadors són idèntics en tots
dos casos. La reredacció profunda pot canviar més coses, però no pot alterar
noms propis, dates, xifres, números romans, citacions, text protegit,
terminologia protegida, negacions ni força epistemològica.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.core.transformation import SemanticRisk
from parafrasi_cat.pipeline.config import PipelineConfig

MIN_LEVEL = 1
MAX_LEVEL = 5

#: Camps de la configuració que cap mode no pot tocar: són les proteccions.
PROTECTED_FIELDS: tuple[str, ...] = (
    "protected_terms",
    "protected_terms_files",
    "dictionaries",
    "preferences",
    "feedback",
)

LEVEL_LABELS: dict[int, str] = {
    1: "lèxic",
    2: "connectors",
    3: "sintaxi",
    4: "entre frases",
    5: "paràgraf",
}


class RewriteMode(StrEnum):
    """Mode de reescriptura triat per l'usuari."""

    CONSERVATIVE = "conservador"
    DEEP = "profund"

    @classmethod
    def parse(cls, value: str | RewriteMode) -> RewriteMode:
        if isinstance(value, RewriteMode):
            return value
        try:
            return cls(value.strip().lower())
        except ValueError as exc:
            valid = ", ".join(member.value for member in cls)
            raise ConfigError(f"Mode desconegut: «{value}» (vàlids: {valid})") from exc


@dataclass(frozen=True, slots=True)
class ModeSettings:
    """Envoltant de seguretat d'un mode.

    Atributs:
        mode: Identificador del mode.
        description: Explicació en una línia per a la interfície.
        max_semantic_risk: Risc semàntic màxim que s'accepta.
        min_confidence: Confiança mínima; ``None`` = la del conjunt de regles.
        max_transformations_per_sentence: Transformacions combinables per candidat.
        candidate_depth: Nivells de reaplicació de regles (1 = cap).
        max_candidates_per_sentence: Candidats avaluats per frase.
        max_level: Nivell màxim de regla que el mode permet.
        length_ratio: Marge de longitud acceptat respecte de l'original.
    """

    mode: RewriteMode
    description: str
    max_semantic_risk: SemanticRisk
    min_confidence: float | None
    max_transformations_per_sentence: int
    candidate_depth: int
    max_candidates_per_sentence: int
    max_level: int
    length_ratio: tuple[float, float]

    @property
    def label(self) -> str:
        return self.mode.value

    def level_for(self, level: int | None) -> int:
        """Nivell efectiu: el que demana l'usuari, retallat pel màxim del mode."""
        requested = self.max_level if level is None else level
        if not MIN_LEVEL <= requested <= MAX_LEVEL:
            raise ConfigError(f"El nivell ha d'estar entre {MIN_LEVEL} i {MAX_LEVEL}")
        return min(requested, self.max_level)

    def apply(self, config: PipelineConfig, level: int | None = None) -> PipelineConfig:
        """Aplica l'envoltant a ``config`` sense tocar cap protecció."""
        applied = config.with_overrides(
            max_semantic_risk=self.max_semantic_risk,
            min_confidence=self.min_confidence,
            max_transformations_per_sentence=self.max_transformations_per_sentence,
            candidate_depth=self.candidate_depth,
            max_candidates_per_sentence=self.max_candidates_per_sentence,
            level=self.level_for(level),
            length_ratio=self.length_ratio,
        )
        for field in PROTECTED_FIELDS:
            if getattr(applied, field) != getattr(config, field):  # pragma: no cover - invariant
                raise ConfigError(f"Un mode no pot modificar la protecció «{field}»")
        return applied

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.mode.value,
            "label": self.label,
            "description": self.description,
            "max_semantic_risk": self.max_semantic_risk.value,
            "min_confidence": self.min_confidence,
            "max_transformations_per_sentence": self.max_transformations_per_sentence,
            "candidate_depth": self.candidate_depth,
            "max_candidates_per_sentence": self.max_candidates_per_sentence,
            "max_level": self.max_level,
        }


CONSERVATIVE = ModeSettings(
    mode=RewriteMode.CONSERVATIVE,
    description=(
        "Només canvis de risc baix i confiança alta, un per frase i sense reestructurar "
        "entre frases. Si cap alternativa no és clarament segura, es conserva l'original."
    ),
    max_semantic_risk=SemanticRisk.LOW,
    min_confidence=0.75,
    max_transformations_per_sentence=1,
    candidate_depth=1,
    max_candidates_per_sentence=12,
    max_level=3,
    length_ratio=(0.8, 1.25),
)

DEEP = ModeSettings(
    mode=RewriteMode.DEEP,
    description=(
        "Fins al nivell 5 (paràgraf), amb combinacions de transformacions i reaplicació "
        "de regles. No pot alterar cap dada protegida ni la força epistemològica."
    ),
    max_semantic_risk=SemanticRisk.MEDIUM,
    min_confidence=None,
    max_transformations_per_sentence=3,
    candidate_depth=2,
    max_candidates_per_sentence=20,
    max_level=5,
    length_ratio=(0.6, 1.6),
)

MODES: dict[RewriteMode, ModeSettings] = {
    RewriteMode.CONSERVATIVE: CONSERVATIVE,
    RewriteMode.DEEP: DEEP,
}


def mode_settings(mode: str | RewriteMode) -> ModeSettings:
    """Envoltant de seguretat del mode indicat."""
    return MODES[RewriteMode.parse(mode)]


def apply_mode(
    config: PipelineConfig, mode: str | RewriteMode, level: int | None = None
) -> PipelineConfig:
    """Configuració amb l'envoltant del mode aplicat i el nivell retallat."""
    return mode_settings(mode).apply(config, level)


def level_label(level: int) -> str:
    """Etiqueta del nivell («3 · sintaxi»)."""
    if level not in LEVEL_LABELS:
        raise ConfigError(f"El nivell ha d'estar entre {MIN_LEVEL} i {MAX_LEVEL}")
    return f"{level} · {LEVEL_LABELS[level]}"
