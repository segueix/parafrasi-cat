#!/usr/bin/env python3
"""Instal·la el diccionari de sinònims de Softcatalà per a l'edició assistida.

Com els altres instal·ladors, aquest script és **fora del paquet**: baixa el
fitxer una sola vegada, amb confirmació explícita, i en genera el recurs
local. Després tot funciona sense connexió.

El fitxer d'origen fa menys d'un megabyte i es baixa directament: no cal git.
Les dades són Creative Commons CC-BY 4.0 i no es distribueixen amb el
projecte, de manera que l'atribució queda al costat de qui les ha fetes.

Component: diccionari de sinònims de Softcatalà (CC-BY-4.0),
https://github.com/Softcatala/sinonims-cat

Ús::

    python scripts/install_thesaurus.py            # demana confirmació
    python scripts/install_thesaurus.py --yes      # sense preguntar
    python scripts/install_thesaurus.py --info     # només informa
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from import_sinonims import (  # noqa: E402 - l'script viu al costat
    ATTRIBUTION,
    DEFAULT_OUTPUT,
    LICENSE,
    SOURCE_FILE,
    SOURCE_REPOSITORY,
)

COMPONENT = "Diccionari de sinònims"
ORIGIN = "https://raw.githubusercontent.com/Softcatala/sinonims-cat/master/dict/sinonims.txt"
APPROXIMATE_SIZE_MB = 1


def describe() -> dict[str, object]:
    """Informació que cal ensenyar abans de baixar res."""
    return {
        "component": COMPONENT,
        "purpose": (
            "Sinònims per a l'edició assistida: en clicar una paraula, el desplegable "
            "ofereix les formes equivalents que qui escriu pot triar. Els antònims no "
            "s'importen mai."
        ),
        "origin": SOURCE_REPOSITORY,
        "version": "darrera revisió publicada del fitxer",
        "license": LICENSE,
        "approximate_size_mb": APPROXIMATE_SIZE_MB,
        "requirement": "cap",
        "attribution": ATTRIBUTION,
        "target": str(DEFAULT_OUTPUT),
        "offline_after_install": True,
        "note": (
            "El diccionari proposa; qui escriu decideix. El motor no substitueix "
            "cap paraula pel seu compte a partir d'aquest recurs."
        ),
    }


def summary() -> str:
    info = describe()
    return "\n".join(
        [
            f"Component: {info['component']}",
            f"Per a què serveix: {info['purpose']}",
            f"Origen: {info['origin']}",
            f"Fitxer: {SOURCE_FILE}",
            f"Mida aproximada de la descàrrega: {info['approximate_size_mb']} MB",
            f"Llicència de les dades: {info['license']}",
            f"Atribució: {info['attribution']}",
            f"Es genera a: {info['target']}",
            f"Nota: {info['note']}",
        ]
    )


def download(url: str, destination: Path) -> Path:
    """Baixa el fitxer d'origen. És l'únic accés a Internet d'aquest instal·lador."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as response, destination.open("wb") as handle:  # noqa: S310 - URL fixa i https
        shutil.copyfileobj(response, handle)
    return destination


def install(output: Path) -> int:
    """Baixa «sinonims.txt» i en genera el recurs local."""
    with tempfile.TemporaryDirectory(prefix="parafrasi-cat-sinonims-") as workspace:
        source = Path(workspace) / "sinonims.txt"
        print(f"\n$ baixant {ORIGIN}")
        try:
            download(ORIGIN, source)
        except OSError as exc:
            print(f"No s'ha pogut baixar el diccionari: {exc}", file=sys.stderr)
            return 1
        command = [
            sys.executable,
            str(Path(__file__).resolve().parent / "import_sinonims.py"),
            "--source",
            str(source),
            "--output",
            str(output),
        ]
        print(f"$ import_sinonims.py --source {source} --output {output}")
        return subprocess.run(command, check=False).returncode  # noqa: S603 - script propi


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install_thesaurus",
        description=(
            "Baixa el diccionari de sinònims de Softcatalà i en genera el recurs local. "
            "Necessita Internet una sola vegada; després tot funciona fora de línia."
        ),
        epilog=f"Font: {SOURCE_REPOSITORY} · Llicència de les dades: {LICENSE}",
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
        answer = input("\nVoleu instal·lar-lo? [s/N] ").strip().lower()
        if answer not in ("s", "si", "sí", "y", "yes"):
            print("Cancel·lat. No s'ha baixat res.")
            return 1
    code = install(args.output)
    if code == 0:
        print(f"\nInstal·lat. El recurs «{args.output}» ja es detecta automàticament.")
    return code


if __name__ == "__main__":
    sys.exit(main())
