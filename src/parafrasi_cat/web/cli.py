"""Subordre ``parafrasi-cat web``: arrenca la interfície.

Exemples::

    parafrasi-cat web                       # només aquest ordinador
    parafrasi-cat web --port 9000 --no-browser
    parafrasi-cat web --history registre.jsonl --enable-history
    parafrasi-cat web --lan                 # també des de la xarxa local

Per defecte el servidor es lliga a l'amfitrió local i no publica res a la
xarxa. Amb ``--lan`` escolta a totes les interfícies d'aquesta màquina i
demana un codi d'accés de sis xifres, generat a cada arrencada, per obrir la
interfície des d'un altre dispositiu de la mateixa Wi-Fi.

Amb el registre desactivat (el comportament per defecte) no es desa cap text.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from collections.abc import Sequence
from pathlib import Path

from parafrasi_cat.adapters.status import resources_status
from parafrasi_cat.core.errors import ParafrasiError
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.web.auth import (
    NETWORK_WARNING,
    PRIVACY_NOTES,
    AccessMode,
    AccessPolicy,
    ServerStatus,
)
from parafrasi_cat.web.history import DEFAULT_HISTORY_FILE, HistoryLog
from parafrasi_cat.web.server import DEFAULT_HOST, DEFAULT_PORT, LAN_HOST, serve
from parafrasi_cat.web.service import DEFAULT_RULE_SET, RewriteService

EXIT_OK = 0
EXIT_ERROR = 1

#: Què cal fer al segon dispositiu. La IP no la sap el procés: en ChromeOS,
#: la del contenidor Linux no és la que veu la resta de la xarxa.
LAN_INSTRUCTIONS = (
    "Consulta l'adreça IP Wi-Fi del Chromebook servidor a la configuració de ChromeOS "
    "i obre-la des de l'altre dispositiu, amb el port d'aquesta línia."
)


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
        "--lan",
        action="store_true",
        help=(
            "obre la interfície a la xarxa local (escolta a totes les interfícies i "
            "demana un codi d'accés). Per defecte només s'hi arriba des d'aquest ordinador"
        ),
    )
    parser.add_argument(
        "--pin",
        metavar="CODI",
        help=(
            "codi d'accés fix per al mode de xarxa local (per defecte se'n genera un de nou "
            "a cada arrencada). El programa no el desa enlloc, però recordeu que queda a "
            "l'historial del terminal"
        ),
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


def build_policy(args: argparse.Namespace) -> AccessPolicy:
    """Política d'accés: local per defecte, de xarxa local només amb ``--lan``.

    En mode de xarxa local, ``--host`` no hi entra: el servidor escolta a
    totes les interfícies i els amfitrions acceptats són els de la LAN. Si
    ``--host`` hi arribés, un nom d'Internet passaria a ser acceptable a la
    capçalera ``Host``, que és justament el que la comprovació evita.
    """
    if not args.lan:
        if args.pin:
            raise ParafrasiError("«--pin» només té sentit amb «--lan»")
        return AccessPolicy.local()
    return AccessPolicy.lan(args.pin)


def component_states(service: RewriteService) -> tuple[tuple[str, str], ...]:
    """Estat dels recursos lingüístics, per al resum d'arrencada.

    Comprovar el parser vol dir carregar el model de spaCy, que triga uns
    segons: per això no es fa mai abans que el servidor comenci a contestar.
    """
    resources = resources_status(service.paths.root)
    return (
        ("LanguageTool", "actiu" if resources.languagetool.active else "no disponible"),
        ("Parser", "actiu" if resources.syntax.active else "no disponible"),
        ("Morfologia", "activa" if resources.morphology.active else "no disponible"),
    )


def report_components(service: RewriteService) -> None:
    """Escriu l'estat dels recursos quan se sap, sense fer esperar ningú.

    La interfície ja el mostra amb ``/api/options``; aquí només és comoditat
    per a qui mira la consola.
    """
    try:
        estats = component_states(service)
    except Exception as exc:  # noqa: BLE001 - un resum informatiu no ha de tombar res
        print(f"Recursos lingüístics: no s'han pogut comprovar ({exc})")
        return
    print("\n".join(f"{name}: {state}" for name, state in estats))


def web_main(argv: Sequence[str] | None = None) -> int:
    args = build_web_parser().parse_args(argv)
    try:
        policy = build_policy(args)
        service = build_service(args)
    except ParafrasiError as exc:
        print(f"parafrasi-cat web: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    host = LAN_HOST if args.lan else args.host

    def announce(url: str) -> None:
        registre = (
            f"Registre actiu: {service.history.path}"
            if service.history.enabled
            else "Registre desactivat: no es desa cap text."
        )
        extra = [PRIVACY_NOTES[policy.mode], registre]
        if policy.mode is AccessMode.LAN:
            extra.extend([LAN_INSTRUCTIONS, NETWORK_WARNING])
        extra.append("Premeu Ctrl+C per aturar el servidor.")
        status = ServerStatus(
            mode=policy.mode,
            port=int(url.rsplit(":", 1)[1].rstrip("/")),
            components=(("Recursos lingüístics", "s'estan comprovant"),),
            pin=policy.pin,
            url=url,
            extra=("", *extra),
        )
        print(status.render(), flush=True)
        # La comprovació carrega el model del parser i triga: es fa a part
        # perquè el servidor ja estigui contestant mentre es fa.
        threading.Thread(target=report_components, args=(service,), daemon=True).start()
        if not args.no_browser:
            webbrowser.open(url)

    try:
        serve(
            service,
            host=host,
            port=args.port,
            quiet=not args.verbose,
            policy=policy,
            on_start=announce,
        )
    except OSError as exc:
        print(f"parafrasi-cat web: no s'ha pogut obrir el port: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK
