"""Adaptador d'Apertium per a l'anàlisi morfològica del català.

Estat: preparat per a fases posteriors. L'analitzador de flux (``parse_apertium_stream``)
i la conversió d'etiquetes funcionen sense Apertium; l'anàlisi real requereix
tenir instal·lats ``apertium`` i el paquet lingüístic ``apertium-cat``.

Llicència d'Apertium: GPL-2.0 o posterior (motor i dades). Aquest adaptador
només invoca l'eina instal·lada com a procés local i no n'incorpora codi.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from parafrasi_cat.morphology.adapters.base import ExternalToolAdapter
from parafrasi_cat.morphology.features import LexicalEntry, MorphFeatures
from parafrasi_cat.resources import as_float, as_str

_UNIT_RE = re.compile(r"\^((?:\\.|[^\\^$])*)\$")
_TAG_RE = re.compile(r"<([^<>]+)>")
_UNESCAPE_RE = re.compile(r"\\(.)")

_POS_TAGS: dict[str, str] = {
    "n": "noun",
    "np": "propn",
    "vblex": "verb",
    "vbhaver": "aux",
    "vbser": "aux",
    "vbmod": "aux",
    "vaux": "aux",
    "adj": "adj",
    "adv": "adv",
    "preadv": "adv",
    "det": "det",
    "predet": "det",
    "prn": "pron",
    "rel": "pron",
    "pr": "adp",
    "cnjcoo": "conj",
    "cnjsub": "conj",
    "cnjadv": "conj",
    "num": "num",
    "ij": "intj",
    "sent": "punct",
    "cm": "punct",
    "lpar": "punct",
    "rpar": "punct",
    "lquot": "punct",
    "rquot": "punct",
    "guio": "punct",
    "apos": "punct",
}
_GENDER_TAGS = {"m": "m", "f": "f"}
_NUMBER_TAGS = {"sg": "sg", "pl": "pl"}
_PERSON_TAGS = {"p1": "1", "p2": "2", "p3": "3"}
_TENSE_MOOD_TAGS: dict[str, tuple[str | None, str]] = {
    "pri": ("pres", "ind"),
    "pii": ("impf", "ind"),
    "ifi": ("past", "ind"),
    "fti": ("fut", "ind"),
    "cni": ("cond", "ind"),
    "prs": ("pres", "subj"),
    "pis": ("impf", "subj"),
    "fts": ("fut", "subj"),
    "inf": (None, "inf"),
    "ger": (None, "ger"),
    "pp": (None, "part"),
    "imp": (None, "imp"),
}


@dataclass(frozen=True, slots=True)
class ApertiumReading:
    """Una lectura d'Apertium: lema i etiquetes (p. ex. ``casa`` ``('n', 'f', 'sg')``)."""

    lemma: str
    tags: tuple[str, ...]

    def to_features(self) -> MorphFeatures:
        pos = gender = number = person = tense = mood = None
        for tag in self.tags:
            if tag in _POS_TAGS and pos is None:
                pos = _POS_TAGS[tag]
            elif tag in _GENDER_TAGS:
                gender = _GENDER_TAGS[tag]
            elif tag in _NUMBER_TAGS:
                number = _NUMBER_TAGS[tag]
            elif tag in _PERSON_TAGS:
                person = _PERSON_TAGS[tag]
            elif tag in _TENSE_MOOD_TAGS:
                tense, mood = _TENSE_MOOD_TAGS[tag]
        return MorphFeatures(
            pos=pos, gender=gender, number=number, person=person, tense=tense, mood=mood
        )


def _unescape(text: str) -> str:
    return _UNESCAPE_RE.sub(r"\1", text)


def _split_unescaped(text: str, separator: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            current.append(text[index : index + 2])
            index += 2
            continue
        if char == separator:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    parts.append("".join(current))
    return parts


def parse_apertium_stream(output: str) -> list[tuple[str, tuple[ApertiumReading, ...]]]:
    """Analitza el format de flux d'Apertium: ``^forma/lema<t1><t2>/lema2<t>$``.

    Les formes desconegudes (``^*forma$``) es retornen sense lectures.
    """
    units: list[tuple[str, tuple[ApertiumReading, ...]]] = []
    for match in _UNIT_RE.finditer(output):
        parts = _split_unescaped(match.group(1), "/")
        surface = _unescape(parts[0])
        if surface.startswith("*"):
            units.append((surface[1:], ()))
            continue
        readings: list[ApertiumReading] = []
        for reading in parts[1:]:
            if not reading:
                continue
            lemma_end = reading.find("<")
            lemma = _unescape(reading if lemma_end < 0 else reading[:lemma_end])
            tags = tuple(_TAG_RE.findall(reading[lemma_end:] if lemma_end >= 0 else ""))
            readings.append(ApertiumReading(lemma, tags))
        units.append((surface, tuple(readings)))
    return units


class ApertiumMorphology(ExternalToolAdapter):
    """Proveïdor morfològic que invoca ``apertium`` localment.

    Opcions: ``command`` (per defecte ``apertium``), ``mode`` (per defecte
    ``cat-morph``), ``data_dir`` (directori de modes, opcional) i ``timeout``.
    """

    provider_id = "apertium"

    def __init__(
        self,
        *,
        command: str = "apertium",
        mode: str = "cat-morph",
        data_dir: str | None = None,
        timeout: float = 30.0,
        confidence: float = 0.9,
    ) -> None:
        super().__init__(command, timeout=timeout)
        self._mode = mode
        self._data_dir = data_dir
        self._confidence = confidence

    @classmethod
    def from_options(cls, options: Mapping[str, object]) -> ApertiumMorphology:
        data_dir = as_str(options, "data_dir", "") or None
        return cls(
            command=as_str(options, "command", "apertium"),
            mode=as_str(options, "mode", "cat-morph"),
            data_dir=data_dir,
            timeout=as_float(options, "timeout", 30.0),
        )

    @property
    def mode(self) -> str:
        return self._mode

    def arguments(self) -> list[str]:
        args: list[str] = []
        if self._data_dir:
            args.extend(["-d", self._data_dir])
        args.append(self._mode)
        return args

    def entries_from_output(self, form: str, output: str) -> tuple[LexicalEntry, ...]:
        for surface, readings in parse_apertium_stream(output):
            if surface.lower() != form.lower():
                continue
            return tuple(
                LexicalEntry(
                    form,
                    reading.lemma,
                    reading.to_features(),
                    confidence=self._confidence,
                    source=self.provider_id,
                )
                for reading in readings
            )
        return ()

    def analyze(self, form: str) -> tuple[LexicalEntry, ...]:
        output = self.run(self.arguments(), form + "\n")
        return self.entries_from_output(form, output)

    def generate(self, lemma: str, features: MorphFeatures) -> tuple[str, ...]:
        return ()  # la generació (lt-proc -g) queda per a fases posteriors
