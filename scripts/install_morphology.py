#!/usr/bin/env python3
"""Instal·la la morfologia catalana de Softcatalà per a la flexió i la concordança.

Com els altres instal·ladors, aquest script és **fora del paquet**: baixa el
diccionari una sola vegada, amb confirmació explícita, i genera el recurs
local. Després tot funciona sense connexió.

Les dades de Softcatalà són copyleft i **no** es distribueixen amb el
projecte: cada usuari se les genera a partir del repositori original, de
manera que la llicència i l'atribució queden on toca.

Component: diccionari català de Softcatalà (GPL-2.0-or-later OR
LGPL-2.1-or-later), https://github.com/Softcatala/catalan-dict-tools
Requisit: git.

Ús::

    python scripts/install_morphology.py            # demana confirmació
    python scripts/install_morphology.py --yes      # sense preguntar
    python scripts/install_morphology.py --info     # només informa
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from import_softcatala import (  # noqa: E402 - l'script viu al costat
    ATTRIBUTION,
    DEFAULT_OUTPUT,
    LICENSE,
    SOURCE_FILE,
    SOURCE_REPOSITORY,
)

COMPONENT = "Morfologia catalana"
APPROXIMATE_SIZE_MB = 90
REQUIREMENT = "git"


def describe() -> dict[str, object]:
    """Informació que cal ensenyar abans de baixar res."""
    return {
        "component": COMPONENT,
        "purpose": (
            "Flexió i concordança fiables: lema, categoria, gènere, nombre, persona, "
            "temps i mode de més d'un milió de formes catalanes."
        ),
        "origin": SOURCE_REPOSITORY,
        "version": "darrera revisió del repositori (es desa el commit exacte)",
        "license": LICENSE,
        "approximate_size_mb": APPROXIMATE_SIZE_MB,
        "requirement": REQUIREMENT,
        "attribution": ATTRIBUTION,
        "target": str(DEFAULT_OUTPUT),
        "offline_after_install": True,
        "note": (
            "Les dades són copyleft i no es distribueixen amb el projecte: es baixen "
            "del repositori original i el recurs es genera en aquest ordinador."
        ),
    }


def summary() -> str:
    info = describe()
    return "\n".join(
        [
            f"Component: {info['component']}",
            f"Per a què serveix: {info['purpose']}",
            f"Origen: {info['origin']}",
            f"Versió: {info['version']}",
            f"Mida aproximada de la descàrrega: {info['approximate_size_mb']} MB",
            f"Llicència de les dades: {info['license']}",
            f"Atribució: {info['attribution']}",
            f"Requisit: {info['requirement']}",
            f"Es genera a: {info['target']}",
            f"Nota: {info['note']}",
        ]
    )


def install(output: Path) -> int:
    """Clona el repositori de Softcatalà i genera el recurs morfològic local."""
    git = shutil.which("git")
    if git is None:
        print(
            "Cal git per baixar el diccionari. Instal·leu-lo i torneu-hi, o cloneu "
            f"{SOURCE_REPOSITORY} a mà i executeu:\n"
            "  python scripts/import_softcatala.py --source <directori>",
            file=sys.stderr,
        )
        return 1
    with tempfile.TemporaryDirectory(prefix="parafrasi-cat-softcatala-") as workspace:
        checkout = Path(workspace) / "catalan-dict-tools"
        clone = [git, "clone", "--depth", "1", SOURCE_REPOSITORY, str(checkout)]
        print(f"\n$ {' '.join(clone[1:])}")
        if subprocess.run(clone, check=False).returncode != 0:  # noqa: S603 - ruta del sistema
            print("No s'ha pogut baixar el diccionari.", file=sys.stderr)
            return 1
        if not (checkout / SOURCE_FILE).is_file():
            print(
                f"El repositori no conté «{SOURCE_FILE}». Reviseu {SOURCE_REPOSITORY}.",
                file=sys.stderr,
            )
            return 1
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            str(Path(__file__).resolve().parent / "import_softcatala.py"),
            "--source",
            str(checkout),
            "--output",
            str(output),
        ]
        print(f"\n$ import_softcatala.py --source {checkout} --output {output}")
        return subprocess.run(command, check=False).returncode  # noqa: S603 - script propi


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install_morphology",
        description=(
            "Baixa el diccionari català de Softcatalà i en genera el recurs morfològic "
            "local. Necessita Internet una sola vegada; després tot funciona fora de línia."
        ),
        epilog=f"Font: {SOURCE_REPOSITORY} · Llicència: {LICENSE}",
    )
    parser.add_argument("-y", "--yes", action="store_true", help="no demanis confirmació")
    parser.add_argument("--info", action="store_true", help="mostra la informació i surt")
    parser.add_argument("--json", action="store_true", help="informació en JSON")
    parser.add_argument(
        "-o", "--output", type=Path, default=DEFAULT_OUTPUT, metavar="FITXER", help="recurs generat"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.json:
        print(json.dumps(describe(), ensure_ascii=False, indent=2))
        return 0
    print(summary())
    if args.info:
        return 0
    if not args.yes:
        answer = input("\nVoleu instal·lar-la? [s/N] ").strip().lower()
        if answer not in ("s", "si", "sí", "y", "yes"):
            print("Cancel·lat. No s'ha baixat res.")
            return 1
    code = install(args.output)
    if code == 0:
        print(f"\nInstal·lada. El recurs «{args.output}» ja es detecta automàticament.")
    return code


if __name__ == "__main__":
    sys.exit(main())
