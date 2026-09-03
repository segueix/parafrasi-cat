"""Subordre ``parafrasi-cat feedback``: registre del feedback manual sobre variants.

Exemples::

    parafrasi-cat feedback preferred "obra de"
    parafrasi-cat feedback acceptable "realitzat per" "sarcòfag funerari"
    parafrasi-cat feedback rejected "fet per" --file preferences/feedback.yml
    parafrasi-cat feedback show
    parafrasi-cat feedback show --json

Cada ordre suma una decisió als recomptes del fitxer de feedback (per
defecte ``preferences/feedback.yml`` del projecte) i el torna a desar. No
s'hi entrena res: el fitxer és un YAML llegible que es pot editar a mà.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from parafrasi_cat.core.errors import ParafrasiError
from parafrasi_cat.preferences.feedback import (
    DEFAULT_FEEDBACK_FILE,
    VERDICT_LABELS,
    VERDICTS,
    FeedbackStore,
)
from parafrasi_cat.resources import ProjectPaths

EXIT_OK = 0
EXIT_ERROR = 1


def build_feedback_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parafrasi-cat feedback",
        description=(
            "Registra el feedback manual de l'autor sobre variants (preferida, acceptable, "
            "rebutjada) com a recomptes explícits en un YAML llegible i versionable. "
            "El motor no hi entrena cap model."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for verdict in VERDICTS:
        sub = commands.add_parser(
            verdict, help=f"marca una o més variants com a «{VERDICT_LABELS[verdict]}»"
        )
        sub.add_argument("forms", nargs="+", metavar="VARIANT", help="variant (paraula o locució)")
        _common_options(sub)
    show = commands.add_parser("show", help="mostra els recomptes acumulats")
    _common_options(show)
    show.add_argument("-j", "--json", action="store_true", help="resultat en JSON")
    return parser


def _common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-f",
        "--file",
        type=Path,
        metavar="FITXER",
        help=f"fitxer de feedback (per defecte, preferences/{DEFAULT_FEEDBACK_FILE} del projecte)",
    )
    parser.add_argument("--home", type=Path, metavar="DIR", help="directori arrel del projecte")


def feedback_file(args: argparse.Namespace) -> Path:
    if args.file is not None:
        return Path(args.file)
    return ProjectPaths.discover(args.home).preferences / DEFAULT_FEEDBACK_FILE


def feedback_main(argv: Sequence[str] | None = None) -> int:
    parser = build_feedback_parser()
    args = parser.parse_args(argv)
    try:
        file = feedback_file(args)
        store = FeedbackStore.load(file)
        if args.command == "show":
            if args.json:
                print(json.dumps(store.to_dict(), ensure_ascii=False, indent=2))
            else:
                print(store.summary())
            return EXIT_OK
        for form in args.forms:
            counts = store.record(form, args.command)
            print(f"«{form}»: {counts.describe()} (pes {counts.weight(store.prior):.2f})")
        saved = store.save()
        print(f"Desat a {saved}")
    except ParafrasiError as exc:
        print(f"parafrasi-cat feedback: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"parafrasi-cat feedback: error d'entrada/sortida: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK
