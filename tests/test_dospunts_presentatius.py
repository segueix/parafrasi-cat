"""Cobertura sintàctica: dos punts explicatius i presentatius «hi ha … que …».

Les tres regles noves exigeixen l'analitzador sintàctic, i per això
`test_regles_definicions.py` se les salta. Aquí es comproven amb el parser
instal·lat: els exemples declarats a les regles, les proves negatives de
negació, modalitat, ambigüitat, dates i nombres romans, i el text que el motor
sencer acaba oferint.
"""

from __future__ import annotations

import pytest

from parafrasi_cat.analyzer.analysis import RuleBasedAnalyzer
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon
from parafrasi_cat.morphology.catalan import CatalanMorphology
from parafrasi_cat.morphology.provider import MorphologyProvider, NullMorphology
from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.config import PipelineConfig
from parafrasi_cat.pipeline.modes import apply_mode
from parafrasi_cat.protected.protector import Protector, default_protector
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.rules import RuleSet, RuleSetConfig, build_rule_set, default_registry
from parafrasi_cat.rules.base import Rule, RuleContext
from parafrasi_cat.syntax.analysis import CachedSyntax, SyntaxProvider
from parafrasi_cat.syntax.spacy_parser import SpacySyntax

COLON_RULE = "dospunts.explicacio_a_relativa_del_subjecte"
PRESENTATIVE_RULE = "presentatiu.hi_ha_np_relativa_a_subjecte"
BARE_PRESENTATIVE_RULE = "presentatiu.hi_ha_plural_nu_a_quantificador"


@pytest.fixture(scope="module")
def morphology(paths: ProjectPaths) -> MorphologyProvider:
    resource = CatalanMorphology.discover(paths.language())
    return resource if resource is not None else NullMorphology()


@pytest.fixture(scope="module")
def parser(morphology: MorphologyProvider) -> SyntaxProvider:
    found = SpacySyntax(morphology=morphology)
    if not found.available:
        pytest.skip("cal el parser local (scripts/install_parser.py)")
    return CachedSyntax(found)


@pytest.fixture(scope="module")
def rule_set(paths: ProjectPaths) -> RuleSet:
    return build_rule_set(
        RuleSetConfig.load(paths.rules / "parafrasi.yaml"), default_registry(), paths
    )


@pytest.fixture(scope="module")
def protector(catalan_analyzer: RuleBasedAnalyzer) -> Protector:
    return default_protector(catalan_analyzer)


def outputs(
    rule_set: RuleSet,
    rule_id: str,
    text: str,
    analyzer: RuleBasedAnalyzer,
    protector: Protector,
    parser: SyntaxProvider,
    lexicon: ClosedClassLexicon,
    morphology: MorphologyProvider,
) -> tuple[str, ...]:
    """Textos que la regla proposa per a una frase, amb analitzador sintàctic."""
    rule = rule_set.rule(rule_id)
    assert isinstance(rule, Rule)
    analysis = analyzer.analyze(text)
    protected = protector.protect(text)
    results: list[str] = []
    for sentence in analysis.sentences:
        ctx = RuleContext(
            sentence=sentence,
            protected_spans=Protector.within(protected, sentence.span),
            document_text=text,
            morphology=morphology,
            lexicon=lexicon,
            syntax=parser,
        )
        results.extend(t.apply(sentence.text) for t in rule.propose(ctx))
    return tuple(results)


@pytest.fixture
def propose(  # type: ignore[no-untyped-def]
    rule_set: RuleSet,
    catalan_analyzer: RuleBasedAnalyzer,
    protector: Protector,
    parser: SyntaxProvider,
    lexicon: ClosedClassLexicon,
    morphology: MorphologyProvider,
):
    def call(rule_id: str, text: str) -> tuple[str, ...]:
        return outputs(
            rule_set, rule_id, text, catalan_analyzer, protector, parser, lexicon, morphology
        )

    return call


# --- exemples declarats a les regles ---------------------------------------------------------


@pytest.mark.parametrize(
    "rule_id", [COLON_RULE, PRESENTATIVE_RULE, BARE_PRESENTATIVE_RULE]
)
def test_declared_examples_hold(  # type: ignore[no-untyped-def]
    rule_set: RuleSet, propose, rule_id: str
) -> None:
    definition = next(d for d in rule_set.definitions if d.rule_id == rule_id)
    for example in definition.positive_examples:
        assert example.output in propose(rule_id, example.input), example.input
    for example in definition.negative_examples:
        assert propose(rule_id, example.input) == (), example.input


# --- dos punts explicatius --------------------------------------------------------------------


def test_colon_explanation_becomes_a_relative_clause(propose) -> None:  # type: ignore[no-untyped-def]
    assert propose(
        COLON_RULE, "El rei no necessita gaire justificació: és el centre del tauler."
    ) == ("El rei, que és el centre del tauler, no necessita gaire justificació.",)


def test_colon_rule_never_introduces_a_causal_connector(propose) -> None:  # type: ignore[no-untyped-def]
    produced = propose(
        COLON_RULE, "El rei no necessita gaire justificació: és el centre del tauler."
    )
    assert all(
        marker not in text
        for text in produced
        for marker in ("perquè", "ja que", "atès que", "com que", "per tant")
    )


def test_colon_rule_keeps_negation_and_hedges(propose) -> None:  # type: ignore[no-untyped-def]
    text = "El rei potser no necessita cap justificació: sembla el centre del tauler."
    for produced in propose(COLON_RULE, text):
        assert "potser" in produced
        assert "no" in produced.split()
        assert "sembla" in produced


@pytest.mark.parametrize(
    "text",
    [
        # Enumeració: darrere dels dos punts no hi ha cap clàusula.
        "Les peces són tres: rei, reina i cavaller.",
        # Identificació nominal.
        "La categoria és aquesta: un home pròxim al rei.",
        # Relat: l'auxiliar de la perífrasi no és el verb de l'explicació.
        "El rei va caure aviat: va perdre la partida.",
        # L'explicació té subjecte propi: el subjecte el·líptic no és el mateix.
        "El rei no necessita justificació: els cavallers sí que en necessiten.",
        # Passat: fora del present descriptiu no se sap si explica o narra.
        "El rei no necessitava justificació: era el centre del tauler.",
        # Ja hi ha un incís entre el subjecte i els dos punts.
        "La reina, quan apareix, no necessita explicació: ocupa el lloc del poder.",
        # Discordança de nombre: el subjecte el·líptic és un altre.
        "El rei no necessita justificació: ocupen el lloc del poder.",
        # Data i xifres protegides dins d'una enumeració.
        "Les dates són dues: 1483 i 1495.",
        # Nombre romà en una identificació nominal.
        "El regnat és aquest: el de Ferran II.",
    ],
)
def test_colon_rule_declines(propose, text: str) -> None:  # type: ignore[no-untyped-def]
    assert propose(COLON_RULE, text) == ()


def test_colon_rule_keeps_dates_and_roman_numerals_intact(propose) -> None:  # type: ignore[no-untyped-def]
    text = "El rei no necessita justificació el 1483: ocupa el centre del tauler."
    for produced in propose(COLON_RULE, text):
        assert "1483" in produced
    text_roman = "El rei no necessita justificació al segle XV: ocupa el centre del tauler."
    for produced in propose(COLON_RULE, text_roman):
        assert "segle XV" in produced


# --- presentatius «hi ha … que …» ---------------------------------------------------------


def test_presentative_promotes_the_phrase_to_subject(propose) -> None:  # type: ignore[no-untyped-def]
    assert propose(
        PRESENTATIVE_RULE, "Però hi ha una peça que no encaixa tan fàcilment: l'orfil."
    ) == ("Però una peça no encaixa tan fàcilment: l'orfil.",)


def test_presentative_keeps_negation_and_hedges(propose) -> None:  # type: ignore[no-untyped-def]
    text = "Hi ha dues peces que no semblen conservar el nom llatí."
    produced = propose(PRESENTATIVE_RULE, text)
    assert produced == ("Dues peces no semblen conservar el nom llatí.",)


def test_presentative_keeps_quantifiers(propose) -> None:  # type: ignore[no-untyped-def]
    produced = propose(PRESENTATIVE_RULE, "Hi ha moltes peces que conserven el nom llatí.")
    assert produced == ("Moltes peces conserven el nom llatí.",)


@pytest.mark.parametrize(
    "text",
    [
        # Negació de l'existencial: promoure el sintagma l'afirmaria.
        "No hi ha cap peça que encaixi.",
        "Ja no hi ha peces que conservin el nom llatí.",
        # El relatiu no és el subjecte: quedaria un sintagma sense oració.
        "Hi ha coses que no entenc.",
        # Existencial subordinat.
        "Si hi ha una peça que no encaixa, la partida canvia.",
        "Quan hi ha una peça que no encaixa, la partida canvia.",
        # Existencial amb locatiu davant: no obre la frase.
        "En aquest sarcòfag hi ha dues peces que conserven el nom.",
        # Sense relatiu.
        "Hi ha dues peces al tauler.",
    ],
)
def test_presentative_declines(propose, text: str) -> None:  # type: ignore[no-untyped-def]
    assert propose(PRESENTATIVE_RULE, text) == ()
    assert propose(BARE_PRESENTATIVE_RULE, text) == ()


def test_presentative_keeps_dates_and_roman_numerals(propose) -> None:  # type: ignore[no-untyped-def]
    produced = propose(
        PRESENTATIVE_RULE, "Hi ha dues peces del segle XV que conserven el nom del 1483."
    )
    assert produced == ("Dues peces del segle XV conserven el nom del 1483.",)


# --- presentatiu amb plural nu: només amb gènere demostrat -----------------------------------


def test_bare_plural_needs_a_quantifier_that_agrees(propose) -> None:  # type: ignore[no-untyped-def]
    assert propose(BARE_PRESENTATIVE_RULE, "Hi ha llibres que expliquen la història del joc.") == (
        "Alguns llibres expliquen la història del joc.",
    )


def test_bare_plural_without_known_gender_is_left_alone(propose) -> None:  # type: ignore[no-untyped-def]
    """Sense evidència de gènere no s'inventa cap quantificador.

    «peces» no porta el tret de gènere ni a l'analitzador ni al recurs
    morfològic per defecte: la regla calla en lloc d'endevinar «alguns» o
    «algunes».
    """
    text = "Hi ha peces dels escacs que semblen haver conservat el seu nom."
    produced = propose(BARE_PRESENTATIVE_RULE, text)
    assert produced in ((), ("Algunes peces dels escacs semblen haver conservat el seu nom.",))


def test_bare_plural_rule_ignores_phrases_with_a_determiner(propose) -> None:  # type: ignore[no-untyped-def]
    assert propose(BARE_PRESENTATIVE_RULE, "Hi ha una peça que no encaixa.") == ()


# --- el motor sencer --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def deep_level3():  # type: ignore[no-untyped-def]
    config = apply_mode(PipelineConfig(rule_set="parafrasi"), "profund", 3)
    pipeline = build_pipeline(config)
    if not pipeline.syntax.available:
        pytest.skip("cal el parser local (scripts/install_parser.py)")
    return pipeline


def test_engine_offers_the_colon_rewrite(deep_level3) -> None:  # type: ignore[no-untyped-def]
    result = deep_level3.run(
        "El rei no necessita gaire justificació: és el centre del tauler i el centre del regne."
    )
    texts = [c.candidate.text for s in result.sentences for c in s.candidates]
    assert (
        "El rei, que és el centre del tauler i el centre del regne, no necessita gaire "
        "justificació." in texts
    )


def test_engine_offers_the_presentative_rewrite(deep_level3) -> None:  # type: ignore[no-untyped-def]
    result = deep_level3.run("Però hi ha una peça que no encaixa tan fàcilment: l'orfil.")
    texts = [c.candidate.text for s in result.sentences for c in s.candidates]
    assert "Però una peça no encaixa tan fàcilment: l'orfil." in texts
