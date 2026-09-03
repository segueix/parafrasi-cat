"""Subordre ``parafrasi-cat style``: construcció i comparació d'empremtes.

Exemples::

    parafrasi-cat style build corpus/author/
    parafrasi-cat style build corpus/author/ --validation corpus/validacio/ --exclude esborrany*
    parafrasi-cat style compare style/author.json style/altre.json
    parafrasi-cat style show style/author.json
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml

from parafrasi_cat.analyzer.analysis import RuleBasedAnalyzer
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon
from parafrasi_cat.core.errors import ConfigError, ParafrasiError
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.style.compare import compare_fingerprints
from parafrasi_cat.style.corpus import load_corpus
from parafrasi_cat.style.fingerprint import StyleFingerprint
from parafrasi_cat.style.observations import StyleResources
from parafrasi_cat.style.preferences import StylePreferences
from parafrasi_cat.style.profile import StyleProfile
from parafrasi_cat.style.profiler import build_fingerprint
from parafrasi_cat.style.schema import SCHEMA_FILE, load_schema, validate

EXIT_OK = 0
EXIT_ERROR = 1


def build_style_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parafrasi-cat style",
        description=(
            "Anàlisi estilomètrica del corpus d'un autor: construeix una empremta JSON "
            "explícita i editable, i compara empremtes. Tot es calcula localment amb "
            "regles i recomptes; no s'hi fa servir cap model."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="construeix l'empremta d'un corpus")
    build.add_argument("corpus", type=Path, help="directori amb els textos de l'autor (.txt/.md)")
    build.add_argument("-o", "--output", type=Path, metavar="FITXER", help="fitxer JSON de sortida")
    build.add_argument(
        "-n", "--name", metavar="NOM", help="nom de l'empremta (per defecte, el del directori)"
    )
    build.add_argument("-d", "--description", default="", metavar="TEXT", help="descripció lliure")
    build.add_argument(
        "--validation",
        type=Path,
        metavar="DIR",
        help="directori amb textos de validació (es comparen amb l'empremta)",
    )
    build.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="RUTA|PATRÓ",
        help="fitxer, directori o patró a excloure (es pot repetir)",
    )
    build.add_argument(
        "--profile",
        type=Path,
        metavar="FITXER",
        help="escriu també un perfil d'estil YAML derivat de l'empremta",
    )
    build.add_argument("--home", type=Path, metavar="DIR", help="directori arrel del projecte")
    build.add_argument("-q", "--quiet", action="store_true", help="no escriu el resum")

    compare = commands.add_parser("compare", help="compara dues empremtes")
    compare.add_argument("first", type=Path, metavar="FITXER1")
    compare.add_argument("second", type=Path, metavar="FITXER2")
    compare.add_argument("-j", "--json", action="store_true", help="resultat en JSON")
    compare.add_argument(
        "--top", type=int, default=15, metavar="N", help="característiques més divergents a mostrar"
    )

    show = commands.add_parser("show", help="mostra un resum llegible d'una empremta")
    show.add_argument("file", type=Path, metavar="FITXER")
    return parser


def style_main(argv: Sequence[str] | None = None) -> int:
    parser = build_style_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            return _build(args)
        if args.command == "compare":
            return _compare(args)
        return _show(args)
    except ParafrasiError as exc:
        print(f"parafrasi-cat style: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"parafrasi-cat style: error d'entrada/sortida: {exc}", file=sys.stderr)
        return EXIT_ERROR


def _build(args: argparse.Namespace) -> int:
    paths = ProjectPaths.discover(args.home)
    corpus_dir = Path(args.corpus)
    name = args.name or corpus_dir.resolve().name
    corpus = load_corpus(corpus_dir, validation_dir=args.validation, exclude=args.exclude)
    lexicon = ClosedClassLexicon.load(paths.language())
    resources = StyleResources.load(paths, lexicon=lexicon)
    analyzer = RuleBasedAnalyzer(lexicon=lexicon)
    fingerprint = build_fingerprint(
        corpus, resources, analyzer, name=name, description=args.description
    )
    schema_file = paths.optional(SCHEMA_FILE)
    if schema_file is not None:
        errors = validate(fingerprint.to_dict(), load_schema(schema_file))
        if errors:
            raise ConfigError("L'empremta generada no compleix l'esquema: " + "; ".join(errors[:5]))
    output = Path(args.output) if args.output else paths.fingerprints / f"{name}.json"
    fingerprint.save(output)
    if args.profile:
        profile = StyleProfile.from_fingerprint(fingerprint, fingerprint_path=str(output))
        Path(args.profile).write_text(
            yaml.safe_dump(profile.to_dict(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    if not args.quiet:
        print(_build_summary(fingerprint, output, corpus.excluded))
    return EXIT_OK


def _build_summary(fingerprint: StyleFingerprint, output: Path, excluded: Sequence[object]) -> str:
    corpus = fingerprint.corpus
    lines = [
        f"Empremta «{fingerprint.name}» desada a {output}",
        f"  documents: {corpus.get('n_documents')} · paràgrafs: {corpus.get('n_paragraphs')} · "
        f"frases: {corpus.get('n_sentences')} · paraules: {corpus.get('n_words')}",
    ]
    if excluded:
        lines.append(f"  textos exclosos: {len(excluded)}")
    preferences = StylePreferences(fingerprint)
    lines.append(preferences.summary())
    validation = fingerprint.validation
    if validation is not None:
        distance = validation.get("distance")
        divergent = validation.get("divergent_features")
        assert isinstance(distance, float) and isinstance(divergent, list)
        lines.append(
            f"  validació: {validation.get('n_documents')} documents, distància {distance:.3f}"
            + (f", divergents: {', '.join(map(str, divergent[:5]))}" if divergent else "")
        )
    return "\n".join(lines)


def _compare(args: argparse.Namespace) -> int:
    first = StyleFingerprint.load(args.first)
    second = StyleFingerprint.load(args.second)
    comparison = compare_fingerprints(first, second)
    if args.json:
        import json

        print(json.dumps(comparison.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(comparison.report(top=args.top))
    return EXIT_OK


def _show(args: argparse.Namespace) -> int:
    fingerprint = StyleFingerprint.load(args.file)
    preferences = StylePreferences(fingerprint)
    corpus = fingerprint.corpus
    lines = [
        f"Empremta «{fingerprint.name}» (esquema {fingerprint.schema_version})",
        f"  documents: {corpus.get('n_documents')} · frases: {corpus.get('n_sentences')} · "
        f"paraules: {corpus.get('n_words')}",
        preferences.summary(),
    ]
    for label, path in (
        ("comes per 100 paraules", "punctuation.comma.per_100_words"),
        ("punts i coma per 100 paraules", "punctuation.semicolon.per_100_words"),
        ("connectors per frase", "connectors.per_sentence"),
        ("impersonals per 100 frases", "impersonal.per_100_sentences"),
        ("primera persona (sg) per 100 frases", "first_person.singular.per_100_sentences"),
        ("passives per 100 frases", "passive.per_100_sentences"),
    ):
        stat = fingerprint.stat(path)
        if stat is not None and stat.value is not None:
            lines.append(f"  {label}: {stat.value:.2f} (confiança {stat.confidence:.2f})")
    print("\n".join(lines))
    return EXIT_OK
