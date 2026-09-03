"""Diccionaris terminològics editables per projecte.

Un diccionari (``dictionaries/<nom>.yml``) és una llista d'entrades::

    description: Terminologia d'història de l'art.
    language: ca
    confidence: 0.8            # opcional: confiança de les substitucions
    entries:
      - term: sarcòfag
        preferred: [sarcòfag]
        accepted: [sarcòfag funerari]
        avoid: [fèretre]
        protected: true
        pos: nom
        notes: "No substituir en contextos arqueològics."

- ``preferred``: formes que el motor ha de fer servir (la primera substitueix
  les formes a evitar); per defecte, el terme mateix;
- ``accepted``: formes tolerades, que ni es proposen ni es penalitzen;
- ``avoid``: formes que cal evitar: es proposa substituir-les per la forma
  preferida i es penalitza qualsevol candidat que les introdueixi;
- ``protected``: cap regla pot modificar el terme ni les seves formes
  preferides o acceptades;
- ``pos`` i ``notes``: informació que s'afegeix a les explicacions.

Diversos diccionaris es poden activar alhora (:class:`DictionarySet`). La
protecció és acumulativa; si dos diccionaris classifiquen una mateixa forma
de manera diferent, mana el primer de la llista d'activació i el conflicte
queda registrat (:meth:`DictionarySet.conflicts`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.core.text import normalize_apostrophes
from parafrasi_cat.resources import (
    as_bool,
    as_float,
    as_mapping_list,
    as_str,
    as_str_list,
    load_mapping,
)

DEFAULT_CONFIDENCE = 0.8

_ENTRY_KEYS = frozenset({"term", "preferred", "accepted", "avoid", "protected", "pos", "notes"})
_DICTIONARY_KEYS = frozenset({"name", "description", "language", "confidence", "entries"})


def normalize_term(form: str) -> str:
    """Clau canònica d'una forma: minúscules, apòstrof recte, un sol espai."""
    return " ".join(normalize_apostrophes(form).lower().split())


def _clean(forms: Iterable[str]) -> tuple[str, ...]:
    """Normalitza els espais i elimina els duplicats (sense distingir majúscules)."""
    result: list[str] = []
    seen: set[str] = set()
    for form in forms:
        text = " ".join(str(form).split())
        key = normalize_term(text)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return tuple(result)


class FormStatus(StrEnum):
    """Classificació d'una forma dins d'un diccionari."""

    PREFERRED = "preferred"
    ACCEPTED = "accepted"
    AVOID = "avoid"

    @property
    def weight(self) -> float:
        """Pes amb signe: +1 preferida, 0 acceptada, −1 a evitar."""
        return _STATUS_WEIGHTS[self]

    @property
    def label(self) -> str:
        return _STATUS_LABELS[self]


_STATUS_WEIGHTS: dict[FormStatus, float] = {
    FormStatus.PREFERRED: 1.0,
    FormStatus.ACCEPTED: 0.0,
    FormStatus.AVOID: -1.0,
}
_STATUS_LABELS: dict[FormStatus, str] = {
    FormStatus.PREFERRED: "forma preferida",
    FormStatus.ACCEPTED: "forma acceptada",
    FormStatus.AVOID: "forma a evitar",
}


@dataclass(frozen=True, slots=True)
class DictionaryEntry:
    """Una entrada d'un diccionari terminològic.

    Atributs:
        term: Terme canònic.
        preferred: Formes que cal fer servir (per defecte, el terme).
        accepted: Formes tolerades.
        avoid: Formes que cal evitar.
        protected: Si és cert, cap regla pot modificar el terme ni les formes conservades.
        pos: Categoria gramatical (informativa).
        notes: Explicació que s'afegeix a les justificacions.
    """

    term: str
    preferred: tuple[str, ...] = ()
    accepted: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    protected: bool = False
    pos: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        term = " ".join(self.term.split())
        if not term:
            raise ConfigError("Una entrada de diccionari necessita un «term» no buit")
        preferred = _clean(self.preferred) or (term,)
        accepted = _clean(self.accepted)
        avoid = _clean(self.avoid)
        kept = {normalize_term(f) for f in (term, *preferred, *accepted)}
        clash = [f for f in avoid if normalize_term(f) in kept]
        if clash:
            raise ConfigError(
                f"L'entrada «{term}» té formes alhora a evitar i a conservar: {clash}"
            )
        object.__setattr__(self, "term", term)
        object.__setattr__(self, "preferred", preferred)
        object.__setattr__(self, "accepted", accepted)
        object.__setattr__(self, "avoid", avoid)
        object.__setattr__(self, "pos", " ".join(self.pos.split()))
        object.__setattr__(self, "notes", " ".join(self.notes.split()))

    @property
    def preferred_form(self) -> str:
        """Forma que substitueix les formes a evitar."""
        return self.preferred[0]

    @property
    def kept_forms(self) -> tuple[str, ...]:
        """Terme, formes preferides i formes acceptades."""
        return _clean((self.term, *self.preferred, *self.accepted))

    @property
    def protected_forms(self) -> tuple[str, ...]:
        return self.kept_forms if self.protected else ()

    @property
    def forms(self) -> tuple[str, ...]:
        """Totes les formes sobre les quals l'entrada té una opinió."""
        return _clean((*self.kept_forms, *self.avoid))

    def status_of(self, form: str) -> FormStatus | None:
        key = normalize_term(form)
        if key == normalize_term(self.term) or key in {normalize_term(f) for f in self.preferred}:
            return FormStatus.PREFERRED
        if key in {normalize_term(f) for f in self.accepted}:
            return FormStatus.ACCEPTED
        if key in {normalize_term(f) for f in self.avoid}:
            return FormStatus.AVOID
        return None

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> DictionaryEntry:
        unknown = sorted(set(data) - _ENTRY_KEYS)
        if unknown:
            term = data.get("term", "?")
            raise ConfigError(f"Claus desconegudes a l'entrada «{term}»: {unknown}")
        return cls(
            term=as_str(data, "term"),
            preferred=as_str_list(data, "preferred"),
            accepted=as_str_list(data, "accepted"),
            avoid=as_str_list(data, "avoid"),
            protected=as_bool(data, "protected", False),
            pos=as_str(data, "pos", ""),
            notes=as_str(data, "notes", ""),
        )

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"term": self.term, "preferred": list(self.preferred)}
        if self.accepted:
            data["accepted"] = list(self.accepted)
        if self.avoid:
            data["avoid"] = list(self.avoid)
        if self.protected:
            data["protected"] = True
        if self.pos:
            data["pos"] = self.pos
        if self.notes:
            data["notes"] = self.notes
        return data

    def describe(self) -> str:
        parts = [f"«{self.term}»"]
        if self.pos:
            parts.append(f"({self.pos})")
        parts.append("preferida: " + ", ".join(self.preferred))
        if self.accepted:
            parts.append("· acceptada: " + ", ".join(self.accepted))
        if self.avoid:
            parts.append("· a evitar: " + ", ".join(self.avoid))
        if self.protected:
            parts.append("[protegit]")
        if self.notes:
            parts.append(f"— {self.notes}")
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class Substitution:
    """Una substitució «forma a evitar → forma preferida» que proposa un diccionari."""

    source: str
    target: str
    entry: DictionaryEntry
    dictionary: str
    confidence: float = DEFAULT_CONFIDENCE


@dataclass(frozen=True, slots=True)
class TermDictionary:
    """Un diccionari terminològic carregat d'un fitxer (o construït en memòria)."""

    name: str
    entries: tuple[DictionaryEntry, ...] = ()
    description: str = ""
    language: str = "ca"
    confidence: float = DEFAULT_CONFIDENCE
    path: Path | None = None
    _index: dict[str, tuple[DictionaryEntry, FormStatus]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ConfigError("Un diccionari necessita un nom")
        if not 0.0 <= self.confidence <= 1.0:
            raise ConfigError(f"La confiança del diccionari «{self.name}» ha d'estar entre 0 i 1")
        for entry in self.entries:
            for form in entry.forms:
                status = entry.status_of(form)
                assert status is not None
                key = normalize_term(form)
                previous = self._index.get(key)
                if previous is not None and previous[1] is not status:
                    raise ConfigError(
                        f"El diccionari «{self.name}» classifica «{form}» de dues maneres: "
                        f"«{previous[0].term}» ({previous[1].label}) i «{entry.term}» "
                        f"({status.label})"
                    )
                self._index.setdefault(key, (entry, status))

    @property
    def forms(self) -> tuple[str, ...]:
        return _clean(form for entry in self.entries for form in entry.forms)

    def lookup(self, form: str) -> tuple[DictionaryEntry, FormStatus] | None:
        return self._index.get(normalize_term(form))

    def entry_for(self, form: str) -> DictionaryEntry | None:
        found = self.lookup(form)
        return None if found is None else found[0]

    def status_of(self, form: str) -> FormStatus | None:
        found = self.lookup(form)
        return None if found is None else found[1]

    @property
    def protected_terms(self) -> tuple[str, ...]:
        return _clean(form for entry in self.entries for form in entry.protected_forms)

    def is_protected(self, form: str) -> bool:
        return normalize_term(form) in {normalize_term(t) for t in self.protected_terms}

    @property
    def substitutions(self) -> tuple[Substitution, ...]:
        """Substitucions «a evitar → preferida» (les formes protegides mai no se substitueixen)."""
        result: list[Substitution] = []
        for entry in self.entries:
            for form in entry.avoid:
                if self.is_protected(form):
                    continue
                result.append(
                    Substitution(form, entry.preferred_form, entry, self.name, self.confidence)
                )
        return tuple(result)

    @classmethod
    def from_mapping(
        cls, data: Mapping[str, object], *, name: str, path: Path | None = None
    ) -> TermDictionary:
        unknown = sorted(set(data) - _DICTIONARY_KEYS)
        if unknown:
            raise ConfigError(f"Claus desconegudes al diccionari «{name}»: {unknown}")
        return cls(
            name=as_str(data, "name", name),
            entries=tuple(
                DictionaryEntry.from_mapping(item) for item in as_mapping_list(data, "entries")
            ),
            description=as_str(data, "description", ""),
            language=as_str(data, "language", "ca"),
            confidence=as_float(data, "confidence", DEFAULT_CONFIDENCE),
            path=path,
        )

    @classmethod
    def load(cls, path: str | Path) -> TermDictionary:
        file = Path(path)
        return cls.from_mapping(load_mapping(file), name=file.stem, path=file)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "language": self.language,
            "confidence": self.confidence,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def summary(self) -> str:
        lines = [f"Diccionari «{self.name}»: {len(self.entries)} entrades"]
        if self.description:
            lines.append(f"  {self.description}")
        lines.extend(f"  - {entry.describe()}" for entry in self.entries)
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class DictionaryMatch:
    """Resultat d'una cerca en un conjunt de diccionaris."""

    dictionary: TermDictionary
    entry: DictionaryEntry
    status: FormStatus


@dataclass(frozen=True, slots=True)
class DictionaryConflict:
    """Una forma que dos diccionaris actius classifiquen de manera diferent."""

    form: str
    statuses: tuple[tuple[str, FormStatus], ...]

    def describe(self) -> str:
        listed = ", ".join(f"{name}: {status.label}" for name, status in self.statuses)
        return f"«{self.form}» — {listed} (mana «{self.statuses[0][0]}»)"


@dataclass(frozen=True, slots=True)
class DictionarySet:
    """Diccionaris actius alhora, en ordre de prioritat."""

    dictionaries: tuple[TermDictionary, ...] = ()

    def __post_init__(self) -> None:
        names = [d.name for d in self.dictionaries]
        if len(names) != len(set(names)):
            raise ConfigError(f"Hi ha diccionaris amb el mateix nom activats alhora: {names}")

    def __bool__(self) -> bool:
        return bool(self.dictionaries)

    def __len__(self) -> int:
        return len(self.dictionaries)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(d.name for d in self.dictionaries)

    @property
    def forms(self) -> tuple[str, ...]:
        return _clean(form for d in self.dictionaries for form in d.forms)

    def lookup(self, form: str) -> DictionaryMatch | None:
        """Primer diccionari (per ordre d'activació) que classifica la forma."""
        for dictionary in self.dictionaries:
            found = dictionary.lookup(form)
            if found is not None:
                return DictionaryMatch(dictionary, found[0], found[1])
        return None

    def status_of(self, form: str) -> FormStatus | None:
        match = self.lookup(form)
        return None if match is None else match.status

    @property
    def protected_terms(self) -> tuple[str, ...]:
        return _clean(term for d in self.dictionaries for term in d.protected_terms)

    def protecting(self, form: str) -> TermDictionary | None:
        """Diccionari que protegeix la forma (el primer, si n'hi ha més d'un)."""
        return next((d for d in self.dictionaries if d.is_protected(form)), None)

    def is_protected(self, form: str) -> bool:
        return self.protecting(form) is not None

    @property
    def substitutions(self) -> tuple[Substitution, ...]:
        """Una substitució per forma a evitar; mana el primer diccionari i la protecció."""
        result: list[Substitution] = []
        seen: set[str] = set()
        for dictionary in self.dictionaries:
            for substitution in dictionary.substitutions:
                key = normalize_term(substitution.source)
                if key in seen:
                    continue
                seen.add(key)
                if self.is_protected(substitution.source):
                    continue
                if self.status_of(substitution.source) is not FormStatus.AVOID:
                    continue  # un diccionari anterior la classifica d'una altra manera
                result.append(substitution)
        return tuple(result)

    def conflicts(self) -> tuple[DictionaryConflict, ...]:
        """Formes que els diccionaris actius classifiquen de manera diferent."""
        result: list[DictionaryConflict] = []
        for form in self.forms:
            statuses: list[tuple[str, FormStatus]] = []
            for dictionary in self.dictionaries:
                status = dictionary.status_of(form)
                if status is not None:
                    statuses.append((dictionary.name, status))
            if len({status for _, status in statuses}) > 1:
                result.append(DictionaryConflict(form, tuple(statuses)))
        return tuple(result)

    @classmethod
    def load(cls, files: Iterable[str | Path]) -> DictionarySet:
        return cls(tuple(TermDictionary.load(file) for file in files))

    def summary(self) -> str:
        if not self.dictionaries:
            return "Cap diccionari actiu"
        lines = ["Diccionaris actius: " + ", ".join(self.names)]
        lines.extend(d.summary() for d in self.dictionaries)
        conflicts = self.conflicts()
        if conflicts:
            lines.append("Conflictes entre diccionaris (mana el primer):")
            lines.extend(f"  - {conflict.describe()}" for conflict in conflicts)
        return "\n".join(lines)
