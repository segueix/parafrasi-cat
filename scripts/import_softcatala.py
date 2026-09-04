#!/usr/bin/env python3
"""Importa la morfologia catalana de Softcatalà a un recurs local compacte.

Font: https://github.com/Softcatala/catalan-dict-tools (doble llicència
GPL-2.0-or-later i LGPL-2.1-or-later). El fitxer d'entrada és
``resultats/lt/diccionari.txt``, que conté una línia per forma amb el format::

    presenten presentar VMIP3P00
    sarcòfags sarcòfag NCMP000

L'etiqueta és del joc EAGLES/PAROLE per al català. Aquest script la converteix
als trets de :class:`~parafrasi_cat.morphology.features.MorphFeatures` i desa el
resultat en una base SQLite indexada, amb un fitxer de metadades al costat
(origen, commit, data, llicència i recomptes).

**El recurs generat no es versiona.** Les dades de Softcatalà són copyleft i la
llicència de ``parafrasi-cat`` encara no està definida, de manera que cada
usuari se les genera localment amb aquest script. Vegeu
``docs/recursos-linguistics.md``.

Ús::

    python scripts/import_softcatala.py --source /ruta/a/catalan-dict-tools
    python scripts/import_softcatala.py --input diccionari.txt --output sortida.sqlite
    python scripts/import_softcatala.py --source ... --limit 5000   # per a proves
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SOURCE_REPOSITORY = "https://github.com/Softcatala/catalan-dict-tools"
SOURCE_FILE = "resultats/lt/diccionari.txt"
LICENSE = "GPL-2.0-or-later OR LGPL-2.1-or-later"
ATTRIBUTION = (
    "Diccionari català de Softcatalà. Copyright (C) 2013- Jaume Ortolà; "
    "Copyright (C) 2002-2008 Joan Moratinos."
)
#: Versió del format del recurs generat. Puja si canvia l'esquema o el mapatge.
RESOURCE_VERSION = 2

DEFAULT_OUTPUT = Path("resources/ca/morphology/generated/catala.sqlite")

#: Categories que interessen al motor. Els noms propis (``NP``) queden fora:
#: el motor els protegeix i no els flexiona mai, i són un terç del diccionari.
KEPT_CATEGORIES = ("NC", "A", "V", "R")

_MOOD = {"I": "ind", "S": "subj", "M": "imp", "N": "inf", "G": "ger", "P": "part"}
_TENSE = {"P": "pres", "I": "impf", "F": "fut", "S": "past", "C": "cond"}
_GENDER = {"M": "m", "F": "f"}
_NUMBER = {"S": "sg", "P": "pl"}
_PERSON = {"1": "1", "2": "2", "3": "3"}

#: Marca de variant a la darrera posició de l'etiqueta verbal: «0» és la forma
#: general i la resta són variants territorials o secundàries («V» valencià,
#: «B» balear, entre altres). Els noms i els adjectius sempre porten «0».
STANDARD_VARIANT = "0"


@dataclass(frozen=True, slots=True)
class Entry:
    """Una forma importada, ja convertida als trets del motor."""

    form: str
    lemma: str
    tag: str
    pos: str
    variant: str = STANDARD_VARIANT
    gender: str | None = None
    number: str | None = None
    person: str | None = None
    tense: str | None = None
    mood: str | None = None

    def row(self) -> tuple[str | None, ...]:
        return (
            self.form,
            self.lemma,
            self.tag,
            self.pos,
            self.variant,
            self.gender,
            self.number,
            self.person,
            self.tense,
            self.mood,
        )


def _at(tag: str, index: int) -> str:
    return tag[index] if len(tag) > index else "0"


def parse_tag(tag: str) -> tuple[str, str, dict[str, str | None]] | None:
    """Converteix una etiqueta EAGLES catalana en (categoria, variant, trets).

    Retorna ``None`` si la categoria no interessa al motor. Les posicions són
    les del joc EAGLES/PAROLE: nom ``N[tipus][gènere][nombre]``, adjectiu
    ``A[tipus][grau][gènere][nombre]`` i verb
    ``V[tipus][mode][temps][persona][nombre][gènere][variant]``.
    """
    if not tag:
        return None
    category = tag[0]
    if category == "N":
        if _at(tag, 1) != "C":
            return None  # nom propi: el motor el protegeix, no el flexiona
        return (
            "noun",
            STANDARD_VARIANT,
            {
                "gender": _GENDER.get(_at(tag, 2)),
                "number": _NUMBER.get(_at(tag, 3)),
            },
        )
    if category == "A":
        return (
            "adj",
            STANDARD_VARIANT,
            {
                "gender": _GENDER.get(_at(tag, 3)),
                "number": _NUMBER.get(_at(tag, 4)),
            },
        )
    if category == "V":
        return (
            "verb",
            _at(tag, 7),
            {
                "mood": _MOOD.get(_at(tag, 2)),
                "tense": _TENSE.get(_at(tag, 3)),
                "person": _PERSON.get(_at(tag, 4)),
                "number": _NUMBER.get(_at(tag, 5)),
                "gender": _GENDER.get(_at(tag, 6)),
            },
        )
    if category == "R":
        return "adv", STANDARD_VARIANT, {}
    return None


def read_entries(path: Path, limit: int | None = None) -> Iterator[Entry]:
    """Llegeix el diccionari original i produeix només les entrades que calen."""
    kept = 0
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            parts = raw.split()
            if len(parts) != 3:
                continue  # línies buides o formes amb espais: no les fem servir
            form, lemma, tag = parts
            parsed = parse_tag(tag)
            if parsed is None:
                continue
            pos, variant, features = parsed
            yield Entry(
                form=form,
                lemma=lemma,
                tag=tag,
                pos=pos,
                variant=variant,
                gender=features.get("gender"),
                number=features.get("number"),
                person=features.get("person"),
                tense=features.get("tense"),
                mood=features.get("mood"),
            )
            kept += 1
            if limit is not None and kept >= limit:
                return


SCHEMA = """
CREATE TABLE entries (
    form   TEXT NOT NULL,
    lemma  TEXT NOT NULL,
    tag    TEXT NOT NULL,
    pos    TEXT NOT NULL,
    variant TEXT NOT NULL,
    gender TEXT,
    number TEXT,
    person TEXT,
    tense  TEXT,
    mood   TEXT
);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

INDEXES = """
CREATE INDEX idx_entries_form ON entries(form);
CREATE INDEX idx_entries_lemma ON entries(lemma, pos);
"""


def build(
    source_file: Path, output: Path, metadata: dict[str, str], limit: int | None
) -> dict[str, object]:
    """Genera la base SQLite i retorna el resum de la importació."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    counts: Counter[str] = Counter()
    variants: Counter[str] = Counter()
    connection = sqlite3.connect(output)
    try:
        connection.executescript(SCHEMA)
        batch: list[tuple[str | None, ...]] = []
        for entry in read_entries(source_file, limit):
            counts[entry.pos] += 1
            variants[entry.variant] += 1
            batch.append(entry.row())
            if len(batch) >= 50_000:
                connection.executemany("INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
                batch.clear()
        if batch:
            connection.executemany("INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
        connection.executescript(INDEXES)
        summary = {
            **metadata,
            "resource_version": str(RESOURCE_VERSION),
            "n_entries": str(sum(counts.values())),
            "n_standard": str(variants[STANDARD_VARIANT]),
            **{f"n_{pos}": str(n) for pos, n in sorted(counts.items())},
        }
        connection.executemany(
            "INSERT INTO metadata (key, value) VALUES (?,?)", sorted(summary.items())
        )
        connection.commit()
        connection.execute("VACUUM")
        connection.commit()
    finally:
        connection.close()
    return {
        **summary,
        "n_by_pos": dict(sorted(counts.items())),
        "n_by_variant": dict(sorted(variants.items())),
    }


def source_commit(source: Path) -> str:
    """Commit del checkout de Softcatalà, per poder reproduir la importació."""
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return "desconegut"
    return result.stdout.strip() or "desconegut"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="import_softcatala",
        description=(
            "Importa la morfologia catalana de Softcatalà a un recurs SQLite local. "
            "El recurs generat no es versiona: les dades són copyleft i cada usuari "
            "se les genera a partir del repositori original."
        ),
        epilog=f"Font: {SOURCE_REPOSITORY} · Llicència: {LICENSE}",
    )
    parser.add_argument(
        "-s", "--source", type=Path, metavar="DIR", help="checkout de catalan-dict-tools"
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        metavar="FITXER",
        help=f"fitxer concret (per defecte {SOURCE_FILE})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="FITXER",
        help=f"base de dades de sortida (per defecte {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "-l", "--limit", type=int, metavar="N", help="importa només N entrades (proves)"
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="no escriguis el resum")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.input is not None:
        source_file = args.input
        commit = source_commit(args.source) if args.source else "desconegut"
    elif args.source is not None:
        source_file = args.source / SOURCE_FILE
        commit = source_commit(args.source)
    else:
        print(
            "Cal indicar --source (checkout de catalan-dict-tools) o --input (fitxer).",
            file=sys.stderr,
        )
        return 2
    if not source_file.is_file():
        print(f"No s'ha trobat el fitxer d'entrada: {source_file}", file=sys.stderr)
        return 1

    metadata = {
        "source_repository": SOURCE_REPOSITORY,
        "source_file": SOURCE_FILE if args.input is None else str(args.input),
        "source_commit": commit,
        "license": LICENSE,
        "attribution": ATTRIBUTION,
        "imported_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    summary = build(source_file, args.output, metadata, args.limit)

    sidecar = args.output.with_suffix(".metadata.json")
    sidecar.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.quiet:
        size = args.output.stat().st_size / 1_000_000
        print(f"Recurs generat: {args.output} ({size:.1f} MB)")
        print(f"Metadades: {sidecar}")
        print(f"Entrades: {summary['n_entries']} · per categoria: {summary['n_by_pos']}")
        print(f"Origen: {SOURCE_REPOSITORY} @ {commit}")
        print(f"Llicència de les dades: {LICENSE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
