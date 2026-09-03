"""Generador de candidats: combinacions, deduplicació, límits, poda, profunditat i guardes."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from parafrasi_cat.candidates import Candidate, CandidateGenerator
from parafrasi_cat.core import ConfigError, SemanticRisk, Span, Transformation, TransformationType


def make(
    before: str, after: str, start: int, rule_id: str = "r", confidence: float = 0.8
) -> Transformation:
    return Transformation(
        rule_id=rule_id,
        text_before=before,
        text_after=after,
        changed_span=Span(start, start + len(before)),
        transformation_type=TransformationType.LEXICAL,
        confidence=confidence,
        semantic_risk=SemanticRisk.LOW,
        explanation=f"{before}→{after}",
    )


TEXT = "gairebé sempre plou i sovint neva"


def test_combinations_up_to_max_transformations() -> None:
    t1 = make("gairebé", "quasi", 0, "a")
    t2 = make("sovint", "freqüentment", 22, "b")
    t3 = make("neva", "nevisca", 29, "c")
    candidates = CandidateGenerator(max_transformations=3, max_candidates=50, max_depth=1).generate(
        0, TEXT, [t1, t2, t3]
    )
    texts = [c.text for c in candidates]
    assert texts[0] == TEXT
    assert len(candidates) == 1 + 3 + 3 + 1  # identitat, 3 soltes, 3 parelles, 1 trio
    assert "quasi sempre plou i freqüentment nevisca" in texts
    assert len(set(texts)) == len(texts)
    limited = CandidateGenerator(max_transformations=2, max_candidates=50, max_depth=1).generate(
        0, TEXT, [t1, t2, t3]
    )
    assert max(c.n_transformations for c in limited) == 2


def test_dedupe_limit_and_pruning() -> None:
    t1 = make("gairebé", "quasi", 0, "a")
    t2 = make("gairebé", "quasi", 0, "b")  # mateix resultat, altra regla → duplicat
    huge = make(TEXT, "x", 0, "c")  # canvia tot el text → podat pel canvi excessiu
    candidates = CandidateGenerator(max_depth=1).generate(0, TEXT, [t1, t2, huge])
    assert [c.text for c in candidates] == [TEXT, "quasi sempre plou i sovint neva"]
    capped = CandidateGenerator(max_candidates=2, max_depth=1).generate(
        0, TEXT, [t1, make("sempre", "tothora", 8, "d")]
    )
    assert len(capped) == 2
    with pytest.raises(ConfigError):
        CandidateGenerator(max_change_ratio=0)
    with pytest.raises(ConfigError):
        CandidateGenerator(max_depth=0)


def test_result_spans_follow_shifts() -> None:
    t1 = make("gairebé", "quasi", 0)
    t2 = make("sovint", "freqüentment", 22)
    candidate = Candidate.from_transformations(0, TEXT, [t1, t2])
    spans = candidate.result_spans()
    assert [s.slice(candidate.text) for s in spans] == ["quasi", "freqüentment"]


def test_depth_remaps_new_proposals_onto_the_source() -> None:
    t1 = make("gairebé", "quasi", 0, "a")

    def expand(text: str) -> Iterable[Transformation]:
        # Sobre «quasi sempre plou i sovint neva» proposem canviar «sovint» (posició desplaçada).
        start = text.find("sovint")
        return [make("sovint", "freqüentment", start, "b")] if start >= 0 else []

    candidates = CandidateGenerator(max_depth=2).generate(0, TEXT, [t1], expand=expand)
    texts = [c.text for c in candidates]
    assert "quasi sempre plou i freqüentment neva" in texts
    composed = next(c for c in candidates if c.text == "quasi sempre plou i freqüentment neva")
    assert composed.rule_ids == ("a", "b")
    assert all(t.can_apply_to(TEXT) for t in composed.transformations)  # relatives a l'original


def test_depth_chains_inside_a_previous_transformation_and_blocks_same_rule() -> None:
    t1 = make("gairebé sempre", "en general", 0, "reordena")

    def expand(text: str) -> Iterable[Transformation]:
        proposals = []
        start = text.find("general")
        if start >= 0:
            proposals.append(make("general", "GENERAL", start, "lexic"))
            proposals.append(
                make("en general", "sempre", 0, "reordena")
            )  # mateixa regla, mateix segment
        return proposals

    candidates = CandidateGenerator(max_depth=2).generate(0, TEXT, [t1], expand=expand)
    texts = [c.text for c in candidates]
    assert "en GENERAL plou i sovint neva" in texts
    assert "sempre plou i sovint neva" not in texts
    chained = next(c for c in candidates if "GENERAL" in c.text)
    assert chained.rule_ids == ("reordena",)
    assert chained.transformations[0].metadata["chained_rules"] == "lexic"
    assert "A continuació" in chained.transformations[0].explanation


def test_compose_rejects_proposals_that_straddle_a_boundary() -> None:
    generator = CandidateGenerator()
    base = Candidate.from_transformations(0, TEXT, [make("gairebé", "quasi", 0, "a")])
    straddling = make("quasi sempre", "x", 0, "b")  # travessa el límit del segment canviat
    assert generator.compose(base, straddling) is None
    assert (
        generator.compose(base, make("plou", "neva", 13, "a")) is not None
    )  # mateixa regla, altre segment
    assert generator.compose(base, make("plou", "plou", 13, "c")) is None  # identitat
