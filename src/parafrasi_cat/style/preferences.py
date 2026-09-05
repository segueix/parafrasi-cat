"""Consulta de les preferències estilístiques d'un autor a partir de l'empremta.

Aquesta és la interfície mínima que la resta del motor (regles, puntuació)
fa servir per saber què prefereix l'autor: longitud de frase, variant
preferida dins d'un grup d'equivalents, connectors habituals i taxes de
puntuació o d'estructures. Només llegeix l'empremta; no en modifica res.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from parafrasi_cat.style.fingerprint import StyleFingerprint

DEFAULT_MIN_OBSERVATIONS = 5
DEFAULT_MIN_CONFIDENCE = 0.25  # cinc observacions en quatre documents: 0,29


class StylePreferences:
    """Vista de només lectura sobre una :class:`StyleFingerprint`."""

    def __init__(
        self,
        fingerprint: StyleFingerprint,
        *,
        min_observations: int = DEFAULT_MIN_OBSERVATIONS,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    ) -> None:
        self._fingerprint = fingerprint
        self._min_observations = min_observations
        self._min_confidence = min_confidence

    @classmethod
    def load(cls, path: str | Path, **kwargs: int | float) -> StylePreferences:
        return cls(StyleFingerprint.load(path), **kwargs)  # type: ignore[arg-type]

    @property
    def fingerprint(self) -> StyleFingerprint:
        return self._fingerprint

    @property
    def name(self) -> str:
        return self._fingerprint.name

    # -- fiabilitat ---------------------------------------------------------------------

    def is_reliable(self, dotted: str) -> bool:
        """Cert si la característica té prou observacions i confiança."""
        node = self._fingerprint.get(dotted)
        if not isinstance(node, Mapping):
            return False
        n = node.get("n_observations", 0)
        confidence = node.get("confidence", 0.0)
        return (
            isinstance(n, int)
            and n >= self._min_observations
            and isinstance(confidence, int | float)
            and confidence >= self._min_confidence
        )

    # -- perfil epistemològic ---------------------------------------------------------------

    @property
    def epistemic_profile(self) -> Mapping[str, object] | None:
        """Perfil epistemològic de l'empremta, si hi és i té prou mostra (``None`` si no)."""
        node = self._fingerprint.get("epistemic_profile")
        if not isinstance(node, Mapping) or node.get("available") is not True:
            return None
        if node.get("confidence") == "low":
            return None
        return node

    def preferred_epistemic_marker(self, category: str) -> str | None:
        """Marcador que l'autor fa servir més per a una categoria (``None`` sense dades)."""
        profile = self.epistemic_profile
        if profile is None:
            return None
        categories = profile.get("categories")
        if not isinstance(categories, Mapping):
            return None
        node = categories.get(category)
        if not isinstance(node, Mapping):
            return None
        preferred = node.get("preferred")
        return str(preferred) if preferred else None

    # -- longitud -------------------------------------------------------------------------

    @property
    def sentence_length(self) -> float | None:
        return self._fingerprint.value("sentence_length")

    @property
    def sentence_length_spread(self) -> float | None:
        node = self._fingerprint.get("sentence_length_distribution")
        if isinstance(node, Mapping):
            value = node.get("iqr")
            if isinstance(value, int | float) and not isinstance(value, bool):
                return float(value)
        return None

    # -- variants equivalents ----------------------------------------------------------------

    @property
    def variant_groups(self) -> tuple[str, ...]:
        return self._fingerprint.variant_groups

    def variant_shares(self, group_id: str) -> dict[str, float]:
        group = self._fingerprint.variant_group(group_id)
        if group is None:
            return {}
        variants = group.get("variants")
        if not isinstance(variants, Mapping):
            return {}
        result: dict[str, float] = {}
        for variant_id, node in variants.items():
            if isinstance(node, Mapping):
                share = node.get("share", 0.0)
                if isinstance(share, int | float) and not isinstance(share, bool):
                    result[str(variant_id)] = float(share)
        return result

    def variant_share(self, group_id: str, variant_id: str) -> float | None:
        return self.variant_shares(group_id).get(variant_id)

    def preferred_variant(self, group_id: str) -> str | None:
        """Variant preferida del grup, o ``None`` si no hi ha prou evidència."""
        if not self.is_reliable(f"variant_preferences.{group_id}"):
            return None
        group = self._fingerprint.variant_group(group_id)
        if group is None:
            return None
        preferred = group.get("preferred")
        return str(preferred) if isinstance(preferred, str) else None

    def prefers(self, group_id: str, variant_id: str) -> bool | None:
        """Cert/fals si l'autor té una preferència clara; ``None`` si no hi ha evidència."""
        preferred = self.preferred_variant(group_id)
        if preferred is None:
            return None
        return preferred == variant_id

    # -- connectors -----------------------------------------------------------------------------

    def top_connectors(self, limit: int = 10) -> tuple[str, ...]:
        node = self._fingerprint.get("connectors.top")
        if not isinstance(node, list):
            return ()
        forms = [str(item["form"]) for item in node if isinstance(item, Mapping) and "form" in item]
        return tuple(forms[:limit])

    def connector_share(self, form: str) -> float | None:
        """Proporció d'ús del connector dins de la seva funció discursiva."""
        node = self._fingerprint.get("connectors.top")
        if not isinstance(node, list):
            return None
        wanted = " ".join(form.lower().replace("’", "'").split())
        for item in node:
            if isinstance(item, Mapping) and str(item.get("form")) == wanted:
                share = item.get("share_in_function")
                if isinstance(share, int | float) and not isinstance(share, bool):
                    return float(share)
        return 0.0 if self.is_reliable("connectors.per_100_words") else None

    def connector_function_shares(self) -> dict[str, float]:
        node = self._fingerprint.get("connectors.by_function_shares")
        if not isinstance(node, Mapping):
            return {}
        return {str(k): float(v) for k, v in node.items() if isinstance(v, int | float)}

    # -- taxes ---------------------------------------------------------------------

    def rate(self, dotted: str) -> float | None:
        """Valor d'una característica numèrica, o ``None`` si no és fiable."""
        if not self.is_reliable(dotted):
            return None
        return self._fingerprint.value(dotted)

    def punctuation_rate(self, mark: str) -> float | None:
        """Signes per 100 paraules (``comma``, ``semicolon``, ``colon``, ``dash``...)."""
        return self._fingerprint.value(f"punctuation.{mark}.per_100_words")

    @property
    def impersonal_rate(self) -> float | None:
        return self._fingerprint.value("impersonal.per_100_sentences")

    @property
    def passive_rate(self) -> float | None:
        return self._fingerprint.value("passive.per_100_sentences")

    def first_person_rate(self, number: str = "singular") -> float | None:
        return self._fingerprint.value(f"first_person.{number}.per_100_sentences")

    # -- resum ---------------------------------------------------------------------

    def summary(self) -> str:
        lines = [f"Preferències d'estil de «{self.name}»"]
        length = self.sentence_length
        if length is not None:
            lines.append(f"  longitud de frase: {length:.1f} paraules")
        for group_id in self.variant_groups:
            preferred = self.preferred_variant(group_id)
            if preferred is not None:
                lines.append(f"  {group_id}: prefereix «{preferred}»")
        connectors = self.top_connectors(5)
        if connectors:
            lines.append("  connectors habituals: " + ", ".join(connectors))
        return "\n".join(lines)
