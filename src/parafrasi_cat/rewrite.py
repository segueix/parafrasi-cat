"""Ordre ``parafrasi-cat rewrite``: reescriptura amb informe de candidats.

Exemples::

    parafrasi-cat rewrite input.txt --style style/author.json --level 3
    parafrasi-cat rewrite input.txt --candidates 10 --discarded 8
    parafrasi-cat rewrite input.txt --json > resultat.json
    parafrasi-cat rewrite input.txt --output sortida.txt

La sortida mostra, per a cada frase, el millor candidat, les regles
aplicades, les puntuacions per dimensió (preservació factual,
epistemològica, terminològica, gramaticalitat, semblança d'estil, grau de
canvi) i els candidats descartats més importants amb el motiu del descart.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from parafrasi_cat.core.errors import ParafrasiError
from parafrasi_cat.core.transformation import SemanticRisk
from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.config import PipelineConfig
from parafrasi_cat.pipeline.result import ParaphraseResult

EXIT_OK = 0
EXIT_ERROR = 1
DEFAULT_RULE_SET = "parafrasi"
DEFAULT_DISCARDED = 5


@dataclass(frozen=True, slots=True)
class RewriteOptions:
    """Opcions de reescriptura (equivalents a les de la línia d'ordres)."""

    style: str | None = None
    level: int | None = None
    candidates: int | None = None
    rule_set: str = DEFAULT_RULE_SET
    max_risk: SemanticRisk | None = None
    min_confidence: float | None = None
    protected_terms: tuple[str, ...] = ()
    protected_terms_files: tuple[Path, ...] = ()
    home: Path | None = None
    config: Path | None = None

    def to_config(self) -> PipelineConfig:
        config = PipelineConfig.load(self.config) if self.config else PipelineConfig()
        overrides: dict[str, object] = {"rule_set": self.rule_set}
        if self.config is not None and self.rule_set == DEFAULT_RULE_SET:
            overrides.pop("rule_set")  # la configuració mana si no s'ha demanat un conjunt
        if self.home is not None:
            overrides["home"] = self.home
        if self.style:
            overrides["style_profile"] = self.style
        if self.level is not None:
            overrides["level"] = self.level
        if self.candidates is not None:
            overrides["max_candidates_per_sentence"] = self.candidates
        if self.max_risk is not None:
            overrides["max_semantic_risk"] = self.max_risk
        if self.min_confidence is not None:
            overrides["min_confidence"] = self.min_confidence
        if self.protected_terms:
            overrides["protected_terms"] = (*config.protected_terms, *self.protected_terms)
        if self.protected_terms_files:
            overrides["protected_terms_files"] = (
                *config.protected_terms_files,
                *self.protected_terms_files,
            )
        return config.with_overrides(**overrides)


def rewrite(text: str, options: RewriteOptions | None = None) -> ParaphraseResult:
    """Reescriu ``text`` amb les opcions indicades i retorna el resultat complet."""
    return build_pipeline((options or RewriteOptions()).to_config()).run(text)


def build_rewrite_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parafrasi-cat rewrite",
        description=(
            "Reescriu un text i mostra el millor candidat de cada frase, les puntuacions per "
            "dimensió, les regles aplicades i els candidats descartats amb el motiu. "
            "Tot es calcula localment amb regles; cap error factual no s'accepta mai."
        ),
    )
    parser.add_argument(
        "input",
        metavar="FITXER",
        help="fitxer de text d'entrada (UTF-8); «-» llegeix l'entrada estàndard",
    )
    parser.add_argument(
        "-s",
        "--style",
        metavar="NOM|FITXER",
        help="perfil d'estil (resources/style/) o empremta d'autor (style/<autor>.json)",
    )
    parser.add_argument(
        "-l",
        "--level",
        type=int,
        choices=range(1, 6),
        metavar="N",
        help="nivell màxim de regles: 1 lèxic, 2 connectors, 3 sintaxi, 4 entre frases, 5 paràgraf",
    )
    parser.add_argument(
        "-n",
        "--candidates",
        type=int,
        metavar="N",
        help="nombre màxim de candidats avaluats per frase",
    )
    parser.add_argument(
        "-r",
        "--rules",
        default=DEFAULT_RULE_SET,
        metavar="NOM|FITXER",
        help=f"conjunt de regles (per defecte «{DEFAULT_RULE_SET}»)",
    )
    parser.add_argument(
        "-c", "--config", type=Path, metavar="FITXER", help="configuració de la canonada"
    )
    parser.add_argument("--home", type=Path, metavar="DIR", help="directori arrel del projecte")
    parser.add_argument(
        "--max-risk", choices=[r.value for r in SemanticRisk], help="risc semàntic màxim acceptat"
    )
    parser.add_argument(
        "--min-confidence", type=float, metavar="X", help="confiança mínima acceptada (0-1)"
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
        "-d",
        "--discarded",
        type=int,
        default=DEFAULT_DISCARDED,
        metavar="N",
        help=f"candidats descartats a mostrar per frase (per defecte {DEFAULT_DISCARDED})",
    )
    parser.add_argument(
        "-o", "--output", type=Path, metavar="FITXER", help="fitxer on escriure el text reescrit"
    )
    parser.add_argument("-j", "--json", action="store_true", help="informe complet en JSON")
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="només el text reescrit, sense informe"
    )
    return parser


def rewrite_main(argv: Sequence[str] | None = None) -> int:
    parser = build_rewrite_parser()
    args = parser.parse_args(argv)
    if args.candidates is not None and args.candidates < 1:
        parser.error("--candidates ha de ser almenys 1")
    if args.discarded < 0:
        parser.error("--discarded no pot ser negatiu")
    options = RewriteOptions(
        style=args.style,
        level=args.level,
        candidates=args.candidates,
        rule_set=args.rules,
        max_risk=SemanticRisk.parse(args.max_risk) if args.max_risk else None,
        min_confidence=args.min_confidence,
        protected_terms=tuple(args.protect),
        protected_terms_files=tuple(args.protect_file),
        home=args.home,
        config=args.config,
    )
    try:
        text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text("utf-8")
        result = rewrite(text, options)
    except ParafrasiError as exc:
        print(f"parafrasi-cat rewrite: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"parafrasi-cat rewrite: error d'entrada/sortida: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if args.output is not None:
        Path(args.output).write_text(result.output_text, encoding="utf-8")
    if args.json:
        print(result.to_json())
    elif args.quiet:
        sys.stdout.write(result.output_text)
        if not result.output_text.endswith("\n"):
            sys.stdout.write("\n")
    else:
        print(result.report(max_discarded=args.discarded))
    return EXIT_OK
