"""Trets morfològics i entrades lèxiques."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class MorphFeatures:
    """Trets morfològics d'una forma. Tots són opcionals.

    Valors recomanats (inspirats en les Universal Dependencies):

    - ``pos``: noun, verb, adj, adv, det, pron, adp, conj, num, intj, propn
    - ``gender``: m, f
    - ``number``: sg, pl
    - ``person``: 1, 2, 3
    - ``tense``: pres, past, fut, impf, cond
    - ``mood``: ind, subj, imp, inf, ger, part
    """

    pos: str | None = None
    gender: str | None = None
    number: str | None = None
    person: str | None = None
    tense: str | None = None
    mood: str | None = None

    def matches(self, required: MorphFeatures) -> bool:
        """Cert si tots els trets definits a ``required`` coincideixen amb aquests."""
        for f in fields(MorphFeatures):
            wanted = getattr(required, f.name)
            if wanted is not None and getattr(self, f.name) != wanted:
                return False
        return True

    def to_dict(self) -> dict[str, str]:
        return {
            f.name: value
            for f in fields(MorphFeatures)
            if (value := getattr(self, f.name)) is not None
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> MorphFeatures:
        values: dict[str, str | None] = {}
        for f in fields(MorphFeatures):
            raw = data.get(f.name)
            values[f.name] = None if raw is None else str(raw)
        return cls(**values)


@dataclass(frozen=True, slots=True)
class LexicalEntry:
    """Una forma flexionada amb el seu lema i els seus trets.

    ``confidence`` (0-1) i ``source`` indiquen d'on prové l'anàlisi (lexicó,
    diccionari, endevinador, eina externa) i quina fiabilitat té.
    """

    form: str
    lemma: str
    features: MorphFeatures = MorphFeatures()
    confidence: float = 1.0
    source: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "form": self.form,
            "lemma": self.lemma,
            "features": self.features.to_dict(),
            "confidence": self.confidence,
            "source": self.source,
        }
