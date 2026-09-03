"""Construcció de la canonada a partir de la configuració i els recursos."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from parafrasi_cat.analyzer.analysis import RuleBasedAnalyzer
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon
from parafrasi_cat.analyzer.sentences import DEFAULT_ABBREVIATIONS, SentenceSplitter
from parafrasi_cat.candidates.generator import CandidateGenerator
from parafrasi_cat.dictionaries.dictionary import DictionarySet
from parafrasi_cat.morphology.registry import create_morphology_provider
from parafrasi_cat.pipeline.config import PipelineConfig
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
from parafrasi_cat.scoring.scorer import CompositeScorer
from parafrasi_cat.style.evaluator import StyleEvaluator
from parafrasi_cat.style.observations import StyleResources
from parafrasi_cat.style.profile import load_style_profile
from parafrasi_cat.validation.base import Validator
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

    Jerarquia de prioritats terminològiques que en resulta: fragments
    protegits explícitament > termes protegits dels diccionaris > formes
    preferides dels diccionaris > preferències explícites de l'autor (fitxer
    i feedback) > empremta estadística > preferències generals del motor.
    """
    config = config or PipelineConfig()
    paths = ProjectPaths.discover(config.home)
    lang = paths.language(config.language)

    lexicon = ClosedClassLexicon.load(lang)
    analyzer = RuleBasedAnalyzer(SentenceSplitter(_load_abbreviations(lang)), lexicon=lexicon)

    dictionaries = load_dictionaries(config, paths)
    author = load_author_preferences(config, paths)
    feedback = load_feedback(config, author)

    # Nivells 1 i 2: proteccions absolutes (protector i validadors).
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
    rule_set = build_rule_set(rule_config, registry or default_registry(), paths).up_to_level(
        config.level
    )
    if dictionaries.substitutions and DictionaryPreferenceRule.DEFAULT_ID not in rule_set.rule_ids:
        # Nivell 3: les formes a evitar dels diccionaris generen propostes de substitució.
        rule_set = rule_set.with_extra_rules([DictionaryPreferenceRule(dictionaries)])

    all_terms = tuple(dict.fromkeys((*user_terms, *dictionary_terms)))
    validators = build_validators(config, paths, analyzer, lexicon, rule_set, all_terms)

    style_profile = load_style_profile(
        paths.resolve_style_profile(config.style_profile), paths=paths
    )
    if author is not None and author.preferred_sentence_length is not None:
        # La longitud de frase explícita de l'autor mana sobre la del perfil o l'empremta.
        style_profile = replace(
            style_profile, target_sentence_length=float(author.preferred_sentence_length)
        )

    # Nivells 3 i 4 (per a la puntuació) i deferència de l'empremta (nivell 5).
    resolver = PreferenceResolver(
        dictionaries=dictionaries,
        author=author,
        feedback=feedback,
        protected_terms=user_terms,
    )
    style_evaluator = None
    if config.use_style:
        # Si el perfil referencia una empremta de l'autor, l'avaluador també mesura
        # la distància respecte de les seves preferències (variants, connectors, comes),
        # excepte per a les formes que ja tenen una preferència explícita.
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
    scorer = CompositeScorer(config.scoring, style_evaluator, preference_evaluator)

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
        max_level=config.level,
        dictionary_names=dictionaries.names,
        preferences_name=author.name if author is not None else "",
    )


def build_validators(
    config: PipelineConfig,
    paths: ProjectPaths,
    analyzer: RuleBasedAnalyzer,
    lexicon: ClosedClassLexicon,
    rule_set: RuleSet,
    user_terms: tuple[str, ...] = (),
) -> list[Validator]:
    """Validadors en ordre de prioritat: contingut, terminologia, epistemologia, gramàtica.

    - fragments protegits, xifres i números romans, noms propis, dates, citacions,
      text entre cometes i negació (preservació factual);
    - terminologia protegida per l'usuari i pels diccionaris del projecte;
    - marcadors d'atenuació i certesa, i classificació epistemològica explícita
      (només les regles amb ``allows_epistemic_change`` poden canviar-la);
    - gramaticalitat heurística i marge de longitud.
    """
    lang = paths.language(config.language)
    modality = load_mapping(lang / "lexicon" / "modalitat.yaml")
    validators: list[Validator] = [
        ProtectedSpanValidator(),
        NumericInvariantValidator(),
        *factual_validators(analyzer, lexicon=lexicon),
        NegationValidator(
            as_str_list(modality, "negation"), as_str_list(modality, "negation_exceptions")
        ),
    ]
    if user_terms:
        validators.append(ProtectedTermValidator(user_terms))
    validators.append(
        HedgeValidator(
            as_str_list(modality, "hedges"),
            as_str_list(modality, "certainty"),
            rule_set.epistemic_rule_ids,
        )
    )
    epistemology = lang / EPISTEMOLOGY_FILE
    if epistemology.is_file():
        validators.append(
            EpistemicValidator(EpistemicLexicon.load(epistemology), rule_set.epistemic_rule_ids)
        )
    validators.append(GrammarHeuristicValidator())
    validators.append(LengthRatioValidator(*config.length_ratio))
    return validators


def load_dictionaries(config: PipelineConfig, paths: ProjectPaths) -> DictionarySet:
    """Diccionaris actius segons la configuració (noms dins de ``dictionaries/`` o rutes)."""
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
    """Feedback manual: el fitxer de la configuració o el que indica el fitxer de preferències."""
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
