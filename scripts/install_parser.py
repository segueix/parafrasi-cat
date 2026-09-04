#!/usr/bin/env python3
"""Instal·la l'analitzador sintàctic català local (spaCy i el model AnCora).

Com l'instal·lador de LanguageTool, aquest script és **fora del paquet**: la
descàrrega es fa una sola vegada, amb confirmació explícita, i després tot
funciona sense connexió. El model **només analitza**: no genera text, no
reescriu i no decideix res.

Components:
  - spaCy (MIT), https://spacy.io
  - ca_core_news_sm (GPL-3.0), entrenat sobre UD Catalan AnCora

Ús::

    python scripts/install_parser.py            # demana confirmació
    python scripts/install_parser.py --yes      # sense preguntar
    python scripts/install_parser.py --info     # només informa
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

COMPONENT = "Parser sintàctic català"
PACKAGE = "spacy"
MODEL = "ca_core_news_sm"
ORIGIN = "https://pypi.org/project/spacy/ i https://github.com/explosion/spacy-models"
LICENSE = "spaCy: MIT · model ca_core_news_sm: GPL-3.0"
APPROXIMATE_SIZE_MB = 120
TRAINING_DATA = "UD Catalan AnCora v2.8"


def describe() -> dict[str, object]:
    return {
        "component": COMPONENT,
        "purpose": (
            "Analitza dependències, subjecte, objecte, subordinades i coordinacions "
            "perquè les transformacions estructurals es puguin fer amb seguretat."
        ),
        "origin": ORIGIN,
        "version": f"{PACKAGE} + {MODEL}",
        "license": LICENSE,
        "approximate_size_mb": APPROXIMATE_SIZE_MB,
        "requirement": "Python 3.11 o superior",
        "training_data": TRAINING_DATA,
        "offline_after_install": True,
        "note": (
            "El model només analitza: no genera text ni pren cap decisió. "
            "Un cop instal·lat, no cal connexió per a res."
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
            f"Dades d'entrenament: {info['training_data']}",
            f"Mida aproximada: {info['approximate_size_mb']} MB",
            f"Llicència: {info['license']}",
            f"Nota: {info['note']}",
        ]
    )


def install() -> int:
    """Instal·la spaCy i el model català amb pip."""
    steps = [
        [sys.executable, "-m", "pip", "install", "--quiet", PACKAGE],
        [sys.executable, "-m", "spacy", "download", MODEL],
    ]
    for step in steps:
        print(f"\n$ {' '.join(step[2:])}")
        completed = subprocess.run(step, check=False)
        if completed.returncode != 0:
            print("La instal·lació ha fallat.", file=sys.stderr)
            return completed.returncode
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install_parser",
        description=(
            "Instal·la l'analitzador sintàctic català local. Necessita Internet una "
            "sola vegada; després tot funciona fora de línia."
        ),
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
        answer = input("\nVoleu instal·lar-lo? [s/N] ").strip().lower()
        if answer not in ("s", "si", "sí", "y", "yes"):
            print("Cancel·lat. No s'ha baixat res.")
            return 1
    code = install()
    if code == 0:
        print(f"\nInstal·lat. El parser «{MODEL}» ja es detecta automàticament.")
    return code


if __name__ == "__main__":
    sys.exit(main())
