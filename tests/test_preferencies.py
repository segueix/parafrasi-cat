"""Fase 6: preferències explícites de l'autor i jerarquia de prioritats."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from parafrasi_cat import PipelineConfig, build_pipeline
from parafrasi_cat.analyzer import ClosedClassLexicon, RuleBasedAnalyzer
from parafrasi_cat.candidates import Candidate
from parafrasi_cat.cli import main
from parafrasi_cat.core import ConfigError
from parafrasi_cat.dictionaries import DictionaryEntry, DictionarySet, TermDictionary
from parafrasi_cat.preferences import (
    AuthorPreferences,
    FeedbackCounts,
    FeedbackStore,
    PreferenceEvaluator,
    PreferenceLevel,
    PreferenceResolver,
    describe_hierarchy,
)
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.rewrite import RewriteOptions, rewrite, rewrite_main
from parafrasi_cat.scoring import DIMENSIONS, CompositeScorer, ScoringWeights
from parafrasi_cat.style import (
    DocumentObserver,
    StyleEvaluator,
    StyleFingerprint,
    StyleProfile,
    StyleResources,
    build_fingerprint,
    load_corpus,
)

SARCOFAG = (
    "En aquest sarcòfag fet per l’escultor Benedetto da Rovezzano hi ha la presència de dos "
    "cranis acompanyats de dos ossos creuats, així com dues serps també creuades."
)


def write_preferences(path: Path, **data: object) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


# --- fitxer de preferències -----------------------------------------------------------------


def test_load_author_preferences(paths: ProjectPaths) -> None:
    prefs = AuthorPreferences.load(paths.resolve_preferences("author"))
    assert prefs.name == "autor" and prefs.path == paths.preferences / "author.yml"
    assert "així com" in prefs.prefer and "a nivell de" in prefs.avoid
    assert prefs.preferred_connectors == ("tanmateix", "així doncs")
    assert prefs.preferred_sentence_length == 22 and prefs.max_sentence_length == 45
    assert prefs.preferred_variants == {"obra de": 1.0, "fet per": 0.4, "realitzat per": 0.7}
    assert prefs.weight_of("Obra de") == 1.0 and prefs.weight_of("fet per") == 0.4
    assert prefs.weight_of("a nivell de") == 0.0 and prefs.weight_of("tanmateix") == 1.0
    assert prefs.weight_of("inexistent") is None and prefs.reason_of("inexistent") is None
    assert "prefer" in (prefs.reason_of("així com") or "")
    assert "0.40" in (prefs.reason_of("fet per") or "")
    assert prefs.feedback_file == paths.preferences / "feedback.yml"
    assert not prefs.is_empty and "obra de" in prefs.forms and "tanmateix" in prefs.forms
    variants = prefs.to_dict()["preferred_variants"]
    assert isinstance(variants, dict) and variants["fet per"] == 0.4
    assert prefs.to_dict()["feedback"] == str(paths.preferences / "feedback.yml")
    assert "longitud de frase màxima: 45" in prefs.summary()
    assert prefs.source_label == "preferències de l'autor (author.yml)"


def test_author_preferences_validation() -> None:
    with pytest.raises(ConfigError):
        AuthorPreferences(prefer=("però",), avoid=("Però",))
    with pytest.raises(ConfigError):
        AuthorPreferences(preferred_variants={"x": 1.5})
    with pytest.raises(ConfigError):
        AuthorPreferences(preferred_sentence_length=30, max_sentence_length=20)
    with pytest.raises(ConfigError):
        AuthorPreferences(max_sentence_length=0)
    with pytest.raises(ConfigError):
        AuthorPreferences.from_mapping({"prefered": ["x"]})
    with pytest.raises(ConfigError):
        AuthorPreferences.from_mapping({"preferred_variants": {"x": "alt"}})
    assert AuthorPreferences().is_empty and AuthorPreferences().forms == ()
    assert AuthorPreferences(prefer=("a", "A", " a ")).prefer == ("a",)


# --- jerarquia -----------------------------------------------------------------------------


def test_hierarchy_resolution(tmp_path: Path) -> None:
    historia = TermDictionary(
        "historia",
        (DictionaryEntry("sarcòfag", avoid=("fèretre",), protected=True, notes="No substituir."),),
    )
    author = AuthorPreferences(
        prefer=("fèretre", "obra de"),
        avoid=("sarcòfag",),
        preferred_variants={"fet per": 0.4},
        path=tmp_path / "author.yml",
    )
    feedback = FeedbackStore(
        {
            "fèretre": FeedbackCounts(preferred=5),
            "realitzat per": FeedbackCounts(rejected=3),
            "obra de": FeedbackCounts(rejected=9),
        },
        path=tmp_path / "feedback.yml",
    )
    resolver = PreferenceResolver(
        dictionaries=DictionarySet((historia,)),
        author=author,
        feedback=feedback,
        protected_terms=("Reial Acadèmia",),
    )
    assert resolver.active
    explicit = resolver.resolve("reial acadèmia")
    assert explicit is not None
    assert explicit.level is PreferenceLevel.EXPLICIT_PROTECTION and explicit.weight == 1.0
    protected = resolver.resolve("Sarcòfag")  # l'autor l'evita, però el diccionari el protegeix
    assert protected is not None
    assert protected.level is PreferenceLevel.DICTIONARY_PROTECTION and protected.weight == 1.0
    assert "historia" in protected.source
    avoided = resolver.resolve(
        "fèretre"
    )  # l'autor el prefereix i el feedback el lloa: mana el diccionari
    assert avoided is not None
    assert avoided.level is PreferenceLevel.DICTIONARY and avoided.weight == -1.0
    assert "No substituir." in avoided.reason
    preferred = resolver.resolve("obra de")  # el feedback el rebutja: mana el fitxer explícit
    assert preferred is not None
    assert preferred.level is PreferenceLevel.AUTHOR and preferred.weight == 1.0
    assert "author.yml" in preferred.source
    variant = resolver.resolve("fet per")
    assert variant is not None and variant.weight == pytest.approx(-0.2)
    assert "0.40" in variant.reason
    fed = resolver.resolve("realitzat per")
    assert fed is not None and fed.level is PreferenceLevel.AUTHOR and fed.weight < 0
    assert "feedback" in fed.source and "rebutjada 3" in fed.reason
    assert resolver.resolve("desconegut") is None  # queda per a l'empremta (5) i el motor (6)
    assert resolver.explicit_forms() >= {
        "reial acadèmia", "sarcòfag", "fèretre", "obra de", "fet per", "realitzat per"
    }  # fmt: skip
    assert "«fèretre» -1.00" in avoided.describe()
    assert describe_hierarchy().startswith("1. fragments protegits explícitament")
    assert describe_hierarchy().rstrip().endswith("6. preferències generals del motor")
    assert "diccionaris: historia" in resolver.describe()
    assert not PreferenceResolver().active and PreferenceResolver().forms == ()
    assert PreferenceLevel.FINGERPRINT.label == "empremta estadística de l'autor"


@pytest.fixture(scope="module")
def academic(
    paths: ProjectPaths, lexicon: ClosedClassLexicon, catalan_analyzer: RuleBasedAnalyzer
) -> tuple[StyleResources, StyleFingerprint]:
    resources = StyleResources.load(paths, lexicon=lexicon)
    corpus = load_corpus(paths.corpus / "exemples" / "academic")
    return resources, build_fingerprint(corpus, resources, catalan_analyzer, name="academic")


def test_explicit_preferences_take_priority_over_fingerprint(
    academic: tuple[StyleResources, StyleFingerprint], catalan_analyzer: RuleBasedAnalyzer
) -> None:
    resources, fingerprint = academic
    profile = StyleProfile.from_fingerprint(fingerprint)
    text = (
        "El pont és el testimoni més antic de la comarca. Però la barana va ser acabada "
        "més tard per un altre mestre."
    )
    plain = StyleEvaluator(profile, catalan_analyzer, resources=resources)
    distance = plain.distance(text)
    assert "variants_autor" in distance.components and "connectors_autor" in distance.components
    observations = DocumentObserver(resources).observe(catalan_analyzer.analyze(text))
    variant_ids = [vid for group in observations.variants.values() for vid in group]
    connectors = [hit.form for hit in observations.connectors]
    assert variant_ids and connectors
    covered = StyleEvaluator(
        profile, catalan_analyzer, resources=resources, explicit_forms=[*variant_ids, *connectors]
    )
    assert covered.explicit_forms >= {v.lower() for v in variant_ids}
    deferred = covered.distance(text)
    assert "variants_autor" not in deferred.components
    assert "connectors_autor" not in deferred.components
    assert deferred.total < distance.total
    partial = StyleEvaluator(
        profile, catalan_analyzer, resources=resources, explicit_forms=connectors
    )
    assert "variants_autor" in partial.distance(text).components
    assert "connectors_autor" not in partial.distance(text).components


# --- efecte a la puntuació i a la selecció -------------------------------------------------


def test_preferences_change_selection_and_explain_it(tmp_path: Path) -> None:
    prefs = write_preferences(
        tmp_path / "author.yml",
        preferred_variants={"obra de": 1.0, "fet per": 0.2, "realitzat per": 0.5},
    )
    result = build_pipeline(PipelineConfig(rule_set="parafrasi", preferences=str(prefs))).run(
        SARCOFAG
    )
    assert "obra de l’escultor" in result.output_text
    assert result.preferences_name == "author"
    selected = result.sentences[0].selected
    assert selected.score is not None
    assert selected.score.components["preferencies"] > 0
    explanation = selected.score.preference_explanation
    assert "introdueix «obra de»" in explanation and "elimina «fet per»" in explanation
    assert "author.yml" in explanation and "pes 1.00" in explanation
    assert selected.score.dimensions["preferencies_autor"] == 1.0
    assert "preferències de l'autor +" in selected.score.explanation
    assert "Preferències de l'autor (+" in result.report()
    assert "Preferències de l'autor: author" in result.report()
    assert "introdueix «obra de»" in result.explain()
    assert "preferències de l'autor 1.00" in selected.score.describe_dimensions()
    reversed_prefs = write_preferences(
        tmp_path / "invers.yml",
        preferred_variants={"obra de": 0.0, "fet per": 1.0, "realitzat per": 0.0},
    )
    kept = build_pipeline(
        PipelineConfig(rule_set="parafrasi", preferences=str(reversed_prefs))
    ).run(SARCOFAG)
    assert "fet per l’escultor" in kept.output_text
    # Els candidats que introdueixen una forma evitada són els pitjor puntuats.
    scored = [e for e in kept.sentences[0].candidates if e.score is not None and e.accepted]
    worst = min(scored, key=lambda e: e.score.total if e.score is not None else 0.0)
    assert "obra de" in worst.candidate.text or "realitzat per" in worst.candidate.text
    assert worst.score is not None and worst.score.components["preferencies"] < 0


def test_avoided_and_preferred_forms_in_evaluator() -> None:
    author = AuthorPreferences(prefer=("així com",), avoid=("i també",))
    evaluator = PreferenceEvaluator(PreferenceResolver(author=author))
    source = "Hi ha dos cranis, així com dues serps."
    worse = evaluator.assess(source, "Hi ha dos cranis, i també dues serps.")
    assert worse.score == -1.0 and worse.applies
    assert "introdueix «i també»" in worse.explanation
    assert "elimina «així com»" in worse.explanation
    same = evaluator.assess(source, source)
    assert same.score == 0.0 and not same.applies and same.explanation == ""
    better = evaluator.assess("Hi ha dos cranis, i també dues serps.", source)
    assert better.score == 1.0
    assert better.changes[0].contribution == 1.0
    data = worse.to_dict()
    changes = data["changes"]
    assert isinstance(changes, list) and data["score"] == -1.0
    assert {c["form"] for c in changes} == {"i també", "així com"}
    assert changes[0]["level"] == PreferenceLevel.AUTHOR.value
    twice = evaluator.assess(source, "I també, i també.")
    assert "introdueix «i també» (2 vegades)" in twice.explanation


def test_max_sentence_length_penalty(catalan_analyzer: RuleBasedAnalyzer) -> None:
    author = AuthorPreferences(max_sentence_length=6)
    evaluator = PreferenceEvaluator(
        PreferenceResolver(author=author),
        max_sentence_length=author.max_sentence_length,
        analyzer=catalan_analyzer,
    )
    assert evaluator.max_sentence_length == 6
    long_text = "Aquesta frase té més de sis paraules en total."
    assessment = evaluator.assess(long_text, long_text)
    assert assessment.length_penalty == -1.0 and assessment.score == -1.0 and assessment.applies
    assert "supera el màxim de 6" in assessment.explanation
    split = "Aquesta frase és curta. Aquesta també ho és."
    assert evaluator.assess(long_text, split).score == 0.0
    assert evaluator.sentence_lengths(split) == (4, 4)
    fallback = PreferenceEvaluator(PreferenceResolver(author=author), max_sentence_length=6)
    assert fallback.sentence_lengths(split) == (4, 4)
    assert fallback.assess(long_text, long_text).length_penalty == -1.0
    assert (
        PreferenceEvaluator(PreferenceResolver(author=author)).assess(long_text, long_text).score
        == 0.0
    )


def test_scoring_weight_and_dimension() -> None:
    weights = ScoringWeights.from_mapping({"preferences": 0.2})
    assert weights.preferences == 0.2 and weights.to_dict()["preferences"] == 0.2
    assert ScoringWeights().preferences == 0.5
    with pytest.raises(ConfigError):
        ScoringWeights(preferences=-1)
    assert "preferencies_autor" in DIMENSIONS
    evaluator = PreferenceEvaluator(
        PreferenceResolver(author=AuthorPreferences(avoid=("degut a",)))
    )
    scorer = CompositeScorer(ScoringWeights(preferences=0.5), preference_evaluator=evaluator)
    assert scorer.preference_evaluator is evaluator
    source = "Plou a causa del vent."
    changed = Candidate(0, source, "Plou degut a un vent fort.")
    score = scorer.score(changed)
    assert score.valid and score.components["preferencies"] == -0.5 and score.total == -0.5
    assert score.dimensions["preferencies_autor"] == 0.0
    assert "degut a" in score.preference_explanation
    assert "preferències de l'autor -0.500" in score.explanation
    assert score.to_dict()["preference_explanation"] == score.preference_explanation
    neutral = scorer.score(Candidate.identity(0, source))
    assert "preferencies" not in neutral.components
    assert neutral.dimensions["preferencies_autor"] is None
    assert neutral.preference_explanation == "" and neutral.total == 0.0


# --- configuració, CLI i rewrite ----------------------------------------------------------


def test_config_cli_and_rewrite_options(
    tmp_path: Path, project_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = PipelineConfig.from_mapping(
        {
            "dictionaries": ["historia", "dictionaries/escacs.yml"],
            "preferences": "preferences/author.yml",
            "feedback": "preferences/feedback.yml",
        },
        base_dir=project_root,
    )
    assert config.dictionaries == ("historia", str(project_root / "dictionaries/escacs.yml"))
    assert config.preferences == str(project_root / "preferences/author.yml")
    assert config.feedback == project_root / "preferences/feedback.yml"
    data = config.to_dict()
    assert data["dictionaries"] == list(config.dictionaries)
    assert data["preferences"] == config.preferences
    assert data["feedback"] == str(config.feedback)
    assert PipelineConfig().to_dict()["preferences"] is None
    assert PipelineConfig().to_dict()["dictionaries"] == []
    pipeline = build_pipeline(PipelineConfig(preferences="author"))
    assert pipeline.preferences_name == "autor"
    assert pipeline.style_profile is not None
    assert pipeline.style_profile.target_sentence_length == 22.0
    assert main(["--preferences", "author", "--dictionary", "historia", "--info"]) == 0
    out = capsys.readouterr().out
    assert "preferences: author" in out and "dictionaries: ['historia']" in out
    source = tmp_path / "text.txt"
    source.write_text(SARCOFAG + "\n", encoding="utf-8")
    assert (
        rewrite_main([str(source), "--preferences", "author", "--dictionary", "historia", "-q"])
        == 0
    )
    assert "obra de l’escultor" in capsys.readouterr().out
    options = RewriteOptions(dictionaries=("historia",), preferences="author")
    assert options.to_config().dictionaries == ("historia",)
    assert options.to_config().preferences == "author"
    result = rewrite(SARCOFAG, options)
    assert result.dictionary_names == ("historia",) and result.preferences_name == "autor"
    report = result.report()
    assert "Diccionaris actius: historia" in report and "Preferències de l'autor: autor" in report
    assert result.to_dict()["dictionaries"] == ["historia"]
    assert result.to_dict()["preferences"] == "autor"
    assert "Diccionaris actius: historia" in result.explain()
    assert main(["--preferences", "inexistent", "Hola."]) == 1
    assert "preferències" in capsys.readouterr().err
