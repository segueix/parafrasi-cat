"""v1.2: empremta amb estructura sintàctica real i ritme de frases.

L'empremta ha de respondre «com escriu aquest autor?» i no només «quines
paraules fa servir?». Els tests cobreixen el ritme (longituds, franges,
transicions, trigrames, ratxes, alternança, paràgrafs), el perfil sintàctic
(coordinació, subordinació, ordre, distància de dependències, complexitat,
patrons abstractes), la puntuació de candidats, el determinisme, la
compatibilitat amb empremtes antigues i el corpus petit.

Els tests que necessiten el parser se salten si no està instal·lat.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from parafrasi_cat import PipelineConfig, build_pipeline
from parafrasi_cat.analyzer import ClosedClassLexicon, RuleBasedAnalyzer
from parafrasi_cat.candidates import Candidate
from parafrasi_cat.core import SemanticRisk
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import Transformation, TransformationType
from parafrasi_cat.pipeline import SourceMode
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.scoring import CompositeScorer, ScoringContext, ScoringWeights
from parafrasi_cat.style.adaptation import AdaptationContext, AuthorAdaptation, UnitStats
from parafrasi_cat.style.corpus import corpus_from_texts, load_corpus
from parafrasi_cat.style.fingerprint import SCHEMA_VERSION, StyleFingerprint
from parafrasi_cat.style.observations import StyleResources
from parafrasi_cat.style.preferences import StylePreferences
from parafrasi_cat.style.profiler import build_fingerprint
from parafrasi_cat.style.rhythm import (
    FALLBACK_LONG_MIN,
    FALLBACK_SHORT_MAX,
    lag1_correlation,
    rhythm_profile,
    rhythm_similarity,
    run_statistics,
    thresholds_for,
    transition_counts,
    trigram_counts,
)
from parafrasi_cat.style.schema import SCHEMA_FILE, load_schema, validate
from parafrasi_cat.style.syntax_profile import (
    observe_sentence_syntax,
    syntactic_profile,
    syntactic_similarity,
)
from parafrasi_cat.syntax import SpacySyntax
from parafrasi_cat.validation import ValidationResult
from parafrasi_cat.web import RewriteService

AUTHOR_LENGTHS = [12, 38, 17, 44, 15, 31, 11, 46]
CANDIDATE_A = [26, 29, 27, 30, 28, 27, 29, 28]
CANDIDATE_B = [14, 36, 18, 41, 16, 32, 13, 43]

#: Corpus de prova amb tendència a MAIN + subordinada, MAIN + coordinació i
#: complement anteposat + MAIN. Frases curtes i llargues, com un autor real.
SYNTACTIC_CORPUS = [
    (
        "El rei, que és el centre del tauler, no necessita gaire explicació. "
        "Quan la reina ocupa el costat del rei, la posició queda protegida. "
        "El cavaller combat i el roc defensa la torre. "
        "Al segle XIII, el peó era la peça més modesta del joc. "
        "Encara que tingui un nom menys evident, el roc pot ser assimilat al veguer. "
        "La peça que apareix al costat del rei té una funció diferent. "
        "Segons la documentació conservada, el joc arribà a la península abans del 1050. "
        "El rei governa el tauler, però el cavaller decideix la batalla."
    ),
    (
        "Al principi, el tauler tenia menys peces i regles més simples. "
        "La reina, que avui és la peça més poderosa, era aleshores un conseller. "
        "Quan el joc arribà a Europa, els noms de les peces canviaren. "
        "El bisbe substituí l'elefant i la torre substituí el carro. "
        "Encara que el nom canviés, la funció es mantingué. "
        "Els tractats que es conserven descriuen partides i problemes. "
        "Durant el segle XV, la reina adquirí el moviment actual. "
        "El joc medieval era lent, però el joc modern és ràpid i tàctic."
    ),
    (
        "Quan el rei queda amenaçat, el jugador ha de respondre. "
        "La torre, que abans era un carro, avança en línia recta. "
        "En les partides llargues, el peó decideix el final. "
        "El cavaller salta i el bisbe llisca per la diagonal. "
        "Els problemes que publicaven les revistes eren difícils. "
        "Encara que la reina sigui poderosa, el rei és la peça essencial. "
        "Segons els manuals antics, la partida començava amb el peó del rei. "
        "El jugador prudent defensa, però el jugador audaç ataca."
    ),
]
SIMPLE_TEXT = (
    "El rei és el centre del tauler. La reina ocupa el costat. El cavaller és militar. "
    "El roc té un nom evident. El peó és la peça modesta. El bisbe mou en diagonal."
)
SIMILAR_TEXT = (
    "El rei, que és el centre del tauler, no necessita explicació. "
    "Quan la reina ocupa el costat, la posició queda protegida. "
    "El cavaller combat i el roc defensa. "
    "Al segle XIII, el peó era la peça més modesta. "
    "Encara que tingui un nom evident, el roc sorprèn. "
    "El bisbe mou en diagonal, però el cavaller salta."
)


def node(container: object, *keys: str) -> dict[str, Any]:
    """Subdiccionari d'un perfil, comprovant que ho és (per a mypy i per al test)."""
    current: object = container
    for key in keys:
        assert isinstance(current, dict), keys
        current = current[key]
    assert isinstance(current, dict), keys
    return current


@pytest.fixture(scope="module")
def parser() -> SpacySyntax:
    found = SpacySyntax()
    if not found.available:
        pytest.skip(f"El parser sintàctic no està instal·lat ({found.failure}).")
    return found


@pytest.fixture(scope="module")
def resources(paths: ProjectPaths, lexicon: ClosedClassLexicon) -> StyleResources:
    return StyleResources.load(paths, lexicon=lexicon)


@pytest.fixture(scope="module")
def syntactic_fingerprint(
    parser: SpacySyntax, resources: StyleResources, catalan_analyzer: RuleBasedAnalyzer
) -> StyleFingerprint:
    corpus = corpus_from_texts(SYNTACTIC_CORPUS)
    return build_fingerprint(corpus, resources, catalan_analyzer, name="sintactic", syntax=parser)


@pytest.fixture(scope="module")
def narrative_fingerprint(
    project_root: Path,
    parser: SpacySyntax,
    resources: StyleResources,
    catalan_analyzer: RuleBasedAnalyzer,
) -> StyleFingerprint:
    corpus = load_corpus(project_root / "corpus" / "exemples" / "narratiu")
    return build_fingerprint(corpus, resources, catalan_analyzer, name="narratiu", syntax=parser)


# --- ritme (sense parser) ---------------------------------------------------------------


def test_rhythm_profile_describes_the_sequence_not_only_the_mean() -> None:
    profile = rhythm_profile([AUTHOR_LENGTHS, AUTHOR_LENGTHS], n_documents=2)
    length = node(profile, "length")
    assert {"mean", "median", "std", "cv", "min", "max", "p10", "p25", "p50", "p75", "p90"} <= set(
        length
    )
    assert length["min"] == 11 and length["max"] == 46
    buckets = node(profile, "buckets")
    assert buckets["thresholds"]["source"] == "tercils"
    assert abs(sum(buckets["shares"].values()) - 1.0) < 1e-9
    transitions = node(profile, "transitions", "shares")
    assert transitions["short_to_long"] > 0.5  # 12→38, 17→44, 15→31, 11→46
    assert transitions["long_to_short"] >= 0.5
    alternation = node(profile, "alternation")
    assert alternation["lag1_sentence_length_correlation"] < -0.5
    assert alternation["mean_absolute_sentence_length_change"] > 20
    assert profile["confidence"] == "medium"
    assert "paraules" in str(profile["unit"]) and "puntuació" in str(profile["unit"])


def test_uniform_and_alternating_sequences_are_told_apart() -> None:
    uniform = rhythm_profile([CANDIDATE_A], n_documents=1)
    alternating = rhythm_profile([CANDIDATE_B], n_documents=1)
    assert node(uniform, "length")["cv"] < node(alternating, "length")["cv"]
    lag_a, lag_b = lag1_correlation([CANDIDATE_A]), lag1_correlation([CANDIDATE_B])
    assert lag_a is not None and lag_b is not None
    assert lag_b < lag_a
    labels = [["medium"] * 6, ["short", "long", "short", "long"]]
    runs = run_statistics(labels)
    assert runs["same_bucket_run_max"] == 6 and runs["repeated_medium_run_rate"] == 1.0
    assert runs["repeated_short_run_rate"] == 0.0
    assert trigram_counts([["short", "long", "short", "long"]]) == {"L-S-L": 1, "S-L-S": 1}
    counts = transition_counts([["short", "long", "short"]])
    assert counts["short_to_long"] == 1 and counts["long_to_short"] == 1


def test_small_corpus_uses_documented_fallbacks_and_never_lies() -> None:
    profile = rhythm_profile([[12, 30, 9]], n_documents=1)
    assert profile["confidence"] == "low"
    thresholds = node(profile, "buckets", "thresholds")
    assert thresholds == {
        "short_max": FALLBACK_SHORT_MAX,
        "long_min": FALLBACK_LONG_MIN,
        "source": "reserva",
    }
    assert node(profile, "alternation")["lag1_sentence_length_correlation"] is None
    assert node(profile, "paragraphs")["available"] is False
    assert thresholds_for([float(n) for n in range(30)])["source"] == "tercils"
    score, _, _ = rhythm_similarity(CANDIDATE_B, profile)
    assert score is None, "amb confiança baixa no es puntua res"
    empty = rhythm_profile([[]], n_documents=1)
    assert empty["sample_size_sentences"] == 0 and empty["length"] == {}


def test_rhythm_example_from_the_specification() -> None:
    """Corpus 12/38/17/44/15/31/11/46: B (14/36/18/41/…) ha de guanyar A (26/29/27/…)."""
    profile = rhythm_profile([AUTHOR_LENGTHS, AUTHOR_LENGTHS], n_documents=2)
    score_a, partial_a, _ = rhythm_similarity(CANDIDATE_A, profile)
    score_b, partial_b, _ = rhythm_similarity(CANDIDATE_B, profile)
    assert score_a is not None and score_b is not None
    assert score_b > score_a
    assert partial_b["variacio"] > partial_a["variacio"]
    assert partial_b["transicions"] > partial_a["transicions"]


# --- perfil sintàctic (amb parser) ---------------------------------------------------------


def test_nominal_coordination_is_detected(parser: SpacySyntax) -> None:
    stats = observe_sentence_syntax(parser.parse("El rei i la reina ocupen una posició central."))
    assert stats is not None
    assert stats.coordinations == (("nominal", 2),)
    assert stats.conjunctions == ("i",)
    assert stats.clause_count == 1 and stats.subordinates == ()


def test_clausal_coordination_is_detected_when_the_parser_sees_it(parser: SpacySyntax) -> None:
    sentence = (
        "Segons la documentació, l'església existia abans del 1050, però no es pot demostrar."
    )
    stats = observe_sentence_syntax(parser.parse(sentence))
    assert stats is not None
    assert any(kind == "clausal" for kind, _ in stats.coordinations)
    assert "però" in stats.conjunctions
    assert "COORD" in stats.pattern and stats.pattern.startswith("OBL + MAIN")
    # «El rei governa i el cavaller combat.»: el parser real pot no reconèixer
    # «governa» com a verb i deixar l'anàlisi sense verb conjugat. Aleshores la
    # frase es descarta (no és fiable) en lloc de comptar-la malament; si l'analitza,
    # hi ha de veure una coordinació, del tipus que sigui.
    other = observe_sentence_syntax(parser.parse("El rei governa i el cavaller combat."))
    if other is not None:
        assert other.n_coordinations >= 1
        assert all(
            kind in ("nominal", "clausal", "adjectival", "adverbial", "other")
            for kind, _ in other.coordinations
        )


def test_subordination_is_reflected(parser: SpacySyntax) -> None:
    concessive_sentence = (
        "El roc, encara que tingui un nom menys evident, pot ser assimilat a la funció de veguer."
    )
    concessive = observe_sentence_syntax(parser.parse(concessive_sentence))
    relative = observe_sentence_syntax(
        parser.parse("La peça que apareix al costat del rei té una funció diferent.")
    )
    assert concessive is not None and relative is not None
    assert "adverbial" in concessive.subordinates
    assert "relative" in relative.subordinates
    assert concessive.clause_count >= 2 and relative.clause_count >= 2
    assert concessive.subordination_depth_max >= 1 and relative.subordination_depth_max >= 1
    assert "REL" in relative.pattern and "ADV" in concessive.pattern
    simple = observe_sentence_syntax(parser.parse("El rei és el centre del tauler."))
    assert simple is not None and simple.subordinates == () and simple.pattern == "MAIN"


def test_preposed_and_postposed_complements_are_told_apart(parser: SpacySyntax) -> None:
    fronted = observe_sentence_syntax(parser.parse("El 1507 es va encarregar el monument."))
    trailing = observe_sentence_syntax(parser.parse("El monument es va encarregar el 1507."))
    assert fronted is not None and trailing is not None
    assert fronted.complements_preposed == 1 and fronted.complements_postposed == 0
    assert trailing.complements_preposed == 0 and trailing.complements_postposed == 1
    assert fronted.initial_oblique and fronted.initial_temporal
    assert not trailing.initial_oblique
    assert fronted.subjects_after == 1 and trailing.subjects_before == 1
    assert fronted.pattern.startswith("TEMP + MAIN")


def test_dependency_distance_and_depth_are_measured(parser: SpacySyntax) -> None:
    stats = observe_sentence_syntax(
        parser.parse("La peça que apareix al costat del rei té una funció diferent.")
    )
    assert stats is not None
    assert stats.dependency_distances and all(d >= 1 for d in stats.dependency_distances)
    assert stats.parse_depth_max >= 3
    profile = syntactic_profile([stats], n_documents=1, parser="prova")
    distance = node(profile, "dependency_distance")
    assert {
        "mean_dependency_distance",
        "median_dependency_distance",
        "dependency_distance_std",
        "dependency_distance_p90",
        "max_dependency_distance",
    } <= set(distance)
    assert profile["confidence"] == "low"


def test_the_fingerprint_carries_the_syntactic_profile(
    syntactic_fingerprint: StyleFingerprint, project_root: Path
) -> None:
    assert syntactic_fingerprint.schema_version == SCHEMA_VERSION == "1.1"
    assert syntactic_fingerprint.has_syntactic_profile and syntactic_fingerprint.has_rhythm_profile
    assert validate(syntactic_fingerprint.to_dict(), load_schema(project_root / SCHEMA_FILE)) == []
    profile = syntactic_fingerprint.features["syntactic_profile"]
    assert isinstance(profile, dict) and profile["available"] is True
    assert profile["sample_size_sentences"] >= 15 and profile["confidence"] != "low"
    assert profile["subordination"]["sentences_with_subordination_share"] >= 0.4
    assert profile["coordination"]["per_sentence"] > 0.2
    assert profile["order"]["preposed_complement_rate"] > 0.2
    assert profile["patterns"]["top"] and all(
        "pattern" in item for item in profile["patterns"]["top"]
    )
    assert syntactic_fingerprint.generator["uses_models"] is True
    assert "només analitza" in str(syntactic_fingerprint.generator["method"])
    text = json.dumps(syntactic_fingerprint.features["syntactic_profile"], ensure_ascii=False)
    for fragment in ("el centre del tauler", "posició queda protegida"):
        assert fragment not in text, "el perfil no pot guardar cap frase del corpus"


def test_syntax_example_from_the_specification(
    syntactic_fingerprint: StyleFingerprint,
    parser: SpacySyntax,
    resources: StyleResources,
    catalan_analyzer: RuleBasedAnalyzer,
) -> None:
    adaptation = AuthorAdaptation(
        StylePreferences(syntactic_fingerprint), catalan_analyzer, resources, syntax=parser
    )
    assert "sintaxi" in adaptation.active_components()
    simple = adaptation.syntactic_similarity(SIMPLE_TEXT)
    similar = adaptation.syntactic_similarity(SIMILAR_TEXT)
    assert simple is not None and similar is not None
    assert similar > simple
    profile = syntactic_fingerprint.features["syntactic_profile"]
    assert isinstance(profile, dict)
    score, partial, _ = syntactic_similarity(adaptation.stats_of(SIMPLE_TEXT).syntax, profile)
    assert score is not None and partial["subordinacio"] < 0.6


# --- puntuació i determinisme ----------------------------------------------------------------


def make_candidate(source: str, text: str) -> Candidate:
    transformation = Transformation(
        rule_id="prova.estil",
        text_before=source[:6],
        text_after=source[:6],
        changed_span=Span(0, 6),
        transformation_type=TransformationType.LEXICAL,
        confidence=0.9,
        semantic_risk=SemanticRisk.LOW,
        explanation="prova",
    )
    return Candidate(0, source, text, (transformation,))


def test_rhythm_and_syntax_only_break_ties_between_safe_candidates(
    narrative_fingerprint: StyleFingerprint,
    parser: SpacySyntax,
    resources: StyleResources,
    catalan_analyzer: RuleBasedAnalyzer,
) -> None:
    adaptation = AuthorAdaptation(
        StylePreferences(narrative_fingerprint), catalan_analyzer, resources, syntax=parser
    )
    scorer = CompositeScorer(ScoringWeights(author_affinity=100.0), adaptation=adaptation)
    source = "El rei és el centre del tauler."
    from parafrasi_cat.validation import ValidationDimension

    invalid = ValidationResult.error("prova", "perd una data", ValidationDimension.FACTUAL)
    score = scorer.score(make_candidate(source, SIMILAR_TEXT), ScoringContext(invalid, source))
    assert not score.valid and score.total == -1.0
    valid = scorer.score(
        make_candidate(source, SIMILAR_TEXT), ScoringContext(ValidationResult.passed(), source)
    )
    components = node(valid.author_affinity, "components")
    assert valid.valid and components.get("ritme") is not None
    assert components.get("sintaxi") is not None
    assert "partials" in valid.author_affinity


def test_scores_and_fingerprints_are_deterministic(
    parser: SpacySyntax, resources: StyleResources, catalan_analyzer: RuleBasedAnalyzer
) -> None:
    corpus = corpus_from_texts(SYNTACTIC_CORPUS)
    first = build_fingerprint(corpus, resources, catalan_analyzer, name="s", syntax=parser)
    second = build_fingerprint(corpus, resources, catalan_analyzer, name="s", syntax=parser)
    assert first.to_dict() == second.to_dict()
    adaptation = AuthorAdaptation(
        StylePreferences(first), catalan_analyzer, resources, syntax=parser
    )
    context = AdaptationContext(
        before=adaptation.stats_of("El tauler és antic."), after=UnitStats()
    )
    one = adaptation.assess(SIMILAR_TEXT, context=context, source_text=SIMPLE_TEXT)
    two = adaptation.assess(SIMILAR_TEXT, context=context, source_text=SIMPLE_TEXT)
    assert one == two


def test_own_mode_uses_the_light_weight_and_llm_draft_the_full_one(
    tmp_path: Path, narrative_fingerprint: StyleFingerprint
) -> None:
    path = narrative_fingerprint.save(tmp_path / "narratiu.json")
    own = build_pipeline(PipelineConfig(rule_set="parafrasi", level=3, style_profile=str(path)))
    draft = build_pipeline(
        PipelineConfig(
            rule_set="parafrasi", level=3, style_profile=str(path), source_mode=SourceMode.LLM_DRAFT
        )
    )
    assert own.adaptation is not None and draft.adaptation is not None
    weights = ScoringWeights()
    own_scorer, draft_scorer = own._scorer, draft._scorer  # noqa: SLF001
    assert isinstance(own_scorer, CompositeScorer) and isinstance(draft_scorer, CompositeScorer)
    assert own_scorer.weights.author_affinity == weights.author_affinity_own
    assert draft_scorer.weights.author_affinity == weights.author_affinity
    assert weights.author_affinity_own < weights.author_affinity
    result = own.run("El sarcòfag presenta dos cranis i dues serps creuades.")
    assert result.output_text


# --- compatibilitat amb empremtes antigues -------------------------------------------------


def test_old_fingerprints_load_and_report_the_new_sections_as_unavailable(
    tmp_path: Path, narrative_fingerprint: StyleFingerprint, project_root: Path
) -> None:
    data = narrative_fingerprint.to_dict()
    data["schema_version"] = "1.0"
    features = data["features"]
    assert isinstance(features, dict)
    features.pop("rhythm_profile")
    features.pop("syntactic_profile")
    generator = node(data, "generator")
    generator["uses_models"] = False
    generator.pop("parser")
    old = StyleFingerprint.from_dict(data)
    assert old.schema_version == "1.0"
    assert not old.has_rhythm_profile and not old.has_syntactic_profile
    assert validate(old.to_dict(), load_schema(project_root / SCHEMA_FILE)) == []

    root = tmp_path / "projecte"
    root.mkdir()
    for name in ("resources", "rules", "dictionaries", "corpus", "preferences"):
        (root / name).symlink_to(project_root / name, target_is_directory=True)
    (root / "style").mkdir()
    old.save(root / "style" / "antiga.json")
    service = RewriteService(ProjectPaths(root))
    summary = service.fingerprint_summary("style/antiga.json")
    assert summary["rhythm"]["available"] is False and summary["syntax"]["available"] is False
    assert "Torna-la a crear" in summary["regenerate_hint"]
    pipeline = build_pipeline(
        PipelineConfig(
            rule_set="parafrasi", level=2, style_profile=str(root / "style" / "antiga.json")
        )
    )
    assert pipeline.adaptation is not None
    assert "ritme" not in pipeline.adaptation.active_components()
    assert "sintaxi" not in pipeline.adaptation.active_components()


def test_the_web_summary_shows_structure_and_rhythm(
    tmp_path: Path, narrative_fingerprint: StyleFingerprint, project_root: Path
) -> None:
    root = tmp_path / "projecte"
    root.mkdir()
    for name in ("resources", "rules", "dictionaries", "corpus", "preferences"):
        (root / name).symlink_to(project_root / name, target_is_directory=True)
    (root / "style").mkdir()
    narrative_fingerprint.save(root / "style" / "narratiu.json")
    summary = RewriteService(ProjectPaths(root)).fingerprint_summary("style/narratiu.json")
    rhythm = summary["rhythm"]
    assert rhythm["available"] and set(rhythm["shares"]) == {"Curta", "Mitjana", "Llarga"}
    assert len(rhythm["transitions"]) == 9
    assert all(
        t["label"] in ("molt freqüent", "freqüent", "ocasional", "poc freqüent")
        for t in rhythm["transitions"]
    )
    syntax = summary["syntax"]
    assert syntax["available"] and "subjecte" in syntax["subject_order"]
    assert syntax["top_patterns"]
    assert summary["regenerate_hint"] == ""
    text = json.dumps(summary, ensure_ascii=False).lower()
    assert "humà" not in text and "detector" not in text
