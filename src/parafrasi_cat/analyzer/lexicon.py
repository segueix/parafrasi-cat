"""Lexicó de classes tancades del català (articles, preposicions, pronoms...).

Les dades es carreguen dels recursos YAML de ``resources/ca/lexicon/`` i de
``resources/ca/connectors/``. El lexicó només identifica formes: no fa cap
transformació. Els mòduls d'anàlisi el fan servir per reconèixer mots
gramaticals, expressions multiparaula i formes auxiliars.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from parafrasi_cat.core.text import phrase_pattern
from parafrasi_cat.resources import as_mapping_list, as_str, as_str_list, load_mapping


class WordClass(StrEnum):
    ARTICLE = "article"
    PREPOSITION = "preposition"
    CONJUNCTION = "conjunction"
    PRONOUN = "pronoun"
    ADVERB = "adverb"
    AUXILIARY = "auxiliary"
    CONNECTOR = "connector"
    DISCOURSE_MARKER = "discourse_marker"

    @property
    def default_pos(self) -> str:
        return _DEFAULT_POS[self]


_DEFAULT_POS: dict[WordClass, str] = {
    WordClass.ARTICLE: "det",
    WordClass.PREPOSITION: "adp",
    WordClass.CONJUNCTION: "conj",
    WordClass.PRONOUN: "pron",
    WordClass.ADVERB: "adv",
    WordClass.AUXILIARY: "aux",
    WordClass.CONNECTOR: "adv",
    WordClass.DISCOURSE_MARKER: "adv",
}

FEATURE_KEYS: tuple[str, ...] = ("pos", "gender", "number", "person", "tense", "mood")

_RESOURCE_FILES: tuple[tuple[WordClass, str], ...] = (
    (WordClass.ARTICLE, "lexicon/articles.yaml"),
    (WordClass.PREPOSITION, "lexicon/preposicions.yaml"),
    (WordClass.CONJUNCTION, "lexicon/conjuncions.yaml"),
    (WordClass.PRONOUN, "lexicon/pronoms.yaml"),
    (WordClass.ADVERB, "lexicon/adverbis.yaml"),
    (WordClass.AUXILIARY, "lexicon/auxiliars.yaml"),
    (WordClass.DISCOURSE_MARKER, "lexicon/marcadors_discursius.yaml"),
)
_CONNECTORS_FILE = "connectors/connectors.yaml"


def normalize_form(form: str) -> str:
    """Forma canònica per a les cerques: minúscules, apòstrof recte, un sol espai."""
    return " ".join(form.strip().lower().replace("’", "'").split())


@dataclass(frozen=True, slots=True)
class LexiconEntry:
    """Una forma d'una classe tancada amb la seva informació gramatical.

    Atributs:
        form: Forma tal com apareix al text (pot ser multiparaula).
        lemma: Lema o forma de referència.
        word_class: Classe del lexicó d'on prové.
        features: Trets gramaticals com a parells (clau, valor): pos, gender, number,
            person, tense, mood.
        subtype: Subtipus lliure (definit, contracció, feble, modal, coordinant...).
        canonical: Per als pronoms febles, la forma canònica (em, et, es, el...).
        parts: Per a les contraccions, els components (dels → de, els).
        function: Funció discursiva (contrast, addició, reformulació...).
        register: Registre (col·loquial, neutre, formal).
        origin: Origen, si és rellevant (p. ex. «llatí»).
        note: Observació lliure.
    """

    form: str
    lemma: str
    word_class: WordClass
    features: tuple[tuple[str, str], ...] = ()
    subtype: str = ""
    canonical: str = ""
    parts: tuple[str, ...] = ()
    function: str = ""
    register: str = ""
    origin: str = ""
    note: str = ""

    @property
    def is_multiword(self) -> bool:
        return " " in self.form.strip()

    @property
    def feature_dict(self) -> dict[str, str]:
        return dict(self.features)

    def feature(self, key: str) -> str | None:
        return self.feature_dict.get(key)

    @property
    def pos(self) -> str:
        return self.feature("pos") or self.word_class.default_pos

    def to_dict(self) -> dict[str, object]:
        return {
            "form": self.form,
            "lemma": self.lemma,
            "word_class": self.word_class.value,
            "features": self.feature_dict,
            "subtype": self.subtype,
            "canonical": self.canonical,
            "parts": list(self.parts),
            "function": self.function,
            "register": self.register,
            "origin": self.origin,
            "note": self.note,
        }


class ClosedClassLexicon:
    """Conjunt d'entrades de classes tancades amb cerca per forma."""

    def __init__(self, entries: Iterable[LexiconEntry] = ()) -> None:
        self._entries: tuple[LexiconEntry, ...] = tuple(entries)
        self._by_form: dict[str, list[LexiconEntry]] = defaultdict(list)
        self._by_class: dict[WordClass, list[LexiconEntry]] = defaultdict(list)
        for entry in self._entries:
            self._by_form[normalize_form(entry.form)].append(entry)
            self._by_class[entry.word_class].append(entry)
        self._multiword: tuple[LexiconEntry, ...] = tuple(
            sorted((e for e in self._entries if e.is_multiword), key=lambda e: -len(e.form))
        )
        self._multiword_patterns: tuple[tuple[LexiconEntry, re.Pattern[str]], ...] | None = None

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> tuple[LexiconEntry, ...]:
        return self._entries

    def lookup(self, form: str) -> tuple[LexiconEntry, ...]:
        """Entrades que coincideixen amb la forma (sense distingir majúscules)."""
        return tuple(self._by_form.get(normalize_form(form), ()))

    def has(self, form: str) -> bool:
        return normalize_form(form) in self._by_form

    def classes_of(self, form: str) -> frozenset[WordClass]:
        return frozenset(entry.word_class for entry in self.lookup(form))

    def of_class(self, word_class: WordClass) -> tuple[LexiconEntry, ...]:
        return tuple(self._by_class.get(word_class, ()))

    def forms_of(self, word_class: WordClass) -> frozenset[str]:
        """Formes normalitzades d'una classe (útil per a conjunts de consulta ràpida)."""
        return frozenset(normalize_form(e.form) for e in self.of_class(word_class))

    @property
    def single_word_forms(self) -> frozenset[str]:
        return frozenset(key for key in self._by_form if " " not in key)

    @property
    def multiword_entries(self) -> tuple[LexiconEntry, ...]:
        """Entrades de més d'una paraula, de més llarga a més curta."""
        return self._multiword

    def multiword_patterns(self) -> tuple[tuple[LexiconEntry, re.Pattern[str]], ...]:
        """Patrons compilats de les expressions multiparaula (es calculen un sol cop)."""
        if self._multiword_patterns is None:
            self._multiword_patterns = tuple(
                (entry, phrase_pattern(entry.form)) for entry in self._multiword
            )
        return self._multiword_patterns

    @classmethod
    def empty(cls) -> ClosedClassLexicon:
        return cls(())

    @classmethod
    def load(cls, lang_dir: str | Path) -> ClosedClassLexicon:
        """Carrega tots els recursos de classes tancades presents a ``lang_dir``.

        Els fitxers absents s'ometen: el lexicó pot ser parcial.
        """
        base = Path(lang_dir)
        entries: list[LexiconEntry] = []
        for word_class, relative in _RESOURCE_FILES:
            file = base / relative
            if file.is_file():
                entries.extend(entries_from_mapping(load_mapping(file), word_class))
        connectors = base / _CONNECTORS_FILE
        if connectors.is_file():
            entries.extend(connector_entries_from_mapping(load_mapping(connectors)))
        return cls(entries)


def entries_from_mapping(data: Mapping[str, object], word_class: WordClass) -> list[LexiconEntry]:
    """Construeix entrades a partir del contingut d'un recurs de classe tancada.

    Format::

        description: ...
        pos: det                      # pos per defecte de les entrades (opcional)
        entries:
          - form: dels
            lemma: de+el             # opcional (per defecte, la forma)
            variants: [dels]         # formes addicionals amb la mateixa informació
            gender: m                # gender, number, person, tense, mood (opcionals)
            number: pl
            persons: ["1", "3"]      # forma compartida: una entrada per persona
            subtype: contracció
            parts: [de, els]
            canonical: ""            # pronoms febles
            function: ""             # connectors i marcadors
            register: ""
            origin: ""
            note: ""
    """
    default_pos = as_str(data, "pos", word_class.default_pos)
    entries: list[LexiconEntry] = []
    for item in as_mapping_list(data, "entries"):
        form = as_str(item, "form")
        forms = [form, *as_str_list(item, "variants")]
        lemma = as_str(item, "lemma", form)
        features: list[tuple[str, str]] = [("pos", as_str(item, "pos", default_pos))]
        for key in FEATURE_KEYS[1:]:
            if key != "person" and item.get(key) is not None:
                features.append((key, as_str(item, key)))
        # «persons: ["1", "3"]» expandeix una forma compartida (havia) en una entrada per persona.
        persons: list[str | None] = list(as_str_list(item, "persons")) or [
            as_str(item, "person") if item.get("person") is not None else None
        ]
        for variant in forms:
            for person in persons:
                entry_features = list(features)
                if person is not None:
                    entry_features.append(("person", person))
                entries.append(
                    LexiconEntry(
                        form=variant.strip(),
                        lemma=lemma,
                        word_class=word_class,
                        features=tuple(entry_features),
                        subtype=as_str(item, "subtype", ""),
                        canonical=as_str(item, "canonical", ""),
                        parts=as_str_list(item, "parts"),
                        function=as_str(item, "function", ""),
                        register=as_str(item, "register", ""),
                        origin=as_str(item, "origin", ""),
                        note=as_str(item, "note", ""),
                    )
                )
    return entries


def connector_entries_from_mapping(data: Mapping[str, object]) -> list[LexiconEntry]:
    """Construeix entrades de connector a partir de ``connectors.yaml`` (grups per funció)."""
    entries: list[LexiconEntry] = []
    for group in as_mapping_list(data, "groups"):
        function = as_str(group, "function", "")
        for connector in as_mapping_list(group, "connectors"):
            form = as_str(connector, "form").strip()
            entries.append(
                LexiconEntry(
                    form=form,
                    lemma=form,
                    word_class=WordClass.CONNECTOR,
                    features=(("pos", as_str(connector, "pos", WordClass.CONNECTOR.default_pos)),),
                    subtype="connector",
                    function=function,
                    register=as_str(connector, "register", ""),
                    origin=as_str(connector, "origin", ""),
                    note=as_str(connector, "note", ""),
                )
            )
    return entries
