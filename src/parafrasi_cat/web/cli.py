"""Subordre ``parafrasi-cat web``: arrenca la interfície local.

Exemples::

    parafrasi-cat web
    parafrasi-cat web --port 9000 --no-browser
    parafrasi-cat web --history registre.jsonl --enable-history

El servidor es lliga a l'amfitrió local i no publica res a la xarxa. Amb el
registre desactivat (el comportament per defecte) no es desa cap text.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from collections.abc import Sequence
from pathlib import Path

from parafrasi_cat.core.errors import ParafrasiError
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.web.history import DEFAULT_HISTORY_FILE, HistoryLog
from parafrasi_cat.web.server import DEFAULT_HOST, DEFAULT_PORT, serve
from parafrasi_cat.web.service import DEFAULT_RULE_SET, RewriteService

EXIT_OK = 0
EXIT_ERROR = 1


def build_web_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parafrasi-cat web",
        description=(
            "Interfície local per reredactar text: escollir nivell, empremta, diccionaris, "
            "preferències i mode; veure candidats, diferències, regles, puntuacions i "
            "advertiments; marcar candidats i editar el resultat. Tot s'executa en aquest "
            "ordinador, sense LLM ni serveis externs."
        ),
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST, metavar="AMFITRIÓ", help=f"per defecte {DEFAULT_HOST}"
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, metavar="PORT", help=f"per defecte {DEFAULT_PORT}"
    )
    parser.add_argument("--home", type=Path, metavar="DIR", help="directori arrel del projecte")
    parser.add_argument(
        "-r",
        "--rules",
        default=DEFAULT_RULE_SET,
        metavar="NOM|FITXER",
        help=f"conjunt de regles (per defecte «{DEFAULT_RULE_SET}»)",
    )
    parser.add_argument(
        "--history",
        type=Path,
        metavar="FITXER",
        help=f"fitxer del registre local (per defecte {DEFAULT_HISTORY_FILE})",
    )
    parser.add_argument(
        "--enable-history",
        action="store_true",
        help="activa el registre des de l'inici (per defecte està desactivat i no desa res)",
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="no obris el navegador en arrencar"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="escriu cada petició a la sortida d'error"
    )
    return parser


def build_service(args: argparse.Namespace) -> RewriteService:
    paths = ProjectPaths.discover(args.home)
    history_file = args.history if args.history is not None else paths.root / DEFAULT_HISTORY_FILE
    history = HistoryLog(history_file, enabled=args.enable_history)
    return RewriteService(paths, history=history, rule_set=args.rules)


def web_main(argv: Sequence[str] | None = None) -> int:
    args = build_web_parser().parse_args(argv)
    try:
        service = build_service(args)
    except ParafrasiError as exc:
        print(f"parafrasi-cat web: error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    def announce(url: str) -> None:
        print(f"parafrasi-cat: interfície local a {url}")
        print("Tot el processament és local. Premeu Ctrl+C per aturar el servidor.")
        if service.history.enabled:
            print(f"Registre actiu: {service.history.path}")
        else:
            print("Registre desactivat: no es desa cap text.")
        if not args.no_browser:
            webbrowser.open(url)

    try:
        serve(service, host=args.host, port=args.port, quiet=not args.verbose, on_start=announce)
    except OSError as exc:
        print(f"parafrasi-cat web: no s'ha pogut obrir el port: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK
