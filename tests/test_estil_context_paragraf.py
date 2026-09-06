"""Estil global i veïnat real: regressió de «Tanmateix… Tanmateix» amb empremta."""

from dataclasses import replace

import pytest

from parafrasi_cat.candidates import Candidate
from parafrasi_cat.pipeline import PipelineConfig, build_pipeline
from parafrasi_cat.pipeline.modes import apply_mode
from parafrasi_cat.pipeline.paragraph_search import BeamState, LocalOption, ParagraphBeam
from parafrasi_cat.pipeline.result import EvaluatedCandidate
from parafrasi_cat.scoring.scorer import ScoreBreakdown
from parafrasi_cat.style.corpus import load_corpus
from parafrasi_cat.style.observations import StyleResources
from parafrasi_cat.style.profiler import build_fingerprint
from parafrasi_cat.validation.result import ValidationResult
from tests.test_seleccio_1317 import ORFIL


@pytest.fixture(scope="module")
def academic_profile(project_root, paths, catalan_analyzer, tmp_path_factory):
    fingerprint = build_fingerprint(
        load_corpus(project_root / "corpus/exemples/academic"),
        StyleResources.load(paths),
        catalan_analyzer,
        name="academic",
    )
    return fingerprint.save(tmp_path_factory.mktemp("academic") / "fingerprint.json")


def test_academic_draft_uses_selected_paragraph_context(academic_profile, monkeypatch):
    pipeline = build_pipeline(
        apply_mode(
            PipelineConfig(
                rule_set="parafrasi",
                syntax="none",
                languagetool=False,
                style_profile=str(academic_profile),
                source_mode="llm_draft",
            ),
            "profund",
            5,
        )
    )
    contexts = []
    search = ParagraphBeam.search

    def record(self, paragraph, sentences, protected, document=None):
        contexts.append(document)
        return search(self, paragraph, sentences, protected, document)

    monkeypatch.setattr(ParagraphBeam, "search", record)
    result = pipeline.run(ORFIL)
    assert pipeline.adaptation is not None
    assert contexts[1].before == pipeline.adaptation.stats_of(result.paragraphs[0].output_text)
    assert contexts[0].after == pipeline.adaptation.stats_of(result.paragraphs[1].source_text)
    assert result.source_text == ORFIL
    # Ha de reescriure sense introduir la repetició reportada entre paràgrafs.
    assert result.output_text != ORFIL
    assert result.output_text.count("Tanmateix") == 1
    assert "Així i tot, no resol el problema occidental." in result.output_text
    assert all(p.selected.accepted for p in result.paragraphs)
    for fact in (
        "Cessolis",
        "don Johan, que volia esser Rey e ara és arfil",
        "semblen haver conservat",
        "pot tenir algun valor remot",
        "només té sentit si",
    ):
        assert fact in result.output_text
    # Ni l'historial del pipeline ni el context de la passada anterior es filtren.
    assert pipeline.run(ORFIL).output_text == result.output_text


def test_beam_does_not_reward_local_style_twice():
    candidate = Candidate.identity(0, "Tanmateix, plou.")
    local = ScoreBreakdown(-0.4, {"estil": -0.4}, "estil local")
    option = LocalOption(
        0, EvaluatedCandidate(candidate, ValidationResult.passed(), local), "prova"
    )
    whole = ScoreBreakdown(-0.1, {"estil": -0.1}, "estil global")
    state = BeamState((option,), candidate, local.total, whole)
    better_local = replace(
        option,
        evaluated=replace(
            option.evaluated, score=ScoreBreakdown(-0.05, {"estil": -0.05}, "altre estil local")
        ),
    )
    alternative = replace(state, options=(better_local,), local_total=-0.05)
    assert state.partial_total == alternative.partial_total
    # Sense puntuació global encara es conserva l'avaluació local.
    assert replace(state, paragraph_score=None).partial_total == local.total
