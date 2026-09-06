"""v1.3.18: la repetició de connectors es mesura en una finestra que passa de paràgraf.

La v1.3.17 ja feia que, dins d'un paràgraf, una arquitectura sense repetició
introduïda guanyés una d'igual de segura i d'igual d'estructural que sí que en
tenia. Quedava fora d'abast, però, la repetició que travessa la frontera entre
dos paràgrafs consecutius: el final d'un i el començament del següent es
decidien sense veure's, perquè la unitat de mesura era el paràgraf.

Aquí es comproven les propietats de la mesura nova —una finestra curta i
determinista de :data:`WINDOW_SENTENCES` frases a cada costat— i les de la
selecció que en depèn. Cap test no exigeix una redacció literal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parafrasi_cat.analyzer import RuleBasedAnalyzer
from parafrasi_cat.candidates import Candidate
from parafrasi_cat.core import SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.core.transformation import CHAINED_RULES_KEY
from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.config import PipelineConfig
from parafrasi_cat.pipeline.modes import RewriteMode, apply_mode
from parafrasi_cat.pipeline.paragraph_search import BeamSettings, ParagraphBeam
from parafrasi_cat.pipeline.pipeline import Pipeline
from parafrasi_cat.pipeline.result import EvaluatedCandidate, SentenceResult
from parafrasi_cat.scoring.scorer import (
    CONNECTOR_COMPONENT,
    INVALID_TOTAL,
    CompositeScorer,
    ScoreBreakdown,
    ScoringContext,
)
from parafrasi_cat.scoring.weights import ScoringWeights
from parafrasi_cat.style.connector_repetition import (
    WINDOW_SENTENCES,
    ConnectorRepetition,
    DocumentWindow,
    distance_weight,
)
from parafrasi_cat.validation.result import ValidationDimension, ValidationResult

#: Text real de l'orfil: dos paràgrafs, amb el contrast «però … Però» a la frontera.
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

FORMS = ("atès que", "ja que", "tanmateix", "no obstant això", "així i tot", "per tant")

CAUSALS = frozenset({"atès que", "ja que"})
CONTRAST = frozenset({"tanmateix", "no obstant això", "així i tot", "amb tot", "malgrat tot"})


# --- eines --------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def repetition(catalan_analyzer: RuleBasedAnalyzer) -> ConnectorRepetition:
    return ConnectorRepetition(catalan_analyzer, FORMS)


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
    return _pipeline(project_root)


@pytest.fixture(scope="module")
def draft(project_root: Path) -> Pipeline:
    return _pipeline(project_root, pressure=0.9)


@pytest.fixture(scope="module")
def orfil(own: Pipeline) -> object:
    return own.run(ORFIL)


def _forms(pipeline: Pipeline, text: str, wanted: frozenset[str]) -> list[str]:
    evaluator = pipeline.scorer.connectors
    assert evaluator is not None
    return [form for form in evaluator.profile(text) if form in wanted]


def _connector(source: str, before: str, after: str, total: float) -> EvaluatedCandidate:
    start = source.index(before)
    transformation = Transformation(
        rule_id=f"prova.connector.{after.replace(' ', '_')}",
        text_before=before,
        text_after=after,
        changed_span=Span(start, start + len(before)),
        transformation_type=TransformationType.CONNECTOR,
        confidence=0.8,
        semantic_risk=SemanticRisk.LOW,
        explanation="prova",
        metadata={"category": "connector"},
    )
    return EvaluatedCandidate(
        Candidate.from_transformations(0, source, [transformation]),
        ValidationResult.passed(),
        ScoreBreakdown(total=total, components={}, explanation="prova"),
    )


def _split(source: str, before: str, after: str, total: float) -> EvaluatedCandidate:
    """Una divisió que tria el connector dins de la seva pròpia sortida."""
    start = source.index(before)
    transformation = Transformation(
        rule_id="prova.divisio.coordinada",
        text_before=before,
        text_after=after,
        changed_span=Span(start, start + len(before)),
        transformation_type=TransformationType.SENTENCE_SPLIT,
        confidence=0.65,
        semantic_risk=SemanticRisk.LOW,
        explanation="prova",
        metadata={"category": "divisio"},
    )
    return EvaluatedCandidate(
        Candidate.from_transformations(0, source, [transformation]),
        ValidationResult.passed(),
        ScoreBreakdown(total=total, components={}, explanation="prova"),
    )


def _identity(source: str) -> EvaluatedCandidate:
    return EvaluatedCandidate(
        Candidate(0, source, source, ()),
        ValidationResult.passed(),
        ScoreBreakdown(total=0.0, components={}, explanation="original"),
    )


def _beam(connectors: ConnectorRepetition | None = None) -> ParagraphBeam:
    return ParagraphBeam(
        settings=BeamSettings(beam_width=6, candidates_per_sentence=1),
        generator=None,  # type: ignore[arg-type] -- local_options no genera res
        scorer=None,  # type: ignore[arg-type] -- local_options no consulta el scorer
        validators=(),
        paragraph_rules=(),
        context_factory=None,  # type: ignore[arg-type] -- local_options no crea context
        rejection_reason=None,  # type: ignore[arg-type] -- local_options no rebutja res
        connectors=connectors,
    )


def _sentence_result(source: str, *candidates: EvaluatedCandidate) -> SentenceResult:
    return SentenceResult(
        index=0,
        source_text=source,
        span=Span(0, len(source)),
        output_text=candidates[0].candidate.text,
        candidates=candidates,
        rejected_proposals=(),
        protected_spans=(),
    )


# --- 1. dues arquitectures igual de segures i d'estructurals ----------------------------------


def test_the_sibling_of_the_best_reaches_the_paragraph(
    repetition: ConnectorRepetition,
) -> None:
    """Propietat 1: la mateixa arquitectura amb un altre connector arriba al paràgraf.

    Les places de ``candidates_per_sentence`` reparteixen arquitectures. Si el
    germà de connector del millor candidat n'hagués de gastar una, una frase amb
    prou alternatives estructurals el deixaria fora i la repetició guanyaria per
    absència de rival, no per mèrit.
    """
    source = "Plou molt aquesta setmana, però hem de sortir igualment."
    best = _split(source, ", però", ". Tanmateix,", 0.50)
    sibling = _split(source, ", però", ". Però", 0.50)
    options = _beam(repetition).local_options(
        _sentence_result(source, _identity(source), best, sibling)
    )

    reasons = [option.reason for option in options]
    assert reasons.count("variant segura de connector") == 1, reasons
    texts = {option.candidate.text for option in options if not option.candidate.is_identity}
    assert texts == {best.candidate.text, sibling.candidate.text}
    # És el mateix salt estructural: la tria entre les dues no pot ser estructural.
    assert best.candidate.signature == sibling.candidate.signature
    assert best.candidate.structural_degree() == sibling.candidate.structural_degree()


def test_only_one_sibling_per_sentence(repetition: ConnectorRepetition) -> None:
    """La reserva és una plaça, no una porta oberta: no creix amb els sinònims."""
    source = "Plou molt aquesta setmana, però hem de sortir igualment."
    options = _beam(repetition).local_options(
        _sentence_result(
            source,
            _identity(source),
            _split(source, ", però", ". Tanmateix,", 0.50),
            _split(source, ", però", ". No obstant això,", 0.49),
            _split(source, ", però", ". Així i tot,", 0.48),
        )
    )
    assert [o.reason for o in options].count("variant segura de connector") == 1


def test_an_equivalent_rewrite_without_a_new_connector_is_not_reserved(
    repetition: ConnectorRepetition,
) -> None:
    """No es reserva res per a una variant que no canvia cap connector."""
    source = "Plou molt aquesta setmana, però hem de sortir igualment."
    options = _beam(repetition).local_options(
        _sentence_result(
            source,
            _identity(source),
            _split(source, ", però", ". Tanmateix,", 0.50),
            _split(source, ", però", ". Tanmateix, encara", 0.49),
        )
    )
    assert "variant segura de connector" not in [o.reason for o in options]


# --- 2 i 3. original contra introduïda --------------------------------------------------------


def test_an_inherited_repetition_is_not_charged(repetition: ConnectorRepetition) -> None:
    """Propietat 2: la repetició que ja hi era es pot conservar sense pagar res."""
    inherited = "Ho sabem atès que plou. Marxem atès que fa vent."
    assert repetition.assess(inherited, inherited).penalty == 0.0
    # I substituir-la per una repetició d'una altra forma sí que costa.
    swapped = "Ho sabem ja que plou. Marxem ja que fa vent."
    assert repetition.assess(swapped, inherited).penalty > 0.0


def test_an_introduced_repetition_can_lose_the_candidate() -> None:
    """Propietat 3: amb la resta igual, la repetició nova resta i decideix."""
    source = "Ho sabem perquè plou. Marxem ja que fa vent."
    repeated = "Ho sabem atès que plou. Marxem atès que fa vent."
    varied = "Ho sabem atès que plou. Marxem ja que fa vent."
    scorer = CompositeScorer(ScoringWeights())
    evaluator = scorer.connectors
    assert evaluator is None  # sense inventari no hi ha desempat possible

    from parafrasi_cat.analyzer import RuleBasedAnalyzer as _Analyzer

    scorer = CompositeScorer(ScoringWeights(), connectors=ConnectorRepetition(_Analyzer(), FORMS))
    ctx = ScoringContext(ValidationResult.passed(), source)
    worse = scorer.score(Candidate(0, source, repeated, ()), ctx)
    better = scorer.score(Candidate(0, source, varied, ()), ctx)
    assert CONNECTOR_COMPONENT in worse.components
    assert CONNECTOR_COMPONENT not in better.components
    assert better.total > worse.total


# --- 4 i 5. les quatre escales ----------------------------------------------------------------


def test_the_four_scales_use_the_same_distance_law(repetition: ConnectorRepetition) -> None:
    """Propietats 4 i 5: mateixa frase, frases consecutives, paràgraf i frontera."""
    neutral = "Ho sabem. Marxem. Tornem."
    same_sentence = repetition.assess("Ho sabem atès que plou i atès que fa vent.", neutral)
    consecutive = repetition.assess("Ho sabem atès que plou. Marxem atès que fa vent.", neutral)
    inside = repetition.assess("Ho sabem atès que plou. Marxem. Tornem atès que fa vent.", neutral)
    # La frontera entre dos paràgrafs: el context anterior ja està decidit.
    window = DocumentWindow(before=("Marxem atès que fa vent.",))
    boundary = repetition.assess("Ho sabem atès que plou.", "Ho sabem perquè plou.", window)

    assert same_sentence.penalty == pytest.approx(distance_weight(0), abs=1e-4)
    assert consecutive.penalty == pytest.approx(distance_weight(1), abs=1e-4)
    assert inside.penalty == pytest.approx(distance_weight(2), abs=1e-4)
    assert boundary.penalty == pytest.approx(distance_weight(1), abs=1e-4)
    # Totes quatre es mesuren, i cap no depèn d'un llindar: només de la distància.
    assert same_sentence.penalty > consecutive.penalty > inside.penalty > 0.0


def test_the_window_is_short_and_bounded(repetition: ConnectorRepetition) -> None:
    """No hi ha cap penalització global il·limitada: fora de la finestra no es mesura res."""
    far = tuple(f"Frase de farciment número {n}." for n in range(WINDOW_SENTENCES + 3))
    near = DocumentWindow.around(before=("Marxem atès que fa vent.", *far))
    assert near.before == far[-WINDOW_SENTENCES:]
    assert (
        repetition.assess("Ho sabem atès que plou.", "Ho sabem perquè plou.", near).penalty == 0.0
    )

    close = DocumentWindow.around(before=("Marxem atès que fa vent.",))
    assert (
        repetition.assess("Ho sabem atès que plou.", "Ho sabem perquè plou.", close).penalty > 0.0
    )


def test_the_boundary_compares_candidate_and_source_on_the_same_window(
    repetition: ConnectorRepetition,
) -> None:
    """Conservar el connector de l'autor no pot costar mai més que canviar-lo."""
    window = DocumentWindow(before=("Marxem atès que fa vent.",))
    source = "Ho sabem atès que plou."
    assert repetition.assess(source, source, window).penalty == 0.0
    assert repetition.assess("Ho sabem ja que plou.", source, window).penalty == 0.0


def test_the_document_shows_no_introduced_repetition(own: Pipeline, orfil: object) -> None:
    """Propietat 5 de punta a punta: ni dins d'un paràgraf ni a la frontera."""
    evaluator = own.scorer.connectors
    assert evaluator is not None
    whole = evaluator.assess(orfil.output_text, ORFIL)  # type: ignore[attr-defined]
    assert whole.penalty == 0.0, whole.describe()

    paragraphs = orfil.paragraphs  # type: ignore[attr-defined]
    assert len(paragraphs) == 2
    last = _forms(own, paragraphs[0].output_text, CONTRAST)
    first = _forms(own, paragraphs[1].output_text, CONTRAST)
    assert last and first
    assert last[-1] != first[0], (last, first)


def test_the_boundary_alternative_wins_on_merit(own: Pipeline, orfil: object) -> None:
    """Propietat 1 a la frontera: la repetitiva existia, s'ha considerat i ha perdut.

    Sense aquesta comprovació, un resultat sense repeticions podria voler dir
    només que el motor no havia arribat a generar la variant repetitiva.
    """
    paragraph = orfil.paragraphs[1]  # type: ignore[attr-defined]
    assert paragraph.search is not None
    previous = _forms(own, orfil.paragraphs[0].output_text, CONTRAST)  # type: ignore[attr-defined]
    assert previous

    profiles = {
        tuple(_forms(own, a.evaluated.candidate.text, CONTRAST))
        for a in paragraph.search.alternatives
    }
    repetitive = {p for p in profiles if p and p[0] == previous[-1]}
    assert repetitive, profiles
    winner = tuple(_forms(own, paragraph.output_text, CONTRAST))
    assert winner not in repetitive


def test_the_paragraph_scale_is_covered_too(own: Pipeline, orfil: object) -> None:
    """Propietat 4 de punta a punta: dues causals del mateix paràgraf no s'igualen."""
    causals = _forms(own, orfil.paragraphs[0].output_text, CAUSALS)  # type: ignore[attr-defined]
    assert len(causals) >= 2, causals
    assert len(set(causals)) > 1, causals


def test_the_window_carries_the_text_already_decided(own: Pipeline, orfil: object) -> None:
    """El costat esquerre de la finestra és la sortida, no l'original.

    És la diferència que fa que la frontera es pugui veure. El connector de
    contrast amb què acaba el primer paràgraf **no hi era**: l'hi ha posat el
    motor. Si la finestra hagués mirat l'original, el segon paràgraf no hauria
    tingut cap motiu per evitar-lo, perquè a l'original no hi és.
    """
    first = orfil.paragraphs[0]  # type: ignore[attr-defined]
    introduced = _forms(own, first.output_text, CONTRAST)
    inherited = _forms(own, first.source_text, CONTRAST)
    assert introduced and introduced[-1] not in inherited
    # I el segon paràgraf no el repeteix.
    assert introduced[-1] not in _forms(own, orfil.paragraphs[1].output_text, CONTRAST)  # type: ignore[attr-defined]


# --- 6 i 7. varietat sense quota --------------------------------------------------------------


def test_different_equivalent_connectors_cost_nothing(repetition: ConnectorRepetition) -> None:
    """Propietat 6: canviar de forma no es paga; només repetir-la."""
    source = "Ho sabem perquè plou. Marxem perquè fa vent."
    varied = "Ho sabem atès que plou. Marxem ja que fa vent."
    assert repetition.assess(varied, source).penalty == 0.0
    window = DocumentWindow(before=("Tornem per tant.",), after=("Hi tornarem ja que convé.",))
    assert (
        repetition.assess("Ho sabem atès que plou.", "Ho sabem perquè plou.", window).penalty == 0.0
    )


def test_there_is_no_forced_rotation(own: Pipeline, repetition: ConnectorRepetition) -> None:
    """Propietat 7: no hi ha cap regla de «no repetir mai», ni cap quota d'alternança.

    La mesura no té llindars: repetir sempre costa alguna cosa dins de la
    finestra i sempre menys com més lluny, de manera que mai no hi ha un punt on
    la repetició passi a ser prohibida. I l'arquitectura que canvia tots els
    connectors no guanya pel fet d'haver-los canviat tots.
    """
    inherited = "Ho sabem atès que plou. Marxem atès que fa vent. Tornem atès que ja és tard."
    assert repetition.assess(inherited, inherited).penalty == 0.0

    near = repetition.assess(
        "Ho sabem atès que plou. Marxem atès que fa vent.", "Ho sabem. Marxem."
    )
    far = repetition.assess(
        "Ho sabem atès que plou. Marxem. Tornem atès que fa vent.", "Ho sabem. Marxem. Tornem."
    )
    assert near.penalty > far.penalty > 0.0

    text = (
        "Ho sabem atès que la font ho diu. Ho repetim atès que la font ho diu. "
        "Ho mantenim atès que la font ho diu."
    )
    result = own.run(text)
    paragraph = result.paragraphs[0]
    assert paragraph.search is not None
    profiles = [
        tuple(f for f in _forms(own, a.evaluated.candidate.text, CAUSALS))
        for a in paragraph.search.alternatives
    ]
    rotated = [p for p in profiles if p and all(f == "ja que" for f in p)]
    assert rotated, profiles  # existia i s'ha considerat
    winner = tuple(f for f in _forms(own, paragraph.output_text, CAUSALS))
    assert winner not in rotated
    # I la repetició que l'autor ja tenia continua sent gratuïta.
    assert repetition.assess(text, text).penalty == 0.0


def test_the_engine_does_not_rewrite_a_text_it_cannot_improve(own: Pipeline) -> None:
    """La varietat és un criteri de qualitat, no una quota: sense alternativa, res."""
    text = "Ho sabem atès que plou."
    result = own.run(text)
    evaluator = own.scorer.connectors
    assert evaluator is not None
    assert evaluator.assess(result.output_text, text).penalty == 0.0


# --- 8 i 9. la jerarquia es manté -------------------------------------------------------------


def test_a_structural_architecture_still_wins(own: Pipeline, orfil: object) -> None:
    """Propietat 8: la distància estructural continua guanyant una versió superficial."""
    result = orfil
    assert result.output_text != ORFIL  # type: ignore[attr-defined]
    changed = [s for s in result.sentences if s.changed]  # type: ignore[attr-defined]
    assert len(changed) >= 3, [s.output_text for s in changed]
    assert any(s.selected.candidate.is_structural for s in changed)
    paragraph = result.paragraphs[0]  # type: ignore[attr-defined]
    assert paragraph.search is not None
    original = next(a for a in paragraph.search.alternatives if a.origin == "original")
    assert paragraph.search.winner.global_total > original.global_total
    # La reordenació bona del roc es conserva: el subjecte va davant de la concessiva.
    roc = next(s for s in result.sentences if "roc" in s.source_text)  # type: ignore[attr-defined]
    assert roc.output_text.index("El roc") < roc.output_text.index("encara que")


def test_no_style_rescues_an_invalid_candidate() -> None:
    """Propietat 9: la varietat no és una moneda que pugui comprar la seguretat."""
    source = "Ho sabem atès que plou. Marxem atès que fa vent."
    varied = "Ho sabem atès que plou. Marxem ja que fa vent."
    from parafrasi_cat.analyzer import RuleBasedAnalyzer as _Analyzer

    scorer = CompositeScorer(ScoringWeights(), connectors=ConnectorRepetition(_Analyzer(), FORMS))
    broken = ValidationResult.error(
        "prova.validador",
        ValidationDimension.FACTUAL,
        "s'ha perdut una data",
    )
    candidate = Candidate(0, source, varied, ())
    score = scorer.score(candidate, ScoringContext(broken, source))
    assert not score.valid
    assert score.total == INVALID_TOTAL
    # La varietat perfecta del candidat no li serveix de res: ni tan sols hi
    # arriba a comptar, perquè la seguretat es resol abans que cap puntuació.
    assert score.total < scorer.score(candidate, ScoringContext(None, source)).total


# --- 10, 11 i 12. res del text real no es trenca ----------------------------------------------


def test_the_conditional_scope_is_protected(orfil: object) -> None:
    """Propietat 10: «només … si» continua sencer i al seu lloc."""
    output = orfil.output_text  # type: ignore[attr-defined]
    assert "només té sentit si arfil designa" in output


def test_the_final_sentence_is_intact(orfil: object) -> None:
    """Propietat 11: el final polític continua correcte."""
    output = orfil.output_text  # type: ignore[attr-defined]
    assert "categoria política: un home pròxim al rei, útil al poder, però ja no sobirà." in output


@pytest.mark.parametrize("mode", ["own", "draft"])
def test_the_marked_causal_is_never_generated(mode: str, own: Pipeline, draft: Pipeline) -> None:
    """Propietat 12: «puix que» es reconeix però no és un objectiu de cap regla."""
    pipeline = own if mode == "own" else draft
    result = pipeline.run(ORFIL)
    assert "puix que" not in result.output_text.lower()
    for sentence in result.sentences:
        for evaluated in sentence.candidates:
            assert "puix que" not in evaluated.candidate.text.lower()


# --- 13 i 14. determinisme i composició profunda ----------------------------------------------


def test_the_selection_is_deterministic(own: Pipeline) -> None:
    """Propietat 13: la mateixa entrada i la mateixa configuració donen el mateix text."""
    runs = [own.run(ORFIL).output_text for _ in range(3)]
    assert len(set(runs)) == 1


def test_deep_composition_still_works(draft: Pipeline) -> None:
    """Propietat 14: la composició d'arquitectures de la v1.3.16 continua viva.

    Les transformacions encadenades es fusionen en una de sola (que conserva la
    identitat de la primera), de manera que la composició es llegeix a la
    signatura conscient de l'arquitectura i a les regles encadenades.
    """
    result = draft.run(ORFIL)
    composed = [
        evaluated.candidate
        for sentence in result.sentences
        for evaluated in sentence.candidates
        if evaluated.accepted and evaluated.candidate.signature.startswith("MULTI_TRANSFORM(")
    ]
    assert composed, [s.selected.candidate.signature for s in result.sentences]
    assert any("::ARCH(" in candidate.signature for candidate in composed)
    assert any(
        len(transformation.metadata.get(CHAINED_RULES_KEY, ())) > 1
        for candidate in composed
        for transformation in candidate.transformations
    )
    assert any(
        s.selected.candidate.signature.startswith("MULTI_TRANSFORM(") for s in result.sentences
    )
