"""Arquitectures alternatives de paràgraf (1.3.2).

Cobreix el grau estructural real (només l'arquitectura lingüística), el
scoring conscient de família, la penalització de degradació local, els
subarbres movibles amb analitzador fiable, la cerca en feix de paràgraf
(òptim local contra òptim global) i el paràgraf real d'Alonso de Barros en
mode profund i en mode conservador. Els tests comproven propietats i
invariants, no frases exactes.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from parafrasi_cat.analyzer.analysis import RuleBasedAnalyzer
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon
from parafrasi_cat.candidates import Candidate, CandidateGenerator
from parafrasi_cat.core import SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.core.transformation import STRUCTURAL_FAMILIES, TransformationFamily
from parafrasi_cat.morphology.catalan import CatalanMorphology
from parafrasi_cat.morphology.provider import NullMorphology
from parafrasi_cat.pipeline.builder import build_pipeline, build_validators
from parafrasi_cat.pipeline.config import PipelineConfig, SourceMode
from parafrasi_cat.pipeline.modes import CONSERVATIVE, DEEP, RewriteMode, apply_mode
from parafrasi_cat.pipeline.pipeline import Pipeline
from parafrasi_cat.pipeline.result import ParaphraseResult
from parafrasi_cat.protected.protector import default_protector
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.rules import RuleSet, RuleSetConfig, build_rule_set, default_registry
from parafrasi_cat.rules.base import AnyRule, ParagraphRule, Rule, RuleContext
from parafrasi_cat.scoring.scorer import CompositeScorer, ScoringContext
from parafrasi_cat.scoring.weights import ScoringWeights
from parafrasi_cat.style.corpus import load_corpus
from parafrasi_cat.style.degradation import StructuralDegradation
from parafrasi_cat.style.observations import StyleResources
from parafrasi_cat.style.profiler import build_fingerprint
from parafrasi_cat.syntax.analysis import (
    CachedSyntax,
    NullSyntax,
    SentenceSyntax,
    SyntaxConfidence,
    SyntaxProvider,
)
from parafrasi_cat.syntax.spacy_parser import SpacySyntax
from parafrasi_cat.validation.result import ValidationResult

REAL_TEXT = (
    "Aquest enfocament més genèric d'Alonso de Barros, en el text de les edicions "
    "madrilenyes, podria interpretar-se com una estratègia calculada per presentar una obra "
    "acceptable dins d'un context inquisitorial particularment delicat. Aquest context estava "
    "profundament marcat per l'esperit de la Contrareforma, impulsada pel Concili de Trento "
    "(1545-1563), que va intensificar la vigilància doctrinal i la persecució de qualsevol "
    "sospita d'heterodòxia. Com detalla Rafael Ramis Barceló, el lul·lisme va gaudir d’una "
    "notable protecció en temps de Felipe II, que fins i tot en promogué textos per a la seva "
    "Acadèmia Matemàtica a Madrid; tanmateix, a les darreries del segle XVI, tant la "
    "Inquisició hispànica com la romana es mostraren cada vegada més bel·ligerants envers "
    "aquesta tradició. Aquesta creixent hostilitat inquisitorial, que es manifestava "
    "precisament en l'època de publicació del joc, hauria fet aconsellable un enfocament "
    "simbòlic més discret. Aquesta prudència s’entén encara més si considerem que l’obra era "
    "dedicada i adreçada, en totes les edicions, a Mateo Vázquez de Leca, que —tal com "
    "indicava el mateix llibre— exercia com a secretari de Felipe II i, alhora, com a "
    "secretari de la Santa Inquisició. Un fet que obligava Alonso de Barros a mantenir un "
    "subtil equilibri per aconseguir l’aprovació del joc, malgrat el reconegut interès i "
    "suport reial envers la figura de Llull."
)

VERBAL_SENTENCE = (
    "Com detalla Rafael Ramis Barceló, el lul·lisme va gaudir d’una notable protecció en "
    "temps de Felipe II, que fins i tot en promogué textos per a la seva Acadèmia Matemàtica "
    "a Madrid; tanmateix, a les darreries del segle XVI, tant la Inquisició hispànica com la "
    "romana es mostraren cada vegada més bel·ligerants envers aquesta tradició."
)

PROTECTED_FRAGMENTS = (
    "Alonso de Barros",
    "Rafael Ramis Barceló",
    "Felipe II",
    "Mateo Vázquez de Leca",
    "Concili de Trento",
    "1545-1563",
    "segle XVI",
    "Llull",
    "Madrid",
    "Santa Inquisició",
)

HEDGES = ("podria interpretar-se", "hauria fet aconsellable")
CERTAINTIES = ("sens dubte", "certament", "evidentment", "és evident", "sense cap dubte")
SURFACE = {
    TransformationFamily.VERBAL,
    TransformationFamily.PUNCTUATION,
    TransformationFamily.CONNECTOR,
    TransformationFamily.LEXICAL,
}


def _make(
    text: str,
    before: str,
    after: str,
    category: str,
    *,
    confidence: float = 0.7,
    kind: TransformationType = TransformationType.SYNTACTIC,
    **metadata: str,
) -> Transformation:
    start = text.index(before)
    return Transformation(
        f"prova.{category}",
        before,
        after,
        Span(start, start + len(before)),
        kind,
        confidence,
        SemanticRisk.LOW,
        "prova",
        {"category": category, **metadata},
    )


def _three_verbal(text: str = VERBAL_SENTENCE) -> Candidate:
    return Candidate.from_transformations(
        0,
        text,
        [
            _make(text, "va gaudir", "gaudí", "verbal", kind=TransformationType.MORPHOLOGICAL),
            _make(text, "promogué", "va promoure", "verbal", kind=TransformationType.MORPHOLOGICAL),
            _make(
                text,
                "es mostraren",
                "es van mostrar",
                "verbal",
                kind=TransformationType.MORPHOLOGICAL,
            ),
        ],
    )


def _whole_sentence_reorder(text: str = VERBAL_SENTENCE, confidence: float = 0.7) -> Candidate:
    body = text[:-1]
    return Candidate.from_transformations(
        0,
        text,
        [
            _make(
                text,
                body,
                "Segons Ramis Barceló, " + body[0].lower() + body[1:],
                "ordre",
                confidence=confidence,
            )
        ],
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
def fingerprint_file(
    project_root: Path,
    paths: ProjectPaths,
    lexicon: ClosedClassLexicon,
    catalan_analyzer: RuleBasedAnalyzer,
    parser: SyntaxProvider,
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """Empremta d'un autor acadèmic real (corpus «academic»), amb perfil sintàctic."""
    corpus = load_corpus(project_root / "corpus" / "exemples" / "academic")
    resources = StyleResources.load(paths, lexicon=lexicon)
    fingerprint = build_fingerprint(
        corpus, resources, catalan_analyzer, name="academic", syntax=parser
    )
    return fingerprint.save(tmp_path_factory.mktemp("empremta") / "academic.json")


def _real_config(project_root: Path, fingerprint_file: Path) -> PipelineConfig:
    return PipelineConfig(
        home=project_root,
        rule_set="parafrasi",
        style_profile=str(fingerprint_file),
        source_mode=SourceMode.LLM_DRAFT,
        languagetool=False,
    )


@pytest.fixture(scope="module")
def deep_real(
    project_root: Path, fingerprint_file: Path, morphology: CatalanMorphology
) -> ParaphraseResult:
    config = apply_mode(_real_config(project_root, fingerprint_file), RewriteMode.DEEP, 5)
    pipeline = build_pipeline(config)
    assert pipeline.syntax.available and pipeline.searches_paragraphs
    return pipeline.run(REAL_TEXT)


@pytest.fixture(scope="module")
def conservative_real(
    project_root: Path, fingerprint_file: Path, morphology: CatalanMorphology
) -> ParaphraseResult:
    config = apply_mode(_real_config(project_root, fingerprint_file), RewriteMode.CONSERVATIVE, 5)
    pipeline = build_pipeline(config)
    assert not pipeline.searches_paragraphs
    return pipeline.run(REAL_TEXT)


# --- 1-5: què és estructural i què no ---------------------------------------------------------


def test_three_verbal_changes_have_zero_structural_degree() -> None:
    """Test obligatori 1: «va gaudir → gaudí, promogué → va promoure, mostraren → van mostrar»."""
    candidate = _three_verbal()
    assert candidate.structural_degree() == 0.0
    assert candidate.surface_degree() > 0.0
    assert candidate.signature == "VERBAL" and not candidate.is_structural
    assert candidate.structural_families == ()


def test_punctuation_is_not_structural() -> None:
    text = "La casa (la gran) és a Girona."
    candidate = Candidate.from_transformations(
        0,
        text,
        [_make(text, " (la gran)", ", la gran,", "puntuacio", kind=TransformationType.PUNCTUATION)],
    )
    assert candidate.structural_degree() == 0.0
    assert not TransformationFamily.PUNCTUATION.structural
    assert TransformationFamily.PUNCTUATION.weight == 0.0


def test_connector_substitution_is_not_structural() -> None:
    text = "Plou molt; tanmateix, sortirem."
    candidate = Candidate.from_transformations(
        0,
        text,
        [
            _make(
                text, "tanmateix", "no obstant això", "connector", kind=TransformationType.CONNECTOR
            )
        ],
    )
    assert candidate.structural_degree() == 0.0 and candidate.surface_degree() > 0.0
    assert not TransformationFamily.CONNECTOR.structural
    assert (
        not TransformationFamily.LEXICAL.structural and not TransformationFamily.REPAIR.structural
    )


def test_reorder_is_structural_by_definition_not_by_threshold() -> None:
    candidate = _whole_sentence_reorder()
    assert 0.0 < candidate.structural_degree() < 1.0
    assert candidate.surface_degree() == 0.0
    assert candidate.is_structural and candidate.structural_families == (
        TransformationFamily.REORDER,
    )
    assert TransformationFamily.REORDER in STRUCTURAL_FAMILIES
    # La propietat és explícita: tota família no estructural té pes estructural 0, i
    # tota família estructural en té un de positiu.
    for family in TransformationFamily:
        assert family.structural == (family in STRUCTURAL_FAMILIES)
        assert (family.weight > 0) == family.structural


def test_subordination_is_structural() -> None:
    text = "La regla no funciona perquè el text és antic."
    candidate = Candidate.from_transformations(
        0,
        text,
        [_make(text, text[:-1], "Com que el text és antic, la regla no funciona", "subordinada")],
    )
    assert candidate.structural_degree() > 0.0
    assert TransformationFamily.SUBORDINATION.structural
    assert (
        TransformationFamily.CLAUSE_SPLIT.structural
        and TransformationFamily.COPULAR_MERGE.structural
    )


# --- 6-7: rendiments decreixents i diversitat ----------------------------------------------------


def test_repeated_transformations_of_a_family_have_diminishing_returns() -> None:
    text = "La norma és clara, segons Fabra, i el text és antic, segons Coromines."
    one = Candidate.from_transformations(
        0,
        text,
        [
            _make(
                text, "La norma és clara, segons Fabra", "Segons Fabra, la norma és clara", "ordre"
            )
        ],
    )
    two = Candidate.from_transformations(
        0,
        text,
        [
            _make(
                text, "La norma és clara, segons Fabra", "Segons Fabra, la norma és clara", "ordre"
            ),
            _make(
                text,
                "el text és antic, segons Coromines",
                "segons Coromines, el text és antic",
                "ordre",
            ),
        ],
    )
    assert one.structural_degree() < two.structural_degree() < 2 * one.structural_degree()
    scorer = CompositeScorer(ScoringWeights())
    verbal = _three_verbal()
    single = Candidate.from_transformations(0, VERBAL_SENTENCE, verbal.transformations[:1])
    assert scorer.transformation_gain(verbal.transformations) < 3 * scorer.transformation_gain(
        single.transformations
    )
    # Sense decaïment (family_gain_decay 1) el guany torna a ser lineal: el paràmetre mana.
    linear = CompositeScorer(ScoringWeights(family_gain_decay=1.0))
    assert linear.transformation_gain(verbal.transformations) == pytest.approx(
        3 * linear.transformation_gain(single.transformations)
    )


def test_a_safe_reorder_beats_three_verbal_retouches_only_in_deep_mode() -> None:
    """Test obligatori 2: B (una reordenació) ha de superar A (tres canvis verbals)."""
    verbal = _three_verbal()
    reorder = _whole_sentence_reorder()
    ctx = ScoringContext(ValidationResult.passed(), VERBAL_SENTENCE)
    deep = CompositeScorer(ScoringWeights(structure=DEEP.structure_gain))
    assert deep.score(reorder, ctx).total > deep.score(verbal, ctx).total
    conservative = CompositeScorer(ScoringWeights(structure=CONSERVATIVE.structure_gain))
    breakdown = conservative.score(reorder, ctx)
    assert "estructura" not in breakdown.components
    assert breakdown.total < deep.score(reorder, ctx).total
    assert deep.score(verbal, ctx).dimensions["grau_estructural"] == 0.0
    assert deep.score(reorder, ctx).dimensions["grau_superficial"] == 0.0


def test_family_diversity_weighs_more_than_surface_repetition() -> None:
    text = VERBAL_SENTENCE
    scorer = CompositeScorer(ScoringWeights())
    same = _three_verbal().transformations
    diverse = (
        same[0],
        _make(
            text, "; tanmateix,", ". Tanmateix,", "divisio", kind=TransformationType.SENTENCE_SPLIT
        ),
        _make(text, "cada vegada", "cada cop", "lexic", kind=TransformationType.LEXICAL),
    )
    assert scorer.transformation_gain(diverse) > scorer.transformation_gain(same)


def test_the_generator_keeps_structural_signatures_over_verbal_combinations() -> None:
    text = VERBAL_SENTENCE
    verbal = list(_three_verbal().transformations)
    reorder = _whole_sentence_reorder().transformations[0]
    split = _make(
        text, "; tanmateix,", ". Tanmateix,", "divisio", kind=TransformationType.SENTENCE_SPLIT
    )
    generator = CandidateGenerator(max_transformations=3, max_candidates=4, max_depth=1)
    candidates = generator.generate(0, text, [*verbal, split, reorder])
    signatures = {c.signature for c in candidates}
    assert "REORDER" in signatures and "CLAUSE_SPLIT" in signatures, signatures


# --- degradació estructural local ---------------------------------------------------------------


def test_consecutive_relatives_are_penalised_not_invalidated(
    catalan_analyzer: RuleBasedAnalyzer,
) -> None:
    original = (
        "Aquest context estava marcat per l'esperit de la Contrareforma, impulsada pel Concili "
        "de Trento, que va intensificar la vigilància."
    )
    scorer = CompositeScorer(
        ScoringWeights(structure=DEEP.structure_gain),
        degradation=StructuralDegradation(catalan_analyzer),
    )
    candidate = Candidate.from_transformations(
        0, original, [_make(original, ", impulsada", ", que fou impulsada", "subordinada")]
    )
    ctx = ScoringContext(ValidationResult.passed(), original)
    breakdown = scorer.score(candidate, ctx)
    assert breakdown.valid  # penalització, no invalidació
    assert breakdown.components["degradacio"] < 0
    assert breakdown.dimensions["qualitat_sintactica"] is not None
    assert breakdown.dimensions["qualitat_sintactica"] < 1.0
    assert any("relatives consecutives" in reason for reason in breakdown.degradation_reasons)
    # Sense penalització de degradació, el mateix candidat puntuaria més.
    plain = CompositeScorer(ScoringWeights(structure=DEEP.structure_gain)).score(candidate, ctx)
    assert breakdown.total < plain.total
    # Un canvi innocu no rep cap penalització.
    harmless = Candidate.from_transformations(
        0,
        original,
        [
            _make(
                original,
                "va intensificar",
                "intensificà",
                "verbal",
                kind=TransformationType.MORPHOLOGICAL,
            )
        ],
    )
    assert "degradacio" not in scorer.score(harmless, ctx).components


# --- subarbres movibles ---------------------------------------------------------------------------

MOVABLE = (
    "Aquesta prudència s’entén encara més si considerem que l’obra era dedicada i adreçada a "
    "Mateo Vázquez de Leca."
)


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


def test_movable_subtree_moves_a_clause_with_an_internal_completive(
    rule_set: RuleSet,
    catalan_analyzer: RuleBasedAnalyzer,
    morphology: CatalanMorphology,
    parser: SyntaxProvider,
) -> None:
    """Test obligatori 4: «si considerem que l’obra era...» es mou sencera."""
    rule = _sentence_rule(rule_set, "ordre.adverbial_final_a_inicial")
    ctx = _context(catalan_analyzer, MOVABLE, morphology=morphology, syntax=parser)
    produced = [t.apply(MOVABLE) for t in rule.propose(ctx)]
    assert produced, "cap proposta amb analitzador fiable"
    fronted = produced[0]
    assert fronted.startswith(
        "Si considerem que l’obra era dedicada i adreçada a Mateo Vázquez de Leca,"
    )
    assert fronted.endswith("aquesta prudència s’entén encara més.")
    assert "Mateo Vázquez de Leca" in fronted


class _Doubtful:
    """Analitzador que retorna arbres reals però marcats com a poc fiables."""

    available = True

    def __init__(self, provider: SyntaxProvider) -> None:
        self._provider = provider

    def parse(self, text: str) -> SentenceSyntax:
        return replace(
            self._provider.parse(text), confidence=SyntaxConfidence(False, ("prova de dubte",))
        )


def test_movable_subtree_needs_a_confident_parse(
    rule_set: RuleSet,
    catalan_analyzer: RuleBasedAnalyzer,
    morphology: CatalanMorphology,
    parser: SyntaxProvider,
) -> None:
    rule = _sentence_rule(rule_set, "ordre.adverbial_final_a_inicial")
    # Sense analitzador mana l'heurística conservadora: la completiva interna bloqueja.
    without = _context(catalan_analyzer, MOVABLE, morphology=morphology)
    assert list(rule.propose(without)) == []
    # Amb analitzador però amb un parse dubtós: tampoc (dubte → conservar l'original).
    doubtful = _context(catalan_analyzer, MOVABLE, morphology=morphology, syntax=_Doubtful(parser))
    assert list(rule.propose(doubtful)) == []
    # Una clàusula simple continua movent-se sense analitzador, com abans.
    simple = "La regla no funciona si el text és antic."
    plain = _context(catalan_analyzer, simple, morphology=morphology)
    assert [t.apply(simple) for t in rule.propose(plain)] == [
        "Si el text és antic, la regla no funciona."
    ]


def test_an_interposed_adjunct_of_the_verb_moves_to_the_front_only_with_the_parser(
    rule_set: RuleSet,
    catalan_analyzer: RuleBasedAnalyzer,
    morphology: CatalanMorphology,
    parser: SyntaxProvider,
) -> None:
    rule = _sentence_rule(rule_set, "ordre.complement_interposat_a_inicial")
    text = (
        "Aquest enfocament més genèric d'Alonso de Barros, en el text de les edicions "
        "madrilenyes, podria interpretar-se com una estratègia calculada."
    )
    with_parser = _context(catalan_analyzer, text, morphology=morphology, syntax=parser)
    produced = [t.apply(text) for t in rule.propose(with_parser)]
    assert produced == [
        "En el text de les edicions madrilenyes, aquest enfocament més genèric d'Alonso de "
        "Barros podria interpretar-se com una estratègia calculada."
    ]
    assert list(rule.propose(_context(catalan_analyzer, text, morphology=morphology))) == []
    # Un connector interposat no és cap complement circumstancial: no es toca aquí.
    connector = "Aquest enfocament, per tant, podria interpretar-se com una estratègia calculada."
    ctx = _context(catalan_analyzer, connector, morphology=morphology, syntax=parser)
    assert list(rule.propose(ctx)) == []


# --- cerca en feix: òptim local contra òptim global ----------------------------------------------


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
    structure: float = 0.0,
    level: int | None = 5,
) -> Pipeline:
    rule_set = RuleSet(RuleSetConfig(name="prova", max_semantic_risk=SemanticRisk.HIGH), rules, ())
    validators = build_validators(PipelineConfig(), paths, analyzer, lexicon, rule_set)
    return Pipeline(
        analyzer=analyzer,
        protector=default_protector(analyzer, lexicon=lexicon),
        rule_set=rule_set,
        validators=validators,
        scorer=CompositeScorer(ScoringWeights(structure=structure)),
        max_level=level,
        paragraph_beam_width=beam_width,
        sentence_candidates_for_paragraph=3,
    )


@pytest.fixture(scope="module")
def copular_fusion(rule_set: RuleSet) -> ParagraphRule:
    rule = rule_set.rule("fusio.copulativa")
    assert isinstance(rule, ParagraphRule)
    return rule


@pytest.fixture(scope="module")
def local_vs_global(
    paths: ProjectPaths,
    lexicon: ClosedClassLexicon,
    catalan_analyzer: RuleBasedAnalyzer,
    copular_fusion: ParagraphRule,
) -> ParaphraseResult:
    """A guanya localment; B, segon, permet una fusió copulativa amb la frase següent."""
    rule_a = _ConfRule("prova.a", "és antic", "resulta antic", 0.95)
    rule_b = _ConfRule("prova.b", "antic", "vell", 0.6, family="SYNTACTIC")
    pipeline = _pipeline(paths, lexicon, catalan_analyzer, (rule_a, rule_b, copular_fusion))
    assert pipeline.searches_paragraphs
    return pipeline.run("El text és antic. És valuós.")


def test_the_beam_keeps_a_locally_second_candidate(local_vs_global: ParaphraseResult) -> None:
    """Test obligatori 3 (primera part): B sobreviu fins a la fase de paràgraf."""
    sentence = local_vs_global.sentences[0]
    search = local_vs_global.paragraphs[0].search
    assert search is not None
    first = search.options[0]
    assert [o.reason for o in first][:2] == ["original", "millor local"]
    assert first[1].candidate.text == "El text resulta antic."  # A guanya localment
    assert any(o.candidate.text == "El text és vell." for o in first)  # B es conserva
    texts = [a.evaluated.candidate.text for a in search.alternatives]
    assert "El text és vell i valuós." in texts
    assert any("el paràgraf ha preferit" in note for note in sentence.notes)


def test_the_locally_second_candidate_wins_globally(local_vs_global: ParaphraseResult) -> None:
    """Test obligatori 3 (segona part): el paràgraf global amb B guanya."""
    assert local_vs_global.output_text == "El text és vell i valuós."
    search = local_vs_global.paragraphs[0].search
    assert search is not None
    assert search.winner.origin == "feix"
    assert search.winner.global_total > search.local_winner_total
    # Les frases queden remarcades d'acord amb la tria del paràgraf.
    assert local_vs_global.sentences[0].output_text == "El text és vell."
    assert local_vs_global.sentences[0].selected.candidate.text == "El text és vell."
    assert local_vs_global.paragraphs[0].applied_rule_ids == ("fusio.copulativa",)


def test_without_the_beam_the_local_winner_decides(
    paths: ProjectPaths,
    lexicon: ClosedClassLexicon,
    catalan_analyzer: RuleBasedAnalyzer,
    copular_fusion: ParagraphRule,
) -> None:
    rule_a = _ConfRule("prova.a", "és antic", "resulta antic", 0.95)
    rule_b = _ConfRule("prova.b", "antic", "vell", 0.6, family="SYNTACTIC")
    for level, width in ((5, 1), (4, 4)):
        pipeline = _pipeline(
            paths, lexicon, catalan_analyzer, (rule_a, rule_b, copular_fusion),
            beam_width=width, level=level,
        )  # fmt: skip
        assert not pipeline.searches_paragraphs
        result = pipeline.run("El text és antic. És valuós.")
        assert result.sentences[0].output_text == "El text resulta antic."
        assert all(p.search is None for p in result.paragraphs)


def test_protected_fragments_survive_the_beam(
    paths: ProjectPaths,
    lexicon: ClosedClassLexicon,
    catalan_analyzer: RuleBasedAnalyzer,
    copular_fusion: ParagraphRule,
) -> None:
    rule = _ConfRule("prova.b", "antic", "vell", 0.8, family="SYNTACTIC")
    pipeline = _pipeline(paths, lexicon, catalan_analyzer, (rule, copular_fusion))
    result = pipeline.run("El tractat de Ramon Llull de 1274 és antic. És valuós.")
    assert "Ramon Llull" in result.output_text and "1274" in result.output_text
    for paragraph in result.paragraphs:
        for evaluated in paragraph.candidates:
            if evaluated.accepted:
                assert (
                    "1274" in evaluated.candidate.text and "Ramon Llull" in evaluated.candidate.text
                )


def test_epistemic_preservation_still_invalidates_inside_the_beam(
    paths: ProjectPaths,
    lexicon: ClosedClassLexicon,
    catalan_analyzer: RuleBasedAnalyzer,
    copular_fusion: ParagraphRule,
) -> None:
    certain = _ConfRule("prova.certesa", "podria ser antic", "és antic", 0.95, family="SYNTACTIC")
    pipeline = _pipeline(paths, lexicon, catalan_analyzer, (certain, copular_fusion))
    result = pipeline.run("El text podria ser antic. És valuós.")
    assert "podria ser antic" in result.output_text
    rejected = [e for e in result.sentences[0].candidates if not e.accepted]
    assert rejected and all("podria" not in e.candidate.text for e in rejected)
    search = result.paragraphs[0].search
    assert search is not None
    assert all(a.valid for a in search.alternatives)
    assert all("podria" in a.evaluated.candidate.text for a in search.alternatives)


# --- configuració i modes ---------------------------------------------------------------------


def test_deep_mode_activates_the_beam_only_at_level_five(project_root: Path) -> None:
    config = PipelineConfig(home=project_root, rule_set="parafrasi")
    assert (
        apply_mode(config, RewriteMode.DEEP, 5).paragraph_beam_width
        == DEEP.paragraph_beam_width
        > 1
    )
    assert apply_mode(config, RewriteMode.DEEP, 4).paragraph_beam_width == 1
    assert apply_mode(config, RewriteMode.CONSERVATIVE, 5).paragraph_beam_width == 1
    assert DEEP.to_dict()["paragraph_beam_width"] == DEEP.paragraph_beam_width
    assert CONSERVATIVE.to_dict()["paragraph_beam_width"] == 1


def test_beam_settings_round_trip_through_the_configuration() -> None:
    config = PipelineConfig.from_mapping(
        {"paragraph_beam_width": 5, "sentence_candidates_for_paragraph": 2}
    )
    assert config.paragraph_beam_width == 5 and config.sentence_candidates_for_paragraph == 2
    data = config.to_dict()
    assert data["paragraph_beam_width"] == 5 and data["sentence_candidates_for_paragraph"] == 2
    weights = ScoringWeights.from_mapping({"family_gain_decay": 0.3, "degradation": 0.2})
    assert weights.family_gain_decay == 0.3 and weights.to_dict()["degradation"] == 0.2
    with pytest.raises(Exception, match="cerca de paràgraf"):
        PipelineConfig(paragraph_beam_width=0)
    with pytest.raises(Exception, match="family_gain_decay"):
        ScoringWeights(family_gain_decay=1.5)


def test_degrees_are_reported_in_results_and_api(local_vs_global: ParaphraseResult) -> None:
    candidate = local_vs_global.sentences[0].selected.candidate.to_dict()
    assert {"structural_degree", "surface_degree", "structural_families"} <= set(candidate)
    paragraph = local_vs_global.paragraphs[0].to_dict()
    assert paragraph["search"] is not None
    search = paragraph["search"]
    assert isinstance(search, dict) and {"options", "alternatives", "pruned", "explored"} <= set(
        search
    )
    assert "Cerca d'arquitectures" in local_vs_global.report()


# --- el paràgraf real ------------------------------------------------------------------------


def test_the_real_paragraph_gets_structural_rewriting(deep_real: ParaphraseResult) -> None:
    output = deep_real.output_text
    # 1. Noms, dates, xifres, romans i fragments protegits intactes.
    for fragment in PROTECTED_FRAGMENTS:
        assert output.count(fragment) == REAL_TEXT.count(fragment), fragment
    # 2-4. Força epistemològica: cap hipòtesi no esdevé certesa.
    for hedge in HEDGES:
        assert hedge in output, hedge
    for certainty in CERTAINTIES:
        assert certainty not in output.casefold()
    # 5-6. El resultat no és només simple ↔ perifràstic, puntuació o connectors: hi ha
    # almenys una família realment estructural entre les transformacions aplicades.
    families = {t.family for t in deep_real.transformations}
    assert families & STRUCTURAL_FAMILIES, families
    assert not families <= SURFACE
    # 7. Tres canvis VERBAL no donen cap grau estructural.
    verbal_only = [
        e.candidate
        for s in deep_real.sentences
        for e in s.candidates
        if e.candidate.n_transformations >= 2
        and set(e.candidate.families) == {TransformationFamily.VERBAL}
    ]
    assert verbal_only, "cap candidat només verbal amb dues o més transformacions"
    assert all(c.structural_degree() == 0.0 for c in verbal_only)
    # 8. El feix conserva alternatives locals i compara arquitectures completes.
    search = deep_real.paragraphs[0].search
    assert search is not None
    assert any(len(group) > 2 for group in search.options)
    assert search.explored >= len(search.alternatives) >= 3
    assert search.winner.valid
    # 9. Cap premi artificial a «que fou impulsada..., que intensificà».
    assert ", que fou impulsada" not in output and ", que va ser impulsada" not in output
    # 10. Reredacció material sense cap distància arbitrària: el text canvia de debò.
    assert output != REAL_TEXT
    changed = [s for s in deep_real.sentences if s.output_text != s.source_text]
    assert len(changed) >= 2


def test_the_real_paragraph_stays_prudent_in_conservative_mode(
    conservative_real: ParaphraseResult,
) -> None:
    output = conservative_real.output_text
    assert conservative_real.paragraphs == ()
    for fragment in PROTECTED_FRAGMENTS:
        assert output.count(fragment) == REAL_TEXT.count(fragment), fragment
    for hedge in HEDGES:
        assert hedge in output
    for sentence in conservative_real.sentences:
        selected = sentence.selected.candidate
        assert selected.n_transformations <= 1
        for t in selected.transformations:
            assert t.semantic_risk is SemanticRisk.LOW and t.confidence >= 0.75
            assert not t.family.cross_sentence
