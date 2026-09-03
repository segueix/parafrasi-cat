"""Fixtures compartides pels tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from parafrasi_cat.analyzer import ClosedClassLexicon, RuleBasedAnalyzer
from parafrasi_cat.resources import ProjectPaths, as_str_list, load_mapping

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def project_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def paths() -> ProjectPaths:
    return ProjectPaths(ROOT)


@pytest.fixture(scope="session")
def analyzer() -> RuleBasedAnalyzer:
    return RuleBasedAnalyzer()


@pytest.fixture(scope="session")
def modality(paths: ProjectPaths) -> dict[str, tuple[str, ...]]:
    data = load_mapping(paths.language() / "lexicon" / "modalitat.yaml")
    return {
        key: as_str_list(data, key)
        for key in ("hedges", "certainty", "negation", "negation_exceptions")
    }


@pytest.fixture(scope="session")
def validation_sentences(paths: ProjectPaths) -> tuple[str, ...]:
    file = paths.corpus / "validation" / "frases_prova.txt"
    lines = file.read_text(encoding="utf-8").splitlines()
    return tuple(line.strip() for line in lines if line.strip())


@pytest.fixture(scope="session")
def lexicon(paths: ProjectPaths) -> ClosedClassLexicon:
    return ClosedClassLexicon.load(paths.language())


@pytest.fixture(scope="session")
def catalan_analyzer(lexicon: ClosedClassLexicon) -> RuleBasedAnalyzer:
    """Analitzador complet: amb lexicó (pronoms resolts, expressions multiparaula)."""
    return RuleBasedAnalyzer(lexicon=lexicon)
