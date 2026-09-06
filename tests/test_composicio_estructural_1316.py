"""1.3.16: composició estructural general i diversitat d'arquitectures.

Les proves són de propietats: no exigeixen una redacció concreta del motor,
sinó que una operació posterior pugui englobar fragments ja transformats
només quan la projecció sobre l'original és exacta, que la traça no perdi cap
operació i que dues arquitectures estructurals de la mateixa família no es
confonguin durant la poda.
"""

from __future__ import annotations

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.candidates.generator import CandidateGenerator
from parafrasi_cat.core import SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.core.transformation import TransformationFamily


def _make(
    text: str,
    before: str,
    after: str,
    rule_id: str,
    family: TransformationFamily,
    *,
    architecture: str = "",
    movement: str = "",
) -> Transformation:
    start = text.index(before)
    metadata = {"family": family.value, "category": "prova"}
    if architecture:
        metadata["architecture"] = architecture
    if movement:
        metadata["movement"] = movement
    return Transformation(
        rule_id=rule_id,
        text_before=before,
        text_after=after,
        changed_span=Span(start, start + len(before)),
        transformation_type=TransformationType.SYNTACTIC,
        confidence=0.9,
        semantic_risk=SemanticRisk.LOW,
        explanation=rule_id,
        metadata=metadata,
    )


def test_an_operation_can_envelope_two_previously_transformed_fragments() -> None:
    source = "alpha beta gamma delta"
    first = _make(
        source,
        "alpha",
        "ALPHA",
        "copula.alpha",
        TransformationFamily.COPULAR,
        architecture="copular",
    )
    second = _make(
        source,
        "gamma",
        "GAMMA",
        "subordinada.gamma",
        TransformationFamily.SUBORDINATION,
        architecture="subordinate",
    )
    base = Candidate.from_transformations(0, source, (first, second))
    proposal = _make(
        base.text,
        "ALPHA beta GAMMA",
        "GAMMA reorganitza ALPHA",
        "ordre.englobant",
        TransformationFamily.REORDER,
        movement="final→initial",
    )

    composed = CandidateGenerator(max_transformations=3).compose(base, proposal)

    assert composed is not None
    assert composed.text == "GAMMA reorganitza ALPHA delta"
    assert composed.n_transformations == 3
    assert composed.rule_ids == ("copula.alpha", "subordinada.gamma", "ordre.englobant")
    assert composed.families == (
        TransformationFamily.COPULAR,
        TransformationFamily.SUBORDINATION,
        TransformationFamily.REORDER,
    )
    assert len(composed.transformations) == 1  # una substitució física, tres operacions reals
    merged = composed.transformations[0]
    assert merged.operation_count == 3
    assert merged.metadata["composition"] == "envelope"
    assert merged.changed_span.slice(source) == "alpha beta gamma"


def test_envelope_can_cross_a_previous_deletion_without_losing_its_provenance() -> None:
    source = "abcXYZdef"
    reduction = _make(
        source,
        "XYZ",
        "",
        "subordinada.redueix",
        TransformationFamily.SUBORDINATION,
        architecture="relative_to_participial",
    )
    base = Candidate.from_transformations(0, source, (reduction,))
    assert base.text == "abcdef"
    proposal = _make(
        base.text,
        "bcde",
        "B",
        "ordre.reestructura",
        TransformationFamily.REORDER,
        movement="internal→initial",
    )

    composed = CandidateGenerator(max_transformations=2).compose(base, proposal)

    assert composed is not None
    assert composed.text == "aBf"
    assert composed.n_transformations == 2
    assert composed.rule_ids == ("subordinada.redueix", "ordre.reestructura")
    assert composed.transformations[0].changed_span == Span(1, 8)
    assert composed.transformations[0].changed_span.slice(source) == "bcXYZde"


def test_a_proposal_that_cuts_through_generated_text_is_rejected() -> None:
    source = "abcdefghij"
    previous = _make(
        source,
        "cdef",
        "WXYZ",
        "ordre.primer",
        TransformationFamily.REORDER,
        movement="initial→final",
    )
    base = Candidate.from_transformations(0, source, (previous,))
    proposal = _make(
        base.text,
        "YZgh",
        "Q",
        "ordre.parcial",
        TransformationFamily.REORDER,
        movement="final→initial",
    )

    assert CandidateGenerator(max_transformations=2).compose(base, proposal) is None


def test_chaining_inside_one_fragment_keeps_all_families_and_architectures() -> None:
    source = "alpha beta"
    previous = _make(
        source,
        "alpha",
        "A_LONG",
        "copula.alpha",
        TransformationFamily.COPULAR,
        architecture="copular_inversion",
    )
    base = Candidate.from_transformations(0, source, (previous,))
    proposal = _make(
        base.text,
        "LONG",
        "BREU",
        "ordre.intern",
        TransformationFamily.REORDER,
        movement="medial→initial",
    )

    composed = CandidateGenerator(max_transformations=2).compose(base, proposal)

    assert composed is not None
    assert composed.text == "A_BREU beta"
    assert composed.n_transformations == 2
    assert composed.rule_ids == ("copula.alpha", "ordre.intern")
    assert composed.families == (TransformationFamily.COPULAR, TransformationFamily.REORDER)
    assert "copular_inversion" in composed.operation_architectures[0]
    assert "medial→initial" in composed.operation_architectures[1]
    assert composed.structural_degree() > 0


def test_real_operation_count_still_caps_deep_composition() -> None:
    source = "alpha beta"
    first = _make(source, "alpha", "A_LONG", "r1", TransformationFamily.COPULAR)
    base = Candidate.from_transformations(0, source, (first,))
    second = _make(base.text, "LONG", "BREU", "r2", TransformationFamily.REORDER)
    generator = CandidateGenerator(max_transformations=2)
    twice = generator.compose(base, second)
    assert twice is not None and twice.n_transformations == 2

    third = _make(twice.text, "BREU", "X", "r3", TransformationFamily.SUBORDINATION)
    assert generator.compose(twice, third) is None


def test_same_family_can_have_two_distinct_structural_architectures() -> None:
    source = "alpha beta"
    left = Candidate.from_transformations(
        0,
        source,
        (
            _make(
                source,
                "alpha",
                "ALPHA",
                "blocs.mou",
                TransformationFamily.REORDER,
                movement="initial→final",
            ),
        ),
    )
    right = Candidate.from_transformations(
        0,
        source,
        (
            _make(
                source,
                "alpha",
                "A",
                "blocs.mou",
                TransformationFamily.REORDER,
                movement="final→initial",
            ),
        ),
    )

    assert left.signature == right.signature == "REORDER"
    assert left.diversity_signature != right.diversity_signature
    selected = CandidateGenerator(max_candidates=3).select(
        (Candidate.identity(0, source), left, right)
    )
    assert left in selected and right in selected


def test_serialized_candidate_exposes_real_operation_trace() -> None:
    source = "alpha beta"
    first = _make(source, "alpha", "A_LONG", "r1", TransformationFamily.COPULAR)
    base = Candidate.from_transformations(0, source, (first,))
    second = _make(
        base.text,
        "LONG",
        "BREU",
        "r2",
        TransformationFamily.REORDER,
        movement="medial→initial",
    )
    composed = CandidateGenerator(max_transformations=2).compose(base, second)
    assert composed is not None

    exported = composed.to_dict()
    assert exported["operation_count"] == 2
    assert exported["operation_rule_ids"] == ["r1", "r2"]
    assert len(exported["operation_architectures"]) == 2
    assert str(exported["architecture_signature"]).startswith("ARCH(")
