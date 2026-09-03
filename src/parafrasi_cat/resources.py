"""Localització i lectura dels recursos del projecte (YAML/JSON, llistes de termes).

Ordre de resolució del directori arrel (el que conté ``resources/``,
``rules/`` i ``dictionaries/``):

1. El paràmetre explícit ``home`` (configuració o opció ``--home`` del CLI).
2. La variable d'entorn ``PARAFRASI_CAT_HOME``.
3. El directori del repositori, si el paquet s'executa des d'un clon local.
4. Les dades empaquetades dins del paquet instal·lat (``parafrasi_cat/_data``).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from parafrasi_cat.core.errors import ResourceError

ENV_HOME = "PARAFRASI_CAT_HOME"
_LANGUAGE_MARKER = ("resources", "ca")


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    """Rutes dels directoris de dades del projecte."""

    root: Path

    @property
    def resources(self) -> Path:
        return self.root / "resources"

    @property
    def rules(self) -> Path:
        return self.root / "rules"

    @property
    def dictionaries(self) -> Path:
        return self.root / "dictionaries"

    @property
    def corpus(self) -> Path:
        return self.root / "corpus"

    @property
    def style(self) -> Path:
        return self.resources / "style"

    @property
    def fingerprints(self) -> Path:
        """Directori de les empremtes estilístiques (``style/<autor>.json``)."""
        return self.root / "style"

    def language(self, code: str = "ca") -> Path:
        return self.resources / code

    def optional(self, relative: str | Path) -> Path | None:
        """Retorna la ruta si existeix; altrament ``None``."""
        path = self.root / relative
        return path if path.exists() else None

    def resolve(self, reference: str | Path) -> Path:
        """Resol una ruta relativa a l'arrel del projecte (les absolutes es respecten)."""
        path = Path(reference)
        return path if path.is_absolute() else self.root / path

    def resolve_rule_set(self, reference: str | Path) -> Path:
        """Resol un conjunt de regles per nom (``rules/<nom>.yaml``) o per ruta."""
        return self._resolve_named(reference, self.rules, "conjunt de regles")

    def resolve_style_profile(self, reference: str | Path) -> Path:
        """Resol un perfil d'estil per nom (``resources/style/<nom>.yaml``) o per ruta."""
        return self._resolve_named(reference, self.style, "perfil d'estil")

    def resolve_fingerprint(self, reference: str | Path) -> Path:
        """Resol una empremta estilística per nom (``style/<nom>.json``) o per ruta."""
        return self._resolve_named(reference, self.fingerprints, "empremta d'estil")

    def _resolve_named(self, reference: str | Path, directory: Path, what: str) -> Path:
        text = str(reference)
        candidates: list[Path] = []
        if (
            isinstance(reference, Path)
            or "/" in text
            or os.sep in text
            or text.endswith((".yaml", ".yml", ".json"))
        ):
            candidates.append(self.resolve(reference))
        else:
            candidates.extend(
                directory / f"{text}{suffix}" for suffix in (".yaml", ".yml", ".json")
            )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise ResourceError(f"No s'ha trobat el {what} «{text}» (cercat a: {directory})")

    @classmethod
    def discover(cls, home: str | Path | None = None) -> ProjectPaths:
        if home is not None:
            root = Path(home).expanduser()
            if not _is_project_root(root):
                raise ResourceError(
                    f"El directori «{root}» no conté resources/ca; no és una arrel vàlida"
                )
            return cls(root.resolve())
        env_home = os.environ.get(ENV_HOME)
        if env_home:
            root = Path(env_home).expanduser()
            if _is_project_root(root):
                return cls(root.resolve())
        package_dir = Path(__file__).resolve().parent
        for parent in package_dir.parents[:4]:
            if _is_project_root(parent):
                return cls(parent)
        bundled = package_dir / "_data"
        if _is_project_root(bundled):
            return cls(bundled)
        raise ResourceError(
            "No s'ha pogut localitzar el directori de recursos. Indiqueu-lo amb l'opció "
            f"«home» o amb la variable d'entorn {ENV_HOME}."
        )


def _is_project_root(path: Path) -> bool:
    return path.joinpath(*_LANGUAGE_MARKER).is_dir()


def load_data(path: str | Path) -> object:
    """Llegeix un fitxer YAML o JSON i retorna l'estructura de dades."""
    file = Path(path)
    if not file.is_file():
        raise ResourceError(f"No s'ha trobat el fitxer de recursos «{file}»")
    try:
        content = file.read_text(encoding="utf-8")
        if file.suffix.lower() == ".json":
            return json.loads(content)
        if file.suffix.lower() in (".yaml", ".yml"):
            return yaml.safe_load(content)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ResourceError(f"No s'ha pogut llegir «{file}»: {exc}") from exc
    raise ResourceError(f"Extensió de recurs no reconeguda: «{file.suffix}» ({file})")


def load_mapping(path: str | Path) -> dict[str, object]:
    """Llegeix un recurs que ha de ser un diccionari de claus textuals."""
    data = load_data(path)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ResourceError(f"El recurs «{path}» ha de contenir un diccionari a l'arrel")
    return {str(key): value for key, value in data.items()}


def read_term_list(path: str | Path) -> tuple[str, ...]:
    """Llegeix una llista de termes: un per línia, ``#`` inicia un comentari."""
    file = Path(path)
    if not file.is_file():
        raise ResourceError(f"No s'ha trobat la llista de termes «{file}»")
    terms: list[str] = []
    for raw_line in file.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line:
            terms.append(line)
    return tuple(dict.fromkeys(terms))


# --- Accessors tipats sobre estructures carregades de YAML/JSON -----------------


def as_str(data: Mapping[str, object], key: str, default: str | None = None) -> str:
    value = data.get(key, default)
    if value is None:
        raise ResourceError(f"Falta la clau obligatòria «{key}»")
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise ResourceError(f"La clau «{key}» ha de ser text, no {type(value).__name__}")
    return str(value)


def as_float(data: Mapping[str, object], key: str, default: float | None = None) -> float:
    value = data.get(key, default)
    if value is None:
        raise ResourceError(f"Falta la clau numèrica obligatòria «{key}»")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ResourceError(f"La clau «{key}» ha de ser un nombre, no {type(value).__name__}")
    return float(value)


def as_int(data: Mapping[str, object], key: str, default: int | None = None) -> int:
    value = data.get(key, default)
    if value is None:
        raise ResourceError(f"Falta la clau entera obligatòria «{key}»")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResourceError(f"La clau «{key}» ha de ser un enter, no {type(value).__name__}")
    return value


def as_bool(data: Mapping[str, object], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ResourceError(f"La clau «{key}» ha de ser cert/fals, no {type(value).__name__}")
    return value


def as_str_list(data: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Sequence):
        raise ResourceError(f"La clau «{key}» ha de ser una llista de textos")
    result: list[str] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, str | int | float):
            raise ResourceError(f"La llista «{key}» només pot contenir textos")
        result.append(str(item))
    return tuple(result)


def as_mapping_list(data: Mapping[str, object], key: str) -> tuple[dict[str, object], ...]:
    value = data.get(key, [])
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise ResourceError(f"La clau «{key}» ha de ser una llista de diccionaris")
    result: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ResourceError(f"Cada element de «{key}» ha de ser un diccionari")
        result.append({str(k): v for k, v in item.items()})
    return tuple(result)


def as_mapping(data: Mapping[str, object], key: str) -> dict[str, object]:
    value = data.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ResourceError(f"La clau «{key}» ha de ser un diccionari")
    return {str(k): v for k, v in value.items()}
