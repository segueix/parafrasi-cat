"""Configuració de la canonada (editable en YAML o JSON)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
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


class SourceMode(StrEnum):
    """D'on ve el text que es reescriu. Ho diu l'usuari; el motor no ho endevina mai."""

    OWN = "own"
    """Text propi: el comportament de sempre."""

    LLM_DRAFT = "llm_draft"
    """Esborrany generat amb un LLM: s'hi afegeix l'adaptació a l'empremta de l'autor."""

    @classmethod
    def parse(cls, value: str | SourceMode) -> SourceMode:
        if isinstance(value, SourceMode):
            return value
        try:
            return cls(value.strip().lower())
        except ValueError as exc:
            valid = ", ".join(member.value for member in cls)
            raise ConfigError(f"Origen del text desconegut: «{value}» (vàlids: {valid})") from exc

    @property
    def label(self) -> str:
        return "Text propi" if self is SourceMode.OWN else "Esborrany generat amb LLM"

    @property
    def description(self) -> str:
        if self is SourceMode.OWN:
            return "Reescriptura amb les regles, els diccionaris i les preferències de sempre."
        return "El text s'adaptarà als patrons estilístics de l'empremta de l'autor."

    @property
    def adapts_to_author(self) -> bool:
        """Cert si el mode afegeix la capa d'adaptació autoral (i, per tant, exigeix empremta)."""
        return self is SourceMode.LLM_DRAFT


#: Missatge que veu l'usuari quan demana adaptar un esborrany sense cap empremta.
FINGERPRINT_REQUIRED = (
    "Per adaptar un esborrany a la teva manera d'escriure, selecciona o crea primer "
    "una empremta d'autor."
)


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Paràmetres de construcció de la canonada.

    Atributs:
        home: Directori arrel amb ``resources/``, ``rules/`` i ``dictionaries/``
            (``None`` = detecció automàtica).
        language: Codi de llengua dels recursos (només ``ca`` en aquesta fase).
        rule_set: Nom (``rules/<nom>.yaml``) o ruta del conjunt de regles.
        style_profile: Nom (``resources/style/<nom>.yaml``) o ruta del perfil d'estil.
        morphology: Nom del proveïdor morfològic (``catalan``, ``internal``, ``dictionary``,
            ``null``, ``apertium``, ``freeling``); vegeu ``parafrasi_cat.morphology.registry``.
            Per defecte ``catalan``: el recurs de Softcatalà si s'ha importat i, si no,
            l'analitzador intern.
        protected_terms: Termes addicionals que cap regla pot tocar.
        protected_terms_files: Fitxers amb termes protegits (un per línia).
        max_semantic_risk: Risc màxim acceptat; ``None`` = el del conjunt de regles.
        min_confidence: Confiança mínima acceptada; ``None`` = la del conjunt de regles.
        scoring: Pesos de la puntuació.
        max_transformations_per_sentence: Límit de transformacions combinades per frase.
        max_candidates_per_sentence: Límit de candidats avaluats per frase.
        candidate_depth: Nivells de reaplicació de regles sobre els candidats (1 = cap).
        paragraph_beam_width: Amplada de la cerca en feix d'arquitectures de paràgraf
            (1 = sense cerca: el paràgraf es reconstrueix amb els guanyadors locals).
            El mode profund l'activa al nivell 5.
        sentence_candidates_for_paragraph: Candidats alternatius (a més de l'original)
            que cada frase conserva per a la cerca de paràgraf.
        level: Nivell màxim de les regles actives (1 lèxic … 5 paràgraf); ``None`` = totes.
        length_ratio: Marge de longitud (mínim, màxim) acceptat respecte de l'original.
        use_style: Si és fals, no es calcula la distància d'estil.
        syntax: Analitzador sintàctic (``auto`` = el parser local si està instal·lat,
            ``none`` = cap). El parser només analitza; mai no genera text.
        languagetool: Si és cert, s'afegeix la validació local de LanguageTool quan
            estigui instal·lada. Per defecte és fals: el motor no depèn de Java ni de
            LanguageTool, i la interfície ofereix activar-lo si el detecta.
        dictionaries: Diccionaris terminològics actius (noms dins de ``dictionaries/`` o rutes).
        preferences: Fitxer de preferències explícites de l'autor (nom dins de
            ``preferences/`` o ruta); ``None`` = cap.
        feedback: Fitxer de feedback manual; ``None`` = el que indiqui el fitxer de
            preferències (clau ``feedback``), si en té.
        source_mode: Origen del text, tal com l'ha indicat l'usuari: ``own`` (per
            defecte, comportament de sempre) o ``llm_draft`` (esborrany generat amb un
            LLM, que s'adapta a l'empremta de l'autor; l'empremta és obligatòria).
        assertive_language: «Llenguatge assertiu»: activa les regles que fan més
            directa la formulació epistemològica (menys doble modalització, hipòtesi,
            inferència i limitació explícites) sense canviar mai la força expressada.
            Per defecte és fals i és ortogonal al mode.
    """

    home: Path | None = None
    language: str = "ca"
    rule_set: str = "default"
    style_profile: str = "default"
    morphology: str = "catalan"
    protected_terms: tuple[str, ...] = ()
    protected_terms_files: tuple[Path, ...] = ()
    max_semantic_risk: SemanticRisk | None = None
    min_confidence: float | None = None
    scoring: ScoringWeights = field(default_factory=ScoringWeights)
    max_transformations_per_sentence: int = 3
    max_candidates_per_sentence: int = 20
    candidate_depth: int = 2
    paragraph_beam_width: int = 1
    sentence_candidates_for_paragraph: int = 3
    level: int | None = None
    length_ratio: tuple[float, float] = (0.6, 1.6)
    use_style: bool = True
    dictionaries: tuple[str, ...] = ()
    preferences: str | None = None
    feedback: Path | None = None
    syntax: str = "auto"
    languagetool: bool = False
    source_mode: SourceMode = SourceMode.OWN
    assertive_language: bool = False

    def __post_init__(self) -> None:
        if self.level is not None and not 1 <= self.level <= 5:
            raise ConfigError("level ha d'estar entre 1 i 5")
        if self.min_confidence is not None and not 0.0 <= self.min_confidence <= 1.0:
            raise ConfigError("min_confidence ha d'estar entre 0 i 1")
        if self.candidate_depth < 1:
            raise ConfigError("candidate_depth ha de ser almenys 1")
        if self.max_transformations_per_sentence < 1 or self.max_candidates_per_sentence < 1:
            raise ConfigError("Els límits de transformacions i candidats han de ser almenys 1")
        if self.paragraph_beam_width < 1 or self.sentence_candidates_for_paragraph < 1:
            raise ConfigError("Els límits de la cerca de paràgraf han de ser almenys 1")
        low, high = self.length_ratio
        if not 0.0 < low <= 1.0 <= high:
            raise ConfigError("length_ratio ha de complir 0 < mínim <= 1 <= màxim")
        # S'admet el nom del mode com a text («llm_draft»); es normalitza sempre.
        object.__setattr__(self, "source_mode", SourceMode.parse(self.source_mode))

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
            paragraph_beam_width=as_int(
                data, "paragraph_beam_width", defaults.paragraph_beam_width
            ),
            sentence_candidates_for_paragraph=as_int(
                data,
                "sentence_candidates_for_paragraph",
                defaults.sentence_candidates_for_paragraph,
            ),
            level=as_int(data, "level") if data.get("level") is not None else None,
            length_ratio=(
                as_float(ratio, "min", defaults.length_ratio[0]),
                as_float(ratio, "max", defaults.length_ratio[1]),
            ),
            use_style=as_bool(data, "use_style", defaults.use_style),
            syntax=as_str(data, "syntax", defaults.syntax),
            languagetool=as_bool(data, "languagetool", defaults.languagetool),
            source_mode=SourceMode.parse(as_str(data, "source_mode", defaults.source_mode.value)),
            assertive_language=as_bool(data, "assertive_language", defaults.assertive_language),
            dictionaries=tuple(
                _maybe_path(item, base_dir) for item in as_str_list(data, "dictionaries")
            ),
            preferences=(
                _maybe_path(as_str(data, "preferences"), base_dir)
                if data.get("preferences")
                else None
            ),
            feedback=(
                _resolve_path(as_str(data, "feedback"), base_dir) if data.get("feedback") else None
            ),
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
            "paragraph_beam_width": self.paragraph_beam_width,
            "sentence_candidates_for_paragraph": self.sentence_candidates_for_paragraph,
            "level": self.level,
            "length_ratio": {"min": self.length_ratio[0], "max": self.length_ratio[1]},
            "use_style": self.use_style,
            "syntax": self.syntax,
            "languagetool": self.languagetool,
            "source_mode": self.source_mode.value,
            "assertive_language": self.assertive_language,
            "dictionaries": list(self.dictionaries),
            "preferences": self.preferences,
            "feedback": None if self.feedback is None else str(self.feedback),
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
