"""Regressions específiques de la v1.3.12: variants de connector dins del feix."""

from __future__ import annotations

from parafrasi_cat.candidates import Candidate, CandidateGenerator
from parafrasi_cat.core import SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.pipeline.paragraph_search import BeamSettings, ParagraphBeam
from parafrasi_cat.pipeline.result import EvaluatedCandidate, SentenceResult
from parafrasi_cat.scoring.scorer import ScoreBreakdown
from parafrasi_cat.validation.result import ValidationResult


def _connector_candidate(source: str, target: str, total: float) -> EvaluatedCandidate:
    before = "perquè"
    start = source.index(before)
    transformation = Transformation(
        rule_id=f"prova.connector.{target.replace(' ', '_')}",
        text_before=before,
        text_after=target,
        changed_span=Span(start, start + len(before)),
        transformation_type=TransformationType.CONNECTOR,
        confidence=0.8,
        semantic_risk=SemanticRisk.LOW,
        explanation="prova",
        metadata={"category": "connector"},
    )
    candidate = Candidate.from_transformations(0, source, [transformation])
    return EvaluatedCandidate(
        candidate,
        ValidationResult.passed(),
        ScoreBreakdown(total=total, components={}, explanation="prova"),
    )


def _identity(source: str) -> EvaluatedCandidate:
    return EvaluatedCandidate(
        Candidate(0, source, source, ()),
        ValidationResult.passed(),
        ScoreBreakdown(total=0.0, components={}, explanation="original"),
    )


def _beam() -> ParagraphBeam:
    return ParagraphBeam(
        settings=BeamSettings(beam_width=6, candidates_per_sentence=3),
        generator=CandidateGenerator(),
        scorer=None,  # type: ignore[arg-type] -- local_options no consulta el scorer
        validators=(),
        paragraph_rules=(),
        context_factory=None,  # type: ignore[arg-type] -- local_options no crea context
        rejection_reason=None,  # type: ignore[arg-type] -- local_options no rebutja propostes
    )


def test_beam_keeps_two_safe_connector_variants_with_same_signature() -> None:
    source = "El cavaller és reconeixible perquè la funció militar el fa transparent."
    ates = _connector_candidate(source, "atès que", 0.50)
    ja_que = _connector_candidate(source, "ja que", 0.49)
    result = SentenceResult(
        index=0,
        source_text=source,
        span=Span(0, len(source)),
        output_text=ates.candidate.text,
        candidates=(_identity(source), ates, ja_que),
        rejected_proposals=(),
        protected_spans=(),
    )

    options = _beam().local_options(result)
    transformed = [option for option in options if not option.candidate.is_identity]

    assert [option.candidate.signature for option in transformed] == ["CONNECTOR", "CONNECTOR"]
    assert {option.candidate.text for option in transformed} == {
        source.replace("perquè", "atès que"),
        source.replace("perquè", "ja que"),
    }
    assert transformed[1].reason == "variant segura de connector"


def test_beam_does_not_keep_unbounded_connector_synonyms() -> None:
    source = "Ho sabem perquè la font ho diu."
    first = _connector_candidate(source, "atès que", 0.50)
    second = _connector_candidate(source, "ja que", 0.49)
    third = _connector_candidate(source, "puix que", 0.48)
    result = SentenceResult(
        index=0,
        source_text=source,
        span=Span(0, len(source)),
        output_text=first.candidate.text,
        candidates=(_identity(source), first, second, third),
        rejected_proposals=(),
        protected_spans=(),
    )

    options = _beam().local_options(result)
    connector_options = [
        option for option in options if option.candidate.signature == "CONNECTOR"
    ]
    assert len(connector_options) == 2
