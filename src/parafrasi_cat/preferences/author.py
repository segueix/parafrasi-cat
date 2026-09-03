"""Preferències explícites de l'autor (``preferences/author.yml``).

Format::

    name: autor
    description: ...
    prefer: ["així com", "per tant"]
    avoid: ["a nivell de", "en base a"]
    preferred_connectors: [tanmateix, "així doncs"]
    preferred_sentence_length: 22
    max_sentence_length: 45
    preferred_variants:
      "obra de": 1.0
      "fet per": 0.4
      "realitzat per": 0.7
    feedback: feedback.yml        # opcional: recomptes del feedback manual

Cada forma rep un pes entre 0 i 1: 1 per a ``prefer`` i
``preferred_connectors``, 0 per a ``avoid`` i el pes declarat per a
``preferred_variants``. Aquestes preferències són explícites i editables, i
tenen prioritat sobre l'empremta estadística de l'autor; només els fragments
protegits i els diccionaris del projecte passen per davant.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.dictionaries.dictionary import normalize_term
from parafrasi_cat.resources import as_int, as_mapping, as_str, as_str_list, load_mapping

_KNOWN_KEYS = frozenset(
    {
        "name", "description", "prefer", "avoid", "preferred_connectors",
        "preferred_sentence_length", "max_sentence_length", "preferred_variants", "feedback",
    }
)  # fmt: skip


def _clean(forms: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for form in forms:
        text = " ".join(str(form).split())
        key = normalize_term(text)
        if key and key not in seen:
            seen.add(key)
            result.append(text)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class AuthorPreferences:
    """Preferències explícites i editables de l'autor.

    Atributs:
        name: Nom de l'autor o del perfil.
        description: Text lliure.
        prefer: Formes o locucions que l'autor prefereix (pes 1).
        avoid: Formes o locucions que l'autor evita (pes 0).
        preferred_connectors: Connectors habituals de l'autor (pes 1).
        preferred_sentence_length: Longitud de frase preferida, en paraules.
        max_sentence_length: Longitud màxima acceptable, en paraules.
        preferred_variants: Pes (0-1) de cada variant equivalent.
        feedback_file: Fitxer amb el feedback manual (opcional).
        path: Fitxer d'on s'han carregat les preferències (opcional).
    """

    name: str = "autor"
    description: str = ""
    prefer: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    preferred_connectors: tuple[str, ...] = ()
    preferred_sentence_length: int | None = None
    max_sentence_length: int | None = None
    preferred_variants: Mapping[str, float] = field(default_factory=dict)
    feedback_file: Path | None = None
    path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "prefer", _clean(tuple(self.prefer)))
        object.__setattr__(self, "avoid", _clean(tuple(self.avoid)))
        object.__setattr__(self, "preferred_connectors", _clean(tuple(self.preferred_connectors)))
        variants: dict[str, float] = {}
        for form, weight in self.preferred_variants.items():
            text = " ".join(str(form).split())
            if isinstance(weight, bool) or not isinstance(weight, int | float):
                raise ConfigError(f"El pes de la variant «{form}» ha de ser un nombre")
            if not 0.0 <= float(weight) <= 1.0:
                raise ConfigError(f"El pes de la variant «{form}» ha d'estar entre 0 i 1")
            if text:
                variants[text] = float(weight)
        object.__setattr__(self, "preferred_variants", variants)
        overlap = {normalize_term(f) for f in self.prefer} & {normalize_term(f) for f in self.avoid}
        if overlap:
            raise ConfigError(f"Formes alhora a «prefer» i a «avoid»: {sorted(overlap)}")
        for name in ("preferred_sentence_length", "max_sentence_length"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise ConfigError(f"«{name}» ha de ser almenys 1")
        if (
            self.preferred_sentence_length is not None
            and self.max_sentence_length is not None
            and self.max_sentence_length < self.preferred_sentence_length
        ):
            raise ConfigError(
                "«max_sentence_length» no pot ser inferior a «preferred_sentence_length»"
            )

    @property
    def is_empty(self) -> bool:
        return (
            not self.forms
            and self.preferred_sentence_length is None
            and self.max_sentence_length is None
        )

    @property
    def forms(self) -> tuple[str, ...]:
        """Totes les formes sobre les quals l'autor ha declarat una preferència."""
        return _clean(
            (*self.prefer, *self.avoid, *self.preferred_variants, *self.preferred_connectors)
        )

    @property
    def source_label(self) -> str:
        return (
            f"preferències de l'autor ({self.path.name})"
            if self.path
            else "preferències de l'autor"
        )

    def weight_of(self, form: str) -> float | None:
        """Pes entre 0 i 1 de la forma, o ``None`` si l'autor no en diu res."""
        key = normalize_term(form)
        if key in {normalize_term(f) for f in self.prefer}:
            return 1.0
        if key in {normalize_term(f) for f in self.avoid}:
            return 0.0
        for variant, weight in self.preferred_variants.items():
            if normalize_term(variant) == key:
                return weight
        if key in {normalize_term(f) for f in self.preferred_connectors}:
            return 1.0
        return None

    def reason_of(self, form: str) -> str | None:
        """Motiu llegible del pes de la forma."""
        key = normalize_term(form)
        if key in {normalize_term(f) for f in self.prefer}:
            return "forma preferida («prefer»)"
        if key in {normalize_term(f) for f in self.avoid}:
            return "forma a evitar («avoid»)"
        for variant, weight in self.preferred_variants.items():
            if normalize_term(variant) == key:
                return f"variant amb pes {weight:.2f} («preferred_variants»)"
        if key in {normalize_term(f) for f in self.preferred_connectors}:
            return "connector preferit («preferred_connectors»)"
        return None

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, object],
        *,
        name: str | None = None,
        base_dir: Path | None = None,
        path: Path | None = None,
    ) -> AuthorPreferences:
        unknown = sorted(set(data) - _KNOWN_KEYS)
        if unknown:
            raise ConfigError(f"Claus desconegudes al fitxer de preferències: {unknown}")
        feedback_value = as_str(data, "feedback", "") if data.get("feedback") is not None else ""
        feedback_file: Path | None = None
        if feedback_value:
            feedback_file = Path(feedback_value).expanduser()
            if not feedback_file.is_absolute() and base_dir is not None:
                feedback_file = base_dir / feedback_file
        return cls(
            name=as_str(data, "name", name or "autor"),
            description=as_str(data, "description", ""),
            prefer=as_str_list(data, "prefer"),
            avoid=as_str_list(data, "avoid"),
            preferred_connectors=as_str_list(data, "preferred_connectors"),
            preferred_sentence_length=(
                as_int(data, "preferred_sentence_length")
                if data.get("preferred_sentence_length") is not None
                else None
            ),
            max_sentence_length=(
                as_int(data, "max_sentence_length")
                if data.get("max_sentence_length") is not None
                else None
            ),
            preferred_variants=_variants(as_mapping(data, "preferred_variants")),
            feedback_file=feedback_file,
            path=path,
        )

    @classmethod
    def load(cls, path: str | Path) -> AuthorPreferences:
        file = Path(path)
        return cls.from_mapping(
            load_mapping(file), name=file.stem, base_dir=file.resolve().parent, path=file
        )

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "name": self.name,
            "description": self.description,
            "prefer": list(self.prefer),
            "avoid": list(self.avoid),
            "preferred_connectors": list(self.preferred_connectors),
            "preferred_sentence_length": self.preferred_sentence_length,
            "max_sentence_length": self.max_sentence_length,
            "preferred_variants": dict(self.preferred_variants),
        }
        if self.feedback_file is not None:
            data["feedback"] = str(self.feedback_file)
        return data

    def summary(self) -> str:
        lines = [f"Preferències explícites de «{self.name}»"]
        if self.prefer:
            lines.append("  prefereix: " + ", ".join(self.prefer))
        if self.avoid:
            lines.append("  evita: " + ", ".join(self.avoid))
        if self.preferred_connectors:
            lines.append("  connectors: " + ", ".join(self.preferred_connectors))
        if self.preferred_sentence_length is not None:
            lines.append(
                f"  longitud de frase preferida: {self.preferred_sentence_length} paraules"
            )
        if self.max_sentence_length is not None:
            lines.append(f"  longitud de frase màxima: {self.max_sentence_length} paraules")
        for variant, weight in self.preferred_variants.items():
            lines.append(f"  variant «{variant}»: pes {weight:.2f}")
        if self.feedback_file is not None:
            lines.append(f"  feedback: {self.feedback_file}")
        return "\n".join(lines)


def _variants(data: Mapping[str, object]) -> dict[str, float]:
    result: dict[str, float] = {}
    for form, weight in data.items():
        if isinstance(weight, bool) or not isinstance(weight, int | float):
            raise ConfigError(f"El pes de la variant «{form}» ha de ser un nombre")
        result[str(form)] = float(weight)
    return result
