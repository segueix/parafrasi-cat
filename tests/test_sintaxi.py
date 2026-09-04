"""v1.0: analitzador sintàctic català local i condicions de regla opt-in.

Els tests que necessiten el parser se salten si no està instal·lat. Els que
comproven que el motor funciona sense ell, i que el parser no genera mai res,
s'executen sempre.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parafrasi_cat import PipelineConfig, build_pipeline
from parafrasi_cat.analyzer import ClosedClassLexicon, RuleBasedAnalyzer
from parafrasi_cat.core import ConfigError
from parafrasi_cat.pipeline.builder import build_syntax_provider
from parafrasi_cat.protected import default_protector
from parafrasi_cat.protected.protector import Protector
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.rules import RuleContext, RuleDefinition
from parafrasi_cat.rules.pattern_rule import PatternRule
from parafrasi_cat.syntax import NullSyntax, SentenceSyntax, SpacySyntax, SyntaxProvider

SINGULAR = "Aquest sarcòfag presenta dos cranis."
PLURAL = "Aquests sarcòfags presenten dos cranis."
SUBORDINATE = (
    "D'acord amb la documentació conservada, que és incompleta, es pot plantejar "
    "una datació anterior."
)
COORDINATION = "Presenta dos cranis i dues serps."
NEGATION = "No es pot demostrar que l'obra sigui anterior."


@pytest.fixture(scope="module")
def parser() -> SpacySyntax:
    found = SpacySyntax()
    if not found.available:
        pytest.skip(
            f"El parser sintàctic no està instal·lat ({found.failure}). "
            "Executeu: python scripts/install_parser.py"
        )
    return found


# --- sense parser: res no canvia ---------------------------------------------------------


def test_engine_works_without_a_parser() -> None:
    """Sense parser, el motor reescriu igual que sempre amb les heurístiques."""
    config = PipelineConfig(rule_set="parafrasi", level=3, syntax="none")
    pipeline = build_pipeline(config)
    assert isinstance(pipeline.syntax, NullSyntax)
    assert pipeline.syntax.available is False
    result = pipeline.run(SINGULAR)
    assert result.output_text
    empty = pipeline.syntax.parse(SINGULAR)
    assert not empty and not empty.confident and empty.root is None


def test_syntax_provider_selection() -> None:
    assert isinstance(build_syntax_provider(PipelineConfig(syntax="none")), NullSyntax)
    auto = build_syntax_provider(PipelineConfig(syntax="auto"))
    assert isinstance(auto, SyntaxProvider)
    with pytest.raises(ConfigError):
        build_syntax_provider(PipelineConfig(syntax="inexistent"))


# --- el parser només analitza -------------------------------------------------------------


def test_the_parser_only_analyses(parser: SpacySyntax) -> None:
    """No té cap manera de generar text: només retorna una anàlisi."""
    analysis = parser.parse(SINGULAR)
    assert isinstance(analysis, SentenceSyntax)
    assert analysis.text == SINGULAR
    # Tot el que retorna són mots del text original, en el mateix ordre.
    assert [t.text for t in analysis.tokens if t.text.strip()] == SINGULAR.replace(
        ".", " ."
    ).split()
    assert not hasattr(parser, "generate")
    assert not hasattr(parser, "rewrite")
    assert not hasattr(analysis, "text_after")


# --- subjecte i verb ------------------------------------------------------------------------


def test_subject_and_verb(parser: SpacySyntax) -> None:
    singular = parser.parse(SINGULAR)
    plural = parser.parse(PLURAL)
    assert singular.subject_number() == "sg"
    assert plural.subject_number() == "pl"
    subject = singular.main_subject()
    assert subject is not None and subject.lemma == "sarcòfag"
    assert singular.root is not None and singular.root.lemma == "presentar"
    assert plural.root is not None and plural.root.lemma == "presentar"
    assert singular.objects and plural.objects


def test_incorrect_agreement_is_visible_to_the_engine(parser: SpacySyntax) -> None:
    """Les frases mal concordades es poden distingir de les correctes."""
    for text, number in ((SINGULAR, "sg"), (PLURAL, "pl")):
        assert parser.parse(text).subject_number() == number
    # Amb concordança trencada, el nombre del subjecte i el del verb no coincideixen.
    broken = parser.parse("Aquests sarcòfags presenta dos cranis.")
    subject = broken.main_subject()
    root = broken.root
    assert subject is not None and root is not None
    assert subject.number == "pl"
    assert root.number in (None, "sg")


def test_subordinate_clause_is_not_split(parser: SpacySyntax) -> None:
    analysis = parser.parse(SUBORDINATE)
    assert analysis.clauses, "el parser ha de veure la subordinada"
    relative = next((t for t in analysis.tokens if t.text == "que"), None)
    assert relative is not None
    # La relativa «que és incompleta» queda lligada al seu antecedent: partir-la
    # pel mig es detecta com a creuament de frontera.
    start = SUBORDINATE.index("que és incompleta")
    assert analysis.crosses_clause_boundary(0, start + 3)


def test_coordination_keeps_every_member(parser: SpacySyntax) -> None:
    analysis = parser.parse(COORDINATION)
    mentioned = {t.lemma for t in analysis.tokens}
    assert "crani" in mentioned and "serp" in mentioned
    members = [t for t in analysis.tokens if t.dep in ("obj", "conj")]
    assert len(members) >= 2, [t.to_dict() for t in analysis.tokens]


def test_negation_is_detected(parser: SpacySyntax) -> None:
    analysis = parser.parse(NEGATION)
    assert analysis.negations
    assert any(t.text.lower() == "no" for t in analysis.negations)
    assert not parser.parse(SINGULAR).negations


# --- condicions opt-in ------------------------------------------------------------------------


def rule_with_syntax(**syntax: object) -> PatternRule:
    return PatternRule(
        RuleDefinition.from_mapping(
            {
                "rule_id": "prova.sintaxi",
                "engine": "pattern",
                "pattern": [{"text": ["presenta", "presenten"], "group": "v"}],
                "transformation": "{v|inflect(mostrar,presenta=mostra,presenten=mostren)}",
                "conditions": {"syntax": syntax},
            }
        )
    )


def propose(rule: PatternRule, text: str, syntax: SyntaxProvider, paths: ProjectPaths) -> list[str]:
    lexicon = ClosedClassLexicon.load(paths.language())
    analyzer = RuleBasedAnalyzer(lexicon=lexicon)
    protected = default_protector(analyzer).protect(text)
    results: list[str] = []
    for sentence in analyzer.analyze(text).sentences:
        ctx = RuleContext(
            sentence=sentence,
            protected_spans=Protector.within(protected, sentence.span),
            document_text=text,
            lexicon=lexicon,
            syntax=syntax,
        )
        results.extend(t.apply(sentence.text) for t in rule.propose(ctx))
    return results


def test_syntactic_conditions_are_opt_in(parser: SpacySyntax, paths: ProjectPaths) -> None:
    """Una regla sense bloc «syntax» no consulta mai el parser."""
    plain = PatternRule(
        RuleDefinition.from_mapping(
            {
                "rule_id": "prova.sense",
                "engine": "pattern",
                "pattern": [{"text": ["presenta"], "group": "v"}],
                "transformation": "{v|inflect(mostrar,presenta=mostra)}",
            }
        )
    )
    assert propose(plain, SINGULAR, parser, paths) == ["Aquest sarcòfag mostra dos cranis."]
    assert propose(plain, SINGULAR, NullSyntax(), paths) == ["Aquest sarcòfag mostra dos cranis."]


def test_subject_number_condition(parser: SpacySyntax, paths: ProjectPaths) -> None:
    rule = rule_with_syntax(requires_parser=True, subject_number="pl")
    assert propose(rule, PLURAL, parser, paths) == ["Aquests sarcòfags mostren dos cranis."]
    assert propose(rule, SINGULAR, parser, paths) == []


def test_a_rule_that_needs_the_parser_stops_without_it(
    parser: SpacySyntax, paths: ProjectPaths
) -> None:
    """Davant del dubte, no es transforma."""
    rule = rule_with_syntax(requires_parser=True, subject_number="pl")
    assert propose(rule, PLURAL, NullSyntax(), paths) == []


def test_conditions_on_clauses_coordinations_and_negation(
    parser: SpacySyntax, paths: ProjectPaths
) -> None:
    assert propose(
        rule_with_syntax(requires_parser=True, no_negation=True), SINGULAR, parser, paths
    )
    negated = "No presenta dos cranis."
    assert (
        propose(rule_with_syntax(requires_parser=True, no_negation=True), negated, parser, paths)
        == []
    )
    assert propose(rule_with_syntax(requires_parser=True, max_clauses=0), SINGULAR, parser, paths)
    assert propose(
        rule_with_syntax(requires_parser=True, requires_subject=True), SINGULAR, parser, paths
    )
    assert (
        propose(
            rule_with_syntax(requires_parser=True, requires_subject=True),
            COORDINATION,
            parser,
            paths,
        )
        == []
    )


# --- integració amb la canonada -------------------------------------------------------------


def test_pipeline_exposes_the_parser(parser: SpacySyntax, project_root: Path) -> None:
    pipeline = build_pipeline(PipelineConfig(rule_set="parafrasi", level=3, home=project_root))
    assert pipeline.syntax.available
    result = pipeline.run(SINGULAR)
    assert result.output_text
    # El parser no ha afegit cap transformació per si mateix.
    for sentence in result.sentences:
        for evaluated in sentence.candidates:
            for transformation in evaluated.candidate.transformations:
                assert transformation.rule_id and not transformation.rule_id.startswith("syntax")
