"""Integració mínima: validació + puntuació + selecció sobre candidats reals, i «rewrite»."""

from __future__ import annotations

import io
import json
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest

from parafrasi_cat import PipelineConfig, build_pipeline
from parafrasi_cat.analyzer import ClosedClassLexicon, RuleBasedAnalyzer
from parafrasi_cat.cli import main
from parafrasi_cat.core import ConfigError, SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.pipeline import Pipeline
from parafrasi_cat.pipeline.builder import build_validators
from parafrasi_cat.protected import default_protector
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.rewrite import RewriteOptions, rewrite
from parafrasi_cat.rules import Rule, RuleContext, RuleDefinition, RuleSet, RuleSetConfig
from parafrasi_cat.scoring import CompositeScorer
from parafrasi_cat.validation import EpistemicLexicon
from parafrasi_cat.validation.epistemic import EPISTEMOLOGY_FILE

TEXT = (
    "La primera referència itàlica és el monument funerari d’Oddo Altoviti, encarregat el 1507 "
    "i finalitzat el 1516. En aquest sarcòfag fet per l’escultor Benedetto da Rovezzano hi ha la "
    "presència de dos cranis acompanyats de dos ossos creuats, així com dues serps també "
    "creuades.\n\nSembla que el motiu podria procedir del capítol IV del tractat de Colonna "
    "(Colonna, 1499), però no es pot demostrar. Potser el capital circulant no hi té res a veure."
)
FACTS = ("Oddo Altoviti", "1507", "1516", "Benedetto da Rovezzano", "IV", "(Colonna, 1499)")
HEDGES = ("Sembla que", "podria", "no es pot demostrar", "Potser")


class ReplaceRule(Rule):
    """Regla de prova: substitueix la primera aparició d'un fragment."""

    def __init__(self, rule_id: str, before: str, after: str, level: int = 1) -> None:
        super().__init__(rule_id, transformation_type=TransformationType.LEXICAL, level=level)
        self._before = before
        self._after = after

    def propose(self, ctx: RuleContext) -> list[Transformation]:
        start = ctx.text.find(self._before)
        if start < 0:
            return []
        return [
            Transformation(
                rule_id=self.rule_id,
                text_before=self._before,
                text_after=self._after,
                changed_span=Span(start, start + len(self._before)),
                transformation_type=self.transformation_type,
                confidence=0.9,
                semantic_risk=SemanticRisk.LOW,
                explanation=f"«{self._before}» → «{self._after}»",
            )
        ]


def make_pipeline(
    rules: Iterable[Rule],
    *,
    definitions: Iterable[RuleDefinition] = (),
    user_terms: tuple[str, ...] = (),
    level: int | None = None,
) -> Pipeline:
    paths = ProjectPaths.discover()
    lexicon = ClosedClassLexicon.load(paths.language())
    analyzer = RuleBasedAnalyzer(lexicon=lexicon)
    rule_set = RuleSet(
        RuleSetConfig(name="prova", max_semantic_risk=SemanticRisk.HIGH),
        tuple(rules),
        tuple(definitions),
    )
    validators = build_validators(PipelineConfig(), paths, analyzer, lexicon, rule_set, user_terms)
    return Pipeline(
        analyzer=analyzer,
        protector=default_protector(analyzer, user_terms=user_terms, lexicon=lexicon),
        rule_set=rule_set,
        validators=validators,
        scorer=CompositeScorer(),
        max_level=level,
    )


def definition(rule_id: str, **kwargs: object) -> RuleDefinition:
    return RuleDefinition(rule_id=rule_id, engine="prova", **kwargs)  # type: ignore[arg-type]


# --- regles reals: dates, noms, nombres, romans, citacions, hipòtesis --------------------


def test_real_rules_preserve_facts_hedges_and_terms(paths: ProjectPaths) -> None:
    config = PipelineConfig(
        rule_set="parafrasi",
        level=3,
        max_candidates_per_sentence=10,
        protected_terms=("capital circulant",),
    )
    pipeline = build_pipeline(config)
    assert pipeline.max_level == 3
    assert all(rule.level <= 3 for rule in pipeline.rule_set.rules)
    result = pipeline.run(TEXT)
    assert result.changed
    lexicon = EpistemicLexicon.load(paths.language() / EPISTEMOLOGY_FILE)
    for sentence in result.sentences:
        assert len(sentence.candidates) <= 10
        for fact in FACTS + HEDGES + ("capital circulant",):
            if fact in sentence.source_text:
                assert fact in sentence.output_text, fact
        for evaluated in sentence.candidates:
            if not evaluated.accepted:
                continue
            assert lexicon.change(sentence.source_text, evaluated.candidate.text) is None
            assert evaluated.score is not None and evaluated.score.valid
            for fact in FACTS:
                if fact in sentence.source_text:
                    assert fact in evaluated.candidate.text
    for fact in FACTS + HEDGES:
        assert result.output_text.count(fact) == TEXT.count(fact)
    report = result.report()
    assert "Regles aplicades" in report and "preservació factual 1.00" in report
    assert "Candidats descartats destacats" in report


def test_level_filter_and_candidate_limit() -> None:
    lexical_only = build_pipeline(PipelineConfig(rule_set="parafrasi", level=1))
    assert lexical_only.rule_set.rule_ids
    assert all(rule.level == 1 for rule in lexical_only.rule_set.rules)
    full = build_pipeline(PipelineConfig(rule_set="parafrasi"))
    assert len(full.rule_set.rules) > len(lexical_only.rule_set.rules)
    assert any(rule.level >= 4 for rule in full.rule_set.rules)
    with pytest.raises(ConfigError):
        PipelineConfig(level=6)
    small = build_pipeline(PipelineConfig(rule_set="parafrasi", max_candidates_per_sentence=3))
    result = small.run(TEXT.split("\n\n")[0])
    assert all(len(s.candidates) <= 3 for s in result.sentences)


# --- regles de prova: bloquejos de segona línia ------------------------------------------


def test_hypothesis_to_certainty_is_blocked_unless_authorized() -> None:
    source = "Potser plourà demà."
    blocked = make_pipeline([ReplaceRule("hedge.drop", "Potser plourà", "Plourà")])
    result = blocked.run(source)
    assert result.output_text == source
    sentence = result.sentences[0]
    rejected = [c for c in sentence.candidates if not c.accepted]
    assert rejected and {i.validator_id for i in rejected[0].validation.errors} & {
        "modality",
        "epistemic",
    }
    assert rejected[0].score is not None and not rejected[0].score.valid
    assert rejected[0].score.dimensions["preservacio_epistemologica"] == 0.0
    discarded = sentence.discarded()
    assert discarded and discarded[0].reason.startswith("rebutjat:")
    assert "rebutjat:" in result.report()
    assert sentence.summary()["n_rejected"] == 1

    authorized = make_pipeline(
        [ReplaceRule("hedge.drop", "Potser plourà", "Plourà")],
        definitions=[definition("hedge.drop", allows_epistemic_change=True)],
    )
    assert authorized.rule_set.epistemic_rule_ids == ("hedge.drop",)
    assert authorized.run(source).output_text == "Plourà demà."


def test_certainty_to_hypothesis_and_function_changes_are_blocked() -> None:
    source = "Aquesta dada demostra que el motiu és italià."
    for after in ("suggereix", "confirma", "indica", "potser demostra"):
        pipeline = make_pipeline([ReplaceRule("epist", "demostra", after)])
        assert pipeline.run(source).output_text == source, after
    source = "Sembla que el motiu és italià."
    assert make_pipeline([ReplaceRule("epist", "Sembla que el", "El")]).run(source).output_text == (
        source
    )
    assert make_pipeline([ReplaceRule("epist", "Sembla", "És evident")]).run(
        source
    ).output_text == (source)
    # Un canvi lèxic que no toca cap marcador sí que passa.
    neutral = make_pipeline([ReplaceRule("lex", "motiu", "tema")])
    assert neutral.run(source).output_text == "Sembla que el tema és italià."


def test_negation_names_dates_and_terms_are_blocked() -> None:
    source = "No plou a Girona des del 12 de gener de 2020, segons el capital circulant."
    negation = make_pipeline([ReplaceRule("neg", "No plou", "Plou")])
    assert negation.run(source).output_text == source
    rejected = [c for c in negation.run(source).sentences[0].candidates if not c.accepted]
    assert rejected and "negació" in rejected[0].rejection_reason
    name = make_pipeline([ReplaceRule("nom", "Girona", "Lleida")])
    result = name.run(source)
    assert result.output_text == source
    assert "protegit" in result.sentences[0].rejected_proposals[0].reason
    date = make_pipeline([ReplaceRule("data", "gener", "febrer")])
    assert date.run(source).output_text == source
    term = make_pipeline(
        [ReplaceRule("terme", "capital circulant", "capital de treball")],
        user_terms=("capital circulant",),
    )
    assert term.run(source).output_text == source
    # Sense la protecció d'usuari, la mateixa substitució sí que s'aplica.
    free = make_pipeline([ReplaceRule("terme", "capital circulant", "capital de treball")])
    assert "capital de treball" in free.run(source).output_text


def test_grammar_defects_are_penalised_or_rejected() -> None:
    source = "Gairebé sempre va al mercat."
    broken = make_pipeline([ReplaceRule("gram", "al mercat", "a el mercat")])
    result = broken.run(source)
    assert result.output_text == source
    rejected = [c for c in result.sentences[0].candidates if not c.accepted]
    assert rejected and rejected[0].score is not None
    assert rejected[0].score.dimensions["gramaticalitat"] == 0.0
    competing = make_pipeline(
        [ReplaceRule("net", "Gairebé", "Quasi"), ReplaceRule("brut", "sempre", "sempre ")]
    )
    result = competing.run(source)
    scored = {c.candidate.text: c.score for c in result.sentences[0].candidates if c.score}
    dirty = scored["Gairebé sempre  va al mercat."]
    clean = scored["Quasi sempre va al mercat."]
    assert dirty.valid and dirty.dimensions["gramaticalitat"] == 0.85
    assert clean.dimensions["gramaticalitat"] == 1.0 and clean.total > dirty.total
    assert result.output_text.startswith("Quasi")


# --- ordre «rewrite» ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def input_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    file = tmp_path_factory.mktemp("rewrite") / "entrada.txt"
    file.write_text(TEXT + "\n", encoding="utf-8")
    return file


@pytest.fixture(scope="module")
def fingerprint_file(project_root: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("empremta") / "academic.json"
    corpus = project_root / "corpus" / "exemples" / "academic"
    assert main(["style", "build", str(corpus), "-o", str(output), "-q"]) == 0
    return output


def test_rewrite_command_with_fingerprint_level_and_candidates(
    input_file: Path, fingerprint_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "sortida.txt"
    code = main(
        [
            "rewrite",
            str(input_file),
            "--style",
            str(fingerprint_file),
            "--level",
            "3",
            "--candidates",
            "10",
            "--protect",
            "capital circulant",
            "-o",
            str(output),
        ]
    )
    assert code == 0
    report = capsys.readouterr().out
    assert "=== Reescriptura ===" in report
    assert "Estil de referència: academic" in report
    assert "Regles aplicades:" in report and "Puntuacions: global" in report
    assert "semblança amb l'estil" in report and "Candidats descartats destacats" in report
    assert "no seleccionat: puntuació" in report
    rewritten = output.read_text(encoding="utf-8")
    for fact in FACTS + HEDGES + ("capital circulant",):
        assert fact in rewritten
    assert rewritten != TEXT + "\n"


def test_rewrite_json_and_quiet_output(
    input_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["rewrite", str(input_file), "--json", "--level", "2"]) == 0
    data = json.loads(capsys.readouterr().out)
    summary = data["sentences"][0]["summary"]
    assert set(summary) >= {"best", "applied_rules", "score", "discarded", "n_rejected"}
    dimensions = summary["score"]["dimensions"]
    assert set(dimensions) >= {"preservacio_factual", "preservacio_epistemologica", "grau_de_canvi"}
    assert all(isinstance(item["reason"], str) for item in summary["discarded"])
    assert main(["rewrite", str(input_file), "--quiet", "--rules", "default"]) == 0
    assert capsys.readouterr().out == TEXT + "\n"


def test_rewrite_stdin_options_and_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("Gairebé sempre plou.\n"))
    assert main(["rewrite", "-", "--rules", "exemple-lexic", "--quiet"]) == 0
    assert capsys.readouterr().out == "Quasi sempre plou.\n"
    assert main(["rewrite", str(tmp_path / "no-existeix.txt")]) == 1
    assert "error" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["rewrite", str(tmp_path / "x.txt"), "--candidates", "0"])
    with pytest.raises(SystemExit):
        main(["rewrite", str(tmp_path / "x.txt"), "--level", "7"])
    options = RewriteOptions(
        style="formal", level=2, candidates=4, max_risk=SemanticRisk.LOW, min_confidence=0.8
    )
    config = options.to_config()
    assert config.rule_set == "parafrasi" and config.style_profile == "formal"
    assert config.level == 2 and config.max_candidates_per_sentence == 4
    assert config.max_semantic_risk is SemanticRisk.LOW and config.min_confidence == 0.8
    result = rewrite("Gairebé tothom ho sap.", RewriteOptions(rule_set="exemple-lexic"))
    assert result.output_text == "Quasi tothom ho sap."
