"""Model de l'empremta estilística (``style/<autor>.json``).

L'empremta és un document JSON explícit i llegible: cada característica
guarda el valor, el nombre d'observacions, la confiança, la variabilitat i,
quan escau, alguns exemples curts del corpus. No conté el corpus.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from parafrasi_cat.core.errors import ResourceError
from parafrasi_cat.style.statistics import RobustSummary, confidence, round_floats

SCHEMA_VERSION = "1.1"
_STAT_KEYS = frozenset({"value", "unit", "n_observations", "confidence"})


@dataclass(frozen=True, slots=True)
class FeatureStat:
    """Una característica numèrica amb la seva fiabilitat i exemples.

    Atributs:
        value: Estimació robusta (mediana o mediana ponderada entre documents).
        unit: Unitat llegible («paraules per frase», «per 100 paraules»...).
        n_observations: Nombre d'observacions que sustenten el valor.
        n_documents: Documents que hi han contribuït.
        confidence: Confiança (0-1) derivada de les observacions i els documents.
        variability: Desviació absoluta mediana entre documents (mateixa unitat).
        pooled: Valor global sense correcció (tot el corpus junt), per comparar.
        per_document: Mínim, mediana i màxim dels valors per document.
        examples: Fragments curts del corpus que il·lustren la característica.
        note: Observació sobre el mètode (p. ex. «aproximat»).
    """

    value: float | None
    unit: str
    n_observations: int
    n_documents: int
    confidence: float
    variability: float | None = None
    pooled: float | None = None
    per_document: dict[str, float] | None = None
    examples: tuple[str, ...] = ()
    note: str = ""

    @classmethod
    def from_summary(
        cls,
        summary: RobustSummary,
        unit: str,
        *,
        examples: tuple[str, ...] = (),
        note: str = "",
        confidence_factor: float = 1.0,
    ) -> FeatureStat:
        base = confidence(summary.n_observations, summary.n_documents)
        return cls(
            value=summary.value,
            unit=unit,
            n_observations=summary.n_observations,
            n_documents=summary.n_documents,
            confidence=round(base * confidence_factor, 3),
            variability=summary.variability,
            pooled=summary.pooled,
            per_document=summary.per_document() if summary.n_documents else None,
            examples=examples,
            note=note,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "unit": self.unit,
            "n_observations": self.n_observations,
            "n_documents": self.n_documents,
            "confidence": self.confidence,
            "variability": self.variability,
            "pooled": self.pooled,
            "per_document": None if self.per_document is None else dict(self.per_document),
            "examples": list(self.examples),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> FeatureStat:
        if not is_stat(data):
            raise ResourceError("El node no és una característica numèrica de l'empremta")
        per_document = data.get("per_document")
        examples = data.get("examples", [])
        return cls(
            value=_optional_float(data.get("value")),
            unit=str(data.get("unit", "")),
            n_observations=int(_number(data.get("n_observations", 0))),
            n_documents=int(_number(data.get("n_documents", 0))),
            confidence=float(_number(data.get("confidence", 0.0))),
            variability=_optional_float(data.get("variability")),
            pooled=_optional_float(data.get("pooled")),
            per_document=(
                {str(k): float(_number(v)) for k, v in per_document.items()}
                if isinstance(per_document, Mapping)
                else None
            ),
            examples=tuple(str(e) for e in examples) if isinstance(examples, list) else (),
            note=str(data.get("note", "")),
        )


def is_stat(data: object) -> bool:
    return isinstance(data, Mapping) and set(data.keys()) >= _STAT_KEYS


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ResourceError(f"S'esperava un nombre i s'ha trobat {value!r}")
    return float(value)


def _optional_float(value: object) -> float | None:
    return None if value is None else _number(value)


@dataclass(frozen=True, slots=True)
class StyleFingerprint:
    """Empremta estilística d'un autor: metadades del corpus i característiques."""

    name: str
    description: str
    language: str
    generator: dict[str, object]
    corpus: dict[str, object]
    features: dict[str, object]
    validation: dict[str, object] | None = None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "schema_version": self.schema_version,
            "name": self.name,
            "description": self.description,
            "language": self.language,
            "generator": dict(self.generator),
            "corpus": dict(self.corpus),
            "features": dict(self.features),
            "validation": None if self.validation is None else dict(self.validation),
        }
        rounded = round_floats(data)
        assert isinstance(rounded, dict)
        return rounded

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent) + "\n"

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> StyleFingerprint:
        for key in ("schema_version", "name", "features"):
            if key not in data:
                raise ResourceError(f"L'empremta no té la clau obligatòria «{key}»")
        version = str(data["schema_version"])
        if version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            raise ResourceError(
                f"Versió d'esquema «{version}» no compatible amb la {SCHEMA_VERSION}"
            )
        features = data["features"]
        if not isinstance(features, Mapping):
            raise ResourceError("«features» ha de ser un objecte")
        validation = data.get("validation")
        return cls(
            name=str(data["name"]),
            description=str(data.get("description", "")),
            language=str(data.get("language", "ca")),
            generator=_as_dict(data.get("generator")),
            corpus=_as_dict(data.get("corpus")),
            features={str(k): v for k, v in features.items()},
            validation=None if validation is None else _as_dict(validation),
            schema_version=version,
        )

    @classmethod
    def load(cls, path: str | Path) -> StyleFingerprint:
        file = Path(path)
        if not file.is_file():
            raise ResourceError(f"No s'ha trobat l'empremta «{file}»")
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ResourceError(f"No s'ha pogut llegir l'empremta «{file}»: {exc}") from exc
        if not isinstance(data, Mapping):
            raise ResourceError(f"L'empremta «{file}» ha de ser un objecte JSON")
        return cls.from_dict(data)

    def save(self, path: str | Path) -> Path:
        file = Path(path)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(self.to_json(), encoding="utf-8")
        return file

    # -- accés còmode ------------------------------------------------------------------

    def get(self, dotted: str) -> object | None:
        """Node de ``features`` per ruta amb punts (``punctuation.comma.per_100_words``)."""
        node: object = self.features
        for part in dotted.split("."):
            if not isinstance(node, Mapping) or part not in node:
                return None
            node = node[part]
        return node

    def stat(self, dotted: str) -> FeatureStat | None:
        node = self.get(dotted)
        if isinstance(node, Mapping) and is_stat(node):
            return FeatureStat.from_dict(node)
        return None

    def value(self, dotted: str) -> float | None:
        stat = self.stat(dotted)
        return None if stat is None else stat.value

    def variant_group(self, group_id: str) -> dict[str, object] | None:
        node = self.get(f"variant_preferences.{group_id}")
        return {str(k): v for k, v in node.items()} if isinstance(node, Mapping) else None

    @property
    def variant_groups(self) -> tuple[str, ...]:
        node = self.features.get("variant_preferences")
        return tuple(str(k) for k in node) if isinstance(node, Mapping) else ()

    @property
    def has_rhythm_profile(self) -> bool:
        """Cert si l'empremta porta el perfil de ritme (esquema 1.1 o posterior)."""
        node = self.features.get("rhythm_profile")
        return isinstance(node, Mapping) and bool(node.get("length"))

    @property
    def has_syntactic_profile(self) -> bool:
        """Cert si l'empremta porta el perfil sintàctic calculat amb el parser."""
        node = self.features.get("syntactic_profile")
        return isinstance(node, Mapping) and node.get("available") is True

    @property
    def n_documents(self) -> int:
        value = self.corpus.get("n_documents", 0)
        return int(value) if isinstance(value, int) else 0

    @property
    def n_words(self) -> int:
        value = self.corpus.get("n_words", 0)
        return int(value) if isinstance(value, int) else 0


def _as_dict(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ResourceError("S'esperava un objecte JSON")
    return {str(k): v for k, v in value.items()}
