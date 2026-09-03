"""Proveïdors d'informació morfològica."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, runtime_checkable

from parafrasi_cat.morphology.features import LexicalEntry, MorphFeatures
from parafrasi_cat.resources import as_mapping_list, as_str, load_mapping


@runtime_checkable
class MorphologyProvider(Protocol):
    """Interfície mínima d'un analitzador/generador morfològic."""

    def analyze(self, form: str) -> tuple[LexicalEntry, ...]:
        """Retorna les anàlisis possibles d'una forma (buit si és desconeguda)."""
        ...

    def generate(self, lemma: str, features: MorphFeatures) -> tuple[str, ...]:
        """Retorna les formes d'un lema compatibles amb els trets indicats."""
        ...


class NullMorphology:
    """Proveïdor que no coneix cap forma. Útil com a valor per defecte."""

    def analyze(self, form: str) -> tuple[LexicalEntry, ...]:
        return ()

    def generate(self, lemma: str, features: MorphFeatures) -> tuple[str, ...]:
        return ()


class DictionaryMorphology:
    """Proveïdor basat en una llista tancada d'entrades (formes → lema + trets)."""

    def __init__(self, entries: Iterable[LexicalEntry]) -> None:
        self._by_form: dict[str, list[LexicalEntry]] = defaultdict(list)
        self._by_lemma: dict[str, list[LexicalEntry]] = defaultdict(list)
        count = 0
        for entry in entries:
            self._by_form[entry.form.lower()].append(entry)
            self._by_lemma[entry.lemma.lower()].append(entry)
            count += 1
        self._count = count

    def __len__(self) -> int:
        return self._count

    def analyze(self, form: str) -> tuple[LexicalEntry, ...]:
        return tuple(self._by_form.get(form.lower(), ()))

    def generate(self, lemma: str, features: MorphFeatures) -> tuple[str, ...]:
        forms = [
            entry.form
            for entry in self._by_lemma.get(lemma.lower(), ())
            if entry.features.matches(features)
        ]
        return tuple(dict.fromkeys(forms))

    @classmethod
    def from_file(cls, path: str | Path) -> DictionaryMorphology:
        """Carrega un diccionari de formes des d'un YAML/JSON.

        Format esperat::

            entries:
              - form: cases
                lemma: casa
                pos: noun
                gender: f
                number: pl
        """
        data = load_mapping(path)
        entries = [
            LexicalEntry(
                form=as_str(item, "form"),
                lemma=as_str(item, "lemma"),
                features=MorphFeatures.from_mapping(item),
            )
            for item in as_mapping_list(data, "entries")
        ]
        return cls(entries)
