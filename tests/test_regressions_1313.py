"""Regressions de la v1.3.13: triar entre connectors equivalents sense repetir per inèrcia.

Tres blocs:

1. La mesura (`style/connector_repetition.py`): inventari, distància i repetició
   introduïda contra repetició que l'original ja tenia.
2. El feix de paràgraf: perfils de connectors diferents sobreviuen a la poda, i
   la poda continua acotada per l'amplada del feix.
3. El comportament complet, sobre text real, amb les proteccions de les versions
   anteriors intactes.

Cap test no exigeix una sortida literal: totes són propietats.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from parafrasi_cat.analyzer import RuleBasedAnalyzer
from parafrasi_cat.candidates import Candidate
from parafrasi_cat.core import SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.config import PipelineConfig
from parafrasi_cat.pipeline.modes import RewriteMode, apply_mode
from parafrasi_cat.pipeline.paragraph_search import (
    CONNECTOR_PROFILE_TAIL,
    BeamSettings,
    BeamState,
    LocalOption,
    ParagraphBeam,
)
from parafrasi_cat.pipeline.pipeline import Pipeline
from parafrasi_cat.pipeline.result import EvaluatedCandidate, ParaphraseResult
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.rules import RuleSetConfig, build_rule_set, default_registry
from parafrasi_cat.scoring.scorer import CONNECTOR_COMPONENT, ScoreBreakdown, ScoringContext
from parafrasi_cat.scoring.weights import ScoringWeights
from parafrasi_cat.style.adaptation import AdaptationContext, UnitStats
from parafrasi_cat.style.connector_repetition import (
    ConnectorRepetition,
    connector_forms,
    distance_weight,
)
from parafrasi_cat.validation.result import ValidationResult

#: Paràgraf real: dues causals separades per dues frases, amb «només … si», dos
#: punts finals i una peça amb cometes tipogràfiques.
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

#: Dues causals equivalents a frases diferents: hi ha alternativa segura per a totes dues.
TWO_CAUSALS = (
    "Ho sabem ja que la font ho diu clarament. Després ho repetim atès que convé insistir-hi."
)
#: L'autor ja repeteix la mateixa causal: conservar-ho no és cap defecte.
REPEATED_BY_AUTHOR = (
    "Ho sabem atès que la font ho diu clarament. Després ho repetim atès que convé insistir-hi."
)


# --- 1. la mesura -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def inventory(paths: ProjectPaths) -> tuple[str, ...]:
    rule_set = build_rule_set(
        RuleSetConfig.load(paths.rules / "parafrasi.yaml"), default_registry(), paths
    )
    return connector_forms(rule_set.rules)


@pytest.fixture(scope="module")
def repetition(
    catalan_analyzer: RuleBasedAnalyzer, inventory: tuple[str, ...]
) -> ConnectorRepetition:
    return ConnectorRepetition(catalan_analyzer, inventory)


def test_the_inventory_comes_from_the_rules_that_can_swap_a_connector(
    inventory: tuple[str, ...],
) -> None:
    """Només entren les formes amb alternativa segura: no és cap llista escrita a mà."""
    forms = set(inventory)
    assert {"atès que", "ja que", "tanmateix", "no obstant això", "per tant"} <= forms
    # «puix que» hi és perquè es reconeix (encara que no es generi mai com a objectiu).
    assert "puix que" in forms
    # Cap marcador d'interacció col·loquial: no són formes que el motor pugui variar.
    assert "home" not in forms and "escolta" not in forms
    # «però» tampoc no hi és: cap classe d'equivalència no el declara, i per tant no
    # existeix cap alternativa segura que el motor pugui triar en el seu lloc.
    assert "però" not in forms
    assert len(forms) < 100


def test_multiword_connectors_are_seen(repetition: ConnectorRepetition) -> None:
    """La regressió de fons: «atès que» no es veia i, per tant, no es podia comparar."""
    assert repetition.profile("Ho sabem atès que plou.") == ("atès que",)
    assert repetition.profile("No obstant això, plou.") == ("no obstant això",)
    assert repetition.profile("Ho sabem ja que plou.") == ("ja que",)


def test_the_penalty_decreases_with_distance(repetition: ConnectorRepetition) -> None:
    assert distance_weight(0) == 1.0
    assert distance_weight(1) == 0.5
    assert distance_weight(2) == pytest.approx(1 / 3)
    assert distance_weight(3) == 0.25
    assert all(distance_weight(d) > distance_weight(d + 1) > 0 for d in range(6))

    neutral = "Res. Res. Res. Res."
    same = "Ho sabem atès que plou i atès que fa vent."
    next_one = "Ho sabem atès que plou. Ho diem atès que convé."
    far = "Ho sabem atès que plou. Res. Res. Ho diem atès que convé."
    penalties = [repetition.assess(text, neutral).penalty for text in (same, next_one, far)]
    assert penalties == sorted(penalties, reverse=True)
    assert penalties[-1] > 0.0


def test_introduced_repetition_weighs_more_than_inherited_repetition(
    repetition: ConnectorRepetition,
) -> None:
    """L'autor pot repetir-se; el motor no hi pot afegir una repetició nova."""
    inherited = repetition.assess(REPEATED_BY_AUTHOR, REPEATED_BY_AUTHOR)
    assert inherited.penalty == 0.0
    assert inherited.repeats and not inherited.introduced

    introduced = repetition.assess(REPEATED_BY_AUTHOR, TWO_CAUSALS)
    assert introduced.penalty > inherited.penalty
    assert introduced.forms == ("atès que",)
    assert all(r.introduced for r in introduced.introduced)
    # Una repetició formal nova sobre una repetició d'una altra forma continua sent nova.
    swapped = "Ho sabem perquè plou. Ho repetim perquè convé."
    assert repetition.assess(REPEATED_BY_AUTHOR, swapped).penalty > 0.0


def test_equivalent_but_different_connectors_are_not_penalised(
    repetition: ConnectorRepetition,
) -> None:
    assert repetition.assess(TWO_CAUSALS, REPEATED_BY_AUTHOR).penalty == 0.0
    assert repetition.assess("Tanmateix, plou. Per tant, no ho sabem.", TWO_CAUSALS).penalty == 0.0


def test_without_a_reference_nothing_is_penalised(repetition: ConnectorRepetition) -> None:
    """Sense original no es pot saber què és nou: davant del dubte, no es penalitza."""
    assert repetition.assess(REPEATED_BY_AUTHOR).penalty == 0.0
    assert repetition.assess(REPEATED_BY_AUTHOR, "").penalty == 0.0
    assert ConnectorRepetition(None, ()).assess(REPEATED_BY_AUTHOR, TWO_CAUSALS).penalty == 0.0


def test_the_neighbouring_unit_counts_as_one_sentence_away(
    repetition: ConnectorRepetition,
) -> None:
    context = AdaptationContext(before=UnitStats(connectors=("tanmateix",)))
    fresh = repetition.assess("Tanmateix, no plou.", "Per tant, no plou.", context)
    assert fresh.penalty == pytest.approx(0.5)
    # Si l'original ja coincidia amb el veí, la coincidència no és nova.
    assert repetition.assess("Tanmateix, no plou.", "Tanmateix, no plou.", context).penalty == 0.0


def test_the_assessment_is_traceable(repetition: ConnectorRepetition) -> None:
    assessment = repetition.assess(REPEATED_BY_AUTHOR, TWO_CAUSALS)
    data = assessment.to_dict()
    assert data["profile"] == list(repetition.profile(REPEATED_BY_AUTHOR))
    assert data["profile"].count("atès que") == 2
    assert data["penalty"] == pytest.approx(assessment.penalty)
    repeat = assessment.introduced[0]
    assert repeat.form == "atès que" and repeat.distance == 1
    assert repeat.to_dict()["weight"] == pytest.approx(0.5)
    assert "nova" in assessment.describe()


# --- 2. el feix -------------------------------------------------------------------------------


def _option(index: int, text: str, total: float, connectors: tuple[str, ...]) -> LocalOption:
    transformation = Transformation(
        rule_id="prova.connector",
        text_before="perquè",
        text_after=connectors[-1] if connectors else "perquè",
        changed_span=Span(0, 6),
        transformation_type=TransformationType.CONNECTOR,
        confidence=0.8,
        semantic_risk=SemanticRisk.LOW,
        explanation="prova",
        metadata={"category": "connector"},
    )
    candidate = Candidate(index, text, text, (transformation,))
    evaluated = EvaluatedCandidate(
        candidate, ValidationResult.passed(), ScoreBreakdown(total, {}, "prova")
    )
    return LocalOption(index, evaluated, "prova", connectors)


def _state(option: LocalOption, total: float, profile: tuple[str, ...]) -> BeamState:
    history = _option(0, "prefix", 0.0, profile[:-1])
    return BeamState(
        (history, option),
        Candidate(0, f"{profile}", f"text {profile} {total}", ()),
        total,
        ScoreBreakdown(0.0, {}, "prova"),
    )


def _beam(width: int = 2) -> ParagraphBeam:
    return ParagraphBeam(
        settings=BeamSettings(beam_width=width, candidates_per_sentence=3),
        generator=None,  # type: ignore[arg-type] -- _prune no genera candidats
        scorer=None,  # type: ignore[arg-type] -- _prune no puntua
        validators=(),
        paragraph_rules=(),
        context_factory=None,  # type: ignore[arg-type] -- _prune no crea context
        rejection_reason=None,  # type: ignore[arg-type] -- _prune no rebutja res
    )


def test_the_beam_keeps_one_state_per_recent_connector_profile() -> None:
    """Dues arquitectures amb les mateixes signatures poden diferir només en un connector."""
    last = _option(1, "final", 0.4, ("atès que",))
    states = [
        _state(last, 1.0, ("atès que", "atès que")),
        _state(last, 0.9, ("atès que", "atès que")),
        _state(last, 0.8, ("ja que", "atès que")),
    ]
    kept = _beam(width=2)._prune(states, (last,), [])

    profiles = [state.connector_key for state in kept]
    assert ("ja que", "atès que") in profiles, "el perfil alternatiu ha mort abans d'hora"
    assert profiles[0] == ("atès que", "atès que")
    assert any("connectors" in state.kept_for for state in kept)


def test_pruning_stays_bounded_by_the_beam_width() -> None:
    forms = ("atès que", "ja que", "però", "tanmateix", "per tant", "no obstant això")
    last = _option(1, "final", 0.4, ("atès que",))
    states = [_state(last, 1.0 - n / 10, (form, "atès que")) for n, form in enumerate(forms)]
    for width in (1, 2, 3, 4):
        kept = _beam(width=width)._prune(states, (last,), [])
        assert len(kept) == width
        assert len({id(state) for state in kept}) == width
    assert CONNECTOR_PROFILE_TAIL >= 1


def test_the_profile_key_is_short_and_ordered() -> None:
    last = _option(1, "final", 0.4, ("però",))
    state = _state(last, 1.0, ("atès que", "ja que", "però"))
    assert len(state.connector_key) <= CONNECTOR_PROFILE_TAIL
    assert state.connector_key == state.connector_profile[-CONNECTOR_PROFILE_TAIL:]


# --- 3. comportament complet ------------------------------------------------------------------


def _pipeline(project_root: Path, *, pressure: float = 0.9) -> Pipeline:
    """Canonada profunda de nivell 5 amb pressió de reescriptura, sense empremta.

    La pressió és la que activa la penalització de repetició (com amb un esborrany
    d'LLM); així el test no depèn de construir cap empremta.
    """
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
def deep(project_root: Path) -> Pipeline:
    return _pipeline(project_root)


@pytest.fixture(scope="module")
def orfil(deep: Pipeline) -> ParaphraseResult:
    return deep.run(ORFIL)


def test_the_engine_does_not_introduce_a_repeated_connector(deep: Pipeline) -> None:
    """La propietat central: entre alternatives igualment segures, guanya la no repetitiva."""
    result = deep.run(TWO_CAUSALS)
    evaluator = deep.scorer.connectors
    assert evaluator is not None
    profile = evaluator.profile(result.output_text)
    causals = [form for form in profile if form in {"atès que", "ja que"}]
    assert len(causals) == 2, profile
    assert causals[0] != causals[1], result.output_text
    assert evaluator.assess(result.output_text, TWO_CAUSALS).penalty == 0.0


def test_a_repetition_the_author_wrote_is_not_forced_to_change(deep: Pipeline) -> None:
    """La no-repetició és un criteri de selecció, no un validador.

    L'original repeteix «atès que». Conservar-ho no costa res; el que el motor no
    pot fer és canviar les dues aparicions per una altra forma i tornar a deixar
    el paràgraf repetitiu.
    """
    result = deep.run(REPEATED_BY_AUTHOR)
    evaluator = deep.scorer.connectors
    assert evaluator is not None
    assert evaluator.assess(result.output_text, REPEATED_BY_AUTHOR).penalty == 0.0
    # I si el motor la conserva tal com era, tampoc no rep cap penalització.
    original = evaluator.assess(REPEATED_BY_AUTHOR, REPEATED_BY_AUTHOR)
    assert original.penalty == 0.0


def test_recreating_the_repetition_loses_the_gain_it_claimed(deep: Pipeline) -> None:
    """Un segon canvi que recrea la repetició no cobra el premi de reescriptura."""
    result = deep.run(REPEATED_BY_AUTHOR)
    search = result.paragraphs[0].search
    assert search is not None
    repetitive = [a for a in search.alternatives if a.connectors.get("penalty", 0.0)]
    assert repetitive, "cap arquitectura repetitiva per comparar"
    for alternative in repetitive:
        components = alternative.evaluated.score.components
        assert components["guany_repeticio_connectors"] < 0
        assert alternative.global_total < search.winner.global_total
    assert not search.winner.connectors.get("penalty")


def test_no_safe_alternative_means_no_change(deep: Pipeline) -> None:
    text = "Hi havia dos cranis. La peça era de marbre."
    result = deep.run(text)
    evaluator = deep.scorer.connectors
    assert evaluator is not None
    assert evaluator.profile(text) == ()
    for sentence in result.sentences:
        if not sentence.changed:
            assert sentence.opportunities.selected_is_original


def test_own_text_gets_no_variety_pressure(project_root: Path) -> None:
    """Sense pressió de reescriptura (text propi) la mesura no s'aplica."""
    pipeline = _pipeline(project_root, pressure=0.0)
    candidate = Candidate(0, TWO_CAUSALS, REPEATED_BY_AUTHOR, ())
    score = pipeline.scorer.score(candidate, ScoringContext(None, TWO_CAUSALS, None))
    assert CONNECTOR_COMPONENT not in score.components
    assert score.dimension("varietat_connectors") is None


def test_the_penalty_reaches_the_score_and_the_trace(deep: Pipeline) -> None:
    candidate = Candidate(0, TWO_CAUSALS, REPEATED_BY_AUTHOR, ())
    score = deep.scorer.score(candidate, ScoringContext(None, TWO_CAUSALS, None))
    assert score.components[CONNECTOR_COMPONENT] < 0
    assert score.dimension("varietat_connectors") == pytest.approx(0.5)
    assert score.to_dict()["connectors"]
    assert "repetició de connectors" in score.explanation


def test_the_paragraph_trace_explains_the_choice(orfil: ParaphraseResult) -> None:
    paragraph = orfil.paragraphs[0]
    assert paragraph.search is not None
    exported = paragraph.search.to_dict()
    alternatives = exported["alternatives"]
    assert isinstance(alternatives, list) and alternatives
    for alternative in alternatives:
        assert isinstance(alternative, dict)
        connectors = alternative["connectors"]
        assert isinstance(connectors, dict)
        assert "profile" in connectors and "penalty" in connectors
    repetitive = [a for a in alternatives if a["connectors"].get("penalty", 0.0) > 0]
    for alternative in repetitive:
        introduced = alternative["connectors"]["introduced"]
        assert introduced and all(item["distance"] >= 0 for item in introduced)


def test_the_real_paragraph_keeps_every_earlier_protection(orfil: ParaphraseResult) -> None:
    text = orfil.output_text
    # v1.3.10: «només … si» conserva l'abast i els dos punts no creen cap fragment nominal.
    assert "només té sentit si arfil designa" in text
    assert "categoria política: un home pròxim al rei" in text
    assert "categoria política. Un home" not in text
    # v1.3.10: «puix que» es reconeix, però no es genera mai.
    assert "puix que" not in text
    # Cap repetició de connector introduïda al text sencer.
    assert "però ja no sobirà" in text


def test_the_result_is_deterministic(project_root: Path, orfil: ParaphraseResult) -> None:
    again = _pipeline(project_root).run(ORFIL)
    assert again.output_text == orfil.output_text
    assert [s.output_text for s in again.sentences] == [s.output_text for s in orfil.sentences]


def test_the_architecture_level_measure_is_not_counted_twice(orfil: ParaphraseResult) -> None:
    """La repetició es mesura sobre el paràgraf sencer, no frase a frase i un altre cop."""
    paragraph = orfil.paragraphs[0]
    assert paragraph.search is not None
    for alternative in paragraph.search.alternatives:
        sentence_penalties = [
            option.evaluated.score.components.get(CONNECTOR_COMPONENT, 0.0)
            for option in alternative.state.options
            if option.evaluated.score is not None
        ]
        # Les puntuacions de frase poden portar la seva aproximació…
        assert all(value <= 0.0 for value in sentence_penalties)
        # …però el total global no les torna a sumar: el descompte és exacte.
        expected = sum(option.total - _discounted(option) for option in alternative.state.options)
        assert alternative.local_total == pytest.approx(round(expected, 4), abs=1e-4)


def _discounted(option: LocalOption) -> float:
    score = option.evaluated.score
    if score is None:
        return 0.0
    return score.components.get("afinitat_autor", 0.0) + score.components.get(
        CONNECTOR_COMPONENT, 0.0
    )


def test_the_beam_reaches_the_global_phase_with_both_variants(orfil: ParaphraseResult) -> None:
    """Si una frase té «ja que» i «atès que» segurs, tots dos han d'arribar al final."""
    paragraph = orfil.paragraphs[0]
    assert paragraph.search is not None
    causal = {"atès que", "ja que"}
    reached = {
        form
        for group in paragraph.search.options
        for option in group
        for form in option.connectors
        if form in causal
    }
    assert reached == causal, reached
    architectures = {
        tuple(f for f in alternative.state.connector_profile if f in causal)
        for alternative in paragraph.search.alternatives
    }
    assert len({a for a in architectures if len(a) == 2}) >= 2, architectures


def test_beam_settings_survive_a_replace() -> None:
    settings = replace(BeamSettings(beam_width=6), coverage_balance=0.06)
    assert settings.beam_width == 6 and settings.coverage_balance == 0.06
