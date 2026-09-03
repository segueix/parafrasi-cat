"""Interfície de línia d'ordres.

Exemples::

    parafrasi-cat "Text a reredactar."
    echo "Text" | parafrasi-cat
    parafrasi-cat --input fitxer.txt --explain
    parafrasi-cat --rules exemple-lexic --json "Gairebé sempre plou."
    parafrasi-cat style build corpus/author/
    parafrasi-cat style compare style/author.json style/altre.json
    parafrasi-cat rewrite input.txt --style style/author.json --level 3 --candidates 10
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from parafrasi_cat import __version__
from parafrasi_cat.core.errors import ParafrasiError
from parafrasi_cat.core.transformation import SemanticRisk
from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.config import PipelineConfig

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parafrasi-cat",
        description=(
            "Motor local de reredacció en català basat en regles. "
            "No fa servir cap LLM ni cap servei extern: tot s'executa a l'ordinador."
        ),
        epilog=(
            "Sense un conjunt de regles actiu, el text es retorna sense modificar. "
            "Subordres: «parafrasi-cat rewrite FITXER» (reescriptura amb informe de candidats) "
            "i «parafrasi-cat style build|compare|show» (empremtes d'estil)."
        ),
    )
    parser.add_argument(
        "text",
        nargs="?",
        help="text a processar (si no s'indica, es llegeix de --input o de l'entrada estàndard)",
    )
    parser.add_argument(
        "-i", "--input", type=Path, metavar="FITXER", help="fitxer de text d'entrada (UTF-8)"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="FITXER",
        help="fitxer on escriure el resultat (per defecte, sortida estàndard)",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        metavar="FITXER",
        help="configuració de la canonada en YAML o JSON",
    )
    parser.add_argument(
        "--home",
        type=Path,
        metavar="DIR",
        help="directori arrel amb resources/, rules/ i dictionaries/",
    )
    parser.add_argument(
        "-r", "--rules", metavar="NOM|FITXER", help="conjunt de regles (nom dins de rules/ o ruta)"
    )
    parser.add_argument(
        "-s",
        "--style",
        metavar="NOM|FITXER",
        help="perfil d'estil (nom dins de resources/style/ o ruta)",
    )
    parser.add_argument(
        "-p",
        "--protect",
        action="append",
        default=[],
        metavar="TERME",
        help="terme que cap regla pot modificar (es pot repetir)",
    )
    parser.add_argument(
        "--protect-file",
        action="append",
        default=[],
        type=Path,
        metavar="FITXER",
        help="fitxer amb termes protegits, un per línia (es pot repetir)",
    )
    parser.add_argument(
        "--max-risk", choices=[r.value for r in SemanticRisk], help="risc semàntic màxim acceptat"
    )
    parser.add_argument(
        "--min-confidence", type=float, metavar="X", help="confiança mínima acceptada (0-1)"
    )
    parser.add_argument(
        "-e",
        "--explain",
        action="store_true",
        help="escriu un informe de les transformacions a la sortida d'error",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="escriu el resultat complet en JSON en lloc del text",
    )
    parser.add_argument("--info", action="store_true", help="mostra la configuració resolta i surt")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def load_config(args: argparse.Namespace) -> PipelineConfig:
    config = PipelineConfig.load(args.config) if args.config else PipelineConfig()
    overrides: dict[str, object] = {}
    if args.home is not None:
        overrides["home"] = args.home
    if args.rules:
        overrides["rule_set"] = args.rules
    if args.style:
        overrides["style_profile"] = args.style
    if args.protect:
        overrides["protected_terms"] = (*config.protected_terms, *args.protect)
    if args.protect_file:
        overrides["protected_terms_files"] = (*config.protected_terms_files, *args.protect_file)
    if args.max_risk:
        overrides["max_semantic_risk"] = SemanticRisk.parse(args.max_risk)
    if args.min_confidence is not None:
        overrides["min_confidence"] = args.min_confidence
    return config.with_overrides(**overrides) if overrides else config


def read_input(args: argparse.Namespace) -> str:
    if args.text is not None:
        return str(args.text)
    if args.input is not None:
        return Path(args.input).read_text(encoding="utf-8")
    return sys.stdin.read()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "style":
        from parafrasi_cat.style.cli import style_main

        return style_main(arguments[1:])
    if arguments and arguments[0] == "rewrite":
        from parafrasi_cat.rewrite import rewrite_main

        return rewrite_main(arguments[1:])
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args)
        pipeline = build_pipeline(config)
        if args.info:
            print(_describe(config, pipeline.rule_set.rule_ids))
            return EXIT_OK
        text = read_input(args)
        result = pipeline.run(text)
    except ParafrasiError as exc:
        print(f"parafrasi-cat: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"parafrasi-cat: error d'entrada/sortida: {exc}", file=sys.stderr)
        return EXIT_ERROR

    output = result.to_json() if args.json else result.output_text
    if args.output is not None:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
    if args.explain:
        print(result.explain(), file=sys.stderr)
    return EXIT_OK


def _describe(config: PipelineConfig, rule_ids: Sequence[str]) -> str:
    lines = [f"parafrasi-cat {__version__}"]
    for key, value in config.to_dict().items():
        lines.append(f"  {key}: {value}")
    lines.append("  regles actives: " + (", ".join(rule_ids) if rule_ids else "cap"))
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
