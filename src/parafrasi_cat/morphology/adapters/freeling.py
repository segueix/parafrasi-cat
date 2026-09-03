"""Adaptador de FreeLing per a l'anàlisi morfològica del català.

Estat: preparat per a fases posteriors. La descodificació d'etiquetes EAGLES
(``decode_eagles``) i l'analitzador de la sortida (``parse_freeling_morfo``)
funcionen sense FreeLing; l'anàlisi real requereix tenir instal·lat
l'executable ``analyze`` i la configuració del català (``ca.cfg``).

Llicència de FreeLing: AGPL-3.0 (amb llicència comercial disponible). Aquest
adaptador només invoca l'eina instal·lada com a procés local i no n'incorpora codi.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from parafrasi_cat.morphology.adapters.base import ExternalToolAdapter
from parafrasi_cat.morphology.features import LexicalEntry, MorphFeatures
from parafrasi_cat.resources import as_float, as_str

_CATEGORY_POS: dict[str, str] = {
    "A": "adj",
    "C": "conj",
    "D": "det",
    "N": "noun",
    "P": "pron",
    "R": "adv",
    "S": "adp",
    "V": "verb",
    "Z": "num",
    "W": "date",
    "F": "punct",
    "I": "intj",
    "Y": "abbr",
    "X": "x",
}
_GENDER = {"M": "m", "F": "f"}
_NUMBER = {"S": "sg", "P": "pl"}
_TENSE = {"P": "pres", "I": "impf", "F": "fut", "S": "past", "C": "cond"}
_MOOD = {"I": "ind", "S": "subj", "M": "imp", "N": "inf", "G": "ger", "P": "part"}


def _at(tag: str, index: int) -> str:
    return tag[index] if index < len(tag) else "0"


def decode_eagles(tag: str) -> MorphFeatures:
    """Converteix una etiqueta EAGLES de FreeLing (p. ex. ``VMIP3S0``) en trets."""
    if not tag:
        return MorphFeatures()
    category = tag[0]
    pos = _CATEGORY_POS.get(category)
    gender = number = person = tense = mood = None
    if category == "V":
        if _at(tag, 1) in ("A", "S"):
            pos = "aux"
        mood = _MOOD.get(_at(tag, 2))
        tense = _TENSE.get(_at(tag, 3))
        person = _at(tag, 4) if _at(tag, 4) in "123" else None
        number = _NUMBER.get(_at(tag, 5))
        gender = _GENDER.get(_at(tag, 6))
    elif category == "N":
        if _at(tag, 1) == "P":
            pos = "propn"
        gender = _GENDER.get(_at(tag, 2))
        number = _NUMBER.get(_at(tag, 3))
    elif category == "A":
        gender = _GENDER.get(_at(tag, 3))
        number = _NUMBER.get(_at(tag, 4))
    elif category in ("D", "P"):
        person = _at(tag, 2) if _at(tag, 2) in "123" else None
        gender = _GENDER.get(_at(tag, 3))
        number = _NUMBER.get(_at(tag, 4))
    return MorphFeatures(
        pos=pos, gender=gender, number=number, person=person, tense=tense, mood=mood
    )


@dataclass(frozen=True, slots=True)
class FreeLingReading:
    lemma: str
    tag: str
    probability: float

    def to_features(self) -> MorphFeatures:
        return decode_eagles(self.tag)


def parse_freeling_morfo(output: str) -> list[tuple[str, tuple[FreeLingReading, ...]]]:
    """Analitza la sortida de ``analyze --outlv morfo``: ``forma lema etiqueta prob [...]``."""
    units: list[tuple[str, tuple[FreeLingReading, ...]]] = []
    for line in output.splitlines():
        fields = line.split()
        if not fields:
            continue
        surface = fields[0]
        readings: list[FreeLingReading] = []
        rest = fields[1:]
        for index in range(0, len(rest) - 2, 3):
            lemma, tag, probability = rest[index], rest[index + 1], rest[index + 2]
            try:
                readings.append(FreeLingReading(lemma, tag, float(probability)))
            except ValueError:
                readings.append(FreeLingReading(lemma, tag, 0.0))
        units.append((surface, tuple(readings)))
    return units


class FreeLingMorphology(ExternalToolAdapter):
    """Proveïdor morfològic que invoca l'executable ``analyze`` de FreeLing.

    Opcions: ``command`` (per defecte ``analyze``), ``config`` (per defecte
    ``ca.cfg``) i ``timeout``.
    """

    provider_id = "freeling"

    def __init__(
        self,
        *,
        command: str = "analyze",
        config: str = "ca.cfg",
        timeout: float = 30.0,
    ) -> None:
        super().__init__(command, timeout=timeout)
        self._config = config

    @classmethod
    def from_options(cls, options: Mapping[str, object]) -> FreeLingMorphology:
        return cls(
            command=as_str(options, "command", "analyze"),
            config=as_str(options, "config", "ca.cfg"),
            timeout=as_float(options, "timeout", 30.0),
        )

    @property
    def config(self) -> str:
        return self._config

    def arguments(self) -> list[str]:
        return ["-f", self._config, "--outlv", "morfo", "--flush"]

    def entries_from_output(self, form: str, output: str) -> tuple[LexicalEntry, ...]:
        for surface, readings in parse_freeling_morfo(output):
            if surface.lower() != form.lower():
                continue
            return tuple(
                LexicalEntry(
                    form,
                    reading.lemma,
                    reading.to_features(),
                    confidence=reading.probability,
                    source=self.provider_id,
                )
                for reading in readings
            )
        return ()

    def analyze(self, form: str) -> tuple[LexicalEntry, ...]:
        output = self.run(self.arguments(), form + "\n")
        return self.entries_from_output(form, output)

    def generate(self, lemma: str, features: MorphFeatures) -> tuple[str, ...]:
        return ()  # FreeLing no genera formes
