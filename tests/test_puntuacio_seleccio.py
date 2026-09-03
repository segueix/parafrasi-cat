"""Puntuació per dimensions, invalidació i selecció."""

from __future__ import annotations

import pytest

from parafrasi_cat.analyzer import RuleBasedAnalyzer
from parafrasi_cat.candidates import Candidate
from parafrasi_cat.core import ConfigError, SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.pipeline.result import EvaluatedCandidate
from parafrasi_cat.scoring import (
    DIMENSIONS,
    CompositeScorer,
    ScoringContext,
    ScoringWeights,
    rank,
    select_best,
)
from parafrasi_cat.style import StyleEvaluator, StyleProfile
from parafrasi_cat.validation import (
    GrammarHeuristicValidator,
    ValidationContext,
    ValidationDimension,
    ValidationResult,
    assess_grammar,
)

TEXT = "gairebé sempre plou al mercat"


def make(before: str, after: str, risk: SemanticRisk = SemanticRisk.LOW) -> Transformation:
    start = TEXT.index(before)
    return Transformation(
        rule_id="t",
        text_before=before,
        text_after=after,
        changed_span=Span(start, start + len(before)),
        transformation_type=TransformationType.LEXICAL,
        confidence=0.9,
        semantic_risk=risk,
        explanation="prova",
    )


def test_dimensions_are_reported_separately() -> None:
    changed = Candidate.from_transformations(0, TEXT, [make("gairebé", "quasi")])
    score = CompositeScorer().score(changed, ScoringContext(ValidationResult.passed(), TEXT))
    assert set(score.dimensions) == set(DIMENSIONS)
    assert score.valid and score.invalidating == ()
    assert score.dimensions["preservacio_factual"] == 1.0
    assert score.dimensions["preservacio_epistemologica"] == 1.0
    assert score.dimensions["compliment_terminologic"] == 1.0
    assert score.dimensions["gramaticalitat"] == 1.0
    assert score.dimensions["semblanca_estil"] is None
    assert 0 < (score.dimensions["grau_de_canvi"] or 0) < 0.5
    assert score.components["gramaticalitat"] == 0.0
    assert score.total == pytest.approx(0.9 * 0.75 / 3, abs=1e-4)
    assert "preservació factual 1.00" in score.describe_dimensions()
    assert score.to_dict()["valid"] is True
    identity = CompositeScorer().score(Candidate.identity(0, TEXT))
    assert (
        identity.dimensions["grau_de_canvi"] == 0.0 and identity.dimension("gramaticalitat") == 1.0
    )


def test_factual_error_invalidates_even_with_high_gain() -> None:
    changed = Candidate.from_transformations(0, TEXT, [make("gairebé", "quasi")])
    validation = ValidationResult.error("dates", "data alterada", ValidationDimension.FACTUAL)
    score = CompositeScorer().score(changed, ScoringContext(validation, TEXT))
    assert not score.valid
    assert score.total == -1.0
    assert score.dimensions["preservacio_factual"] == 0.0
    assert score.dimensions["preservacio_epistemologica"] == 1.0
    assert score.invalidating == ("data alterada",)
    assert "invalidat" in score.explanation
    epistemic = ValidationResult.error("epistemic", "certesa", ValidationDimension.EPISTEMIC)
    assert (
        CompositeScorer()
        .score(changed, ScoringContext(epistemic, TEXT))
        .dimensions["preservacio_epistemologica"]
        == 0.0
    )
    terms = ValidationResult.error("protected_terms", "terme", ValidationDimension.TERMINOLOGY)
    assert (
        CompositeScorer()
        .score(changed, ScoringContext(terms, TEXT))
        .dimensions["compliment_terminologic"]
        == 0.0
    )


def test_grammar_warnings_lower_the_score_and_errors_invalidate() -> None:
    changed = Candidate.from_transformations(0, TEXT, [make("gairebé", "quasi")])
    warning = ValidationResult.warning("grammar", "espais dobles", ValidationDimension.GRAMMAR)
    score = CompositeScorer().score(changed, ScoringContext(warning, TEXT))
    assert score.valid and score.dimensions["gramaticalitat"] == 0.85
    assert score.components["gramaticalitat"] == pytest.approx(-0.075)
    clean = CompositeScorer().score(changed, ScoringContext(ValidationResult.passed(), TEXT))
    assert score.total < clean.total
    error = ValidationResult.error("grammar", "desaparellats", ValidationDimension.GRAMMAR)
    bad = CompositeScorer().score(changed, ScoringContext(error, TEXT))
    assert not bad.valid and bad.dimensions["gramaticalitat"] == 0.0


def test_style_similarity_dimension(analyzer: RuleBasedAnalyzer) -> None:
    profile = StyleProfile(name="p", target_sentence_length=5, sentence_length_tolerance=1)
    scorer = CompositeScorer(ScoringWeights(style_distance=1.0), StyleEvaluator(profile, analyzer))
    score = scorer.score(Candidate.identity(0, "Plou molt avui i demà també plourà molt."))
    similarity = score.dimensions["semblanca_estil"]
    assert similarity is not None and 0.0 <= similarity < 1.0
    assert score.total < 0


def test_selection_skips_invalid_candidates() -> None:
    identity = Candidate.identity(0, TEXT)
    changed = Candidate.from_transformations(0, TEXT, [make("gairebé", "quasi")])
    scorer = CompositeScorer()
    invalid = ValidationResult.error("dates", "data", ValidationDimension.FACTUAL)
    items = [
        (changed, scorer.score(changed, ScoringContext(invalid, TEXT))),
        (identity, scorer.score(identity, ScoringContext(ValidationResult.passed(), TEXT))),
    ]
    best = select_best(items, lambda i: i[0], lambda i: i[1])
    assert best is not None and best[0].is_identity
    assert rank(items, lambda i: i[0], lambda i: i[1]) == [items[1]]
    assert select_best([items[0]], lambda i: i[0], lambda i: i[1]) is None
    valid_items = [
        (identity, scorer.score(identity)),
        (changed, scorer.score(changed)),
    ]
    ranked = rank(valid_items, lambda i: i[0], lambda i: i[1])
    assert [c.is_identity for c, _ in ranked] == [False, True]


def test_weights_include_grammar() -> None:
    weights = ScoringWeights.from_mapping({"grammar": 0.2})
    assert weights.grammar == 0.2 and weights.to_dict()["grammar"] == 0.2
    with pytest.raises(ConfigError):
        ScoringWeights(grammar=-1)


def test_grammar_heuristics() -> None:
    reference = "Va anar al mercat (ahir)."
    assert assess_grammar(reference, reference).score == 1.0
    contraction = assess_grammar("Va anar a el mercat (ahir).", reference)
    assert contraction.errors and "contracció" in contraction.errors[0]
    unbalanced = assess_grammar("Va anar al mercat (ahir.", reference)
    assert any("desaparellats" in e for e in unbalanced.errors)
    missing_end = assess_grammar("Va anar al mercat (ahir)", reference)
    assert any("puntuació final" in e for e in missing_end.errors)
    warnings = assess_grammar("va anar  al mercat mercat (ahir) .", reference)
    assert not warnings.errors
    assert {w.split(":")[0] for w in warnings.warnings} >= {
        "espais dobles",
        "paraula repetida",
        "espai abans d'un signe de puntuació",
        "la frase comença en minúscula",
    }
    assert warnings.score == pytest.approx(1 - 0.15 * len(warnings.warnings))
    assert assess_grammar("   ", reference).errors == ("el text és buit",)
    # Un defecte que ja tenia l'original no es penalitza.
    assert assess_grammar("De el mercat.", "De el mercat.").errors == ()
    validator = GrammarHeuristicValidator()
    source = "Va anar al mercat."
    ok = validator.validate(Candidate.identity(0, source), ValidationContext(source))
    assert ok.ok and ok.issues == ()
    bad = Candidate.from_transformations(
        0,
        source,
        [
            Transformation(
                "g",
                "al",
                "a el",
                Span(8, 10),
                TransformationType.LEXICAL,
                0.9,
                SemanticRisk.LOW,
                "x",
            )
        ],
    )
    result = validator.validate(bad, ValidationContext(source))
    assert not result.ok and result.errors[0].dimension is ValidationDimension.GRAMMAR


def test_evaluated_candidate_reports_rejection_reason() -> None:
    changed = Candidate.from_transformations(0, TEXT, [make("gairebé", "quasi")])
    validation = ValidationResult.error("dates", "data alterada", ValidationDimension.FACTUAL)
    score = CompositeScorer().score(changed, ScoringContext(validation, TEXT))
    evaluated = EvaluatedCandidate(changed, validation, score)
    assert not evaluated.accepted
    assert evaluated.rejection_reason == "data alterada"
    assert evaluated.importance == pytest.approx(0.9)
    assert evaluated.to_dict()["accepted"] is False
    accepted = EvaluatedCandidate(
        changed, ValidationResult.passed(), CompositeScorer().score(changed)
    )
    assert accepted.accepted and accepted.rejection_reason == ""
