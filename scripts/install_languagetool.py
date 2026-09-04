#!/usr/bin/env python3
"""Instal·la LanguageTool localment per a la validació avançada de català.

Aquest script **no forma part del paquet** ``parafrasi_cat``: és l'única peça
del projecte que baixa res d'Internet, i s'executa una sola vegada, sempre amb
confirmació explícita. El paquet en si no conté cap client de xarxa, i un test
ho comprova.

Un cop instal·lat, ``parafrasi-cat`` funciona completament fora de línia:
LanguageTool s'executa com un procés local i no envia text enlloc. Mai no es
fa servir l'API de languagetool.org.

Component: LanguageTool (LGPL-2.1-or-later), https://languagetool.org
Requisit: Java.

Ús::

    python scripts/install_languagetool.py            # demana confirmació
    python scripts/install_languagetool.py --yes      # sense preguntar
    python scripts/install_languagetool.py --info     # només informa, no baixa
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

COMPONENT = "LanguageTool"
ORIGIN = "https://languagetool.org/download/LanguageTool-stable.zip"
HOMEPAGE = "https://languagetool.org"
LICENSE = "LGPL-2.1-or-later"
APPROXIMATE_SIZE_MB = 250
DEFAULT_TARGET = Path("vendor/languagetool")
REQUIREMENT = "Java"


def describe() -> dict[str, object]:
    """Informació que cal ensenyar abans de baixar res."""
    return {
        "component": COMPONENT,
        "purpose": "Validació avançada de gramàtica, concordança i puntuació en català.",
        "origin": ORIGIN,
        "homepage": HOMEPAGE,
        "license": LICENSE,
        "approximate_size_mb": APPROXIMATE_SIZE_MB,
        "requirement": REQUIREMENT,
        "target": str(DEFAULT_TARGET),
        "offline_after_install": True,
        "note": (
            "La descàrrega es fa una sola vegada. Després, LanguageTool s'executa "
            "en aquest ordinador i no s'envia cap text enlloc."
        ),
    }


def summary() -> str:
    info = describe()
    return "\n".join(
        [
            f"Component: {info['component']}",
            f"Per a què serveix: {info['purpose']}",
            f"Origen: {info['origin']}",
            f"Mida aproximada: {info['approximate_size_mb']} MB",
            f"Llicència: {info['license']}",
            f"Requisit: {info['requirement']}",
            f"Es desarà a: {info['target']}",
            f"Nota: {info['note']}",
        ]
    )


def download(url: str, destination: Path) -> Path:
    """Baixa el fitxer. És l'únic accés a Internet de tot el projecte."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=600) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return destination


def extract(archive: Path, target: Path) -> Path:
    """Desempaqueta la distribució i deixa el contingut directament a ``target``."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    with tempfile.TemporaryDirectory(dir=target.parent) as workspace:
        staging = Path(workspace)
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                # Refusa qualsevol ruta que se'n vagi fora del directori de destinació.
                resolved = (staging / member).resolve()
                if not str(resolved).startswith(str(staging.resolve())):
                    raise ValueError(f"Ruta insegura dins del fitxer comprimit: {member}")
            bundle.extractall(staging)
        roots = [child for child in staging.iterdir() if child.is_dir()]
        source = roots[0] if len(roots) == 1 else staging
        shutil.move(str(source), str(target))
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install_languagetool",
        description=(
            "Instal·la LanguageTool localment per a la validació avançada de català. "
            "És l'únic pas del projecte que necessita Internet, i només una vegada."
        ),
    )
    parser.add_argument(
        "-t", "--target", type=Path, default=DEFAULT_TARGET, metavar="DIR", help="on instal·lar-lo"
    )
    parser.add_argument("-y", "--yes", action="store_true", help="no demanis confirmació")
    parser.add_argument("--info", action="store_true", help="mostra la informació i surt")
    parser.add_argument("--json", action="store_true", help="informació en JSON")
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
        answer = input("\nVoleu baixar-lo i instal·lar-lo? [s/N] ").strip().lower()
        if answer not in ("s", "si", "sí", "y", "yes"):
            print("Cancel·lat. No s'ha baixat res.")
            return 1
    print(f"\nBaixant {ORIGIN} …")
    with tempfile.TemporaryDirectory() as workspace:
        archive = download(ORIGIN, Path(workspace) / "languagetool.zip")
        size = archive.stat().st_size / 1_000_000
        print(f"Baixat ({size:.0f} MB). Desempaquetant a {args.target} …")
        target = extract(archive, args.target)
    print(f"Instal·lat a {target}.")
    print("A partir d'ara tot funciona fora de línia: LanguageTool s'executa en local.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
