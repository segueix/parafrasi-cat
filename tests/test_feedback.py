"""Fase 6: feedback manual sobre variants, persistència i efecte en la puntuació."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from parafrasi_cat import PipelineConfig, build_pipeline
from parafrasi_cat.cli import main
from parafrasi_cat.core import ConfigError, ResourceError
from parafrasi_cat.preferences import (
    DEFAULT_PRIOR,
    AuthorPreferences,
    FeedbackCounts,
    FeedbackStore,
    PreferenceLevel,
    PreferenceResolver,
)
from parafrasi_cat.preferences.cli import build_feedback_parser, feedback_file, feedback_main
from parafrasi_cat.resources import ProjectPaths

SARCOFAG = (
    "En aquest sarcòfag fet per l’escultor Benedetto da Rovezzano hi ha la presència de dos "
    "cranis acompanyats de dos ossos creuats, així com dues serps també creuades."
)


def test_record_and_counts() -> None:
    store = FeedbackStore()
    assert not store.forms and len(store) == 0 and store.path is None
    for _ in range(4):
        store.record("obra de", "preferred")
    store.record("obra de", "acceptable", times=2)
    store.record("Fet per", "rejected", 3)
    store.record("fet per", "acceptable")
    assert store.counts_of("obra de") == FeedbackCounts(4, 2, 0)
    assert store.counts_of("FET PER") == FeedbackCounts(0, 1, 3)
    assert store.forms == ("Fet per", "obra de")
    assert store.counts_of("realitzat per") is None and store.weight_of("realitzat per") is None
    assert len(store) == 2 and not store.is_empty
    with pytest.raises(ConfigError):
        store.record("obra de", "meh")
    with pytest.raises(ConfigError):
        store.record("  ", "preferred")
    with pytest.raises(ConfigError):
        store.record("obra de", "preferred", times=0)
    with pytest.raises(ConfigError):
        FeedbackCounts(preferred=-1)
    with pytest.raises(ConfigError):
        FeedbackStore(prior=-1)
    assert FeedbackCounts(4, 2, 0).describe() == "preferida 4 vegades, acceptable 2 i rebutjada 0"
    assert FeedbackCounts(4, 2, 0).to_dict() == {"preferred": 4, "acceptable": 2, "rejected": 0}
    assert store.summary().count("«") == 2 and "prior 3" in store.summary()
    assert FeedbackStore().summary() == "Cap variant amb feedback"
    assert store.source_label == "feedback de l'autor"


def test_weights_are_smoothed_so_one_decision_is_not_drastic() -> None:
    assert FeedbackCounts().weight() == 0.5
    one = FeedbackCounts(preferred=1).weight()
    assert one == pytest.approx(0.625) and 0.5 < one < 0.7
    assert FeedbackCounts(rejected=1).weight() == pytest.approx(0.375)
    assert FeedbackCounts(preferred=10).weight() == pytest.approx(11.5 / 13)
    assert FeedbackCounts(preferred=4, acceptable=2).weight() == pytest.approx(6.5 / 9)
    assert FeedbackCounts(acceptable=1, rejected=3).weight() == pytest.approx(2.0 / 7)
    assert FeedbackCounts(preferred=1).weight(prior=0) == 1.0
    assert FeedbackCounts(preferred=1).weight(prior=10) < FeedbackCounts(preferred=1).weight(
        prior=1
    )
    with pytest.raises(ConfigError):
        FeedbackCounts().weight(prior=-1)
    # Monòton: més decisions coherents acosten el pes al límit sense arribar-hi de cop.
    weights = [FeedbackCounts(preferred=n).weight() for n in range(8)]
    assert weights == sorted(weights) and weights[-1] < 1.0
    assert FeedbackCounts(preferred=4, acceptable=2, rejected=0).total == 6


def test_persistence_is_readable_and_deterministic(tmp_path: Path) -> None:
    file = tmp_path / "feedback.yml"
    store = FeedbackStore.load(file)  # el fitxer encara no existeix
    assert store.is_empty and store.path == file and store.prior == DEFAULT_PRIOR
    store.record("obra de", "preferred", 4)
    store.record("obra de", "acceptable", 2)
    store.record("fet per", "rejected", 3)
    store.record("fet per", "acceptable")
    assert store.save() == file
    text = file.read_text(encoding="utf-8")
    assert text.startswith("# Feedback manual")
    assert "obra de:" in text and "preferred: 4" in text and "rejected: 3" in text
    data = yaml.safe_load(text)
    assert data["variants"]["fet per"] == {"preferred": 0, "acceptable": 1, "rejected": 3}
    assert data["prior"] == DEFAULT_PRIOR and data["description"]
    loaded = FeedbackStore.load(file)
    assert loaded.counts_of("obra de") == FeedbackCounts(4, 2, 0)
    assert loaded.forms == ("fet per", "obra de")
    assert loaded.to_dict() == store.to_dict()
    assert loaded.source_label == "feedback de l'autor (feedback.yml)"
    loaded.save()
    assert file.read_text(encoding="utf-8") == text  # determinista
    # Un fitxer escrit a mà, amb «prior» propi.
    hand = tmp_path / "manual.yml"
    hand.write_text("prior: 1\nvariants:\n  realitzat per:\n    preferred: 2\n", encoding="utf-8")
    manual = FeedbackStore.load(hand)
    assert manual.prior == 1 and manual.counts_of("realitzat per") == FeedbackCounts(2, 0, 0)
    assert manual.weight_of("realitzat per") == pytest.approx(2.5 / 3)
    other = tmp_path / "sub" / "altre.yml"
    assert manual.save(other) == other and other.is_file() and manual.path == other
    bad = tmp_path / "bad.yml"
    bad.write_text("variants:\n  x:\n    liked: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        FeedbackStore.load(bad)
    bad.write_text("variants:\n  x: 3\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        FeedbackStore.load(bad)
    with pytest.raises(ResourceError):
        FeedbackStore().save()


def test_feedback_cli(
    tmp_path: Path, paths: ProjectPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    file = tmp_path / "feedback.yml"
    assert main(["feedback", "preferred", "obra de", "--file", str(file)]) == 0
    out = capsys.readouterr().out
    assert "«obra de»: preferida 1 vegades" in out and "Desat a" in out
    assert feedback_main(["preferred", "obra de", "realitzat per", "-f", str(file)]) == 0
    capsys.readouterr()
    assert feedback_main(["rejected", "fet per", "-f", str(file)]) == 0
    capsys.readouterr()
    assert feedback_main(["show", "-f", str(file)]) == 0
    out = capsys.readouterr().out
    assert "«obra de»: preferida 2" in out
    assert "«fet per»: preferida 0 · acceptable 0 · rebutjada 1" in out
    assert main(["feedback", "show", "--file", str(file), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["variants"]["obra de"]["preferred"] == 2
    assert data["variants"]["realitzat per"]["preferred"] == 1
    assert yaml.safe_load(file.read_text(encoding="utf-8"))["variants"]["fet per"]["rejected"] == 1
    # Fitxer per defecte del projecte.
    args = build_feedback_parser().parse_args(["show"])
    assert feedback_file(args) == paths.preferences / "feedback.yml"
    assert feedback_main(["show"]) == 0
    assert "feedback" in capsys.readouterr().out.lower()
    with pytest.raises(SystemExit):
        feedback_main([])
    bad = tmp_path / "bad.yml"
    bad.write_text("variants: [1]\n", encoding="utf-8")
    assert feedback_main(["show", "-f", str(bad)]) == 1
    assert "error" in capsys.readouterr().err


def test_feedback_changes_selection_with_an_explanation(tmp_path: Path) -> None:
    feedback = FeedbackStore(path=tmp_path / "feedback.yml")
    feedback.record("obra de", "preferred", 4)
    feedback.record("obra de", "acceptable", 2)
    feedback.record("fet per", "acceptable")
    feedback.record("fet per", "rejected", 3)
    feedback.record("realitzat per", "preferred", 2)
    feedback.record("realitzat per", "acceptable", 2)
    feedback.record("realitzat per", "rejected", 1)
    feedback.save()
    (tmp_path / "author.yml").write_text("name: prova\nfeedback: feedback.yml\n", encoding="utf-8")
    author = AuthorPreferences.load(tmp_path / "author.yml")
    assert author.feedback_file == tmp_path / "feedback.yml" and author.is_empty
    config = PipelineConfig(rule_set="parafrasi", preferences=str(tmp_path / "author.yml"))
    result = build_pipeline(config).run(SARCOFAG)
    assert "obra de l’escultor" in result.output_text
    assert result.preferences_name == "prova"
    selected = result.sentences[0].selected
    assert selected.score is not None and selected.score.components["preferencies"] > 0
    explanation = selected.score.preference_explanation
    assert "introdueix «obra de»" in explanation
    assert "preferida 4 vegades, acceptable 2 i rebutjada 0" in explanation
    assert "elimina «fet per»" in explanation and "rebutjada 3" in explanation
    assert "feedback de l'autor (feedback.yml)" in explanation
    report = result.report()
    assert "Preferències de l'autor (+" in report and "«obra de»" in report
    # Un fitxer de feedback indicat a la configuració mana sobre el del fitxer de preferències.
    other = FeedbackStore(path=tmp_path / "altre.yml")
    other.record("fet per", "preferred", 6)
    other.save()
    kept = build_pipeline(
        PipelineConfig(
            rule_set="parafrasi",
            preferences=str(tmp_path / "author.yml"),
            feedback=tmp_path / "altre.yml",
        )
    ).run(SARCOFAG)
    assert "fet per l’escultor" in kept.output_text
    # Sense fitxer de feedback (encara), el fitxer de preferències continua funcionant.
    (tmp_path / "buit.yml").write_text("feedback: no-existeix.yml\n", encoding="utf-8")
    pipeline = build_pipeline(PipelineConfig(preferences=str(tmp_path / "buit.yml")))
    assert pipeline.preferences_name == "buit"


def test_explicit_weight_beats_feedback_and_feedback_beats_nothing() -> None:
    author = AuthorPreferences(preferred_variants={"fet per": 1.0, "obra de": 0.2})
    feedback = FeedbackStore(
        {"obra de": FeedbackCounts(preferred=20), "fet per": FeedbackCounts(rejected=20)}
    )
    resolver = PreferenceResolver(author=author, feedback=feedback)
    explicit = resolver.resolve("fet per")
    assert explicit is not None and explicit.weight == 1.0
    assert "preferències de l'autor" in explicit.source
    variant = resolver.resolve("obra de")
    assert variant is not None and variant.weight == pytest.approx(-0.6)
    only_feedback = PreferenceResolver(feedback=feedback)
    fed = only_feedback.resolve("obra de")
    assert fed is not None and fed.weight > 0.8 and fed.level is PreferenceLevel.AUTHOR
    assert "preferida 20 vegades" in fed.reason
    assert only_feedback.forms == ("fet per", "obra de")
