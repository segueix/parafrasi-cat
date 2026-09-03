"""Construcció de la canonada a partir de la configuració i els recursos."""

from __future__ import annotations

from pathlib import Path

from parafrasi_cat.analyzer.analysis import RuleBasedAnalyzer
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon
from parafrasi_cat.analyzer.sentences import DEFAULT_ABBREVIATIONS, SentenceSplitter
from parafrasi_cat.candidates.generator import CandidateGenerator
from parafrasi_cat.morphology.registry import create_morphology_provider
from parafrasi_cat.pipeline.config import PipelineConfig
from parafrasi_cat.pipeline.pipeline import Pipeline
from parafrasi_cat.protected.protector import default_protector
from parafrasi_cat.resources import (
    ProjectPaths,
    as_mapping_list,
    as_str,
    as_str_list,
    load_mapping,
    read_term_list,
)
from parafrasi_cat.rules.registry import RuleRegistry, default_registry
from parafrasi_cat.rules.ruleset import RuleSetConfig, build_rule_set
from parafrasi_cat.scoring.scorer import CompositeScorer
from parafrasi_cat.style.evaluator import StyleEvaluator
from parafrasi_cat.style.profile import load_style_profile
from parafrasi_cat.validation.base import Validator
from parafrasi_cat.validation.invariants import (
    HedgeValidator,
    LengthRatioValidator,
    NegationValidator,
    NumericInvariantValidator,
    ProtectedSpanValidator,
)

PROTECTED_TERMS_FILE = "dictionaries/termes_protegits.txt"
KNOWN_NAMES_FILE = "dictionaries/noms_propis.txt"


def build_pipeline(
    config: PipelineConfig | None = None,
    *,
    registry: RuleRegistry | None = None,
) -> Pipeline:
    """Munta la canonada completa amb els recursos del projecte.

    Tots els components es creen aquí de manera explícita perquè sigui fàcil
    substituir-ne qualsevol (un altre analitzador, més validadors, etc.).
    """
    config = config or PipelineConfig()
    paths = ProjectPaths.discover(config.home)
    lang = paths.language(config.language)

    lexicon = ClosedClassLexicon.load(lang)
    analyzer = RuleBasedAnalyzer(SentenceSplitter(_load_abbreviations(lang)), lexicon=lexicon)

    protector = default_protector(
        analyzer,
        user_terms=_collect_user_terms(config, paths),
        known_names=_read_optional_terms(paths, KNOWN_NAMES_FILE),
        lexicon=lexicon,
    )

    rule_config = RuleSetConfig.load(paths.resolve_rule_set(config.rule_set))
    rule_set = build_rule_set(rule_config, registry or default_registry(), paths)

    modality = load_mapping(lang / "lexicon" / "modalitat.yaml")
    validators: list[Validator] = [
        ProtectedSpanValidator(),
        NumericInvariantValidator(),
        NegationValidator(
            as_str_list(modality, "negation"), as_str_list(modality, "negation_exceptions")
        ),
        HedgeValidator(as_str_list(modality, "hedges"), as_str_list(modality, "certainty")),
        LengthRatioValidator(*config.length_ratio),
    ]

    style_profile = load_style_profile(paths.resolve_style_profile(config.style_profile))
    style_evaluator = None
    if config.use_style:
        style_evaluator = StyleEvaluator(style_profile, analyzer, _load_connectors(lang))
    scorer = CompositeScorer(config.scoring, style_evaluator)

    return Pipeline(
        analyzer=analyzer,
        protector=protector,
        rule_set=rule_set,
        generator=CandidateGenerator(
            max_transformations=config.max_transformations_per_sentence,
            max_candidates=config.max_candidates_per_sentence,
            max_depth=config.candidate_depth,
        ),
        validators=validators,
        scorer=scorer,
        max_semantic_risk=config.max_semantic_risk,
        min_confidence=config.min_confidence,
        style_profile=style_profile,
        morphology=create_morphology_provider(config.morphology, lang, lexicon=lexicon),
        lexicon=lexicon,
    )


def _load_abbreviations(lang: Path) -> frozenset[str]:
    file = lang / "lexicon" / "abreviatures.yaml"
    if not file.is_file():
        return DEFAULT_ABBREVIATIONS
    data = load_mapping(file)
    return DEFAULT_ABBREVIATIONS | frozenset(as_str_list(data, "abbreviations"))


def _load_connectors(lang: Path) -> tuple[str, ...]:
    file = lang / "connectors" / "connectors.yaml"
    if not file.is_file():
        return ()
    data = load_mapping(file)
    forms: list[str] = []
    for group in as_mapping_list(data, "groups"):
        for connector in as_mapping_list(group, "connectors"):
            forms.append(as_str(connector, "form"))
    return tuple(dict.fromkeys(forms))


def _read_optional_terms(paths: ProjectPaths, relative: str) -> tuple[str, ...]:
    file = paths.optional(relative)
    return read_term_list(file) if file is not None else ()


def _collect_user_terms(config: PipelineConfig, paths: ProjectPaths) -> tuple[str, ...]:
    terms: list[str] = list(config.protected_terms)
    for file in config.protected_terms_files:
        terms.extend(read_term_list(file))
    terms.extend(_read_optional_terms(paths, PROTECTED_TERMS_FILE))
    return tuple(dict.fromkeys(terms))
