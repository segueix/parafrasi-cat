"""Perfils d'estil configurables en YAML/JSON.

Un perfil pot referenciar una empremta estilística (``fingerprint:
style/autor.json``); en carregar-lo amb :func:`load_style_profile`, les
preferències de l'autor (:class:`StylePreferences`) queden disponibles a
``profile.preferences`` perquè l'avaluador d'estil i les regles les consultin.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.resources import (
    ProjectPaths,
    as_float,
    as_mapping,
    as_str,
    as_str_list,
    load_mapping,
)
from parafrasi_cat.style.fingerprint import StyleFingerprint
from parafrasi_cat.style.preferences import StylePreferences

_MIN_TOLERANCE = 4.0
_PREFERRED_CONNECTOR_MIN_SHARE = 0.5
_PREFERRED_CONNECTOR_MIN_COUNT = 2
_MAX_PREFERRED_CONNECTORS = 5


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
        fingerprint: Nom (``style/<nom>.json``) o ruta de l'empremta de l'autor (opcional).
        preferences: Preferències carregades de l'empremta (no es desa al YAML).
    """

    name: str
    description: str = ""
    target_sentence_length: float = 20.0
    sentence_length_tolerance: float = 8.0
    formality: float = 0.5
    preferred_connectors: tuple[str, ...] = field(default_factory=tuple)
    avoided_words: tuple[str, ...] = field(default_factory=tuple)
    max_change_ratio: float = 0.35
    fingerprint: str = ""
    preferences: StylePreferences | None = field(default=None, compare=False, repr=False)

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
            fingerprint=as_str(data, "fingerprint", ""),
        )

    @classmethod
    def from_fingerprint(
        cls,
        fingerprint: StyleFingerprint,
        *,
        name: str | None = None,
        description: str = "",
        fingerprint_path: str = "",
    ) -> StyleProfile:
        """Deriva un perfil de l'empremta: longitud de frase, connectors i formalitat.

        - la longitud objectiu és la mediana de paraules per frase i la tolerància,
          el rang interquartílic (mínim 4 paraules);
        - els connectors preferits són els que l'autor fa servir en més de la meitat
          dels casos dins de la seva funció (com a màxim cinc);
        - la formalitat es dedueix del registre dels connectors (formal − col·loquial).
        """
        preferences = StylePreferences(fingerprint)
        target = preferences.sentence_length or 20.0
        spread = preferences.sentence_length_spread
        tolerance = max(_MIN_TOLERANCE, spread) if spread is not None else 8.0
        connectors: list[str] = []
        top = fingerprint.get("connectors.top")
        if isinstance(top, list):
            for item in top:
                if not isinstance(item, Mapping):
                    continue
                count = item.get("count", 0)
                share = item.get("share_in_function", 0.0)
                if (
                    isinstance(count, int)
                    and count >= _PREFERRED_CONNECTOR_MIN_COUNT
                    and isinstance(share, int | float)
                    and share >= _PREFERRED_CONNECTOR_MIN_SHARE
                ):
                    connectors.append(str(item["form"]))
                if len(connectors) >= _MAX_PREFERRED_CONNECTORS:
                    break
        registers = fingerprint.get("connectors.by_register_shares")
        formality = 0.5
        if isinstance(registers, Mapping):
            formal = registers.get("formal", 0.0)
            colloquial = registers.get("col·loquial", 0.0)
            if isinstance(formal, int | float) and isinstance(colloquial, int | float):
                formality = max(0.0, min(1.0, 0.5 + (float(formal) - float(colloquial)) / 2))
        return cls(
            name=name or fingerprint.name,
            description=description
            or (
                f"Perfil derivat de l'empremta «{fingerprint.name}» "
                f"({fingerprint.n_documents} documents)"
            ),
            target_sentence_length=round(target, 2),
            sentence_length_tolerance=round(tolerance, 2),
            formality=round(formality, 2),
            preferred_connectors=tuple(connectors),
            fingerprint=fingerprint_path,
            preferences=preferences,
        )

    def with_preferences(self, preferences: StylePreferences | None) -> StyleProfile:
        return replace(self, preferences=preferences)

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
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
        if self.fingerprint:
            data["fingerprint"] = self.fingerprint
        return data


def load_style_profile(path: str | Path, *, paths: ProjectPaths | None = None) -> StyleProfile:
    """Carrega un perfil i, si referencia una empremta, també les preferències.

    L'empremta es resol com a nom dins de ``style/`` o com a ruta (absoluta,
    relativa a l'arrel del projecte si es passa ``paths``, o relativa al
    directori del perfil).
    """
    file = Path(path)
    data = load_mapping(file)
    if _is_fingerprint(data):
        fingerprint = StyleFingerprint.from_dict(data)
        return StyleProfile.from_fingerprint(fingerprint, fingerprint_path=str(file))
    profile = StyleProfile.from_mapping(data)
    if not profile.fingerprint:
        return profile
    fingerprint_file = _resolve_fingerprint(profile.fingerprint, file, paths)
    return profile.with_preferences(StylePreferences(StyleFingerprint.load(fingerprint_file)))


def _is_fingerprint(data: Mapping[str, object]) -> bool:
    """Cert si el fitxer carregat és una empremta (``style/<autor>.json``) i no un perfil."""
    return "schema_version" in data and "features" in data


def _resolve_fingerprint(reference: str, profile_file: Path, paths: ProjectPaths | None) -> Path:
    candidate = Path(reference).expanduser()
    if candidate.is_absolute() and candidate.is_file():
        return candidate
    relative = profile_file.resolve().parent / candidate
    if relative.is_file():
        return relative
    if paths is not None:
        return paths.resolve_fingerprint(reference)
    if candidate.is_file():
        return candidate
    raise ConfigError(f"No s'ha trobat l'empremta «{reference}» referenciada pel perfil")
