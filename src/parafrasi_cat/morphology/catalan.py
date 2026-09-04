"""Proveïdor morfològic català sobre el recurs importat de Softcatalà.

El recurs és una base SQLite que genera ``scripts/import_softcatala.py`` a
partir de https://github.com/Softcatala/catalan-dict-tools. Conté una fila per
forma flexionada amb el lema i els trets ja convertits, de manera que
l'anàlisi i la generació són consultes indexades: no cal carregar el
diccionari a memòria ni endevinar res.

Principis:

- **Mai no inventa formes.** Si el recurs no coneix una forma o un lema, es
  retorna buit i el motor recorre al mapatge explícit o a l'endevinador.
- **Determinista.** Totes les consultes porten un ordre explícit, de manera
  que la mateixa pregunta dona sempre la mateixa resposta.
- **Local.** És un fitxer d'aquest ordinador; no hi ha cap consulta remota.

El recurs no es versiona: les dades de Softcatalà són copyleft. Vegeu
``docs/recursos-linguistics.md``.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path

from parafrasi_cat.core.errors import ResourceError
from parafrasi_cat.morphology.features import LexicalEntry, MorphFeatures
from parafrasi_cat.morphology.provider import inflect_like

SOURCE = "softcatala"
RESOURCE_RELATIVE = "morphology/generated/catala.sqlite"
"""Ruta del recurs dins del directori de llengua (``resources/ca/``)."""

DEFAULT_RESOURCE = f"resources/ca/{RESOURCE_RELATIVE}"
"""Ruta del recurs des de l'arrel del projecte."""

#: Ordre de preferència dels modes quan una forma és ambigua. És explícit
#: perquè la tria no depengui de l'ordre alfabètic de les etiquetes.
_MOOD_ORDER = ("ind", "subj", "imp", "inf", "ger", "part")

_FEATURE_COLUMNS = ("pos", "gender", "number", "person", "tense", "mood")

#: Variant general del diccionari. Les altres («V» valencià, «B» balear i les
#: formes secundàries) es coneixen igualment, però no es proposen mai primer.
STANDARD_VARIANT = "0"

_VARIANT_ORDER = f"CASE WHEN variant = '{STANDARD_VARIANT}' THEN 0 ELSE 1 END"

_MOOD_CASE = (
    "CASE mood "
    + " ".join(f"WHEN '{mood}' THEN {index}" for index, mood in enumerate(_MOOD_ORDER))
    + " ELSE 99 END"
)


class CatalanMorphology:
    """Analitzador i generador morfològic català basat en el recurs de Softcatalà."""

    def __init__(self, path: str | Path) -> None:
        file = Path(path)
        if not file.is_file():
            raise ResourceError(f"No s'ha trobat el recurs morfològic «{file}»")
        self._path = file
        self._local = threading.local()
        try:
            self._metadata = {
                str(key): str(value)
                for key, value in self._connection().execute("SELECT key, value FROM metadata")
            }
            row = self._connection().execute("SELECT COUNT(*) FROM entries").fetchone()
        except sqlite3.Error as exc:
            raise ResourceError(f"El recurs morfològic «{file}» no és llegible: {exc}") from exc
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
        """Origen, commit, data i llicència de les dades importades."""
        return dict(self._metadata)

    def __len__(self) -> int:
        return self._count

    def describe(self) -> str:
        origin = self._metadata.get("source_repository", "?")
        commit = self._metadata.get("source_commit", "?")[:12]
        return f"{self._count} formes de {origin} @ {commit}"

    # -- anàlisi -----------------------------------------------------------------------------

    def analyze(self, form: str) -> tuple[LexicalEntry, ...]:
        """Anàlisis possibles d'una forma, de la més probable a la menys.

        Buit si el recurs no la coneix: el motor ha de recórrer al fallback.
        """
        key = form.strip().lower()
        if not key:
            return ()
        rows = self._connection().execute(
            "SELECT form, lemma, pos, gender, number, person, tense, mood FROM entries "
            f"WHERE form = ? ORDER BY {_VARIANT_ORDER}, {_MOOD_CASE}, pos, lemma, tag",
            (key,),
        )
        return tuple(
            LexicalEntry(
                form=row[0],
                lemma=row[1],
                features=MorphFeatures(
                    pos=row[2],
                    gender=row[3],
                    number=row[4],
                    person=row[5],
                    tense=row[6],
                    mood=row[7],
                ),
                confidence=1.0,
                source=SOURCE,
            )
            for row in rows
        )

    def lemma(self, form: str, pos: str | None = None) -> str | None:
        """Lema més probable d'una forma, o ``None`` si el recurs no la coneix."""
        for entry in self.analyze(form):
            if pos is None or entry.features.pos == pos:
                return entry.lemma
        return None

    def features(self, form: str, pos: str | None = None) -> MorphFeatures | None:
        """Trets de l'anàlisi més probable, o ``None`` si la forma és desconeguda."""
        for entry in self.analyze(form):
            if pos is None or entry.features.pos == pos:
                return entry.features
        return None

    def knows(self, form: str) -> bool:
        return bool(self.analyze(form))

    # -- generació ---------------------------------------------------------------------------

    def generate(self, lemma: str, features: MorphFeatures) -> tuple[str, ...]:
        """Formes del lema compatibles amb els trets indicats, sense inventar-ne cap."""
        key = lemma.strip().lower()
        if not key:
            return ()
        conditions = ["lemma = ?"]
        values: list[str] = [key]
        for name in _FEATURE_COLUMNS:
            wanted = getattr(features, name)
            if wanted is not None:
                conditions.append(f"{name} = ?")
                values.append(str(wanted))
        rows = self._connection().execute(
            "SELECT form FROM entries WHERE "
            + " AND ".join(conditions)
            + f" ORDER BY {_VARIANT_ORDER}, {_MOOD_CASE}, LENGTH(form), form",
            values,
        )
        return tuple(dict.fromkeys(row[0] for row in rows))

    def inflect_like(self, form: str, lemma: str, *, pos: str | None = None) -> str | None:
        """Forma de ``lemma`` amb els mateixos trets que ``form``.

        És l'operació que fan servir les regles: «és» amb el lema «constituir»
        dona «constitueix», i «són» dona «constitueixen». Retorna ``None`` si
        el recurs no coneix la forma d'origen o no té la forma d'arribada, de
        manera que la regla pugui recórrer al seu mapatge explícit.
        """
        # Es demanen tots els trets de l'anàlisi, gènere inclòs: en un participi
        # («feta» amb el lema «realitzar» dona «realitzada») el gènere és
        # imprescindible, i en una forma finita val None i no filtra res.
        return inflect_like(self, form, lemma, pos=pos)

    def agrees(self, first: str, second: str) -> bool | None:
        """Cert si les dues formes comparteixen gènere i nombre; ``None`` si no se sap."""
        left = self.features(first)
        right = self.features(second)
        if left is None or right is None:
            return None
        for name in ("gender", "number"):
            a, b = getattr(left, name), getattr(right, name)
            if a is not None and b is not None and a != b:
                return False
        return True

    # -- càrrega -----------------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> CatalanMorphology:
        return cls(path)

    @classmethod
    def discover(
        cls, root: str | Path, relative: str = RESOURCE_RELATIVE
    ) -> CatalanMorphology | None:
        """Carrega el recurs si existeix; ``None`` si encara no s'ha importat."""
        candidate = Path(root) / relative
        if not candidate.is_file():
            return None
        try:
            return cls(candidate)
        except ResourceError:
            return None


def feature_names() -> tuple[str, ...]:
    """Noms dels trets que el recurs desa (per als informes i la interfície)."""
    return tuple(f.name for f in fields(MorphFeatures))
