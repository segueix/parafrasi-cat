"""Consulta del diccionari de sinònims català sobre el recurs local.

El recurs és una base SQLite que genera ``scripts/import_sinonims.py`` a
partir de https://github.com/Softcatala/sinonims-cat. Cada fila de
``members`` és una forma d'un **grup de significat**; la taula ``groups`` en
diu la categoria i, quan el diccionari la dona, la glossa del sentit.

Principis, els mateixos que la resta de proveïdors del projecte:

- **Mai no inventa formes.** Si el recurs no coneix una forma, es retorna buit.
- **Determinista.** Totes les consultes porten un ordre explícit.
- **Local.** És un fitxer d'aquest ordinador; no hi ha cap consulta remota.
- **Cap antònim.** No s'importen, de manera que no es poden servir.

Una paraula corrent pertany a diversos grups («ras» de cel i «ras» de
soldat). El proveïdor no en tria cap: els retorna tots, amb la glossa, perquè
qui edita vegi de quin sentit parla cadascun. Endevinar-ho seria justament el
que el projecte no fa.
"""

from __future__ import annotations

import sqlite3
import threading
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from parafrasi_cat.core.errors import ResourceError

SOURCE = "softcatala-sinonims"
RESOURCE_RELATIVE = "thesaurus/generated/sinonims.sqlite"
"""Ruta del recurs dins del directori de llengua (``resources/ca/``)."""

DEFAULT_RESOURCE = f"resources/ca/{RESOURCE_RELATIVE}"
"""Ruta del recurs des de l'arrel del projecte."""

#: Categories que el recurs distingeix, amb el nom que fa servir la morfologia.
POS_LABELS: Mapping[str, str] = {
    "noun": "nom",
    "verb": "verb",
    "adj": "adjectiu",
    "adv": "adverbi",
    "loc": "locució",
    "adp": "preposició",
    "conj": "conjunció",
    "pron": "pronom",
    "det": "determinant",
    "intj": "interjecció",
}


def normalize(form: str) -> str:
    """Forma de consulta: la mateixa normalització que fa l'importador."""
    text = unicodedata.normalize("NFC", form).strip().lower()
    text = text.replace("’", "'").replace("ʼ", "'")
    return " ".join(text.split())


@dataclass(frozen=True, slots=True)
class SynonymMember:
    """Una forma equivalent, amb el registre que el diccionari li atribueix."""

    form: str
    """Forma tal com surt al diccionari (lema o locució)."""
    register: str = ""
    """``col·loquial``, ``vulgar``, ``antic``, ``dialectal``… o buit si és neutra."""
    secondary: bool = False
    """Cert si el diccionari la posa fora del nucli del grup (equivalència més fluixa)."""

    @property
    def neutral(self) -> bool:
        return not self.register

    def to_dict(self) -> dict[str, object]:
        return {"form": self.form, "register": self.register, "secondary": self.secondary}


@dataclass(frozen=True, slots=True)
class SynonymGroup:
    """Un grup de significat: una categoria, un sentit i les formes equivalents."""

    pos: str
    sense: str
    members: tuple[SynonymMember, ...]

    @property
    def label(self) -> str:
        """Com s'anomena aquest sentit a la interfície."""
        category = " / ".join(POS_LABELS.get(part, part) for part in self.pos.split("/") if part)
        if self.sense and category:
            return f"{category} · {self.sense}"
        return self.sense or category

    def to_dict(self) -> dict[str, object]:
        return {
            "pos": self.pos,
            "sense": self.sense,
            "label": self.label,
            "members": [member.to_dict() for member in self.members],
        }


class CatalanThesaurus:
    """Grups de sinònims d'una forma, sobre el recurs local de Softcatalà."""

    def __init__(self, path: str | Path) -> None:
        file = Path(path)
        if not file.is_file():
            raise ResourceError(f"No s'ha trobat el diccionari de sinònims «{file}»")
        self._path = file
        self._local = threading.local()
        try:
            self._metadata = {
                str(key): str(value)
                for key, value in self._connection().execute("SELECT key, value FROM metadata")
            }
            row = self._connection().execute("SELECT COUNT(*) FROM groups").fetchone()
        except sqlite3.Error as exc:
            raise ResourceError(
                f"El diccionari de sinònims «{file}» no és llegible: {exc}"
            ) from exc
        self._count = int(row[0]) if row else 0

    # -- connexió (una per fil: el servidor local és multifil) -------------------------------

    def _connection(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(f"file:{self._path}?mode=ro", uri=True)
            self._local.connection = connection
        return connection

    # -- identitat ---------------------------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    @property
    def metadata(self) -> Mapping[str, str]:
        """Origen, commit, data, llicència i atribució de les dades importades."""
        return dict(self._metadata)

    def __len__(self) -> int:
        return self._count

    def describe(self) -> str:
        origin = self._metadata.get("source_repository", "?")
        forms = self._metadata.get("n_forms", "?")
        return f"{self._count} grups i {forms} formes de {origin}"

    # -- consulta ----------------------------------------------------------------------------

    def knows(self, form: str) -> bool:
        row = (
            self._connection()
            .execute("SELECT 1 FROM members WHERE form = ? LIMIT 1", (normalize(form),))
            .fetchone()
        )
        return row is not None

    def groups(self, form: str, pos: str | None = None) -> tuple[SynonymGroup, ...]:
        """Grups de significat on surt la forma, sense ella mateixa.

        ``pos`` filtra per categoria (``noun``, ``verb``, ``adj``…). Un grup
        del diccionari pot declarar més d'una categoria (``adj/noun``), de
        manera que la comparació és per pertinença, no per igualtat.
        """
        key = normalize(form)
        if not key:
            return ()
        rows = self._connection().execute(
            "SELECT g.group_id, g.pos, g.sense, m.display, m.register, m.secondary "
            "FROM members AS own "
            "JOIN groups AS g ON g.group_id = own.group_id "
            "JOIN members AS m ON m.group_id = own.group_id "
            "WHERE own.form = ? AND m.form <> ? "
            "ORDER BY g.group_id, m.secondary, m.position",
            (key, key),
        )
        collected: dict[int, tuple[str, str, list[SynonymMember]]] = {}
        for group_id, group_pos, sense, display, register, secondary in rows:
            if pos is not None and not _matches(str(group_pos), pos):
                continue
            entry = collected.setdefault(int(group_id), (str(group_pos), str(sense), []))
            entry[2].append(SynonymMember(str(display), str(register), bool(secondary)))
        return tuple(
            SynonymGroup(group_pos, sense, tuple(members))
            for group_pos, sense, members in collected.values()
            if members
        )

    # -- càrrega -----------------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> CatalanThesaurus:
        return cls(path)

    @classmethod
    def discover(
        cls, root: str | Path, relative: str = RESOURCE_RELATIVE
    ) -> CatalanThesaurus | None:
        """Carrega el recurs si hi és; ``None`` si el component no està instal·lat."""
        path = Path(root) / relative
        if not path.is_file():
            return None
        try:
            return cls(path)
        except ResourceError:
            return None


def _matches(group_pos: str, pos: str) -> bool:
    """Cert si el grup declara aquesta categoria (les compostes en declaren més d'una)."""
    return pos in group_pos.split("/")


__all__ = [
    "DEFAULT_RESOURCE",
    "POS_LABELS",
    "RESOURCE_RELATIVE",
    "SOURCE",
    "CatalanThesaurus",
    "SynonymGroup",
    "SynonymMember",
    "normalize",
]
