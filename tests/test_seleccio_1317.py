"""v1.3.17: la selecció final no pot guanyar-se acumulant premis del mateix fet.

Dos defectes reals, tots dos reproduïts abans de tocar res:

1. El desempat de repetició de connectors estava condicionat a
   ``rewrite_pressure > 0``, és a dir, només s'aplicava als esborranys d'LLM.
   Amb text propi, dues arquitectures empataven **exactament** i guanyava la
   repetitiva per ordre d'arribada.
2. El grau estructural es cobrava dues vegades a la mateixa frase: al bonus
   d'estructura i, un altre cop, dins de la pressió de reescriptura. Una sola
   reordenació arribava a valer sis vegades el desempat estilístic més gran.

Cap test no exigeix una redacció literal: totes són propietats.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parafrasi_cat.candidates import Candidate
from parafrasi_cat.core import SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.core.transformation import CHAINED_RULES_KEY
from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.config import PipelineConfig
from parafrasi_cat.pipeline.modes import DEEP, RewriteMode, apply_mode
from parafrasi_cat.pipeline.pipeline import Pipeline
from parafrasi_cat.scoring.scorer import (
    CONNECTOR_COMPONENT,
    INVALID_TOTAL,
    STRUCTURAL_PRESSURE_SHARE,
    SURFACE_PRESSURE_SHARE,
    CompositeScorer,
    ScoringContext,
)
from parafrasi_cat.scoring.weights import ScoringWeights
from parafrasi_cat.style.connector_repetition import ConnectorRepetition
from parafrasi_cat.validation.result import ValidationDimension, ValidationResult

SENTENCE = (
    "El cavaller és reconeixible perquè el cavall, l’armament i la funció militar el fan "
    "transparent."
)

#: Paràgraf real: dues causals intercanviables a frases diferents, «només … si»,
#: dos punts finals i una reordenació estructural possible a la frase del roc.
ORFIL = (
    "Hi ha peces dels escacs que semblen haver conservat el seu nom perquè la seva funció era "
    "clara. El rei no necessita gaire justificació: és el centre del tauler i el centre del "
    "regne. La reina, quan apareix o quan es consolida, tampoc no necessita una explicació "
    "excessiva: ocupa el lloc immediat del poder domèstic, dinàstic i polític al costat del "
    "rei. El cavaller és reconeixible perquè el cavall, l’armament i la funció militar el fan "
    "transparent. Encara que tingui un nom menys evident, el roc pot ser assimilat a la funció "
    "de veguer, oficial o executor de la força reial, però hi ha una peça que no encaixa tan "
    "fàcilment: l’orfil.\n\n"
    "La lectura tradicional ha volgut fer derivar aquesta peça de l’alfil oriental i, a partir "
    "d’aquí, explicar-la per l’elefant, i aquesta explicació pot tenir algun valor remot per a "
    "una capa oriental del nom. Però no resol el problema occidental. No explica per què, en la "
    "tradició moralitzada de Cessolis, l’orfil no és tractat com un animal, sinó com un jutge. "
    "Tampoc explica per què en català antic pot aparèixer una frase com “don Johan, que volia "
    "esser Rey e ara és arfil”, on el contrast no pot ser entre rei i elefant, sinó entre "
    "sobirania i una funció subordinada. La frase només té sentit si arfil designa una "
    "categoria política: un home pròxim al rei, útil al poder, però ja no sobirà."
)

CAUSALS = frozenset({"atès que", "ja que"})


def _make(
    text: str,
    before: str,
    after: str,
    category: str,
    *,
    kind: TransformationType = TransformationType.SYNTACTIC,
    confidence: float = 0.7,
    family: str = "",
) -> Transformation:
    start = text.index(before)
    metadata = {"category": category, **({"family": family} if family else {})}
    return Transformation(
        rule_id=f"prova.{category}",
        text_before=before,
        text_after=after,
        changed_span=Span(start, start + len(before)),
        transformation_type=kind,
        confidence=confidence,
        semantic_risk=SemanticRisk.LOW,
        explanation="prova",
        metadata=metadata,
    )


def _structural(text: str = SENTENCE) -> Candidate:
    """Una reordenació que abasta tota la frase: grau estructural alt."""
    body = text[:-1]
    return Candidate.from_transformations(
        0, text, [_make(text, body, "Es reconeix el cavaller", "ordre", family="REORDER")]
    )


def _surface(text: str = SENTENCE) -> Candidate:
    """Un canvi verbal del mateix abast: grau estructural 0, mateixa distància."""
    body = text[:-1]
    return Candidate.from_transformations(
        0,
        text,
        [
            _make(
                text,
                body,
                "Es reconeix el cavaller",
                "verbal",
                kind=TransformationType.MORPHOLOGICAL,
                family="VERBAL",
            )
        ],
    )


def _deep_weights(pressure: float = 0.9) -> ScoringWeights:
    return ScoringWeights(structure=DEEP.structure_gain, rewrite_pressure=pressure)


# --- 1. el grau estructural es paga una sola vegada -------------------------------------------


def test_the_structural_degree_is_paid_once() -> None:
    """Dos candidats amb la mateixa distància i diferent grau: només un component ha de variar."""
    scorer = CompositeScorer(_deep_weights())
    ctx = ScoringContext(ValidationResult.passed(), SENTENCE)
    structural = scorer.score(_structural(), ctx)
    surface = scorer.score(_surface(), ctx)

    assert structural.dimension("grau_estructural") > 0
    assert surface.dimension("grau_estructural") == 0
    assert structural.dimension("grau_de_canvi") == pytest.approx(
        surface.dimension("grau_de_canvi")
    )
    # La pressió de reescriptura paga la distància superficial, no el grau: amb la
    # mateixa distància val exactament el mateix per als dos.
    assert structural.components["pressio_reescriptura"] == pytest.approx(
        surface.components["pressio_reescriptura"]
    )
    # I la preferència per la reredacció viu en un únic component.
    assert "estructura" in structural.components
    assert "estructura" not in surface.components
    assert structural.total > surface.total


def test_the_rewrite_pressure_only_pays_the_surface_distance() -> None:
    weights = _deep_weights()
    scorer = CompositeScorer(weights)
    ctx = ScoringContext(ValidationResult.passed(), SENTENCE)
    score = scorer.score(_structural(), ctx)
    change = score.dimension("grau_de_canvi")
    degree = score.dimension("grau_estructural")
    assert change is not None and degree is not None

    assert score.components["pressio_reescriptura"] == pytest.approx(
        weights.rewrite_pressure * SURFACE_PRESSURE_SHARE * change, abs=1e-4
    )
    expected = (weights.structure + STRUCTURAL_PRESSURE_SHARE * weights.rewrite_pressure) * degree
    assert score.components["estructura"] == pytest.approx(expected, abs=1e-4)


def test_the_total_structural_preference_is_preserved() -> None:
    """La 1.3.16 no perd capacitat: el pes total de la reredacció és el mateix."""
    weights = _deep_weights()
    scorer = CompositeScorer(weights)
    ctx = ScoringContext(ValidationResult.passed(), SENTENCE)
    score = scorer.score(_structural(), ctx)
    degree = score.dimension("grau_estructural")
    change = score.dimension("grau_de_canvi")
    assert degree is not None and change is not None

    # Fórmula antiga: estructura + pressió, amb el grau dins de totes dues.
    before = weights.structure * degree + weights.rewrite_pressure * min(
        1.0, SURFACE_PRESSURE_SHARE * change + STRUCTURAL_PRESSURE_SHARE * degree
    )
    now = score.components["estructura"] + score.components["pressio_reescriptura"]
    assert now == pytest.approx(before, abs=1e-4)


def test_a_structural_reward_never_survives_a_damaged_rhythm() -> None:
    """Abans, la part estructural de la pressió escapava de la penalització de ritme."""
    weights = _deep_weights()
    degree, change, rhythm = 0.65, 0.2, 0.5

    before = weights.structure * degree * rhythm + weights.rewrite_pressure * min(
        1.0, SURFACE_PRESSURE_SHARE * change + STRUCTURAL_PRESSURE_SHARE * degree
    )
    now = (
        weights.structure + STRUCTURAL_PRESSURE_SHARE * weights.rewrite_pressure
    ) * degree * rhythm + weights.rewrite_pressure * SURFACE_PRESSURE_SHARE * change
    assert now < before, "una fusió que trenca el ritme ha de perdre tot el premi, no la meitat"

    # Sense penalització de ritme, el premi total no canvia gens.
    intact_before = weights.structure * degree + weights.rewrite_pressure * min(
        1.0, SURFACE_PRESSURE_SHARE * change + STRUCTURAL_PRESSURE_SHARE * degree
    )
    intact_now = (
        weights.structure + STRUCTURAL_PRESSURE_SHARE * weights.rewrite_pressure
    ) * degree + weights.rewrite_pressure * SURFACE_PRESSURE_SHARE * change
    assert intact_now == pytest.approx(intact_before, abs=1e-9)


# --- 2. el desempat estilístic existeix sempre ------------------------------------------------


def test_the_connector_tie_break_does_not_depend_on_the_source_mode(
    project_root: Path,
) -> None:
    """La causa real del cas reportat: amb text propi el desempat no s'aplicava."""
    pipeline = _pipeline(project_root, pressure=0.0)
    evaluator = pipeline.scorer.connectors
    assert isinstance(evaluator, ConnectorRepetition)
    source = "Ho sabem ja que la font ho diu. Després ho repetim atès que convé."
    repeated = "Ho sabem atès que la font ho diu. Després ho repetim atès que convé."
    candidate = Candidate(0, source, repeated, ())

    assert pipeline.scorer.weights.rewrite_pressure == 0.0
    score = pipeline.scorer.score(candidate, ScoringContext(None, source, None))
    assert score.components[CONNECTOR_COMPONENT] < 0
    assert score.dimension("varietat_connectors") < 1.0


def test_no_style_criterion_rescues_an_invalid_candidate() -> None:
    """La seguretat mana: cap bonus estilístic no pot rescatar un candidat invalidat."""
    scorer = CompositeScorer(_deep_weights())
    broken = ValidationResult.error(
        "prova.factual", "s'ha perdut una data", ValidationDimension.FACTUAL
    )
    score = scorer.score(_structural(), ScoringContext(broken, SENTENCE))
    assert not score.valid
    assert score.total == INVALID_TOTAL
    healthy = scorer.score(_structural(), ScoringContext(ValidationResult.passed(), SENTENCE))
    assert score.total < healthy.total


def test_structural_diversity_still_beats_a_surface_retouch() -> None:
    scorer = CompositeScorer(ScoringWeights(structure=DEEP.structure_gain))
    ctx = ScoringContext(ValidationResult.passed(), SENTENCE)
    assert scorer.score(_structural(), ctx).total > scorer.score(_surface(), ctx).total
    # En mode conservador, sense pes estructural, l'avantatge desapareix.
    plain = CompositeScorer(ScoringWeights())
    assert plain.score(_structural(), ctx).total == pytest.approx(
        plain.score(_surface(), ctx).total
    )


# --- 3. comportament complet ------------------------------------------------------------------


def _pipeline(project_root: Path, *, pressure: float = 0.0) -> Pipeline:
    config = apply_mode(
        PipelineConfig(
            home=project_root,
            rule_set="parafrasi",
            languagetool=False,
            scoring=ScoringWeights(rewrite_pressure=pressure),
        ),
        RewriteMode.DEEP,
        5,
    )
    return build_pipeline(config)


@pytest.fixture(scope="module")
def own(project_root: Path) -> Pipeline:
    """Text propi: sense pressió de reescriptura, que és on faltava el desempat."""
    return _pipeline(project_root)


@pytest.fixture(scope="module")
def draft(project_root: Path) -> Pipeline:
    return _pipeline(project_root, pressure=0.9)


def _causals(pipeline: Pipeline, text: str) -> list[str]:
    evaluator = pipeline.scorer.connectors
    assert evaluator is not None
    return [form for form in evaluator.profile(text) if form in CAUSALS]


@pytest.mark.parametrize("mode", ["own", "draft"])
def test_an_introduced_repetition_loses_to_an_equally_structural_alternative(
    mode: str, own: Pipeline, draft: Pipeline
) -> None:
    """A i B tenen la mateixa reordenació; B, que no repeteix el connector, ha de guanyar."""
    pipeline = own if mode == "own" else draft
    result = pipeline.run(ORFIL)
    evaluator = pipeline.scorer.connectors
    assert evaluator is not None

    for paragraph in result.paragraphs:
        assessment = evaluator.assess(paragraph.output_text, paragraph.source_text)
        assert assessment.penalty == 0.0, assessment.describe()
    causals = _causals(pipeline, result.output_text)
    assert len(causals) >= 2, causals
    assert len(set(causals)) > 1, causals

    # L'arquitectura repetitiva existia i s'ha considerat: no ha guanyat per casualitat.
    search = result.paragraphs[0].search
    assert search is not None
    profiles = {
        tuple(f for f in evaluator.profile(a.evaluated.candidate.text) if f in CAUSALS)
        for a in search.alternatives
    }
    repetitive = {p for p in profiles if len(p) >= 2 and len(set(p)) == 1}
    assert repetitive, profiles
    winner = tuple(
        f for f in evaluator.profile(search.winner.evaluated.candidate.text) if f in CAUSALS
    )
    assert winner not in repetitive


def test_a_real_structural_difference_still_wins(own: Pipeline) -> None:
    """L'altra meitat del principi: una arquitectura realment diferent conserva l'avantatge."""
    result = own.run(ORFIL)
    assert result.output_text != ORFIL
    changed = [s for s in result.sentences if s.changed]
    assert len(changed) >= 3, [s.output_text for s in result.sentences]
    assert any(s.selected.candidate.is_structural for s in changed)
    paragraph = result.paragraphs[0]
    assert paragraph.search is not None
    original = next(a for a in paragraph.search.alternatives if a.origin == "original")
    assert paragraph.search.winner.global_total > original.global_total


def test_deep_composition_still_works(draft: Pipeline) -> None:
    """La composició de la v1.3.16 continua viva: arquitectures de més d'una família.

    Les transformacions encadenades es fusionen en una de sola (conserva la
    identitat de la primera), de manera que la composició es llegeix a la
    signatura conscient de l'arquitectura i a les regles encadenades, no pas
    comptant famílies dins de ``transformations``.
    """
    result = draft.run(ORFIL)
    accepted = [e.candidate for s in result.sentences for e in s.candidates if e.accepted]
    composed = [c for c in accepted if c.n_transformations > 1 or _chained(c)]
    assert composed, "cap candidat compost"
    multi = [c for c in composed if c.signature.startswith("MULTI_TRANSFORM(")]
    assert multi, [c.signature for c in composed]
    assert any("+" in c.signature.split("(", 1)[1] for c in multi)
    assert any(_chained(c) for c in accepted), "cap regla reaplicada sobre un candidat"


def _chained(candidate: Candidate) -> bool:
    return any(t.metadata.get(CHAINED_RULES_KEY) for t in candidate.transformations)


def test_the_earlier_protections_are_intact(own: Pipeline) -> None:
    text = own.run(ORFIL).output_text
    assert "només té sentit si arfil designa" in text
    assert "categoria política: un home pròxim al rei" in text
    assert "categoria política. Un home" not in text
    assert "puix que" not in text
    for fact in ("Cessolis", "don Johan", "arfil"):
        assert fact in text


@pytest.mark.parametrize("mode", ["own", "draft"])
def test_the_selection_is_deterministic(mode: str, own: Pipeline, draft: Pipeline) -> None:
    pipeline = own if mode == "own" else draft
    first = pipeline.run(ORFIL)
    second = pipeline.run(ORFIL)
    assert first.output_text == second.output_text
    assert [s.output_text for s in first.sentences] == [s.output_text for s in second.sentences]
