"""Selecció: un canvi superficial ha de justificar-se; l'original guanya si no ho fa.

Tres defectes reproduïts abans de tocar res, tots tres amb la frase real de la
mostra:

1. El guany per transformacions es cobrava pel sol fet d'haver-hi un canvi, molt
   per damunt de la penalització per degradació estructural: «perquè» → «ja que»
   guanyava tot i baixar ``qualitat_sintactica`` d'1 a 0,8.
2. Amb el perfil d'estil per defecte, la distància només depèn de la longitud
   mitjana de frase: allargar el connector («Però» → «No obstant això,») acostava
   la frase a l'objectiu i feia guanyar el candidat més llarg.
3. Una substitució de connector absorbida dins d'una reordenació eixamplava la
   substitució física i, amb ella, el grau de reredacció estructural.
"""

from __future__ import annotations

import pytest

from parafrasi_cat.analyzer.analysis import RuleBasedAnalyzer
from parafrasi_cat.candidates import Candidate
from parafrasi_cat.core import SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.core.transformation import (
    CHAINED_FAMILIES_KEY,
    CHAINED_RULES_KEY,
    OPERATION_COUNT_KEY,
    STRUCTURAL_EXTENT_KEY,
)
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.scoring.scorer import UNJUSTIFIED_SURFACE, CompositeScorer, ScoringContext
from parafrasi_cat.scoring.selection import rank, select_best
from parafrasi_cat.scoring.weights import ScoringWeights
from parafrasi_cat.style.evaluator import StyleEvaluator
from parafrasi_cat.style.profile import load_style_profile
from parafrasi_cat.validation.result import ValidationResult

SENTENCE = "Però hi ha una peça que no encaixa tan fàcilment: l'orfil."
CAUSAL = "Hi ha peces dels escacs que han conservat el nom perquè la seva funció era clara."


def _transformation(
    text: str,
    before: str,
    after: str,
    *,
    rule_id: str,
    family: str,
    kind: TransformationType = TransformationType.CONNECTOR,
) -> Transformation:
    start = text.index(before)
    return Transformation(
        rule_id=rule_id,
        text_before=before,
        text_after=after,
        changed_span=Span(start, start + len(before)),
        transformation_type=kind,
        confidence=0.8,
        semantic_risk=SemanticRisk.LOW,
        explanation="prova",
        metadata={"category": "prova", "family": family},
    )


def _connector(text: str, before: str, after: str) -> Candidate:
    return Candidate.from_transformations(
        0,
        text,
        [_transformation(text, before, after, rule_id="prova.connector", family="CONNECTOR")],
    )


@pytest.fixture(scope="module")
def style(paths: ProjectPaths, catalan_analyzer: RuleBasedAnalyzer) -> StyleEvaluator:
    """El perfil per defecte: la distància només depèn de la longitud de frase."""
    profile = load_style_profile(paths.style / "default.yaml")
    return StyleEvaluator(profile, catalan_analyzer)


@pytest.fixture
def scorer(style: StyleEvaluator) -> CompositeScorer:
    return CompositeScorer(ScoringWeights(structure=0.35), style_evaluator=style)


# --- 1. cap premi per canviar per canviar -----------------------------------------------------


def test_a_connector_swap_without_benefit_earns_nothing(scorer: CompositeScorer) -> None:
    ctx = ScoringContext(ValidationResult.passed(), SENTENCE)
    score = scorer.score(_connector(SENTENCE, "Però", "No obstant això,"), ctx)
    assert score.components["transformacions"] == 0.0
    assert UNJUSTIFIED_SURFACE in score.explanation


def test_the_original_wins_when_nothing_improves(scorer: CompositeScorer) -> None:
    ctx = ScoringContext(ValidationResult.passed(), SENTENCE)
    original = Candidate.identity(0, SENTENCE)
    swaps = [
        _connector(SENTENCE, "Però", "No obstant això,"),
        _connector(SENTENCE, "Però", "Tanmateix,"),
        _connector(SENTENCE, "Però", "Així i tot,"),
    ]
    items = [original, *swaps]
    best = select_best(items, lambda c: c, lambda c: scorer.score(c, ctx))
    assert best is original


def test_a_longer_connector_does_not_buy_style(scorer: CompositeScorer) -> None:
    """La longitud de frase no es mou per als canvis que no reorganitzen res."""
    ctx = ScoringContext(ValidationResult.passed(), SENTENCE)
    original = scorer.score(Candidate.identity(0, SENTENCE), ctx)
    longer = scorer.score(_connector(SENTENCE, "Però", "No obstant això,"), ctx)
    shorter = scorer.score(_connector(SENTENCE, "Però", "Tanmateix,"), ctx)
    assert longer.components["estil"] == pytest.approx(original.components["estil"])
    assert shorter.components["estil"] == pytest.approx(original.components["estil"])
    assert longer.total == pytest.approx(shorter.total)


def test_a_structural_candidate_still_earns_its_gain(scorer: CompositeScorer) -> None:
    ctx = ScoringContext(ValidationResult.passed(), SENTENCE)
    structural = Candidate.from_transformations(
        0,
        SENTENCE,
        [
            _transformation(
                SENTENCE,
                "hi ha una peça que",
                "una peça",
                rule_id="prova.presentatiu",
                family="SYNTACTIC",
                kind=TransformationType.SYNTACTIC,
            )
        ],
    )
    score = scorer.score(structural, ctx)
    assert score.components["transformacions"] > 0
    assert score.components["estructura"] > 0
    assert score.total > scorer.score(Candidate.identity(0, SENTENCE), ctx).total


def test_an_avoided_word_still_justifies_a_surface_change(
    paths: ProjectPaths, catalan_analyzer: RuleBasedAnalyzer
) -> None:
    """El guany no desapareix: només deixa de ser automàtic."""
    profile = load_style_profile(paths.style / "default.yaml")
    from dataclasses import replace

    avoiding = replace(profile, avoided_words=("però",))
    scorer = CompositeScorer(
        ScoringWeights(structure=0.35),
        style_evaluator=StyleEvaluator(avoiding, catalan_analyzer),
    )
    ctx = ScoringContext(ValidationResult.passed(), SENTENCE)
    score = scorer.score(_connector(SENTENCE, "Però", "Tanmateix,"), ctx)
    assert score.components["transformacions"] > 0
    assert UNJUSTIFIED_SURFACE not in score.explanation


# --- 2. qualitat sintàctica ---------------------------------------------------------------


def test_the_syntactic_quality_reports_the_added_subordinator(
    paths: ProjectPaths, catalan_analyzer: RuleBasedAnalyzer
) -> None:
    """«perquè» → «ja que» afegeix un «que»: la mètrica ho ha de dir i ha de manar."""
    from parafrasi_cat.style.degradation import StructuralDegradation

    scorer = CompositeScorer(
        ScoringWeights(structure=0.35),
        style_evaluator=StyleEvaluator(
            load_style_profile(paths.style / "default.yaml"), catalan_analyzer
        ),
        degradation=StructuralDegradation(catalan_analyzer),
    )
    ctx = ScoringContext(ValidationResult.passed(), CAUSAL)
    candidate = _connector(CAUSAL, "perquè", "ja que")
    score = scorer.score(candidate, ctx)
    quality = score.dimension("qualitat_sintactica")
    assert quality is not None and quality < 1.0
    assert "subordinant" in " ".join(score.degradation_reasons)
    assert score.total < scorer.score(Candidate.identity(0, CAUSAL), ctx).total


# --- 3. estructures i variants absorbides -------------------------------------------------


def _composed(text: str) -> Candidate:
    """Una reordenació que ha absorbit un canvi de connector, com fa el generador."""
    start = 0
    before = text[: text.index(":")]
    after = before.replace("Però hi ha una peça que", "Tanmateix, una peça")
    transformation = Transformation(
        rule_id="prova.presentatiu",
        text_before=before,
        text_after=after,
        changed_span=Span(start, start + len(before)),
        transformation_type=TransformationType.SYNTACTIC,
        confidence=0.8,
        semantic_risk=SemanticRisk.LOW,
        explanation="prova",
        metadata={
            "category": "prova",
            "family": "SYNTACTIC",
            CHAINED_RULES_KEY: "prova.connector",
            CHAINED_FAMILIES_KEY: "CONNECTOR",
            OPERATION_COUNT_KEY: "2",
            STRUCTURAL_EXTENT_KEY: str(len("hi ha una peça que")),
        },
    )
    return Candidate.from_transformations(0, text, [transformation])


def test_an_absorbed_connector_does_not_inflate_the_structural_degree() -> None:
    simple = Candidate.from_transformations(
        0,
        SENTENCE,
        [
            _transformation(
                SENTENCE,
                "hi ha una peça que",
                "una peça",
                rule_id="prova.presentatiu",
                family="SYNTACTIC",
                kind=TransformationType.SYNTACTIC,
            )
        ],
    )
    composed = _composed(SENTENCE)
    assert composed.structural_degree() == pytest.approx(simple.structural_degree())
    assert composed.n_transformations == 2
    assert simple.n_transformations == 1


def test_the_tie_break_prefers_fewer_real_operations(scorer: CompositeScorer) -> None:
    ctx = ScoringContext(ValidationResult.passed(), SENTENCE)
    simple = Candidate.from_transformations(
        0,
        SENTENCE,
        [
            _transformation(
                SENTENCE,
                "hi ha una peça que",
                "una peça",
                rule_id="prova.presentatiu",
                family="SYNTACTIC",
                kind=TransformationType.SYNTACTIC,
            )
        ],
    )
    composed = _composed(SENTENCE)
    items = [composed, simple]
    best = select_best(items, lambda c: c, lambda c: scorer.score(c, ctx))
    assert best is simple
    assert rank(items, lambda c: c, lambda c: scorer.score(c, ctx))[0] is simple
