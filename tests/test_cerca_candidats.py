"""Cerca de candidats: la reserva inicial no pot ofegar l'expansió estructural.

Tres blocs:

1. Pressupostos: la reserva base se satura amb variants superficials i, tot i
   així, l'expansió de segon nivell continua tenint marge; el feix d'expansió
   conserva la diversitat estructural.
2. Admissió: la reparació, la validació i la puntuació decideixen qui ocupa
   plaça, es consulten amb memòria cau i els candidats invàlids no en gasten cap
   però continuen explicats.
3. Comportament complet a la canonada, amb les proteccions intactes.

Cap test no exigeix una sortida literal: totes són propietats.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.candidates.generator import (
    BUDGET,
    DUPLICATE,
    EXCESSIVE,
    SAFETY,
    SCORE,
    CandidateAssessment,
    CandidateGenerator,
)
from parafrasi_cat.core import SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.config import PipelineConfig
from parafrasi_cat.pipeline.modes import RewriteMode, apply_mode
from parafrasi_cat.pipeline.pipeline import Pipeline

WORDS = ("alfa", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta")
SOURCE = "El text diu " + ", ".join(WORDS) + " i prou."
FRONTED = "Diu el text"


def _transformation(
    source: str,
    before: str,
    after: str,
    rule_id: str,
    *,
    kind: TransformationType = TransformationType.LEXICAL,
    confidence: float = 0.95,
    family: str = "",
    category: str = "lexic",
) -> Transformation:
    start = source.index(before)
    metadata = {"category": category, **({"family": family} if family else {})}
    return Transformation(
        rule_id=rule_id,
        text_before=before,
        text_after=after,
        changed_span=Span(start, start + len(before)),
        transformation_type=kind,
        confidence=confidence,
        semantic_risk=SemanticRisk.LOW,
        explanation="prova",
        metadata=metadata,
    )


def _surface(source: str = SOURCE) -> list[Transformation]:
    """Un retoc lèxic independent per paraula: prou per saturar la reserva base."""
    return [_transformation(source, word, word.upper(), f"lexic.{word}") for word in WORDS]


def _reorder(source: str = SOURCE) -> Transformation:
    """Una reordenació segura, menys confiada que els retocs però estructural."""
    return _transformation(
        source,
        "El text diu",
        FRONTED,
        "ordre.inversio",
        kind=TransformationType.SYNTACTIC,
        confidence=0.7,
        family="REORDER",
        category="ordre",
    )


# --- 1. pressupostos --------------------------------------------------------------------------


def test_the_expansion_budget_is_explicit_and_above_the_base_pool() -> None:
    generator = CandidateGenerator(max_candidates=24, beam_width=6)
    assert generator.expansion_budget > 0
    assert generator.work_limit == generator.pool_limit + generator.expansion_budget
    assert generator.pool_limit >= generator.max_candidates
    tuned = CandidateGenerator(max_candidates=24, expansion_budget=3)
    assert tuned.expansion_budget == 3
    with pytest.raises(ConfigError):
        CandidateGenerator(expansion_budget=-1)


def test_a_saturated_pool_still_leaves_room_for_the_second_level() -> None:
    """La regressió de fons: amb prou variants superficials, l'expansió no s'arribava a cridar."""
    generator = CandidateGenerator(max_transformations=3, max_candidates=24, max_depth=2)
    calls: list[str] = []

    def expand(text: str) -> list[Transformation]:
        calls.append(text)
        if text.startswith(FRONTED):
            return [_transformation(text, "i prou", "i res més", "lexic.prou")]
        return []

    result = generator.search(0, SOURCE, [*_surface(), _reorder()], expand=expand)

    assert result.trace.truncated, "la reserva base no s'ha saturat"
    assert result.trace.generated >= generator.pool_limit - 1
    assert calls, "l'expansió no s'ha arribat a cridar"
    assert result.trace.expansion_calls == len(calls)
    assert result.trace.expanded >= 1
    assert result.trace.generated <= generator.work_limit


def test_the_expansion_beam_keeps_structural_diversity() -> None:
    """Tres retocs lèxics sumen més confiança que una reordenació: no l'han de desplaçar."""
    generator = CandidateGenerator(max_transformations=3, max_candidates=24, beam_width=6)
    expanded: list[str] = []

    def expand(text: str) -> list[Transformation]:
        expanded.append(text)
        return []

    generator.search(0, SOURCE, [*_surface(), _reorder()], expand=expand)

    assert any(text.startswith(FRONTED) for text in expanded), expanded[:3]
    assert len(expanded) <= 6


def test_the_structural_alternative_survives_the_final_selection() -> None:
    generator = CandidateGenerator(max_transformations=3, max_candidates=6)
    candidates = generator.generate(0, SOURCE, [*_surface(), _reorder()])
    assert len(candidates) <= 6
    assert any("ordre.inversio" in c.rule_ids for c in candidates)
    assert candidates[0].is_identity


def test_the_expansion_produces_a_useful_safe_alternative() -> None:
    """Una regla que només encaixa amb el text ja reordenat ha d'arribar a la tria."""
    generator = CandidateGenerator(max_transformations=3, max_candidates=24)

    def expand(text: str) -> list[Transformation]:
        if not text.startswith(FRONTED):
            return []
        return [
            _transformation(
                text,
                "i prou",
                "perquè no cal res més",
                "subordinada.causal",
                kind=TransformationType.SYNTACTIC,
                confidence=0.75,
                family="SUBORDINATION",
                category="subordinada",
            )
        ]

    result = generator.search(0, SOURCE, [*_surface(), _reorder()], expand=expand)
    chained = [
        c for c in result.candidates if {"ordre.inversio", "subordinada.causal"} <= set(c.rule_ids)
    ]
    assert chained, [c.rule_ids for c in result.candidates]
    for candidate in chained:
        assert candidate.text.startswith(FRONTED)
        assert "perquè no cal res més" in candidate.text
    # És una alternativa que la generació base no podia construir: la regla
    # causal no encaixa amb el text original.
    assert not any(
        "subordinada.causal" in c.rule_ids and "ordre.inversio" not in c.rule_ids
        for c in result.candidates
    )


# --- 2. admissió ------------------------------------------------------------------------------


def test_invalid_candidates_do_not_take_the_places_of_valid_ones() -> None:
    generator = CandidateGenerator(max_transformations=1, max_candidates=4)
    proposals = _surface()
    banned = {"ALFA", "BETA", "GAMMA"}

    def admissible(candidate: Candidate) -> CandidateAssessment:
        invalid = any(word in candidate.text for word in banned)
        return CandidateAssessment(candidate, valid=not invalid, reason="prova" if invalid else "")

    result = generator.search(0, SOURCE, proposals, admissible=admissible)

    assert len(result.candidates) == 4  # l'original i tres alternatives vàlides
    assert all(not any(word in c.text for word in banned) for c in result.candidates)
    assert len(result.rejected) == len(banned)
    assert result.trace.discarded[SAFETY] == len(banned)
    # Sense admissió, les places se les enduien els candidats invàlids.
    without = generator.generate(0, SOURCE, proposals)
    assert any(any(word in c.text for word in banned) for c in without)


def test_the_admission_is_consulted_once_per_candidate() -> None:
    generator = CandidateGenerator(max_transformations=2, max_candidates=8)
    seen: list[str] = []

    def admissible(candidate: Candidate) -> CandidateAssessment:
        seen.append(candidate.text)
        return CandidateAssessment(candidate)

    result = generator.search(0, SOURCE, _surface(), admissible=admissible)

    assert len(seen) == len(set(seen)), "s'ha consultat dues vegades el mateix candidat"
    assert result.trace.assessed == len(seen)
    # Mandra: només s'avalua el que està a punt d'entrar, no tota la reserva.
    assert result.trace.assessed <= len(result.candidates) + len(result.rejected)
    assert result.trace.assessed < result.trace.generated


def test_the_admission_may_replace_the_candidate_with_its_repair() -> None:
    generator = CandidateGenerator(max_transformations=1, max_candidates=4)

    def admissible(candidate: Candidate) -> CandidateAssessment:
        repaired = Candidate(
            candidate.sentence_index,
            candidate.source_text,
            candidate.text.replace("ALFA", "Alfa"),
            candidate.transformations,
        )
        return CandidateAssessment(repaired)

    result = generator.search(0, SOURCE, _surface()[:2], admissible=admissible)
    assert all("ALFA" not in c.text for c in result.candidates)
    assert any("Alfa" in c.text for c in result.candidates)


def test_the_original_is_always_kept_and_comes_first() -> None:
    generator = CandidateGenerator(max_transformations=3, max_candidates=3)

    def admissible(candidate: Candidate) -> CandidateAssessment:
        return CandidateAssessment(candidate, valid=candidate.is_identity)

    result = generator.search(0, SOURCE, _surface(), admissible=admissible)
    assert result.candidates[0].is_identity
    assert len(result.candidates) == 1, "sense alternativa segura no se'n força cap"


def test_the_trace_records_why_each_candidate_falls() -> None:
    generator = CandidateGenerator(max_transformations=2, max_candidates=3)
    duplicate = _transformation(SOURCE, "alfa", "ALFA", "lexic.copia")
    huge = _transformation(SOURCE, SOURCE[:-1], "Res.", "lexic.enorme")

    def admissible(candidate: Candidate) -> CandidateAssessment:
        return CandidateAssessment(candidate, valid="BETA" not in candidate.text)

    result = generator.search(0, SOURCE, [*_surface(), duplicate, huge], admissible=admissible)
    discarded = result.trace.discarded
    assert discarded.get(DUPLICATE, 0) >= 1
    assert discarded.get(EXCESSIVE, 0) >= 1
    assert discarded.get(SAFETY, 0) >= 1
    assert discarded.get(SCORE, 0) >= 1, "els que no s'arriben a mirar també es compten"
    assert set(discarded) <= {DUPLICATE, EXCESSIVE, BUDGET, SAFETY, SCORE}
    exported = result.trace.to_dict()
    assert exported["selected"] == len(result.candidates)
    assert exported["discarded"] == dict(sorted(discarded.items()))
    assert "descartats" in result.trace.describe()


def test_the_pool_is_bounded_even_with_many_proposals() -> None:
    generator = CandidateGenerator(max_transformations=3, max_candidates=10)
    result = generator.search(0, SOURCE, _surface())
    assert len(result.candidates) <= 10
    assert result.trace.generated <= generator.work_limit
    # El que sobra de la reserva cau per puntuació, no per pressupost: hi cabia.
    assert result.trace.discarded[SCORE] == result.trace.generated - (len(result.candidates) - 1)

    # Amb la reserva plena, la traça ho diu i el sostre es respecta.
    tight = CandidateGenerator(max_transformations=3, max_candidates=24)
    saturated = tight.search(0, SOURCE, _surface())
    assert saturated.trace.truncated
    assert saturated.trace.generated == tight.pool_limit - 1  # l'original no hi compta
    assert "reserva plena" in saturated.trace.describe()


def test_the_search_is_deterministic() -> None:
    generator = CandidateGenerator(max_transformations=3, max_candidates=8)

    def expand(text: str) -> list[Transformation]:
        if text.startswith(FRONTED):
            return [_transformation(text, "i prou", "i res més", "lexic.prou")]
        return []

    proposals = [*_surface(), _reorder()]
    first = generator.search(0, SOURCE, proposals, expand=expand)
    second = generator.search(0, SOURCE, proposals, expand=expand)
    assert [c.text for c in first.candidates] == [c.text for c in second.candidates]
    assert first.trace.to_dict() == second.trace.to_dict()


# --- 3. la canonada ---------------------------------------------------------------------------

ALTOVITI = (
    "La primera referència itàlica és el monument funerari d’Oddo Altoviti, encarregat el 1507 "
    "i finalitzat el 1516."
)
FACTS = ("Oddo Altoviti", "1507", "1516")


@pytest.fixture(scope="module")
def deep(project_root: Path) -> Pipeline:
    config = apply_mode(
        PipelineConfig(home=project_root, rule_set="parafrasi", languagetool=False),
        RewriteMode.DEEP,
        5,
    )
    return build_pipeline(config)


def test_the_pipeline_reports_the_search(deep: Pipeline) -> None:
    result = deep.run(ALTOVITI)
    sentence = result.sentences[0]
    trace = sentence.generation
    assert trace.proposals > 0
    assert trace.selected == len([e for e in sentence.candidates if e.accepted])
    assert trace.assessed >= trace.selected
    assert "Cerca:" in result.report()
    exported = sentence.to_dict()["generation"]
    assert isinstance(exported, dict) and exported["proposals"] == trace.proposals


def test_the_pipeline_expands_and_keeps_the_protections(deep: Pipeline) -> None:
    result = deep.run(ALTOVITI)
    sentence = result.sentences[0]
    assert sentence.generation.expansion_calls > 0
    for evaluated in sentence.candidates:
        if evaluated.accepted:
            for fact in FACTS:
                assert fact in evaluated.candidate.text, evaluated.candidate.text
    for fact in FACTS:
        assert fact in result.output_text


def test_rejected_candidates_are_still_explained(deep: Pipeline) -> None:
    """No ocupen plaça, però el resultat continua dient per què s'han descartat."""
    result = deep.run(ALTOVITI)
    for sentence in result.sentences:
        for evaluated in sentence.candidates:
            if not evaluated.accepted:
                assert evaluated.rejection_reason
        accepted = [e for e in sentence.candidates if e.accepted]
        assert len(accepted) <= deep.generator.max_candidates


def test_no_safe_alternative_leaves_the_sentence_alone(deep: Pipeline) -> None:
    text = "Hi havia dos cranis."
    result = deep.run(text)
    assert result.output_text == text
    assert result.sentences[0].generation.selected >= 1


def test_the_pipeline_is_deterministic(deep: Pipeline) -> None:
    first = deep.run(ALTOVITI)
    second = deep.run(ALTOVITI)
    assert first.output_text == second.output_text
    assert first.sentences[0].generation.to_dict() == second.sentences[0].generation.to_dict()
