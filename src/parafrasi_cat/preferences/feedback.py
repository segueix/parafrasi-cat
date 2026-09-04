"""Feedback manual de l'autor sobre variants, com a recomptes explícits.

L'autor marca una variant com a *preferida*, *acceptable* o *rebutjada*
(``parafrasi-cat feedback preferred "obra de"``). Els recomptes es desen en
un YAML llegible i versionable::

    description: Feedback manual de l'autor sobre variants.
    prior: 3
    variants:
      fet per: {preferred: 0, acceptable: 1, rejected: 3}
      obra de: {preferred: 4, acceptable: 2, rejected: 0}

El pes d'una variant és la mitjana d'aprovació (preferida = 1, acceptable =
0,5, rebutjada = 0) suavitzada amb ``prior`` observacions neutres, de manera
que una única decisió mou el pes poc (amb ``prior`` 3, una sola «preferida»
dona 0,625 i no 1). No s'hi entrena cap model: el pes es calcula cada vegada
a partir dels recomptes, que qualsevol pot llegir i editar.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from parafrasi_cat.core.errors import ConfigError, ResourceError
from parafrasi_cat.dictionaries.dictionary import normalize_term
from parafrasi_cat.resources import as_int, as_mapping, as_str, load_mapping, write_atomically

DEFAULT_PRIOR = 3
DEFAULT_FEEDBACK_FILE = "feedback.yml"
VERDICTS: tuple[str, ...] = ("preferred", "acceptable", "rejected")
VERDICT_LABELS: dict[str, str] = {
    "preferred": "preferida",
    "acceptable": "acceptable",
    "rejected": "rebutjada",
}
_DEFAULT_DESCRIPTION = (
    "Feedback manual de l'autor sobre variants (recomptes explícits; cap model entrenat)."
)
_HEADER = (
    "# Feedback manual de l'autor sobre variants: recomptes explícits i inspeccionables.\n"
    "# El motor no hi entrena cap model; només llegeix aquests nombres.\n"
    "# Ordres: parafrasi-cat feedback preferred|acceptable|rejected VARIANT\n"
    "#         parafrasi-cat feedback show\n"
)


@dataclass(frozen=True, slots=True)
class FeedbackCounts:
    """Recomptes de les decisions de l'autor sobre una variant."""

    preferred: int = 0
    acceptable: int = 0
    rejected: int = 0

    def __post_init__(self) -> None:
        for verdict in VERDICTS:
            if getattr(self, verdict) < 0:
                raise ConfigError(f"El recompte «{verdict}» no pot ser negatiu")

    @property
    def total(self) -> int:
        return self.preferred + self.acceptable + self.rejected

    def weight(self, prior: int = DEFAULT_PRIOR) -> float:
        """Aprovació mitjana entre 0 i 1, suavitzada amb ``prior`` observacions neutres."""
        if prior < 0:
            raise ConfigError("«prior» no pot ser negatiu")
        if self.total + prior == 0:
            return 0.5
        return (self.preferred + 0.5 * self.acceptable + 0.5 * prior) / (self.total + prior)

    def with_verdict(self, verdict: str, times: int = 1) -> FeedbackCounts:
        if verdict not in VERDICTS:
            raise ConfigError(f"Veredicte desconegut: «{verdict}» (vàlids: {', '.join(VERDICTS)})")
        if times < 1:
            raise ConfigError("«times» ha de ser almenys 1")
        values = {v: getattr(self, v) for v in VERDICTS}
        values[verdict] += times
        return FeedbackCounts(**values)

    def describe(self) -> str:
        return (
            f"preferida {self.preferred} vegades, acceptable {self.acceptable} "
            f"i rebutjada {self.rejected}"
        )

    def to_dict(self) -> dict[str, int]:
        return {verdict: getattr(self, verdict) for verdict in VERDICTS}

    @classmethod
    def from_mapping(cls, form: str, data: Mapping[str, object]) -> FeedbackCounts:
        unknown = sorted(set(data) - set(VERDICTS))
        if unknown:
            raise ConfigError(f"Veredictes desconeguts per a «{form}»: {unknown}")
        return cls(**{verdict: as_int(data, verdict, 0) for verdict in VERDICTS})


class FeedbackStore:
    """Recomptes de feedback per variant, amb persistència en YAML."""

    def __init__(
        self,
        counts: Mapping[str, FeedbackCounts] | None = None,
        *,
        path: Path | None = None,
        prior: int = DEFAULT_PRIOR,
        description: str = _DEFAULT_DESCRIPTION,
    ) -> None:
        if prior < 0:
            raise ConfigError("«prior» no pot ser negatiu")
        self._counts: dict[str, tuple[str, FeedbackCounts]] = {}
        for form, value in (counts or {}).items():
            self._set(form, value)
        self._path = path
        self._prior = prior
        self._description = description

    # -- consulta -------------------------------------------------------------------------------

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def prior(self) -> int:
        return self._prior

    @property
    def description(self) -> str:
        return self._description

    @property
    def is_empty(self) -> bool:
        return not self._counts

    def __len__(self) -> int:
        return len(self._counts)

    @property
    def forms(self) -> tuple[str, ...]:
        """Variants amb feedback, en ordre alfabètic (determinista)."""
        return tuple(form for _, (form, _counts) in sorted(self._counts.items()))

    @property
    def source_label(self) -> str:
        return f"feedback de l'autor ({self._path.name})" if self._path else "feedback de l'autor"

    def counts_of(self, form: str) -> FeedbackCounts | None:
        found = self._counts.get(normalize_term(form))
        return None if found is None else found[1]

    def weight_of(self, form: str) -> float | None:
        """Pes entre 0 i 1 de la variant, o ``None`` si no en té cap feedback."""
        counts = self.counts_of(form)
        return None if counts is None else counts.weight(self._prior)

    # -- registre -------------------------------------------------------------------------------

    def record(self, form: str, verdict: str, times: int = 1) -> FeedbackCounts:
        """Suma una decisió de l'autor i retorna els recomptes actualitzats."""
        text = " ".join(form.split())
        if not text:
            raise ConfigError("La variant no pot ser buida")
        current = self.counts_of(text) or FeedbackCounts()
        updated = current.with_verdict(verdict, times)
        key = normalize_term(text)
        display = self._counts[key][0] if key in self._counts else text
        self._counts[key] = (display, updated)
        return updated

    def _set(self, form: str, counts: FeedbackCounts) -> None:
        text = " ".join(str(form).split())
        if not text:
            raise ConfigError("La variant no pot ser buida")
        self._counts[normalize_term(text)] = (text, counts)

    # -- persistència ---------------------------------------------------------------------------

    @classmethod
    def from_mapping(cls, data: Mapping[str, object], *, path: Path | None = None) -> FeedbackStore:
        variants = as_mapping(data, "variants") if "variants" in data else {}
        counts: dict[str, FeedbackCounts] = {}
        for form, value in variants.items():
            if not isinstance(value, Mapping):
                raise ConfigError(f"Els recomptes de «{form}» han de ser un diccionari")
            counts[form] = FeedbackCounts.from_mapping(form, {str(k): v for k, v in value.items()})
        return cls(
            counts,
            path=path,
            prior=as_int(data, "prior", DEFAULT_PRIOR),
            description=as_str(data, "description", _DEFAULT_DESCRIPTION),
        )

    @classmethod
    def load(cls, path: str | Path) -> FeedbackStore:
        """Carrega el fitxer; si no existeix, retorna un magatzem buit lligat a la ruta."""
        file = Path(path)
        if not file.is_file():
            return cls(path=file)
        return cls.from_mapping(load_mapping(file), path=file)

    def to_dict(self) -> dict[str, object]:
        return {
            "description": self._description,
            "prior": self._prior,
            "variants": {form: counts.to_dict() for form, counts in self._sorted()},
        }

    def to_yaml(self) -> str:
        body = yaml.safe_dump(
            self.to_dict(),
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )
        return _HEADER + body

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path is not None else self._path
        if target is None:
            raise ResourceError("No s'ha indicat cap fitxer on desar el feedback")
        target.parent.mkdir(parents=True, exist_ok=True)
        write_atomically(target, self.to_yaml())
        self._path = target
        return target

    # -- resum ----------------------------------------------------------------------------------

    def _sorted(self) -> list[tuple[str, FeedbackCounts]]:
        return [(form, counts) for _, (form, counts) in sorted(self._counts.items())]

    def summary(self) -> str:
        if not self._counts:
            return "Cap variant amb feedback"
        lines = [f"Feedback de l'autor ({len(self._counts)} variants, prior {self._prior}):"]
        for form, counts in self._sorted():
            lines.append(
                f"  «{form}»: preferida {counts.preferred} · acceptable {counts.acceptable} · "
                f"rebutjada {counts.rejected} → pes {counts.weight(self._prior):.2f}"
            )
        return "\n".join(lines)
