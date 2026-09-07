"""La composició reserva una alternativa estructural sense relaxar la validació."""
from dataclasses import replace

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.compose.options import choose_options
from parafrasi_cat.core import SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.pipeline.result import EvaluatedCandidate
from parafrasi_cat.scoring.scorer import ScoreBreakdown
from parafrasi_cat.validation.result import ValidationResult


def option(text, family, score, confidence=0.9):
    source = "El rei dirigia l’exèrcit durant la batalla."
    transformation = Transformation(
        rule_id='prova.' + family, text_before=source, text_after=text,
        changed_span=Span(0, len(source)),
        transformation_type=TransformationType.SYNTACTIC,
        confidence=confidence, semantic_risk=SemanticRisk.LOW, explanation='prova', metadata={'family': family},
    )
    return EvaluatedCandidate(Candidate.from_transformations(0, source, (transformation,)),
                              ValidationResult.passed(), ScoreBreakdown(score, {}, 'prova'))


def test_low_scoring_structural_option_has_a_reserved_slot():
    local = [option('Text local ' + str(i), 'LEXICAL', 1-i/10) for i in range(5)]
    structural = option('Durant la batalla, el rei dirigia l’exèrcit.', 'REORDER', .1)
    for wanted in (1, 2, 3, 10):
        picked = choose_options([*local, structural], wanted)
        assert structural in picked
        assert len(picked) <= wanted
        assert picked == choose_options([*local, structural], wanted)
    assert choose_options([*local, structural], 0) == ()


def test_greatest_structural_change_wins_and_rejections_never_enter():
    shallow = option('Durant la batalla, el rei dirigia l’exèrcit.', 'REORDER', 1, .5)
    deep = option('L’exèrcit era dirigit pel rei durant la batalla.', 'REORDER', .1)
    rejected = replace(deep, validation=ValidationResult.error('test', 'No vàlid'))
    assert choose_options([shallow, deep], 1) == (deep,)
    assert choose_options([shallow, rejected], 1) == (shallow,)
    assert choose_options([rejected], 3) == ()


def test_duplicate_wordings_keep_structural_trace_without_duplicate_cards():
    surface = option('Durant la batalla, el rei dirigia l’exèrcit.', 'LEXICAL', 1)
    structural = option(surface.candidate.text, 'REORDER', .1)
    picked = choose_options([surface, structural], 3)
    assert picked == (structural,)


def test_no_structural_option_does_not_fabricate_one():
    local = option('El monarca dirigia l’exèrcit durant la batalla.', 'LEXICAL', 1)
    assert choose_options([local], 3) == (local,)
