"""v1.1: origen del text i adaptació autoral per a esborranys generats amb LLM.

El mode no detecta res ni amaga res: l'origen el diu l'usuari, i quan diu que
el text és un esborrany generat amb LLM, el motor prioritza els candidats que
s'assemblen més a l'empremta real de l'autor. Sense empremta no hi ha mode.

Tests A–J demanats: compatibilitat, selecció, empremta obligatòria,
connectors, longitud, invariants factuals, epistemologia, determinisme,
contaminació del corpus i funcionament fora de línia.
"""

from __future__ import annotations

import re
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from parafrasi_cat import PipelineConfig, build_pipeline
from parafrasi_cat.analyzer import ClosedClassLexicon, RuleBasedAnalyzer
from parafrasi_cat.candidates import Candidate
from parafrasi_cat.core import ConfigError, SemanticRisk
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import Transformation, TransformationType
from parafrasi_cat.pipeline import FINGERPRINT_REQUIRED, SourceMode
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.scoring import DIMENSIONS, CompositeScorer, ScoringContext, ScoringWeights
from parafrasi_cat.style.adaptation import AuthorAdaptation, UnitStats
from parafrasi_cat.style.corpus import load_corpus
from parafrasi_cat.style.observations import StyleResources
from parafrasi_cat.style.preferences import StylePreferences
from parafrasi_cat.style.profiler import build_fingerprint
from parafrasi_cat.validation import ValidationDimension, ValidationResult
from parafrasi_cat.web import RewriteService
from parafrasi_cat.web.service import LLM_DRAFT_NOT_CORPUS, FeedbackRequest, RewriteRequest

#: Esborrany amb la regularitat típica d'un text generatiu: connector per frase,
#: longituds semblants, «per la seva banda».
DRAFT = (
    "El rei constitueix el centre simbòlic del tauler, mentre que la reina ocupa una posició "
    "immediata al seu costat. El cavaller, per la seva banda, és fàcilment identificable per "
    "la seva funció militar. El roc, en canvi, presenta una denominació menys transparent."
)
ALTOVITI = (
    "La primera referència itàlica és el monument funerari d’Oddo Altoviti, encarregat el 1507 "
    "i finalitzat el 1516. En aquest sarcòfag fet per l’escultor Benedetto da Rovezzano hi ha la "
    "presència de dos cranis acompanyats de dos ossos creuats, així com dues serps també creuades."
)
FACTS = ("Oddo Altoviti", "1507", "1516", "Benedetto da Rovezzano", "dos cranis", "dos ossos")
EPISTEMIC = (
    "Aquesta documentació permet plantejar que l'església podria haver existit abans del 1050, "
    "però no es pot demostrar."
)
HEDGES = ("permet plantejar", "podria", "no es pot demostrar")

UNIFORM = (
    "El rei constitueix el centre simbòlic del tauler i la reina ocupa una posició al seu costat. "
    "El cavaller és fàcilment identificable per la seva funció militar i pel seu nom. "
    "El roc presenta una denominació menys transparent que les altres peces del joc. "
    "El peó constitueix la peça més nombrosa i la més modesta de tot el conjunt del tauler."
)
VARIED = (
    "El rei és el centre del tauler i no necessita gaire explicació. Al seu costat hi ha la "
    "reina. Amb el cavaller el problema és diferent: el cavall i la funció militar el fan prou "
    "transparent. El nom del roc, en canvi, és menys evident."
)
LOADED = (
    "En aquest sentit, el rei és el centre del tauler. Així doncs, la reina ocupa el seu costat. "
    "Per la seva banda, el cavaller és identificable. En canvi, el roc presenta un nom menys "
    "clar. Finalment, cal destacar que el peó és la peça més modesta."
)
PLAIN = (
    "El rei és el centre del tauler. La reina ocupa el seu costat. El cavaller és "
    "identificable. El roc presenta un nom menys clar. El peó és la peça més modesta."
)


@pytest.fixture(scope="module")
def resources(paths: ProjectPaths, lexicon: ClosedClassLexicon) -> StyleResources:
    return StyleResources.load(paths, lexicon=lexicon)


@pytest.fixture(scope="module")
def fingerprint_file(
    project_root: Path,
    tmp_path_factory: pytest.TempPathFactory,
    resources: StyleResources,
    catalan_analyzer: RuleBasedAnalyzer,
) -> Path:
    """Empremta d'un autor de frase desigual i pocs connectors (corpus «narratiu»)."""
    corpus = load_corpus(project_root / "corpus" / "exemples" / "narratiu")
    fingerprint = build_fingerprint(corpus, resources, catalan_analyzer, name="narratiu")
    return fingerprint.save(tmp_path_factory.mktemp("empremta") / "narratiu.json")


@pytest.fixture(scope="module")
def adaptation(
    fingerprint_file: Path, resources: StyleResources, catalan_analyzer: RuleBasedAnalyzer
) -> AuthorAdaptation:
    return AuthorAdaptation(StylePreferences.load(fingerprint_file), catalan_analyzer, resources)


def config(fingerprint_file: Path, source_mode: SourceMode = SourceMode.OWN) -> PipelineConfig:
    return PipelineConfig(
        rule_set="parafrasi",
        level=5,
        style_profile=str(fingerprint_file),
        source_mode=source_mode,
    )


def candidate(source: str, text: str, before: str, after: str) -> Candidate:
    """Candidat amb una transformació de guany idèntic, per comparar només l'estil."""
    start = source.index(before)
    transformation = Transformation(
        rule_id="prova.estil",
        text_before=before,
        text_after=after,
        changed_span=Span(start, start + len(before)),
        transformation_type=TransformationType.LEXICAL,
        confidence=0.9,
        semantic_risk=SemanticRisk.LOW,
        explanation="prova",
    )
    return Candidate(0, source, text, (transformation,))


# --- A: compatibilitat -----------------------------------------------------------------------


def test_own_text_keeps_the_previous_behaviour(fingerprint_file: Path) -> None:
    implicit = build_pipeline(config(fingerprint_file))
    explicit = build_pipeline(config(fingerprint_file, SourceMode.OWN))
    assert implicit.source_mode == "own" and implicit.adaptation is None
    assert explicit.adaptation is None
    first, second = implicit.run(DRAFT), explicit.run(DRAFT)
    assert first.to_dict() == second.to_dict()
    assert first.source_mode == "own"
    for sentence in first.sentences:
        for evaluated in sentence.candidates:
            assert evaluated.score is not None
            assert evaluated.score.dimensions["afinitat_autor"] is None
            assert evaluated.score.author_explanation == ""


def test_source_mode_defaults_to_own_everywhere() -> None:
    assert PipelineConfig().source_mode is SourceMode.OWN
    assert PipelineConfig.from_mapping({}).source_mode is SourceMode.OWN
    assert RewriteRequest(DRAFT).source_mode is SourceMode.OWN
    assert RewriteRequest.from_mapping({"text": DRAFT}).source_mode is SourceMode.OWN
    assert FeedbackRequest("preferred").source_mode is SourceMode.OWN
    assert SourceMode.parse("llm_draft") is SourceMode.LLM_DRAFT
    with pytest.raises(ConfigError):
        SourceMode.parse("desconegut")


# --- B: selecció -----------------------------------------------------------------------------


def test_llm_draft_activates_the_author_adaptation(fingerprint_file: Path) -> None:
    pipeline = build_pipeline(config(fingerprint_file, SourceMode.LLM_DRAFT))
    assert pipeline.source_mode == "llm_draft"
    assert pipeline.adaptation is not None
    assert pipeline.adaptation.name == "narratiu"
    assert "longitud" in pipeline.adaptation.active_components()
    result = pipeline.run(DRAFT)
    assert result.source_mode == "llm_draft"
    assert "afinitat_autor" in DIMENSIONS
    for sentence in result.sentences:
        for evaluated in sentence.candidates:
            assert evaluated.score is not None
            affinity = evaluated.score.dimensions["afinitat_autor"]
            assert affinity is not None and 0.0 <= affinity <= 1.0
            assert evaluated.score.author_affinity["components"]
    assert "esborrany generat amb LLM" in result.report()


# --- C: empremta obligatòria -----------------------------------------------------------------


def test_llm_draft_without_a_fingerprint_is_refused_with_a_clear_message() -> None:
    with pytest.raises(ConfigError, match=re.escape(FINGERPRINT_REQUIRED)):
        build_pipeline(PipelineConfig(rule_set="parafrasi", source_mode=SourceMode.LLM_DRAFT))
    service = RewriteService()
    with pytest.raises(ConfigError, match="empremta d'autor"):
        service.rewrite(RewriteRequest(DRAFT, source_mode=SourceMode.LLM_DRAFT))
    options = service.options()
    modes = {item["id"]: item for item in options["source_modes"]}
    assert modes["own"]["default"] is True and modes["own"]["requires_fingerprint"] is False
    assert modes["llm_draft"]["requires_fingerprint"] is True
    assert modes["llm_draft"]["description"] == (
        "El text s'adaptarà als patrons estilístics de l'empremta de l'autor."
    )
    assert options["fingerprint_required"] == FINGERPRINT_REQUIRED
    forbidden = ("humanitz", "detect", "indetectable", "rastres")
    for mode in modes.values():
        assert not any(word in mode["description"].lower() for word in forbidden)


# --- D: connectors ---------------------------------------------------------------------------


def test_connector_overuse_is_penalised_relative_to_the_fingerprint(
    adaptation: AuthorAdaptation,
) -> None:
    loaded = adaptation.assess(LOADED)
    plain = adaptation.assess(PLAIN)
    assert loaded.components["connectors"] < plain.components["connectors"]
    assert loaded.score < plain.score
    assert "connectors per frase" in loaded.notes["connectors"]


def test_a_candidate_that_adds_an_unusual_connector_loses_to_one_that_does_not(
    adaptation: AuthorAdaptation,
) -> None:
    source = "El roc presenta un nom menys clar."
    with_connector = candidate(
        source,
        "Per la seva banda, el roc presenta un nom menys clar.",
        "El roc",
        "Per la seva banda, el roc",
    )
    without = candidate(source, "El roc mostra un nom menys clar.", "presenta", "mostra")
    scorer = CompositeScorer(ScoringWeights(), adaptation=adaptation)
    ctx = ScoringContext(ValidationResult.passed(), source)
    scored_with, scored_without = scorer.score(with_connector, ctx), scorer.score(without, ctx)
    assert scored_with.components["afinitat_autor"] < 0.0
    assert scored_without.total > scored_with.total
    assert "connectors" in scored_with.author_explanation


# --- E: longitud i ritme ---------------------------------------------------------------------


def test_a_varied_rhythm_beats_a_uniform_one_when_the_author_alternates(
    adaptation: AuthorAdaptation,
) -> None:
    uniform = adaptation.assess(UNIFORM)
    varied = adaptation.assess(VARIED)
    assert varied.components["longitud"] > uniform.components["longitud"]
    assert varied.score > uniform.score


def test_the_scorer_prefers_the_distribution_closer_to_the_fingerprint(
    adaptation: AuthorAdaptation,
) -> None:
    """Amb la resta de criteris igual, el candidat de ritme més propi de l'autor guanya."""
    source = "El rei és el centre del tauler i la reina ocupa el seu costat."
    uniform = candidate(source, UNIFORM, "El rei", "El rei")
    varied = candidate(source, VARIED, "El rei", "El rei")
    scorer = CompositeScorer(ScoringWeights(), adaptation=adaptation)
    ctx = ScoringContext(ValidationResult.passed(), source)
    assert scorer.score(varied, ctx).total > scorer.score(uniform, ctx).total


# --- F i G: invariants ---------------------------------------------------------------------


def test_the_author_mode_never_loses_names_dates_or_quantities(fingerprint_file: Path) -> None:
    result = build_pipeline(config(fingerprint_file, SourceMode.LLM_DRAFT)).run(ALTOVITI)
    for fact in FACTS:
        assert fact in result.output_text, fact
    for sentence in result.sentences:
        for evaluated in sentence.candidates:
            if evaluated.accepted:
                for fact in FACTS:
                    if fact in sentence.source_text:
                        assert fact in evaluated.candidate.text, (fact, evaluated.candidate.text)


def test_the_author_mode_never_raises_certainty(fingerprint_file: Path) -> None:
    result = build_pipeline(config(fingerprint_file, SourceMode.LLM_DRAFT)).run(EPISTEMIC)
    lowered = result.output_text.lower()
    for hedge in HEDGES:
        assert hedge in lowered, hedge
    assert "demostra que" not in lowered and "confirma" not in lowered
    for evaluated in result.sentences[0].candidates:
        if evaluated.accepted:
            assert "no es pot demostrar" in evaluated.candidate.text


def test_style_can_never_compensate_an_invalidated_candidate(adaptation: AuthorAdaptation) -> None:
    source = "El rei és el centre del tauler."
    scorer = CompositeScorer(ScoringWeights(author_affinity=100.0), adaptation=adaptation)
    invalid = ValidationResult.error("prova", "perd una data", ValidationDimension.FACTUAL)
    score = scorer.score(
        candidate(source, VARIED, "El rei", "El rei"), ScoringContext(invalid, source)
    )
    assert not score.valid and score.total == -1.0


# --- H: determinisme -------------------------------------------------------------------------


def test_two_identical_runs_give_the_same_ranking(fingerprint_file: Path) -> None:
    first = build_pipeline(config(fingerprint_file, SourceMode.LLM_DRAFT)).run(DRAFT)
    second = build_pipeline(config(fingerprint_file, SourceMode.LLM_DRAFT)).run(DRAFT)
    assert first.to_dict() == second.to_dict()
    for a, b in zip(first.sentences, second.sentences, strict=True):
        assert [c.candidate.text for c in a.candidates] == [c.candidate.text for c in b.candidates]
        assert [c.score.total for c in a.candidates if c.score] == [
            c.score.total for c in b.candidates if c.score
        ]


# --- I: contaminació del corpus ------------------------------------------------------------------


def test_an_llm_draft_never_enters_the_authors_corpus(
    tmp_path: Path, project_root: Path, fingerprint_file: Path
) -> None:
    root = tmp_path / "projecte"
    root.mkdir()
    for name in ("resources", "rules", "dictionaries", "corpus", "preferences"):
        (root / name).symlink_to(project_root / name, target_is_directory=True)
    (root / "style").mkdir()
    (root / "style" / "narratiu.json").write_text(fingerprint_file.read_text("utf-8"), "utf-8")
    service = RewriteService(ProjectPaths(root))
    before = {p.name: p.stat().st_mtime_ns for p in (root / "style").iterdir()}

    with pytest.raises(ConfigError, match=re.escape(LLM_DRAFT_NOT_CORPUS)):
        service.create_fingerprint("autor", [DRAFT], source_mode="llm_draft")
    service.rewrite(
        RewriteRequest(DRAFT, style_profile="style/narratiu.json", source_mode=SourceMode.LLM_DRAFT)
    )
    after = {p.name: p.stat().st_mtime_ns for p in (root / "style").iterdir()}
    assert after == before, "una reescriptura d'esborrany no pot tocar cap empremta"
    created = service.create_fingerprint("propi", ["Text propi de prova. Curt."], source_mode="own")
    assert created["n_documents"] == 1


def test_feedback_records_where_the_text_came_from(tmp_path: Path, project_root: Path) -> None:
    root = tmp_path / "projecte"
    root.mkdir()
    for name in ("resources", "rules", "dictionaries", "corpus", "style"):
        (root / name).symlink_to(project_root / name, target_is_directory=True)
    (root / "preferences").mkdir()
    service = RewriteService(ProjectPaths(root))
    response = service.record_feedback(
        FeedbackRequest("acceptable", variants=("obra de",), source_mode=SourceMode.LLM_DRAFT)
    )
    assert response["source_mode"] == "llm_draft"
    assert response["recorded"][0]["variant"] == "obra de"


# --- J: fora de línia -------------------------------------------------------------------


class _LoopbackOnly(socket.socket):
    def connect(self, address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise AssertionError(f"Intent de connexió externa a {address!r}")
        super().connect(address)  # pragma: no cover - cap component ho fa aquí


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"Intent de connexió externa: {args} {kwargs}")

    monkeypatch.setattr(socket, "socket", _LoopbackOnly)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    yield


@pytest.mark.usefixtures("offline")
def test_the_author_mode_opens_no_external_connection(fingerprint_file: Path) -> None:
    pipeline = build_pipeline(config(fingerprint_file, SourceMode.LLM_DRAFT))
    result = pipeline.run(DRAFT)
    assert result.output_text
    assert pipeline.adaptation is not None
    assert pipeline.adaptation.assess(PLAIN, context=UnitStats()).score > 0.0
