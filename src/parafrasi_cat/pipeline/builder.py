"""Construcció de la canonada a partir de la configuració i els recursos."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from parafrasi_cat.adapters.languagetool import LanguageToolClient, LanguageToolValidator
from parafrasi_cat.analyzer.analysis import RuleBasedAnalyzer
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon
from parafrasi_cat.analyzer.sentences import DEFAULT_ABBREVIATIONS, SentenceSplitter
from parafrasi_cat.candidates.generator import CandidateGenerator
from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.dictionaries.dictionary import DictionarySet
from parafrasi_cat.morphology.provider import MorphologyProvider
from parafrasi_cat.morphology.registry import create_morphology_provider
from parafrasi_cat.pipeline.config import FINGERPRINT_REQUIRED, PipelineConfig
from parafrasi_cat.pipeline.pipeline import Pipeline
from parafrasi_cat.preferences.author import AuthorPreferences
from parafrasi_cat.preferences.evaluator import PreferenceEvaluator
from parafrasi_cat.preferences.feedback import FeedbackStore
from parafrasi_cat.preferences.resolver import PreferenceResolver
from parafrasi_cat.protected.protector import default_protector
from parafrasi_cat.resources import (
    ProjectPaths,
    as_mapping_list,
    as_str,
    as_str_list,
    load_mapping,
    read_term_list,
)
from parafrasi_cat.rules.dictionary import DictionaryPreferenceRule
from parafrasi_cat.rules.registry import RuleRegistry, default_registry
from parafrasi_cat.rules.ruleset import RuleSet, RuleSetConfig, build_rule_set
from parafrasi_cat.scoring.assertive import AssertiveEvaluator
from parafrasi_cat.scoring.scorer import CompositeScorer
from parafrasi_cat.style.adaptation import AuthorAdaptation
from parafrasi_cat.style.connector_repetition import ConnectorRepetition, connector_forms
from parafrasi_cat.style.degradation import StructuralDegradation
from parafrasi_cat.style.evaluator import StyleEvaluator
from parafrasi_cat.style.fusion_rhythm import FusionRhythm
from parafrasi_cat.style.observations import StyleResources
from parafrasi_cat.style.profile import load_style_profile
from parafrasi_cat.syntax.analysis import CachedSyntax, NullSyntax, SyntaxProvider
from parafrasi_cat.syntax.spacy_parser import SpacySyntax
from parafrasi_cat.validation.agreement import AgreementValidator
from parafrasi_cat.validation.base import Validator
from parafrasi_cat.validation.conditional_scope import ConditionalScopeValidator
from parafrasi_cat.validation.epistemic import (
    EPISTEMOLOGY_FILE,
    EpistemicLexicon,
    EpistemicValidator,
)
from parafrasi_cat.validation.factual import ProtectedTermValidator, factual_validators
from parafrasi_cat.validation.grammar import GrammarHeuristicValidator
from parafrasi_cat.validation.invariants import (
    HedgeValidator,
    LengthRatioValidator,
    NegationValidator,
    NumericInvariantValidator,
    ProtectedSpanValidator,
)
from parafrasi_cat.validation.verbal import VerbalTransformationValidator

PROTECTED_TERMS_FILE = "dictionaries/termes_protegits.txt"
ASSERTIVE_OPTION = "assertive_language"
KNOWN_NAMES_FILE = "dictionaries/noms_propis.txt"
#: Pressió de canvi segura per als esborranys generats amb LLM. És deliberadament
#: inferior al pes d'afinitat autoral: la finalitat és preferir una alternativa
#: segura, no canviar per quota ni sacrificar l'estil de l'autor.
LLM_REWRITE_PRESSURE = 0.9


def build_pipeline(
    config: PipelineConfig | None = None,
    *,
    registry: RuleRegistry | None = None,
) -> Pipeline:
    config = config or PipelineConfig()
    paths = ProjectPaths.discover(config.home)
    lang = paths.language(config.language)

    lexicon = ClosedClassLexicon.load(lang)
    analyzer = RuleBasedAnalyzer(SentenceSplitter(_load_abbreviations(lang)), lexicon=lexicon)

    dictionaries = load_dictionaries(config, paths)
    author = load_author_preferences(config, paths)
    feedback = load_feedback(config, author)

    user_terms = _collect_user_terms(config, paths)
    dictionary_terms = dictionaries.protected_terms
    protector = default_protector(
        analyzer,
        user_terms=user_terms,
        known_names=_read_optional_terms(paths, KNOWN_NAMES_FILE),
        dictionary_terms=dictionary_terms,
        lexicon=lexicon,
    )

    rule_config = RuleSetConfig.load(paths.resolve_rule_set(config.rule_set))
    options = frozenset({ASSERTIVE_OPTION}) if config.assertive_language else frozenset()
    rule_set = (
        build_rule_set(rule_config, registry or default_registry(), paths)
        .for_options(options)
        .up_to_level(config.level)
    )
    if dictionaries.substitutions and DictionaryPreferenceRule.DEFAULT_ID not in rule_set.rule_ids:
        rule_set = rule_set.with_extra_rules([DictionaryPreferenceRule(dictionaries)])

    all_terms = tuple(dict.fromkeys((*user_terms, *dictionary_terms)))
    morphology = create_morphology_provider(config.morphology, lang, lexicon=lexicon)
    syntax = build_syntax_provider(config, morphology)
    if syntax.available and not isinstance(syntax, CachedSyntax):
        syntax = CachedSyntax(syntax)
    validators = build_validators(
        config, paths, analyzer, lexicon, rule_set, all_terms, syntax, morphology
    )

    style_profile = load_style_profile(
        paths.resolve_style_profile(config.style_profile), paths=paths
    )
    if author is not None and author.preferred_sentence_length is not None:
        style_profile = replace(
            style_profile, target_sentence_length=float(author.preferred_sentence_length)
        )

    resolver = PreferenceResolver(
        dictionaries=dictionaries,
        author=author,
        feedback=feedback,
        protected_terms=user_terms,
    )
    style_evaluator = None
    if config.use_style:
        style_resources = (
            StyleResources.load(paths, config.language, lexicon=lexicon)
            if style_profile.preferences is not None
            else None
        )
        style_evaluator = StyleEvaluator(
            style_profile,
            analyzer,
            _load_connectors(lang),
            resources=style_resources,
            explicit_forms=resolver.explicit_forms(),
        )
    preference_evaluator = None
    if resolver.active:
        preference_evaluator = PreferenceEvaluator(
            resolver,
            max_sentence_length=author.max_sentence_length if author is not None else None,
            analyzer=analyzer,
        )

    adaptation = None
    weights = config.scoring
    if config.source_mode.adapts_to_author and style_profile.preferences is None:
        raise ConfigError(FINGERPRINT_REQUIRED)
    if style_profile.preferences is not None:
        adaptation = AuthorAdaptation(
            style_profile.preferences,
            analyzer,
            StyleResources.load(paths, config.language, lexicon=lexicon),
            explicit_forms=resolver.explicit_forms(),
            syntax=syntax,
        )
        if config.source_mode.adapts_to_author:
            # Un esborrany LLM ja pot estar molt ben redactat. No exigim que la
            # transformació sigui una "millora" absoluta: entre alternatives que
            # han superat els validadors, premiem la reescriptura real i l'afinitat
            # amb l'autor. El valor explícit de configuració mana si és més alt.
            weights = replace(
                weights,
                rewrite_pressure=max(weights.rewrite_pressure, LLM_REWRITE_PRESSURE),
            )
        else:
            weights = replace(
                weights,
                author_affinity=weights.author_affinity_own,
                rewrite_pressure=0.0,
            )

    degradation = StructuralDegradation(analyzer, syntax, style_profile.preferences)
    assertive = None
    epistemology = lang / EPISTEMOLOGY_FILE
    if config.assertive_language and epistemology.is_file():
        assertive = AssertiveEvaluator(
            EpistemicLexicon.load(epistemology), style_profile.preferences
        )
    rhythm = FusionRhythm(analyzer, syntax, style_profile.preferences, style_profile)
    # L'inventari de connectors surt de les regles actives: són les formes que el
    # motor pot intercanviar amb seguretat i, per tant, les úniques que té sentit
    # comptar quan es mira si una repetició s'ha introduït o ja hi era.
    connectors = ConnectorRepetition(analyzer, connector_forms(rule_set.rules))
    scorer = CompositeScorer(
        weights,
        style_evaluator,
        preference_evaluator,
        adaptation,
        degradation,
        assertive,
        rhythm,
        connectors,
    )

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
        morphology=morphology,
        syntax=syntax,
        lexicon=lexicon,
        max_level=config.level,
        dictionary_names=dictionaries.names,
        preferences_name=author.name if author is not None else "",
        preferred_sentence_length=author.preferred_sentence_length if author else None,
        max_sentence_length=author.max_sentence_length if author else None,
        adaptation=adaptation,
        source_mode=config.source_mode.value,
        paragraph_beam_width=config.paragraph_beam_width,
        sentence_candidates_for_paragraph=config.sentence_candidates_for_paragraph,
        assertive_language=config.assertive_language,
    )


def build_validators(
    config: PipelineConfig,
    paths: ProjectPaths,
    analyzer: RuleBasedAnalyzer,
    lexicon: ClosedClassLexicon,
    rule_set: RuleSet,
    user_terms: tuple[str, ...] = (),
    syntax: SyntaxProvider | None = None,
    morphology: MorphologyProvider | None = None,
) -> list[Validator]:
    lang = paths.language(config.language)
    modality = load_mapping(lang / "lexicon" / "modalitat.yaml")
    validators: list[Validator] = [
        ProtectedSpanValidator(),
        NumericInvariantValidator(),
        *factual_validators(analyzer, lexicon=lexicon),
        NegationValidator(
            as_str_list(modality, "negation"), as_str_list(modality, "negation_exceptions")
        ),
        ConditionalScopeValidator(),
    ]
    if user_terms:
        validators.append(ProtectedTermValidator(user_terms))
    validators.append(
        HedgeValidator(
            as_str_list(modality, "hedges"),
            as_str_list(modality, "certainty"),
            (*rule_set.epistemic_rule_ids, *rule_set.redundancy_rule_ids),
        )
    )
    epistemology = lang / EPISTEMOLOGY_FILE
    if epistemology.is_file():
        validators.append(
            EpistemicValidator(
                EpistemicLexicon.load(epistemology),
                rule_set.epistemic_rule_ids,
                rule_set.redundancy_rule_ids,
            )
        )
    validators.append(GrammarHeuristicValidator())
    if morphology is not None:
        validators.append(VerbalTransformationValidator(morphology, syntax))
    if syntax is not None and syntax.available:
        validators.append(AgreementValidator(syntax))
    validators.append(LengthRatioValidator(*config.length_ratio))
    languagetool = build_languagetool_validator(config, paths)
    if languagetool is not None:
        validators.append(languagetool)
    return validators


def build_syntax_provider(
    config: PipelineConfig, morphology: MorphologyProvider | None = None
) -> SyntaxProvider:
    if config.syntax in ("none", "null", ""):
        return NullSyntax()
    if config.syntax in ("auto", "spacy"):
        parser = SpacySyntax(morphology=morphology)
        return parser if parser.available else NullSyntax()
    raise ConfigError(f"Analitzador sintàctic desconegut: «{config.syntax}» (auto, spacy, none)")


def build_languagetool_validator(
    config: PipelineConfig, paths: ProjectPaths
) -> LanguageToolValidator | None:
    if not config.languagetool:
        return None
    client = LanguageToolClient.discover(paths.root)
    return LanguageToolValidator(client) if client.available else None


def load_dictionaries(config: PipelineConfig, paths: ProjectPaths) -> DictionarySet:
    return DictionarySet.load(
        paths.resolve_dictionary(reference) for reference in config.dictionaries
    )


def load_author_preferences(
    config: PipelineConfig, paths: ProjectPaths
) -> AuthorPreferences | None:
    if not config.preferences:
        return None
    return AuthorPreferences.load(paths.resolve_preferences(config.preferences))


def load_feedback(config: PipelineConfig, author: AuthorPreferences | None) -> FeedbackStore | None:
    file = config.feedback
    if file is None and author is not None:
        file = author.feedback_file
    if file is None:
        return None
    return FeedbackStore.load(file)


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
            form = as_str(connector, "form").strip()
            if form:
                forms.append(form)
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
