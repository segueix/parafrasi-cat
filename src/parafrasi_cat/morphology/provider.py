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


def inflect_like(
    provider: MorphologyProvider, form: str, lemma: str, *, pos: str | None = None
) -> str | None:
    """Forma de ``lemma`` amb els mateixos trets que ``form``, o ``None``.

    És l'operació que fan servir les regles per canviar de verb conservant la
    persona, el nombre i el gènere: «és» amb el lema «constituir» dona
    «constitueix», i «feta» amb «realitzar» dona «realitzada». Funciona amb
    qualsevol proveïdor; si no en coneix la forma d'origen o no té la
    d'arribada, retorna ``None`` i la regla recorre al seu mapatge explícit.
    """
    for entry in provider.analyze(form):
        if pos is not None and entry.features.pos != pos:
            continue
        generated = provider.generate(lemma, entry.features)
        if generated:
            return generated[0]
    return None


class NullMorphology:
    """Proveïdor que no coneix cap forma. Útil com a valor per defecte."""

    def analyze(self, form: str) -> tuple[LexicalEntry, ...]:
        return ()

    def generate(self, lemma: str, features: MorphFeatures) -> tuple[str, ...]:
        return ()


class ChainedMorphology:
    """Consulta diversos proveïdors en ordre de fiabilitat.

    El primer que conegui una forma o un lema respon. Serveix per posar el
    recurs de Softcatalà davant de l'analitzador intern sense perdre'l: si el
    recurs no s'ha importat, o no coneix una forma, actua el fallback de
    sempre.
    """

    def __init__(self, *providers: MorphologyProvider) -> None:
        self._providers = tuple(providers)

    @property
    def providers(self) -> tuple[MorphologyProvider, ...]:
        return self._providers

    def analyze(self, form: str) -> tuple[LexicalEntry, ...]:
        for provider in self._providers:
            entries = provider.analyze(form)
            if entries:
                return entries
        return ()

    def generate(self, lemma: str, features: MorphFeatures) -> tuple[str, ...]:
        for provider in self._providers:
            forms = provider.generate(lemma, features)
            if forms:
                return forms
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
