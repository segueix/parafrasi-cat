"""Reparació segura de «Un fet que...» quan queda com a fragment anafòric."""

from __future__ import annotations

import pytest

from parafrasi_cat.analyzer import ClosedClassLexicon, RuleBasedAnalyzer
from parafrasi_cat.protected import default_protector
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.rules import ParagraphContext, ParagraphRule, default_registry, load_rule_definitions
from parafrasi_cat.syntax import NullSyntax, SpacySyntax, SyntaxProvider


@pytest.fixture(scope="module")
def parser() -> SpacySyntax:
    found = SpacySyntax()
    if not found.available:
        pytest.skip(f"El parser sintàctic no està instal·lat ({found.failure}).")
    return found


def _rule(paths: ProjectPaths) -> ParagraphRule:
    definition = next(
        d
        for d in load_rule_definitions(paths.language() / "transformations" / "fusio.yaml")
        if d.rule_id == "fusio.repara_fragment_anaforic"
    )
    rule = default_registry().create_from_definition(definition, paths)
    assert isinstance(rule, ParagraphRule)
    return rule


def _outputs(text: str, paths: ProjectPaths, syntax: SyntaxProvider) -> list[str]:
    lexicon = ClosedClassLexicon.load(paths.language())
    analyzer = RuleBasedAnalyzer(lexicon=lexicon)
    analysis = analyzer.analyze(text)
    protected = default_protector(analyzer).protect(text)
    ctx = ParagraphContext(
        text=text,
        sentences=analysis.sentences,
        protected_spans=protected,
        source_text=text,
        lexicon=lexicon,
        syntax=syntax,
    )
    return [t.apply(text) for t in _rule(paths).propose(ctx)]


def test_fragment_becomes_an_independent_anaphoric_sentence(
    parser: SpacySyntax, paths: ProjectPaths
) -> None:
    source = (
        "L'obra era dedicada al secretari de la Inquisició. "
        "Un fet que obligava l'autor a mantenir un equilibri subtil."
    )
    assert _outputs(source, paths, parser) == [
        "L'obra era dedicada al secretari de la Inquisició. "
        "Aquest fet obligava l'autor a mantenir un equilibri subtil."
    ]


def test_complete_relative_sentence_is_not_repaired(
    parser: SpacySyntax, paths: ProjectPaths
) -> None:
    source = "La data és rellevant. Un fet que cal considerar és la data de l'edició."
    assert _outputs(source, paths, parser) == []


def test_no_antecedent_means_no_demonstrative(parser: SpacySyntax, paths: ProjectPaths) -> None:
    assert _outputs("Un fet que obligava l'autor a actuar.", paths, parser) == []


def test_without_parser_the_rule_is_inactive(paths: ProjectPaths) -> None:
    source = "La data és rellevant. Un fet que obligava l'autor a actuar."
    assert _outputs(source, paths, NullSyntax()) == []
