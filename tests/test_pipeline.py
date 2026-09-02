from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from parafrasi_cat import PipelineConfig, build_pipeline, paraphrase
from parafrasi_cat.analyzer import RuleBasedAnalyzer
from parafrasi_cat.core import SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.pipeline import Pipeline
from parafrasi_cat.protected import default_protector
from parafrasi_cat.rules import Rule, RuleContext, RuleSet, RuleSetConfig
from parafrasi_cat.scoring import CompositeScorer
from parafrasi_cat.validation import (
    HedgeValidator,
    NumericInvariantValidator,
    ProtectedSpanValidator,
)

NUMBERS = re.compile(r"\d+(?:[.,]\d+)*")


def test_default_pipeline_is_identity(
    validation_sentences: tuple[str, ...], project_root: Path
) -> None:
    pipeline = build_pipeline()
    assert pipeline.rule_set.rules == ()
    corpus = "\n".join(validation_sentences)
    result = pipeline.run(corpus)
    assert result.output_text == corpus
    assert not result.changed
    assert result.transformations == ()
    assert len(result.sentences) == len(validation_sentences)
    assert result.protected_spans
    example = (project_root / "examples" / "text_exemple.txt").read_text(encoding="utf-8")
    assert build_pipeline().run(example).output_text == example


def test_identity_preserves_whitespace_and_empty_text() -> None:
    pipeline = build_pipeline()
    for text in ("", "   ", "\n\n", "  Hola.  \n\nAdeu.  ", "Sense punt final"):
        assert pipeline.run(text).output_text == text


def test_example_rules_apply_substitution() -> None:
    result = paraphrase("Gairebé tothom ho sap.", PipelineConfig(rule_set="exemple-lexic"))
    assert result.output_text == "Quasi tothom ho sap."
    assert result.changed
    assert len(result.transformations) == 1
    transformation = result.transformations[0]
    assert transformation.rule_id == "lexical.substitution"
    assert transformation.text_before == "Gairebé"
    assert transformation.explanation
    report = result.explain()
    assert "lexical.substitution" in report and "Quasi" in report
    data = json.loads(result.to_json())
    assert data["output_text"] == "Quasi tothom ho sap."
    assert data["sentences"][0]["candidates"][0]["candidate"]["text"] == "Gairebé tothom ho sap."


def test_reassembly_keeps_layout() -> None:
    text = "  Gairebé sempre.\n\nSovint plou.  "
    result = paraphrase(text, PipelineConfig(rule_set="exemple-lexic"))
    assert result.output_text == "  Quasi sempre.\n\nFreqüentment plou.  "


def test_protected_terms_block_rules() -> None:
    config = PipelineConfig(rule_set="exemple-lexic", protected_terms=("gairebé",))
    result = paraphrase("Gairebé tothom.", config)
    assert not result.changed
    assert [p.text for p in result.protected_spans] == ["Gairebé"]
    # La regla ja evita el fragment protegit, de manera que no hi ha cap proposta.
    sentence = result.sentences[0]
    assert sentence.rejected_proposals == ()
    assert len(sentence.candidates) == 1 and sentence.candidates[0].candidate.is_identity


def test_thresholds_from_config() -> None:
    text = "Actualment plou."  # entrada amb confiança 0.7
    assert paraphrase(text, PipelineConfig(rule_set="exemple-lexic")).changed
    strict = PipelineConfig(rule_set="exemple-lexic", min_confidence=0.95)
    result = paraphrase(text, strict)
    assert not result.changed
    assert "confiança" in result.sentences[0].rejected_proposals[0].reason

    risky = "Cal començar ara."  # entrada amb risc mitjà
    result = paraphrase(risky, PipelineConfig(rule_set="exemple-lexic"))
    assert not result.changed
    assert "risc" in result.sentences[0].rejected_proposals[0].reason
    permissive = PipelineConfig(rule_set="exemple-lexic", max_semantic_risk=SemanticRisk.MEDIUM)
    assert paraphrase(risky, permissive).output_text == "Cal iniciar ara."


def test_content_invariants_on_corpus(validation_sentences: tuple[str, ...]) -> None:
    pipeline = build_pipeline(PipelineConfig(rule_set="exemple-lexic"))
    for sentence in validation_sentences:
        result = pipeline.run(sentence)
        output = result.output_text
        for protected in result.protected_spans:
            assert protected.text in output, (sentence, protected)
        assert Counter(NUMBERS.findall(sentence)) == Counter(NUMBERS.findall(output))
        for transformation in result.transformations:
            for protected in result.protected_spans:
                assert not protected.overlaps(transformation.changed_span)


class DeleteHedgeRule(Rule):
    """Regla deliberadament perillosa: elimina «Potser » del començament."""

    def __init__(self) -> None:
        super().__init__("test.delete_hedge", transformation_type=TransformationType.SYNTACTIC)

    def propose(self, ctx: RuleContext) -> list[Transformation]:
        if not ctx.text.startswith("Potser "):
            return []
        return [
            Transformation(
                rule_id=self.rule_id,
                text_before="Potser ",
                text_after="",
                changed_span=Span(0, 7),
                transformation_type=self.transformation_type,
                confidence=1.0,
                semantic_risk=SemanticRisk.NONE,
                explanation="elimina l'atenuació (no s'hauria d'acceptar mai)",
            )
        ]


def test_validators_are_second_line_of_defense(modality: dict[str, tuple[str, ...]]) -> None:
    analyzer = RuleBasedAnalyzer()
    pipeline = Pipeline(
        analyzer=analyzer,
        protector=default_protector(analyzer),
        rule_set=RuleSet(RuleSetConfig(name="perillós"), (DeleteHedgeRule(),)),
        validators=[
            ProtectedSpanValidator(),
            NumericInvariantValidator(),
            HedgeValidator(modality["hedges"], modality["certainty"]),
        ],
        scorer=CompositeScorer(),
    )
    result = pipeline.run("Potser plourà el 2030.")
    assert result.output_text == "Potser plourà el 2030."
    sentence = result.sentences[0]
    assert sentence.rejected_proposals == ()
    rejected = [c for c in sentence.candidates if not c.accepted]
    assert len(rejected) == 1
    assert rejected[0].validation.errors[0].validator_id == "modality"
    assert "rebutjat" in result.explain()


def test_pipeline_without_validators_still_blocks_protected(
    modality: dict[str, tuple[str, ...]],
) -> None:
    analyzer = RuleBasedAnalyzer()
    pipeline = Pipeline(
        analyzer=analyzer,
        protector=default_protector(analyzer, user_terms=["potser"]),
        rule_set=RuleSet(
            RuleSetConfig(name="perillós", max_semantic_risk=SemanticRisk.HIGH),
            (DeleteHedgeRule(),),
        ),
        scorer=CompositeScorer(),
    )
    result = pipeline.run("Potser plourà.")
    assert result.output_text == "Potser plourà."
    assert "protegit" in result.sentences[0].rejected_proposals[0].reason


def test_config_loading(project_root: Path) -> None:
    config = PipelineConfig.load(project_root / "examples" / "config_exemple.yaml")
    assert config.rule_set == "exemple-lexic"
    assert config.style_profile == "formal"
    assert config.protected_terms == ("capital circulant", "Pla d'Acció")
    assert config.max_semantic_risk is SemanticRisk.LOW
    assert config.length_ratio == (0.6, 1.6)
    scoring = config.to_dict()["scoring"]
    assert isinstance(scoring, dict) and scoring["max_transformations"] == 3
    pipeline = build_pipeline(config)
    assert pipeline.style_profile is not None and pipeline.style_profile.name == "formal"
    assert pipeline.run("El Pla d'Acció comença.").output_text == "El Pla d'Acció comença."


def test_config_validation() -> None:
    from parafrasi_cat.core import ConfigError

    with pytest.raises(ConfigError):
        PipelineConfig(min_confidence=2)
    with pytest.raises(ConfigError):
        PipelineConfig(length_ratio=(1.5, 2.0))
    with pytest.raises(ConfigError):
        PipelineConfig(max_candidates_per_sentence=0)
