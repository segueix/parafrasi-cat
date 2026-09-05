"""1.3.3: cobertura d'alternatives segures al nivell 5 profund i opció «Llenguatge assertiu».

Quatre blocs:

1. Els deu tests dels cinc canvis de cobertura (capa intermèdia, blocs
   sintàctics, balanç de cobertura, ritme de les fusions i oportunitats).
2. Els tests unitaris A–F de l'opció «Llenguatge assertiu»: més clara, mai
   més certa.
3. La matriu de transicions epistemològiques i el perfil epistemològic de
   l'empremta (només recomptes).
4. El text real de deu frases en mode profund nivell 5 amb l'empremta
   acadèmica, amb l'opció desactivada i activada, i la interfície.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

import parafrasi_cat.web as web_package
from parafrasi_cat.analyzer.analysis import RuleBasedAnalyzer
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon
from parafrasi_cat.candidates import Candidate
from parafrasi_cat.cli import main
from parafrasi_cat.core import SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.morphology.catalan import CatalanMorphology
from parafrasi_cat.morphology.provider import NullMorphology
from parafrasi_cat.pipeline.builder import ASSERTIVE_OPTION, build_pipeline, build_validators
from parafrasi_cat.pipeline.config import PipelineConfig, SourceMode
from parafrasi_cat.pipeline.modes import RewriteMode, apply_mode
from parafrasi_cat.pipeline.paragraph_search import _coverage_balance
from parafrasi_cat.pipeline.pipeline import Pipeline
from parafrasi_cat.pipeline.result import OpportunityStats, ParagraphOpportunities, ParaphraseResult
from parafrasi_cat.protected.protector import default_protector
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.rules import RuleSet, RuleSetConfig, build_rule_set, default_registry
from parafrasi_cat.rules.base import AnyRule, ParagraphRule, Rule, RuleContext
from parafrasi_cat.scoring.assertive import AssertiveEvaluator
from parafrasi_cat.scoring.scorer import CompositeScorer
from parafrasi_cat.scoring.weights import ScoringWeights
from parafrasi_cat.style.corpus import load_corpus
from parafrasi_cat.style.epistemic_profile import epistemic_profile
from parafrasi_cat.style.fusion_rhythm import FusionRhythm
from parafrasi_cat.style.observations import StyleResources
from parafrasi_cat.style.profile import StyleProfile, load_style_profile
from parafrasi_cat.style.profiler import build_fingerprint
from parafrasi_cat.syntax.analysis import (
    CachedSyntax,
    NullSyntax,
    SentenceSyntax,
    SyntaxConfidence,
    SyntaxProvider,
)
from parafrasi_cat.syntax.spacy_parser import SpacySyntax
from parafrasi_cat.validation import EpistemicLexicon
from parafrasi_cat.validation.categories import EpistemicCategory
from parafrasi_cat.validation.epistemic import EPISTEMOLOGY_FILE
from parafrasi_cat.validation.transitions import Transition, check_categories, transition_between
from parafrasi_cat.web import HistoryLog, RewriteService
from parafrasi_cat.web.service import ASSERTIVE_HELP, RewriteRequest

SENTENCES = (
    "Aquest conjunt d’indicis podria permetre interpretar el document com el resultat d’un "
    "procés de reelaboració més complex del que s’havia plantejat fins ara.",
    "La hipòtesi no depèn, però, d’una sola coincidència, sinó de l’acumulació de diversos "
    "elements que apunten en una mateixa direcció.",
    "Si considerem conjuntament la terminologia, l’estructura del text i el context en què "
    "apareix, aquesta possibilitat adquireix una consistència més gran.",
    "El problema principal és que cap d’aquests elements, considerat de manera aïllada, permet "
    "arribar a una conclusió definitiva.",
    "Tanmateix, la coincidència entre indicis independents pot tenir un valor que desapareix "
    "quan cadascun és examinat per separat.",
    "Aquesta dificultat s’accentua encara més quan la documentació conservada és fragmentària "
    "i obliga a reconstruir relacions que les fonts no expliquen de manera explícita.",
    "En aquest sentit, no es pot demostrar que totes les peces formessin part d’un mateix "
    "projecte, encara que la seva proximitat cronològica permeti plantejar aquesta possibilitat.",
    "La qüestió, per tant, no és només determinar si existeix una relació entre els testimonis.",
    "També cal establir fins a quin punt aquesta relació pot explicar les diferències que "
    "presenten entre ells.",
    "Una interpretació d’aquest tipus continuaria sent hipotètica, però permetria ordenar les "
    "dades disponibles sense convertir una possibilitat raonable en una certesa documental.",
)
TEXT_10 = " ".join(SENTENCES)

#: Formulacions de certesa que cap candidat no pot introduir en cap dels dos modes.
CERTAINTY = (
    "demostra que",
    "demostren",
    "queda demostrat",
    "està demostrat",
    "confirma que",
    "és evident",
    "sens dubte",
    "certament",
    "evidentment",
    "sense cap dubte",
)


# --- recursos --------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def morphology(paths: ProjectPaths) -> CatalanMorphology:
    resource = CatalanMorphology.discover(paths.language())
    if resource is None:
        pytest.skip("cal el recurs morfològic de Softcatalà (scripts/install_morphology.py)")
    assert resource is not None
    return resource


@pytest.fixture(scope="module")
def parser(morphology: CatalanMorphology) -> SyntaxProvider:
    found = SpacySyntax(morphology=morphology)
    if not found.available:
        pytest.skip("cal el parser local (scripts/install_parser.py)")
    return CachedSyntax(found)


@pytest.fixture(scope="module")
def rule_set(paths: ProjectPaths) -> RuleSet:
    return build_rule_set(
        RuleSetConfig.load(paths.rules / "parafrasi.yaml"), default_registry(), paths
    )


@pytest.fixture(scope="module")
def epistemic(paths: ProjectPaths) -> EpistemicLexicon:
    return EpistemicLexicon.load(paths.language() / EPISTEMOLOGY_FILE)


@pytest.fixture(scope="module")
def fingerprint_file(
    project_root: Path,
    paths: ProjectPaths,
    lexicon: ClosedClassLexicon,
    catalan_analyzer: RuleBasedAnalyzer,
    parser: SyntaxProvider,
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """Empremta d'un autor acadèmic real (corpus «academic»), amb perfil epistemològic."""
    corpus = load_corpus(project_root / "corpus" / "exemples" / "academic")
    resources = StyleResources.load(paths, lexicon=lexicon)
    fingerprint = build_fingerprint(
        corpus, resources, catalan_analyzer, name="academic", syntax=parser
    )
    return fingerprint.save(tmp_path_factory.mktemp("empremta") / "academic.json")


def _real_config(project_root: Path, fingerprint_file: Path, *, assertive: bool) -> PipelineConfig:
    return PipelineConfig(
        home=project_root,
        rule_set="parafrasi",
        style_profile=str(fingerprint_file),
        source_mode=SourceMode.LLM_DRAFT,
        languagetool=False,
        assertive_language=assertive,
    )


@pytest.fixture(scope="module")
def deep_off(
    project_root: Path, fingerprint_file: Path, morphology: CatalanMorphology
) -> ParaphraseResult:
    config = apply_mode(_real_config(project_root, fingerprint_file, assertive=False), "profund", 5)
    pipeline = build_pipeline(config)
    assert pipeline.syntax.available and pipeline.searches_paragraphs
    assert not pipeline.assertive_language
    return pipeline.run(TEXT_10)


@pytest.fixture(scope="module")
def deep_on(
    project_root: Path, fingerprint_file: Path, morphology: CatalanMorphology
) -> ParaphraseResult:
    config = apply_mode(_real_config(project_root, fingerprint_file, assertive=True), "profund", 5)
    pipeline = build_pipeline(config)
    assert pipeline.assertive_language
    return pipeline.run(TEXT_10)


@pytest.fixture(scope="module")
def assertive_pipeline(project_root: Path, morphology: CatalanMorphology) -> Pipeline:
    """Mode conservador amb l'opció activa: el que veu qui marca la casella."""
    config = PipelineConfig(
        home=project_root, rule_set="parafrasi", languagetool=False, assertive_language=True
    )
    return build_pipeline(apply_mode(config, "conservador", 5))


@pytest.fixture(scope="module")
def plain_pipeline(project_root: Path, morphology: CatalanMorphology) -> Pipeline:
    config = PipelineConfig(home=project_root, rule_set="parafrasi", languagetool=False)
    return build_pipeline(apply_mode(config, "conservador", 5))


# --- ajudes ----------------------------------------------------------------------------------


def _context(
    analyzer: RuleBasedAnalyzer,
    text: str,
    *,
    morphology: CatalanMorphology | None = None,
    syntax: SyntaxProvider | None = None,
) -> RuleContext:
    sentence = analyzer.analyze(text).sentences[0]
    provider: SyntaxProvider = syntax if syntax is not None else NullSyntax()
    return RuleContext(
        sentence=sentence,
        protected_spans=default_protector(analyzer).protect(text),
        document_text=text,
        morphology=morphology if morphology is not None else NullMorphology(),
        lexicon=analyzer.lexicon,
        syntax=provider,
        analysis=provider.parse(text) if provider.available else None,
    )


def _sentence_rule(rule_set: RuleSet, rule_id: str) -> Rule:
    rule = rule_set.rule(rule_id)
    assert isinstance(rule, Rule), rule_id
    return rule


class _Doubtful:
    """Analitzador que retorna arbres reals però marcats com a poc fiables."""

    available = True

    def __init__(self, provider: SyntaxProvider) -> None:
        self._provider = provider

    def parse(self, text: str) -> SentenceSyntax:
        return replace(
            self._provider.parse(text), confidence=SyntaxConfidence(False, ("prova de dubte",))
        )


class _ConfRule(Rule):
    """Regla de prova: substitueix un fragment amb la confiança i la família indicades."""

    def __init__(
        self, rule_id: str, before: str, after: str, confidence: float, family: str = ""
    ) -> None:
        super().__init__(rule_id, transformation_type=TransformationType.LEXICAL, category="lexic")
        self._before, self._after, self._confidence, self._family = (
            before,
            after,
            confidence,
            family,
        )

    def propose(self, ctx: RuleContext) -> list[Transformation]:
        start = ctx.text.find(self._before)
        if start < 0:
            return []
        metadata = {"category": "lexic", **({"family": self._family} if self._family else {})}
        return [
            Transformation(
                self.rule_id,
                self._before,
                self._after,
                Span(start, start + len(self._before)),
                self.transformation_type,
                self._confidence,
                SemanticRisk.LOW,
                f"«{self._before}» → «{self._after}»",
                metadata,
            )
        ]


def _pipeline(
    paths: ProjectPaths,
    lexicon: ClosedClassLexicon,
    analyzer: RuleBasedAnalyzer,
    rules: tuple[AnyRule, ...],
    *,
    beam_width: int = 4,
    weights: ScoringWeights | None = None,
) -> Pipeline:
    rule_set = RuleSet(RuleSetConfig(name="prova", max_semantic_risk=SemanticRisk.HIGH), rules, ())
    validators = build_validators(PipelineConfig(), paths, analyzer, lexicon, rule_set)
    return Pipeline(
        analyzer=analyzer,
        protector=default_protector(analyzer, lexicon=lexicon),
        rule_set=rule_set,
        validators=validators,
        scorer=CompositeScorer(weights or ScoringWeights()),
        max_level=5,
        paragraph_beam_width=beam_width,
        sentence_candidates_for_paragraph=3,
    )


def _merge_candidate(first: str, second: str) -> Candidate:
    """Candidat amb una sola fusió: «A. B.» → «A, i b.»."""
    source = f"{first}. {second}."
    before = f". {second.split(' ', 1)[0]}"
    after = f", i {second.split(' ', 1)[0].lower()}"
    start = source.index(before)
    transformation = Transformation(
        "prova.fusio",
        before,
        after,
        Span(start, start + len(before)),
        TransformationType.SENTENCE_MERGE,
        0.7,
        SemanticRisk.LOW,
        "prova",
        {"category": "fusio"},
    )
    return Candidate.from_transformations(0, source, [transformation])


def _accepted(result: ParaphraseResult, index: int) -> list[str]:
    return list(result.alternatives(index))


def _words(text: str) -> int:
    return len([w for w in text.replace("’", "'").split() if any(c.isalnum() for c in w)])


# ==============================================================================================
# 1. Els deu tests dels cinc canvis de cobertura
# ==============================================================================================


def test_1_a_medial_connector_gets_a_safe_initial_alternative(
    rule_set: RuleSet, catalan_analyzer: RuleBasedAnalyzer, morphology: CatalanMorphology
) -> None:
    """Capa intermèdia: «no depèn, però, d'una» → «Tanmateix, no depèn d'una», sense lèxic nou."""
    rule = _sentence_rule(rule_set, "ordre.pero_medial_a_inicial")
    text = SENTENCES[1]
    produced = [
        t.apply(text) for t in rule.propose(_context(catalan_analyzer, text, morphology=morphology))
    ]
    assert (
        "Tanmateix, la hipòtesi no depèn d’una sola coincidència, sinó de l’acumulació de "
        "diversos elements que apunten en una mateixa direcció." in produced
    ), produced
    # Cap substitució lèxica: només el connector canvia de lloc i de forma.
    original_words = Counter(re.findall(r"\w+", text.lower()))
    original_words.subtract({"però": 1})
    for candidate in produced:
        new_words = Counter(re.findall(r"\w+", candidate.lower()))
        for connector in ("tanmateix", "no obstant això"):
            if candidate.lower().startswith(connector):
                new_words.subtract(Counter(connector.split()))
        assert new_words == original_words, candidate
    # És estructural (REORDER) però amb un pes moderat: canvia l'arquitectura discursiva.
    transformation = next(
        iter(rule.propose(_context(catalan_analyzer, text, morphology=morphology)))
    )
    assert transformation.family.name == "REORDER"
    assert 0 < transformation.structural_weight < 0.7


def test_2_an_internal_subordinate_block_moves_as_a_whole(
    rule_set: RuleSet,
    catalan_analyzer: RuleBasedAnalyzer,
    morphology: CatalanMorphology,
    parser: SyntaxProvider,
) -> None:
    """Bloc condicional sencer, amb la seva completiva interna, d'una punta a l'altra."""
    rule = _sentence_rule(rule_set, "blocs.subordinada_adverbial")
    text = SENTENCES[2]
    ctx = _context(catalan_analyzer, text, morphology=morphology, syntax=parser)
    produced = [t.apply(text) for t in rule.propose(ctx)]
    assert produced == [
        "Aquesta possibilitat adquireix una consistència més gran si considerem conjuntament "
        "la terminologia, l’estructura del text i el context en què apareix."
    ]
    # I en sentit contrari: la condicional final passa al davant, sencera.
    movable = (
        "Aquesta prudència s’entén encara més si considerem que l’obra era dedicada a "
        "Mateo Vázquez de Leca."
    )
    ctx = _context(catalan_analyzer, movable, morphology=morphology, syntax=parser)
    fronted = [t.apply(movable) for t in rule.propose(ctx)]
    assert fronted == [
        "Si considerem que l’obra era dedicada a Mateo Vázquez de Leca, aquesta prudència "
        "s’entén encara més."
    ]
    transformation = next(iter(rule.propose(ctx)))
    assert transformation.metadata["block_kind"] == "adverbial"
    assert transformation.family.structural


def test_3_a_doubtful_parse_blocks_every_block_move(
    rule_set: RuleSet,
    catalan_analyzer: RuleBasedAnalyzer,
    morphology: CatalanMorphology,
    parser: SyntaxProvider,
) -> None:
    """movable_subtree: si el parser no és fiable, no s'aplica; sense parser, tampoc."""
    for rule_id in (
        "blocs.subordinada_adverbial",
        "blocs.complement_del_verb",
        "blocs.participial_del_subjecte",
    ):
        rule = _sentence_rule(rule_set, rule_id)
        for text in (SENTENCES[2], SENTENCES[3], SENTENCES[5]):
            doubtful = _context(
                catalan_analyzer, text, morphology=morphology, syntax=_Doubtful(parser)
            )
            assert list(rule.propose(doubtful)) == [], (rule_id, text)
            without = _context(catalan_analyzer, text, morphology=morphology)
            assert list(rule.propose(without)) == [], (rule_id, text)
    # Amb el parser fiable, el participial interposat del subjecte sí que es mou.
    rule = _sentence_rule(rule_set, "blocs.participial_del_subjecte")
    ctx = _context(catalan_analyzer, SENTENCES[3], morphology=morphology, syntax=parser)
    assert [t.apply(SENTENCES[3]) for t in rule.propose(ctx)] == [
        "El problema principal és que, considerat de manera aïllada, cap d’aquests elements "
        "permet arribar a una conclusió definitiva."
    ]


def test_4_coverage_balance_only_counts_sentences_with_safe_alternatives() -> None:
    """El balanç reparteix entre les oportunitats segures existents; mai no és una quota."""
    # Sense cap frase amb alternativa segura no hi ha res a repartir.
    assert _coverage_balance([0.0, 0.0, 0.0], []) is None
    # El mateix canvi total repartit entre dues frases puntua més que concentrat en una.
    concentrated = _coverage_balance([1.0, 0.0], [0, 1])
    spread = _coverage_balance([0.5, 0.5], [0, 1])
    assert concentrated is not None and spread is not None
    assert spread > concentrated
    # Una frase sense alternativa segura no hi entra: no penalitza el repartiment.
    assert _coverage_balance([1.0, 0.0, 0.0], [0]) == 1.0
    assert _coverage_balance([0.5, 0.0, 0.0], [0]) == 0.5
    # Sempre entre 0 i 1.
    assert 0.0 <= (_coverage_balance([0.2, 0.9, 0.0], [0, 1]) or 0.0) <= 1.0


def test_4b_coverage_balance_is_only_active_in_deep_mode_at_level_five(project_root: Path) -> None:
    base = PipelineConfig(home=project_root, rule_set="parafrasi")
    assert apply_mode(base, "profund", 5).scoring.coverage_balance > 0
    assert apply_mode(base, "profund", 4).scoring.coverage_balance == 0
    assert apply_mode(base, "conservador", 5).scoring.coverage_balance == 0
    # Petit: mai decisiu davant de la preservació ni de la gramàtica.
    assert apply_mode(base, "profund", 5).scoring.coverage_balance <= 0.1


def test_5_coverage_balance_never_forces_a_change_where_there_is_no_opportunity(
    paths: ProjectPaths,
    lexicon: ClosedClassLexicon,
    catalan_analyzer: RuleBasedAnalyzer,
    rule_set: RuleSet,
) -> None:
    fusion = rule_set.rule("fusio.copulativa")
    assert isinstance(fusion, ParagraphRule)
    rule = _ConfRule("prova.a", "és antic", "resulta antic", 0.9, family="REORDER")
    pipeline = _pipeline(
        paths,
        lexicon,
        catalan_analyzer,
        (rule, fusion),
        weights=ScoringWeights(coverage_balance=0.06, structure=0.3),
    )
    assert pipeline.searches_paragraphs
    result = pipeline.run("El text és antic. La resta del volum no presenta cap alteració.")
    first, second = result.sentences
    assert first.changed and first.opportunities.detected == 1
    assert not second.changed
    assert second.opportunities.detected == 0
    assert second.opportunities.verdict == "sense cap alternativa"
    assert second.output_text == "La resta del volum no presenta cap alteració."
    paragraph = result.paragraphs[0]
    assert paragraph.opportunities.safe == 1 and paragraph.opportunities.structural == 1
    assert paragraph.opportunities.to_dict()["paragraph_safe_opportunities"] == 1


SHORT_FIRST = "El monument fou encarregat el 1507 pel mercader Oddo Altoviti"
SHORT_SECOND = "L’escultor no el va finalitzar fins al 1516"
LONG_FIRST = (
    "El monument funerari fou encarregat el 1507 pel mercader Oddo Altoviti a un taller "
    "florentí de gran prestigi en una etapa de prosperitat comercial notable"
)
LONG_SECOND = (
    "L’escultor Benedetto da Rovezzano no el va finalitzar fins al 1516 després d’una llarga "
    "sèrie d’interrupcions degudes a la manca de marbre de qualitat"
)


def test_6_a_fusion_too_long_for_the_author_rhythm_is_penalised_not_invalidated(
    catalan_analyzer: RuleBasedAnalyzer,
) -> None:
    long_merge = _merge_candidate(LONG_FIRST, LONG_SECOND)
    assert _words(long_merge.text) >= 40
    short_style = StyleProfile("curt", target_sentence_length=12.0, sentence_length_tolerance=4.0)
    rhythm = FusionRhythm(catalan_analyzer, None, None, short_style)
    assessment = rhythm.assess(long_merge)
    assert 0 < assessment.penalty <= 1.0
    assert assessment.penalised
    assert any("paraules" in reason for reason in assessment.reasons), assessment.reasons
    assert assessment.details["long_threshold"] == 18.0
    # És una penalització, no una invalidació: el candidat continua sent un candidat.
    assert long_merge.transformations and long_merge.text
    # I la mateixa fusió, per a un autor de frases llargues, no paga per longitud.
    long_style = StyleProfile("llarg", target_sentence_length=50.0, sentence_length_tolerance=10.0)
    assert FusionRhythm(catalan_analyzer, None, None, long_style).assess(long_merge).penalty == 0.0
    # Sense cap fusió no hi ha res a valorar.
    plain = Candidate.from_transformations(0, "El text és antic.", [])
    assert FusionRhythm(catalan_analyzer, None, None, short_style).assess(plain).penalty == 0.0


def test_7_a_fusion_compatible_with_the_author_rhythm_is_not_penalised(
    catalan_analyzer: RuleBasedAnalyzer, fingerprint_file: Path, paths: ProjectPaths
) -> None:
    """El llindar surt de l'empremta real (mediana, IQR, p90), no d'un «max_words = 40»."""
    profile = load_style_profile(fingerprint_file, paths=paths)
    preferences = profile.preferences
    assert preferences is not None
    node = preferences.fingerprint.get("sentence_length_distribution")
    assert isinstance(node, dict)
    median, iqr, p90 = float(node["median"]), float(node["iqr"]), float(node["p90"])
    rhythm = FusionRhythm(catalan_analyzer, None, preferences, profile)
    expected_long = max(p90, median + max(iqr, 6.0))
    assert rhythm.long_threshold == expected_long
    assert rhythm.long_threshold != 40.0
    short_merge = _merge_candidate(SHORT_FIRST, SHORT_SECOND)
    assert _words(short_merge.text) < expected_long
    assessment = rhythm.assess(short_merge)
    assert assessment.penalty == 0.0 and not assessment.penalised
    # La mateixa fusió curta sí que paga per a un autor de frases molt curtes.
    short_style = StyleProfile("curt", target_sentence_length=8.0, sentence_length_tolerance=2.0)
    assert FusionRhythm(catalan_analyzer, None, None, short_style).assess(short_merge).penalty > 0


@pytest.fixture(scope="module")
def counted(
    paths: ProjectPaths, lexicon: ClosedClassLexicon, catalan_analyzer: RuleBasedAnalyzer
) -> ParaphraseResult:
    """Quatre propostes: una segura superficial, una segura estructural, una insegura
    (perd la modalització) i una descartada abans (toca una dada protegida)."""
    rules = (
        _ConfRule("prova.lexic", "antic", "vell", 0.9),
        _ConfRule(
            "prova.ordre", "El text podria ser antic", "Antic podria ser el text", 0.8, "REORDER"
        ),
        _ConfRule("prova.certesa", "podria ser", "és", 0.9),
        _ConfRule("prova.data", "1507", "1508", 0.9),
    )
    pipeline = _pipeline(paths, lexicon, catalan_analyzer, rules, beam_width=0)
    return pipeline.run("El text podria ser antic segons el catàleg de 1507.")


def test_8_opportunities_detected_counts_every_proposal(counted: ParaphraseResult) -> None:
    stats = counted.sentences[0].opportunities
    assert stats.detected == 4
    assert stats.detected == stats.safe + stats.unsafe + stats.rejected_proposals
    assert stats.detected >= stats.safe
    assert stats.verdict == "transformada" and not stats.selected_is_original
    exported = stats.to_dict()
    assert exported["opportunities_detected"] == 4
    assert set(exported) >= {
        "opportunities_detected",
        "safe_proposals",
        "structural_proposals",
        "surface_proposals",
        "selected_family",
        "selected_is_original",
    }
    assert "4 oportunitats detectades" in counted.report()


def test_9_safe_proposals_leave_out_the_rejected_ones(counted: ParaphraseResult) -> None:
    sentence = counted.sentences[0]
    stats = sentence.opportunities
    assert stats.safe == 2
    # La proposta que perd «podria» no supera la validació epistemològica: insegura.
    assert stats.unsafe == 1
    assert any(
        not e.accepted and "prova.certesa" in e.candidate.rule_ids for e in sentence.candidates
    )
    # La que toca la data protegida es descarta abans de generar cap candidat.
    assert stats.rejected_proposals == 1
    assert [r.transformation.rule_id for r in sentence.rejected_proposals] == ["prova.data"]
    # I les tres situacions es distingeixen pel veredicte.
    assert OpportunityStats().verdict == "sense cap alternativa"
    assert OpportunityStats(detected=2, unsafe=2).verdict == "cap alternativa segura"
    assert OpportunityStats(detected=2, safe=2).verdict == "l'original ha guanyat"
    assert (
        OpportunityStats(
            detected=1, safe=1, selected_family="REORDER", selected_is_original=False
        ).verdict
        == "transformada"
    )


def test_10_structural_proposals_exclude_verbal_and_punctuation_changes(
    paths: ProjectPaths,
    lexicon: ClosedClassLexicon,
    catalan_analyzer: RuleBasedAnalyzer,
    counted: ParaphraseResult,
) -> None:
    stats = counted.sentences[0].opportunities
    assert stats.structural == 1 and stats.surface == 1
    rules = (
        _ConfRule("prova.verbal", "va ser copiat", "fou copiat", 0.9, "VERBAL"),
        _ConfRule("prova.punt", "antic, i", "antic i", 0.9, "PUNCTUATION"),
        _ConfRule("prova.ordre", "El text és antic", "Antic és el text", 0.8, "REORDER"),
    )
    result = _pipeline(paths, lexicon, catalan_analyzer, rules, beam_width=0).run(
        "El text és antic, i va ser copiat més tard."
    )
    stats = result.sentences[0].opportunities
    assert stats.safe == 3
    assert stats.structural == 1
    assert stats.surface == 2


# ==============================================================================================
# 2. «Llenguatge assertiu»: tests unitaris A–F
# ==============================================================================================

HYPOTHESIS = "Aquest enfocament podria interpretar-se com una estratègia calculada."


def test_a_a_hypothesis_never_becomes_a_fact(
    assertive_pipeline: Pipeline, epistemic: EpistemicLexicon
) -> None:
    """A. «podria interpretar-se» mai no esdevé «era» ni «demostra»."""
    result = assertive_pipeline.run(HYPOTHESIS)
    for evaluated in result.sentences[0].candidates:
        if not evaluated.accepted:
            continue
        text = evaluated.candidate.text
        assert "era una estratègia" not in text and "demostra" not in text, text
        assert epistemic.categorize(text) is not EpistemicCategory.EVIDENCE, text
    for after in (
        "Aquest enfocament era una estratègia calculada.",
        "Aquest enfocament demostra una estratègia calculada.",
    ):
        verdict = epistemic.verdict(HYPOTHESIS, after)
        assert verdict is not None and verdict.transition is Transition.FORBIDDEN, after
        assert not verdict.allowed(authorized=True)


def test_b_the_hypothesis_can_be_made_explicit(
    assertive_pipeline: Pipeline, epistemic: EpistemicLexicon
) -> None:
    """B. La forma permesa: «permet plantejar la hipòtesi d'una estratègia calculada»."""
    result = assertive_pipeline.run(HYPOTHESIS)
    explicit = "Aquest enfocament permet plantejar la hipòtesi d'una estratègia calculada."
    assert explicit in _accepted(result, 0), _accepted(result, 0)
    assert epistemic.categorize(explicit) is EpistemicCategory.HYPOTHESIS
    verdict = epistemic.verdict(HYPOTHESIS, explicit)
    assert verdict is None or verdict.transition is not Transition.FORBIDDEN
    selected = result.sentences[0].selected
    assert selected.candidate.text == explicit
    assert "assertiu.hipotesi_explicita" in selected.candidate.rule_ids


ATTRIBUTION = "Com detalla Rafael Ramis Barceló, el lul·lisme va gaudir d’una notable protecció."


def test_c_an_attribution_becomes_a_direct_statement_of_the_source(
    assertive_pipeline: Pipeline, epistemic: EpistemicLexicon
) -> None:
    """C. «Com detalla X, …» → «X detalla que …», mai «documenta» si no és compatible."""
    result = assertive_pipeline.run(ATTRIBUTION)
    direct = "Rafael Ramis Barceló detalla que el lul·lisme va gaudir d’una notable protecció."
    alternatives = _accepted(result, 0)
    assert direct in alternatives, alternatives
    assert not any("documenta" in alt for alt in alternatives)
    assert epistemic.categorize(ATTRIBUTION) is EpistemicCategory.EVIDENCE
    assert epistemic.categorize(direct) is EpistemicCategory.EVIDENCE
    assert epistemic.verdict(ATTRIBUTION, direct) is None
    # Pujar de força dins de la mateixa categoria està prohibit encara que sigui evidència.
    stronger = epistemic.verdict(
        ATTRIBUTION, "Està demostrat que el lul·lisme va gaudir d’una notable protecció."
    )
    assert stronger is not None and stronger.transition is Transition.FORBIDDEN


def test_d_a_limitation_is_only_rephrased_with_documentary_context(
    assertive_pipeline: Pipeline, epistemic: EpistemicLexicon
) -> None:
    """D. «No es pot demostrar que…» → «La documentació disponible no permet demostrar que…»."""
    with_context = "No es pot demostrar que els documents fossin contemporanis."
    result = assertive_pipeline.run(with_context)
    rephrased = (
        "La documentació disponible no permet demostrar que els documents fossin contemporanis."
    )
    assert rephrased in _accepted(result, 0), _accepted(result, 0)
    for alt in _accepted(result, 0):
        assert epistemic.categorize(alt) is EpistemicCategory.LIMITATION, alt
    # Sense cap context documental la limitació es manté tal com és.
    without = "No es pot demostrar que fossin contemporanis."
    kept = assertive_pipeline.run(without)
    assert not any("documentació disponible" in alt for alt in _accepted(kept, 0))
    for alt in _accepted(kept, 0):
        assert epistemic.categorize(alt) is EpistemicCategory.LIMITATION, alt
    # I una limitació mai no passa a evidència, per cap regla.
    verdict = epistemic.verdict(
        with_context, "Està documentat que els documents foren contemporanis."
    )
    assert verdict is not None and verdict.transition is Transition.FORBIDDEN


def test_e_no_evidence_is_invented(
    assertive_pipeline: Pipeline, epistemic: EpistemicLexicon
) -> None:
    """E. L'indicatiu gramatical no és cap evidència: no s'hi afegeixen marcadors."""
    plain = "L’església existia el 1050 i tenia una sola nau."
    result = assertive_pipeline.run(plain)
    for evaluated in result.sentences[0].candidates:
        if evaluated.accepted:
            text = evaluated.candidate.text
            assert epistemic.categorize(text) is EpistemicCategory.UNKNOWN, text
            for marker in ("consta", "documenta", "està documentat", "demostra", "sens dubte"):
                assert marker not in text, text
    # «indica» no és «demostra»: dins de l'evidència, pujar de força està prohibit.
    verdict = epistemic.verdict("El document indica una data.", "El document demostra una data.")
    assert verdict is not None and verdict.transition is Transition.FORBIDDEN
    # I afegir un marcador d'evidència a una afirmació no marcada també.
    added = epistemic.verdict(plain, "Està documentat que l’església existia el 1050.")
    assert added is not None and added.transition is Transition.FORBIDDEN


def test_f_double_hedging_is_reduced_only_when_the_option_is_active(
    assertive_pipeline: Pipeline,
    plain_pipeline: Pipeline,
    epistemic: EpistemicLexicon,
    rule_set: RuleSet,
) -> None:
    """F. «Potser podria ser…» → «Podria ser…» amb l'opció; sense l'opció, res."""
    doubled = "Potser podria ser una còpia posterior."
    reduced = "Podria ser una còpia posterior."
    on = assertive_pipeline.run(doubled)
    assert reduced in _accepted(on, 0)
    assert on.sentences[0].selected.candidate.text == reduced
    assert epistemic.categorize(reduced) is EpistemicCategory.HYPOTHESIS
    # La reducció només val perquè una regla la declara com a redundància.
    assert epistemic.verdict(doubled, reduced, redundancy=True) is None
    plain_verdict = epistemic.verdict(doubled, reduced)
    assert plain_verdict is not None and plain_verdict.transition is Transition.FORBIDDEN
    # Sense l'opció, cap regla assertiva no existeix i la frase es queda com és.
    off = plain_pipeline.run(doubled)
    assert reduced not in _accepted(off, 0)
    assert not any(
        r.startswith("assertiu.") for e in off.sentences[0].candidates for r in e.candidate.rule_ids
    )
    assert not any(r.startswith("assertiu.") for r in plain_pipeline.rule_set.rule_ids)
    assert any(r.startswith("assertiu.") for r in assertive_pipeline.rule_set.rule_ids)
    assert not any(r.startswith("assertiu.") for r in rule_set.for_options(()).rule_ids)
    assert any(
        r.startswith("assertiu.") for r in rule_set.for_options((ASSERTIVE_OPTION,)).rule_ids
    )
    # Mai més certa: cap candidat acceptat no perd tota la modalització.
    for evaluated in on.sentences[0].candidates:
        if evaluated.accepted:
            assert epistemic.categorize(evaluated.candidate.text) is EpistemicCategory.HYPOTHESIS


def test_the_assertive_bonus_is_small_and_comes_after_preservation(
    epistemic: EpistemicLexicon,
) -> None:
    evaluator = AssertiveEvaluator(epistemic)
    doubled = "Potser podria ser una còpia posterior."
    better = evaluator.assess(doubled, "Podria ser una còpia posterior.")
    assert better.delta > 0 and "redueix la doble modalització" in better.reasons
    same = evaluator.assess(doubled, doubled)
    assert same.delta == 0 and same.reasons == ()
    worse = evaluator.assess("Podria ser una còpia posterior.", doubled)
    assert worse.delta < 0
    explicit = evaluator.assess(
        HYPOTHESIS, "Aquest enfocament permet plantejar la hipòtesi d'una estratègia calculada."
    )
    assert explicit.delta > 0
    # El pes del bonus és petit davant del guany, del risc i de l'estructura.
    weights = ScoringWeights()
    assert weights.assertive < weights.semantic_risk
    assert weights.assertive < weights.transformation_gain
    assert weights.assertive <= 0.25


# ==============================================================================================
# 3. Matriu de transicions i perfil epistemològic de l'empremta
# ==============================================================================================


def test_the_transition_matrix_is_explicit_and_never_raises_certainty() -> None:
    E, INF, H, L, U = (  # noqa: N806 - inicials de la matriu de l'especificació
        EpistemicCategory.EVIDENCE,
        EpistemicCategory.INFERENCE,
        EpistemicCategory.HYPOTHESIS,
        EpistemicCategory.LIMITATION,
        EpistemicCategory.UNKNOWN,
    )
    for category in EpistemicCategory:
        assert transition_between(category, category) is Transition.ALLOWED
    # Els tres errors de l'especificació.
    assert transition_between(H, E) is Transition.FORBIDDEN
    assert transition_between(INF, E) is Transition.FORBIDDEN
    assert transition_between(L, E) is Transition.FORBIDDEN
    # Una limitació no es converteix en res.
    for target in (E, INF, H, U):
        assert transition_between(L, target) is Transition.FORBIDDEN
    # Hipòtesi → inferència només per una regla que ho declari.
    assert transition_between(H, INF) is Transition.RULE_ONLY
    assert transition_between(H, U) is Transition.FORBIDDEN
    # Baixar de certesa és cosa d'una regla; una afirmació no pot esdevenir evidència.
    assert transition_between(E, INF) is Transition.RULE_ONLY
    assert transition_between(U, E) is Transition.FORBIDDEN
    assert transition_between(U, H) is Transition.RULE_ONLY
    # Ordre de força: limitació < hipòtesi < inferència < evidència.
    assert L.rank < H.rank < INF.rank < E.rank  # type: ignore[operator]
    assert U.rank is None


def test_category_verdicts_from_counts() -> None:
    H, E = EpistemicCategory.HYPOTHESIS, EpistemicCategory.EVIDENCE  # noqa: N806
    assert check_categories(Counter({H: 1}), Counter({H: 1})) is None
    # Perdre un marcador sense substituir-lo: afirmació no marcada (prohibit).
    lost = check_categories(Counter({H: 1}), Counter())
    assert lost is not None and lost.transition is Transition.FORBIDDEN
    assert lost.after is EpistemicCategory.UNKNOWN
    # Reduir una redundància conserva la categoria més feble: cap transició.
    assert check_categories(Counter({H: 2}), Counter({H: 1}), redundancy=True) is None
    # Però la mateixa reducció sense una regla de redundància és una pèrdua.
    reduced = check_categories(Counter({H: 2}), Counter({H: 1}))
    assert reduced is not None and reduced.transition is Transition.FORBIDDEN
    # Pujar de categoria: prohibit; la descripció ho diu.
    raised = check_categories(Counter({H: 1}), Counter({E: 1}))
    assert raised is not None and raised.transition is Transition.FORBIDDEN
    assert "augmenta la certesa" in raised.describe()
    assert "hipòtesi" in raised.describe() and "evidència" in raised.describe()


def test_the_lexicon_classifies_the_spec_markers(epistemic: EpistemicLexicon) -> None:
    cases = {
        "Segons el document, el temple era antic.": EpistemicCategory.EVIDENCE,
        "Consta que el temple era antic.": EpistemicCategory.EVIDENCE,
        "Això permet inferir que el temple era antic.": EpistemicCategory.INFERENCE,
        "Això sembla indicar que el temple era antic.": EpistemicCategory.INFERENCE,
        "Això apunta a un temple antic.": EpistemicCategory.INFERENCE,
        "El temple podria ser antic.": EpistemicCategory.HYPOTHESIS,
        "Potser el temple era antic.": EpistemicCategory.HYPOTHESIS,
        "És una hipòtesi que el temple fos antic.": EpistemicCategory.HYPOTHESIS,
        "No es pot demostrar que el temple fos antic.": EpistemicCategory.LIMITATION,
        "No hi ha constància que el temple fos antic.": EpistemicCategory.LIMITATION,
        "La documentació no permet establir que el temple fos antic.": EpistemicCategory.LIMITATION,
        "El temple era antic.": EpistemicCategory.UNKNOWN,
    }
    for text, expected in cases.items():
        assert epistemic.categorize(text) is expected, (text, epistemic.profile(text).matches)
    # La més feble mana: una inferència recolzada en una hipòtesi és una hipòtesi.
    mixed = "Segons el document, el temple podria ser antic."
    assert epistemic.categorize(mixed) is EpistemicCategory.HYPOTHESIS


def test_the_epistemic_profile_keeps_counts_and_never_sentences(
    catalan_analyzer: RuleBasedAnalyzer, epistemic: EpistemicLexicon, fingerprint_file: Path
) -> None:
    texts = (
        "Segons el document, el temple era antic. Potser el temple era més antic encara.",
        "No es pot demostrar que fos romànic. Això permet inferir una data tardana. Era gran.",
    )
    profile = epistemic_profile(texts, catalan_analyzer, epistemic)
    assert profile["available"] is True
    assert profile["sample_size_sentences"] == 5
    assert profile["confidence"] == "low"
    categories = profile["categories"]
    assert isinstance(categories, dict)
    assert categories["EVIDENCE"]["count"] == 1
    assert categories["HYPOTHESIS"]["count"] == 1
    assert categories["LIMITATION"]["count"] == 1
    assert categories["INFERENCE"]["count"] == 1
    assert profile["direct_share"] == 0.2
    # Només recomptes: cap frase del corpus no es desa.
    serialized = json.dumps(profile, ensure_ascii=False)
    for text in texts:
        for sentence in text.split(". "):
            assert sentence.strip(". ") not in serialized
    # L'empremta real porta el perfil, amb la confiança segons la mida de la mostra.
    data = json.loads(fingerprint_file.read_text(encoding="utf-8"))
    saved = data["features"]["epistemic_profile"]
    assert saved["available"] is True
    assert saved["confidence"] in {"low", "medium", "high"}
    assert saved["sample_size_sentences"] >= 10
    ranked = {c.value for c in EpistemicCategory if c is not EpistemicCategory.UNKNOWN}
    assert set(saved["categories"]) == ranked


# ==============================================================================================
# 4. Text real de deu frases: profund nivell 5, empremta acadèmica, OFF i ON
# ==============================================================================================


def _outputs(result: ParaphraseResult) -> list[str]:
    return [s.output_text for s in result.sentences]


@pytest.mark.parametrize("which", ["off", "on"])
def test_real_every_epistemic_marker_survives(
    which: str, deep_off: ParaphraseResult, deep_on: ParaphraseResult, epistemic: EpistemicLexicon
) -> None:
    """Criteris 1-5: cap marcador es perd, cap «podria» esdevé certesa, la hipòtesi continua
    sent hipòtesi, «no es pot demostrar» continua sent limitació i «permeti plantejar» no
    esdevé «demostra»."""
    result = deep_off if which == "off" else deep_on
    for sentence in result.sentences:
        source, output = sentence.source_text, sentence.output_text
        assert epistemic.categorize(output) is epistemic.categorize(source), (source, output)
        for marker in CERTAINTY:
            assert marker not in output.lower() or marker in source.lower(), (marker, output)
    outputs = _outputs(result)
    assert "podria permetre interpretar" in outputs[0]
    assert "hipòtesi" in outputs[1]
    assert "no es pot demostrar" in outputs[6] or "no permet demostrar" in outputs[6]
    assert "permeti plantejar aquesta possibilitat" in outputs[6]
    assert "demostra que" not in outputs[6]
    assert "hipotètica" in outputs[9] and "possibilitat raonable" in outputs[9]
    assert "certesa documental" in outputs[9]
    # Ni al paràgraf final ni a cap candidat acceptat de cap frase.
    for sentence in result.sentences:
        for evaluated in sentence.candidates:
            if evaluated.accepted:
                text = evaluated.candidate.text
                assert epistemic.categorize(text) is epistemic.categorize(sentence.source_text), (
                    text
                )
    for marker in CERTAINTY:
        assert marker not in result.output_text.lower()


def test_real_the_assertive_version_is_more_direct_but_not_more_certain(
    deep_off: ParaphraseResult, deep_on: ParaphraseResult, epistemic: EpistemicLexicon
) -> None:
    """Criteris 6-7: l'opció fa explícita la limitació documental i pot treure redundància."""
    assert deep_on.assertive_language and not deep_off.assertive_language
    off, on = _outputs(deep_off), _outputs(deep_on)
    assert "la documentació disponible no permet demostrar que" in on[6]
    assert "no es pot demostrar que" in off[6]
    assert epistemic.categorize(on[6]) is EpistemicCategory.LIMITATION
    assert any("assertiu." in r for r in deep_on.sentences[6].applied_rule_ids)
    assert not any("assertiu." in r for s in deep_off.sentences for r in s.applied_rule_ids)
    # L'opció no toca res més que la formulació epistemològica: la resta coincideix.
    for index in (0, 1, 2, 3, 4, 5, 7, 8, 9):
        assert on[index] == off[index], index
    # Cap doble modalització a la sortida (el text no en tenia, i no se n'afegeix cap).
    for text in (deep_off.output_text, deep_on.output_text):
        assert "potser podria" not in text.lower() and "sembla que podria" not in text.lower()
    assert "Llenguatge assertiu: actiu" in deep_on.report()
    assert "Llenguatge assertiu: inactiu" in deep_off.report()


def test_real_the_first_sentences_have_structural_opportunities_now(
    deep_off: ParaphraseResult,
) -> None:
    """Criteri 8: amb el parser fiable, les frases 1-4 tenen alternatives estructurals segures."""
    for index in (1, 2, 3, 4):
        sentence = deep_off.sentences[index]
        stats = sentence.opportunities
        assert stats.structural >= 1, (index, stats.describe())
        assert stats.safe >= 1 and stats.detected >= stats.safe
        assert sentence.changed and sentence.selected.candidate.is_structural, index
    outputs = _outputs(deep_off)
    assert outputs[1].startswith("Tanmateix, la hipòtesi no depèn d’una sola coincidència")
    assert outputs[2].startswith(
        "Aquesta possibilitat adquireix una consistència més gran si considerem"
    )
    assert outputs[3] == (
        "El problema principal és que, considerat de manera aïllada, cap d’aquests elements "
        "permet arribar a una conclusió definitiva."
    )
    assert "tanmateix" in outputs[4].lower()
    # La frase coordinada amb «però» es pot dividir: també és estructural.
    assert deep_off.sentences[9].opportunities.structural >= 1
    paragraph = deep_off.paragraphs[0].opportunities
    assert paragraph.safe >= 6 and paragraph.structural >= 4
    assert paragraph.fusion >= 2 and paragraph.split >= 1
    exported = paragraph.to_dict()
    assert exported["paragraph_structural_opportunities"] == paragraph.structural
    assert set(exported) >= {
        "paragraph_safe_opportunities",
        "paragraph_structural_opportunities",
        "paragraph_fusion_opportunities",
        "paragraph_split_opportunities",
    }


def test_real_not_every_sentence_changes(deep_off: ParaphraseResult) -> None:
    """Criteri 9: sense cap alternativa segura, la frase es queda tal com és."""
    first = deep_off.sentences[0]
    assert not first.changed
    assert first.opportunities.detected == 0
    assert first.opportunities.verdict == "sense cap alternativa"
    assert first.output_text == SENTENCES[0]
    untouched = [s for s in deep_off.sentences if not s.changed]
    assert untouched and all(s.opportunities.selected_is_original for s in untouched)


def test_real_fusions_respect_the_author_rhythm(
    deep_off: ParaphraseResult, fingerprint_file: Path, paths: ProjectPaths
) -> None:
    """Criteri 10: cap fusió escollida no supera el límit dur del ritme real de l'autor."""
    profile = load_style_profile(fingerprint_file, paths=paths)
    assert profile.preferences is not None
    node = profile.preferences.fingerprint.get("sentence_length_distribution")
    assert isinstance(node, dict)
    median, iqr, p90 = float(node["median"]), float(node["iqr"]), float(node["p90"])
    long = max(p90, median + max(iqr, 6.0))
    hard = max(2.0 * median, long + max(iqr, 6.0))
    paragraph = deep_off.paragraphs[0]
    assert paragraph.changed and paragraph.opportunities.fusion >= 1
    selected = next(e for e in paragraph.candidates if e.candidate.text == paragraph.output_text)
    assert selected.accepted and selected.score is not None
    assert "ritme_fusio" in selected.score.dimensions
    for fused in paragraph.output_text.split(". "):
        assert _words(fused) <= hard, fused
    assert selected.score.dimensions["ritme_fusio"] is not None
    # Tots els candidats de paràgraf acceptats amb una fusió porten la valoració del ritme,
    # i el ritme mai no suma.
    for evaluated in paragraph.candidates:
        if evaluated.accepted and evaluated.score is not None:
            assert evaluated.score.components.get("ritme", 0.0) <= 0.0
            rhythm = evaluated.score.dimensions["ritme_fusio"]
            merges = any(
                t.transformation_type is TransformationType.SENTENCE_MERGE
                for t in evaluated.candidate.transformations
            )
            assert (rhythm is not None) == merges, evaluated.candidate.rule_ids
            if rhythm is not None:
                assert 0.0 <= rhythm <= 1.0


def test_real_opportunities_tell_no_alternative_from_original_won(
    deep_off: ParaphraseResult,
) -> None:
    """Criteri 11: «sense cap alternativa» ≠ «l'original ha guanyat»."""
    verdicts = {s.index: s.opportunities.verdict for s in deep_off.sentences}
    assert verdicts[0] == "sense cap alternativa"
    assert "transformada" in verdicts.values()
    for sentence in deep_off.sentences:
        stats = sentence.opportunities
        if stats.detected == 0:
            assert stats.verdict == "sense cap alternativa" and not sentence.changed
        elif not sentence.changed:
            assert stats.verdict in {"cap alternativa segura", "l'original ha guanyat"}
        report_line = f"Oportunitats: {stats.describe()}"
        assert report_line in deep_off.report()


def test_real_runs_in_reasonable_time(deep_off: ParaphraseResult) -> None:
    assert deep_off.n_candidates >= 30
    assert len(deep_off.sentences) == 10


# ==============================================================================================
# 5. Interfície: casella, API, historial i exportació
# ==============================================================================================


def test_the_request_parses_the_assertive_flag() -> None:
    assert RewriteRequest("Hola món.").assertive_language is False
    assert RewriteRequest.from_mapping({"text": "Hola món."}).assertive_language is False
    truthy: tuple[object, ...] = (True, "true", "1", "on", "yes")
    falsy: tuple[object, ...] = (False, "false", "0", "", None)
    for value in truthy:
        request = RewriteRequest.from_mapping({"text": "Hola món.", "assertive_language": value})
        assert request.assertive_language is True, value
    for value in falsy:
        request = RewriteRequest.from_mapping({"text": "Hola món.", "assertive_language": value})
        assert request.assertive_language is False, value
    config = RewriteRequest("Hola món.", assertive_language=True).to_config(Path("."))
    assert config.assertive_language is True
    assert PipelineConfig.from_mapping({"assertive_language": True}).assertive_language is True
    assert PipelineConfig(assertive_language=True).to_dict()["assertive_language"] is True


def test_the_service_reports_the_option_and_the_opportunities(
    project_root: Path, tmp_path: Path, morphology: CatalanMorphology
) -> None:
    service = RewriteService(ProjectPaths(project_root), history=HistoryLog(tmp_path / "h.jsonl"))
    doubled = "Potser podria ser una còpia posterior."
    on = service.rewrite(
        RewriteRequest(doubled, mode=RewriteMode.CONSERVATIVE, level=5, assertive_language=True)
    )
    assert on["assertive_language"] == {
        "active": True,
        "label": "actiu",
        "description": ASSERTIVE_HELP,
    }
    assert on["output_text"] == "Podria ser una còpia posterior."
    off = service.rewrite(RewriteRequest(doubled, mode=RewriteMode.CONSERVATIVE, level=5))
    assert off["assertive_language"]["active"] is False
    assert off["assertive_language"]["label"] == "inactiu"
    assert off["output_text"] != on["output_text"]
    # Les dues configuracions conviuen a la memòria cau del servei.
    assert len(service._pipelines) == 2  # noqa: SLF001 - comprovació de la reutilització
    for result in (on, off):
        for unit in result["units"]:
            stats = unit["opportunities"]
            assert {"opportunities_detected", "safe_proposals", "verdict"} <= set(stats)
    # Historial i exportació conserven l'opció.
    service.set_history_enabled(True)
    saved = service.save_history(
        {
            "source_text": doubled,
            "final_text": str(on["output_text"]),
            "config": {"mode": "conservador", "level": 5, "assertive_language": True},
        }
    )
    assert saved["saved"]
    entries = service.history_entries()["entries"]
    assert entries[-1]["assertive_language"] is True
    exported = json.loads(service.history_export())
    assert exported[-1]["config"]["assertive_language"] is True
    # L'opció també és ortogonal al mode: en mode profund continua sent la mateixa casella.
    deep = service.rewrite(
        RewriteRequest(doubled, mode=RewriteMode.DEEP, level=3, assertive_language=True)
    )
    assert deep["assertive_language"]["label"] == "actiu"


def test_the_page_offers_the_checkbox_off_by_default() -> None:
    static = Path(web_package.__file__).parent / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    script = (static / "app.js").read_text(encoding="utf-8")
    assert 'type="checkbox" id="assertiu"' in html
    assert "Llenguatge assertiu" in html
    assert ASSERTIVE_HELP in html
    checkbox_line = next(line for line in html.splitlines() if 'id="assertiu"' in line)
    assert "checked" not in checkbox_line
    assert 'assertive_language: $("assertiu").checked' in script
    assert "resum-assertiu" in html and "resum-assertiu" in script


def test_the_cli_switch(capsys: pytest.CaptureFixture[str], morphology: CatalanMorphology) -> None:
    text = "Potser podria ser una còpia posterior."
    assert main(["--rules", "parafrasi", "--assertiu", "--explain", text]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "Podria ser una còpia posterior."
    assert "Llenguatge assertiu: actiu" in captured.err
    assert main(["--rules", "parafrasi", "--explain", text]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "Potser podria ser una còpia posterior."
    assert "Llenguatge assertiu: inactiu" in captured.err


def test_paragraph_opportunities_default_shape() -> None:
    stats = ParagraphOpportunities()
    assert stats.to_dict()["paragraph_fusion_opportunities"] == 0
    assert stats.to_dict()["paragraph_split_opportunities"] == 0
