"""Diversitat estructural del paràgraf guiada per l'empremta."""

from __future__ import annotations

from parafrasi_cat.style.diversity import structural_diversity_similarity
from parafrasi_cat.style.syntax_profile import SentenceSyntaxStats


def _stat(pattern: str) -> SentenceSyntaxStats:
    return SentenceSyntaxStats(
        n_tokens=8,
        clause_count=1,
        subordinates=(),
        subordination_depth_max=0,
        parse_depth_max=2,
        parse_depth_mean=1.0,
        coordinations=(),
        coordination_depth_max=0,
        conjunctions=(),
        nominal_modifiers=0,
        adjectival_modifiers=0,
        appositions=0,
        copular=0,
        passive=0,
        subjects_before=1,
        subjects_after=0,
        objects_before=0,
        objects_after=1,
        complements_preposed=0,
        complements_postposed=0,
        initial_oblique=False,
        initial_temporal=False,
        initial_locative=False,
        dependency_distances=(1, 2, 1),
        pattern=pattern,
    )


def _profile() -> dict[str, object]:
    # Empremta compatible amb les versions anteriors: no necessita cap camp nou,
    # només la distribució de patrons que ja guardava syntactic_profile.
    return {
        "available": True,
        "confidence": "high",
        "patterns": {
            "n_distinct": 8,
            "top": [
                {"pattern": "MAIN", "count": 25, "share": 0.25},
                {"pattern": "ADV + MAIN", "count": 20, "share": 0.20},
                {"pattern": "OBL + MAIN", "count": 15, "share": 0.15},
                {"pattern": "MAIN + REL", "count": 15, "share": 0.15},
            ],
        },
    }


def test_diverse_paragraph_scores_better_than_monotonous_one() -> None:
    repetitive = tuple(_stat("MAIN") for _ in range(6))
    diverse = tuple(
        _stat(pattern)
        for pattern in (
            "MAIN",
            "ADV + MAIN",
            "OBL + MAIN",
            "MAIN + REL",
            "MAIN",
            "ADV + MAIN",
        )
    )

    repetitive_score = structural_diversity_similarity(repetitive, _profile())
    diverse_score = structural_diversity_similarity(diverse, _profile())

    assert repetitive_score is not None and diverse_score is not None
    assert diverse_score[0] > repetitive_score[0]
    assert diverse_score[1]["concentracio"] > repetitive_score[1]["concentracio"]
    assert diverse_score[1]["ratxes"] > repetitive_score[1]["ratxes"]


def test_more_diversity_than_author_is_not_rewarded_above_one() -> None:
    stats = tuple(_stat(pattern) for pattern in ("A", "B", "C", "D"))
    result = structural_diversity_similarity(stats, _profile())
    assert result is not None
    assert result[0] == 1.0


def test_small_sample_and_low_confidence_do_not_invent_a_pattern() -> None:
    assert structural_diversity_similarity((_stat("MAIN"), _stat("MAIN")), _profile()) is None
    low = {**_profile(), "confidence": "low"}
    assert structural_diversity_similarity(tuple(_stat("MAIN") for _ in range(4)), low) is None
