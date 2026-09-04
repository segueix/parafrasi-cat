"""Registre de proveïdors morfològics.

La canonada demana un proveïdor pel nom («internal», «dictionary», «null»,
«apertium», «freeling») i no depèn de cap implementació concreta. Els
adaptadors d'eines externes es creen només si s'han demanat explícitament i
fallen amb un missatge clar si l'eina no està instal·lada.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon
from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.morphology.adapters.apertium import ApertiumMorphology
from parafrasi_cat.morphology.adapters.freeling import FreeLingMorphology
from parafrasi_cat.morphology.catalan import CatalanMorphology
from parafrasi_cat.morphology.internal import InternalMorphology
from parafrasi_cat.morphology.provider import (
    ChainedMorphology,
    DictionaryMorphology,
    MorphologyProvider,
    NullMorphology,
)

FORMS_FILE = "morphology/formes.yaml"


@dataclass(frozen=True, slots=True)
class MorphologyContext:
    """Tot el que una fàbrica de proveïdors pot necessitar."""

    lang_dir: Path
    lexicon: ClosedClassLexicon | None = None
    options: Mapping[str, object] = field(default_factory=dict)

    def load_dictionary(self) -> DictionaryMorphology | None:
        file = self.lang_dir / FORMS_FILE
        return DictionaryMorphology.from_file(file) if file.is_file() else None

    def load_lexicon(self) -> ClosedClassLexicon:
        return self.lexicon if self.lexicon is not None else ClosedClassLexicon.load(self.lang_dir)

    def load_catalan(self) -> CatalanMorphology | None:
        """Recurs de Softcatalà, si l'usuari l'ha importat; ``None`` altrament."""
        return CatalanMorphology.discover(self.lang_dir)


MorphologyFactory = Callable[[MorphologyContext], MorphologyProvider]


@dataclass(frozen=True, slots=True)
class _Registration:
    factory: MorphologyFactory
    description: str


class MorphologyRegistry:
    """Associa un nom de proveïdor amb la funció que el construeix."""

    def __init__(self) -> None:
        self._providers: dict[str, _Registration] = {}

    def register(self, name: str, factory: MorphologyFactory, *, description: str = "") -> None:
        if name in self._providers:
            raise ConfigError(f"El proveïdor morfològic «{name}» ja està registrat")
        self._providers[name] = _Registration(factory, description)

    def available(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    def describe(self, name: str) -> str:
        return self._registration(name).description

    def create(self, name: str, context: MorphologyContext) -> MorphologyProvider:
        return self._registration(name).factory(context)

    def _registration(self, name: str) -> _Registration:
        try:
            return self._providers[name]
        except KeyError:
            valid = ", ".join(self.available()) or "(cap)"
            raise ConfigError(
                f"Proveïdor morfològic desconegut: «{name}». Disponibles: {valid}"
            ) from None


def _null_factory(context: MorphologyContext) -> MorphologyProvider:
    return NullMorphology()


def _dictionary_factory(context: MorphologyContext) -> MorphologyProvider:
    return context.load_dictionary() or DictionaryMorphology(())


def _internal_factory(context: MorphologyContext) -> MorphologyProvider:
    return InternalMorphology(context.load_lexicon(), context.load_dictionary())


def _catalan_factory(context: MorphologyContext) -> MorphologyProvider:
    """Softcatalà davant de l'analitzador intern, o només l'intern si no s'ha importat."""
    internal = InternalMorphology(context.load_lexicon(), context.load_dictionary())
    catalan = context.load_catalan()
    return internal if catalan is None else ChainedMorphology(catalan, internal)


def _apertium_factory(context: MorphologyContext) -> MorphologyProvider:
    adapter = ApertiumMorphology.from_options(context.options)
    adapter.require()
    return adapter


def _freeling_factory(context: MorphologyContext) -> MorphologyProvider:
    adapter = FreeLingMorphology.from_options(context.options)
    adapter.require()
    return adapter


def default_morphology_registry() -> MorphologyRegistry:
    registry = MorphologyRegistry()
    registry.register("null", _null_factory, description="Cap informació morfològica")
    registry.register(
        "dictionary",
        _dictionary_factory,
        description="Diccionari de formes (resources/ca/morphology/formes.yaml)",
    )
    registry.register(
        "internal",
        _internal_factory,
        description="Analitzador intern: lexicó de classes tancades, diccionari i endevinador",
    )
    registry.register(
        "catalan",
        _catalan_factory,
        description=(
            "Morfologia catalana de Softcatalà (importada amb scripts/import_softcatala.py) "
            "amb l'analitzador intern com a reserva"
        ),
    )
    registry.register(
        "apertium",
        _apertium_factory,
        description=(
            "Adaptador d'Apertium (cal tenir-lo instal·lat; opcions: command, mode, data_dir)"
        ),
    )
    registry.register(
        "freeling",
        _freeling_factory,
        description="Adaptador de FreeLing (cal tenir-lo instal·lat; opcions: command, config)",
    )
    return registry


def create_morphology_provider(
    name: str,
    lang_dir: str | Path,
    *,
    lexicon: ClosedClassLexicon | None = None,
    options: Mapping[str, object] | None = None,
    registry: MorphologyRegistry | None = None,
) -> MorphologyProvider:
    """Crea el proveïdor morfològic ``name`` amb els recursos de ``lang_dir``."""
    context = MorphologyContext(Path(lang_dir), lexicon, dict(options or {}))
    return (registry or default_morphology_registry()).create(name, context)
