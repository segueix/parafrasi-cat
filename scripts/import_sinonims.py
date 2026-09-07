#!/usr/bin/env python3
"""Converteix el diccionari de sinònims de Softcatalà en un recurs local consultable.

Font: https://github.com/Softcatala/sinonims-cat (fitxer ``dict/sinonims.txt``).
Les dades són **CC-BY 4.0**; el programari del repositori d'origen és GPL-2.0.
Aquest projecte no distribueix les dades: cada usuari se les baixa i genera el
recurs a casa, de manera que l'atribució queda on toca.

Format d'origen, una línia per grup de significat::

    -adj (cel): ras, serè, clar, sense núvols, ennuvolat (antònim)
    -n: casa, habitatge, domicili # xamba (col·loquial)

- ``-<categoria>`` pot ser composta (``adj/n``).
- El parèntesi immediatament posterior, si n'hi ha, és la **glossa del sentit**.
- Cada membre pot dur un marcador entre parèntesis: registre (``col·loquial``,
  ``vulgar``, ``pejoratiu``, ``antic``…), gènere (``NOFEM``, ``FEM …``) o
  àmbit (``dret``, ``música``…).
- ``#`` separa el nucli del grup de les formes més allunyades o marcades.

Dues decisions de contingut, preses aquí i no a la consulta:

1. **Els antònims no s'importen.** Un antònim és el contrari, no un
   equivalent: guardar-lo seria posar a l'abast del motor una substitució que
   inverteix el sentit del text. El projecte no pot oferir-la mai, ni tan sols
   marcada.
2. **El registre es conserva com a dada**, no com a filtre. Qui consulta
   decideix; aquí només s'anota si una forma és col·loquial, vulgar, antiga o
   dialectal, perquè la interfície ho pugui dir a qui tria.

Ús::

    python scripts/import_sinonims.py --source dict/sinonims.txt
    python scripts/import_sinonims.py --source <fitxer> --output <sqlite>
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SOURCE_REPOSITORY = "https://github.com/Softcatala/sinonims-cat"
SOURCE_FILE = "dict/sinonims.txt"
LICENSE = "CC-BY-4.0 (dades) · GPL-2.0 (programari d'origen)"
ATTRIBUTION = (
    "Diccionari de sinònims de Softcatalà (autor principal: Jaume Ortolà i Font), "
    "llicència Creative Commons CC-BY 4.0."
)
DEFAULT_OUTPUT = Path("resources/ca/thesaurus/generated/sinonims.sqlite")

#: Marcador que exclou una forma del recurs: no és un equivalent, és el contrari.
ANTONYM = "antònim"

#: Marcadors de registre que es conserven com a avís per a qui tria.
REGISTERS: dict[str, str] = {
    "col·loquial": "col·loquial",
    "colloquial": "col·loquial",
    "vulgar": "vulgar",
    "pejoratiu": "pejoratiu",
    "despectiu": "pejoratiu",
    "infantil": "infantil",
    "antic": "antic",
    "arcaic": "antic",
    "ort. pre-2017": "ortografia antiga",
    "anglès": "manlleu",
    "castellà": "manlleu",
    "francès": "manlleu",
    "valencià": "dialectal",
    "mallorquí": "dialectal",
    "menorquí": "dialectal",
    "eivissenc": "dialectal",
    "balear": "dialectal",
    "occidental": "dialectal",
    "rossellonès": "dialectal",
    "alguerès": "dialectal",
    "onomatopeia": "onomatopeia",
}

#: Categories que el recurs reconeix, amb el nom que fa servir la morfologia
#: (les mateixes etiquetes que ``MorphFeatures.pos``, d'inspiració UD).
POS_MAP: dict[str, str] = {
    "n": "noun",
    "m": "noun",
    "f": "noun",
    "v": "verb",
    "adj": "adj",
    "adv": "adv",
    "loc": "loc",
    "prep": "adp",
    "conj": "conj",
    "pron": "pron",
    "det": "det",
    "indef": "det",
    "ij": "intj",
}

_HEAD = re.compile(r"^-(?P<pos>[a-zA-Z/]+)\s*(?:\((?P<sense>[^)]*)\))?\s*:\s*(?P<body>.*)$")
_MARKER = re.compile(r"\s*\(([^)]*)\)\s*$")

SCHEMA = """
CREATE TABLE groups (
    group_id INTEGER PRIMARY KEY,
    pos TEXT NOT NULL,
    sense TEXT NOT NULL DEFAULT ''
);
CREATE TABLE members (
    group_id INTEGER NOT NULL REFERENCES groups(group_id),
    form TEXT NOT NULL,
    display TEXT NOT NULL,
    register TEXT NOT NULL DEFAULT '',
    secondary INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL
);
CREATE INDEX members_form ON members(form);
CREATE INDEX members_group ON members(group_id);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def normalize(form: str) -> str:
    """Forma de consulta: minúscules, apòstrofs rectes i espais simples."""
    text = unicodedata.normalize("NFC", form).strip().lower()
    text = text.replace("’", "'").replace("ʼ", "'")
    return " ".join(text.split())


@dataclass(frozen=True, slots=True)
class Member:
    """Una forma d'un grup de significat, amb el seu marcador."""

    form: str
    display: str
    register: str
    secondary: bool


@dataclass(frozen=True, slots=True)
class Group:
    """Un grup de significat: una categoria, una glossa opcional i les seves formes."""

    pos: str
    sense: str
    members: tuple[Member, ...]


def split_members(body: str) -> Iterator[tuple[str, bool]]:
    """Membres del grup en ordre, dient si són darrere del ``#`` (formes allunyades)."""
    for secondary, chunk in enumerate(body.split("#")):
        for raw in chunk.split(","):
            text = raw.strip()
            if text and text != "...":
                yield text, bool(secondary)


def parse_member(raw: str, secondary: bool) -> Member | None:
    """Una forma amb el seu marcador; ``None`` si és un antònim (no s'importa mai)."""
    marker = ""
    match = _MARKER.search(raw)
    display = raw
    if match is not None:
        marker = match.group(1).strip().lower()
        display = raw[: match.start()].strip()
    if not display:
        return None
    if ANTONYM in marker:
        return None
    register = ""
    for key, label in REGISTERS.items():
        if key in marker:
            register = label
            break
    return Member(normalize(display), display, register, secondary)


def parse_line(line: str) -> Group | None:
    """Un grup de significat, o ``None`` si la línia no és una entrada."""
    match = _HEAD.match(line.strip())
    if match is None:
        return None
    tags = [POS_MAP.get(part.strip().lower(), "") for part in match["pos"].split("/")]
    pos = "/".join(sorted({tag for tag in tags if tag}))
    members: list[Member] = []
    seen: set[str] = set()
    for raw, secondary in split_members(match["body"]):
        member = parse_member(raw, secondary)
        if member is None or member.form in seen:
            continue
        seen.add(member.form)
        members.append(member)
    if len(members) < 2:
        return None  # un grup d'una sola forma no ofereix cap alternativa
    return Group(pos, (match["sense"] or "").strip(), tuple(members))


def read_groups(path: Path) -> Iterator[Group]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            group = parse_line(line)
            if group is not None:
                yield group


def build(source: Path, output: Path, metadata: dict[str, str]) -> dict[str, str]:
    """Genera el recurs SQLite i en retorna el resum."""
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    connection = sqlite3.connect(output)
    try:
        connection.executescript(SCHEMA)
        n_groups = 0
        n_members = 0
        forms: set[str] = set()
        for group in read_groups(source):
            n_groups += 1
            cursor = connection.execute(
                "INSERT INTO groups (pos, sense) VALUES (?,?)", (group.pos, group.sense)
            )
            group_id = cursor.lastrowid
            connection.executemany(
                "INSERT INTO members (group_id, form, display, register, secondary, position) "
                "VALUES (?,?,?,?,?,?)",
                [
                    (group_id, m.form, m.display, m.register, int(m.secondary), position)
                    for position, m in enumerate(group.members)
                ],
            )
            n_members += len(group.members)
            forms.update(m.form for m in group.members)
        summary = {
            **metadata,
            "n_groups": str(n_groups),
            "n_members": str(n_members),
            "n_forms": str(len(forms)),
            "imported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        connection.executemany(
            "INSERT INTO metadata (key, value) VALUES (?,?)", sorted(summary.items())
        )
        connection.commit()
    finally:
        connection.close()
    return summary


def source_commit(source: Path) -> str:
    """Commit del repositori d'origen, si el fitxer ve d'un clon de git."""
    root = source.parent
    while root != root.parent and not (root / ".git").exists():
        root = root.parent
    if not (root / ".git").exists():
        return ""
    try:
        result = subprocess.run(  # noqa: S603 - ruta del sistema, arguments fixos
            ["git", "-C", str(root), "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="import_sinonims",
        description=(
            "Converteix «dict/sinonims.txt» de Softcatalà en un recurs SQLite local. "
            "Els antònims no s'importen mai."
        ),
        epilog=f"Font: {SOURCE_REPOSITORY} · Llicència de les dades: CC-BY-4.0",
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        metavar="FITXER",
        help=f"«{SOURCE_FILE}» del repositori d'origen, o un clon sencer",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=DEFAULT_OUTPUT, metavar="FITXER", help="recurs generat"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.source / SOURCE_FILE if args.source.is_dir() else args.source
    if not source.is_file():
        print(f"No s'ha trobat «{source}».", file=sys.stderr)
        return 1
    metadata = {
        "source_repository": SOURCE_REPOSITORY,
        "source_file": SOURCE_FILE,
        "source_commit": source_commit(source),
        "license": LICENSE,
        "attribution": ATTRIBUTION,
    }
    summary = build(source, args.output, metadata)
    sidecar = args.output.with_suffix(".metadata.json")
    sidecar.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"{summary['n_groups']} grups, {summary['n_members']} formes "
        f"({summary['n_forms']} diferents) → {args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
