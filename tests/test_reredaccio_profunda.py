"""Correcció 1.3.1: evidència verbal general i reredacció profunda real.

Dos problemes detectats en una prova real:

1. «però ja no sobirà» es va transformar en «però ja no va sobirar»: la regla
   del passat perifràstic prenia qualsevol forma en «-à» precedida de «no» per
   un verb. Ara només transforma amb evidència morfosintàctica suficient, i la
   validació per classe de transformació bloqueja qualsevol verb inventat.
2. El mode profund tornava massa sovint l'original o canvis mínims. Ara hi ha
   famílies sintàctiques generals guiades pel parser, signatures estructurals,
   deduplicació i un grau de reredacció que, entre candidats igualment segurs,
   dona avantatge a la reestructuració real.

Els tests que necessiten el recurs morfològic o el parser se salten si no hi
són; els que comproven que mai no apareix un verb inventat passen en tots els
modes, també sense recursos.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from difflib import SequenceMatcher
from pathlib import Path

import pytest

from parafrasi_cat.analyzer.analysis import RuleBasedAnalyzer
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon
from parafrasi_cat.candidates import Candidate, CandidateGenerator
from parafrasi_cat.core import SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.core.transformation import TransformationFamily
from parafrasi_cat.morphology.catalan import CatalanMorphology
from parafrasi_cat.morphology.provider import MorphologyProvider, NullMorphology
from parafrasi_cat.morphology.registry import create_morphology_provider
from parafrasi_cat.morphology.verbal import Verdict, lexical_readings
from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.config import PipelineConfig
from parafrasi_cat.pipeline.modes import CONSERVATIVE, DEEP, RewriteMode, apply_mode
from parafrasi_cat.pipeline.result import ParaphraseResult
from parafrasi_cat.protected.protector import Protector, default_protector
from parafrasi_cat.resources import ProjectPaths, as_mapping
from parafrasi_cat.rules import RuleSet, RuleSetConfig, build_rule_set, default_registry
from parafrasi_cat.rules.base import Rule, RuleContext
from parafrasi_cat.rules.definition import RuleDefinition
from parafrasi_cat.rules.registry import _Hints
from parafrasi_cat.rules.verbal import PeriphrasticPastRule, load_irregular_pasts
from parafrasi_cat.scoring.scorer import CompositeScorer, ScoringContext
from parafrasi_cat.scoring.weights import ScoringWeights
from parafrasi_cat.syntax.analysis import CachedSyntax, NullSyntax, SyntaxProvider
from parafrasi_cat.syntax.spacy_parser import SpacySyntax
from parafrasi_cat.validation.base import ValidationContext
from parafrasi_cat.validation.result import ValidationResult
from parafrasi_cat.validation.verbal import VerbalTransformationValidator

REAL_TEXT = (
    "Hi ha peces dels escacs que semblen haver conservat el seu nom perquè la seva funció era "
    "clara. El rei no necessita gaire justificació: és el centre del tauler i el centre del "
    "regne. La reina, quan apareix o quan es consolida, tampoc no necessita una explicació "
    "excessiva: ocupa el lloc immediat del poder domèstic, dinàstic i polític al costat del "
    "rei. El cavaller és reconeixible perquè el cavall, l’armament i la funció militar el fan "
    "transparent. El roc, encara que tingui un nom menys evident, pot ser assimilat a la funció "
    "de veguer, oficial o executor de la força reial. Però hi ha una peça que no encaixa tan "
    "fàcilment: l’orfil.\n\n"
    "La lectura tradicional ha volgut fer derivar aquesta peça de l’alfil oriental i, a partir "
    "d’aquí, explicar-la per l’elefant. Aquesta explicació pot tenir algun valor remot per a "
    "una capa oriental del nom, però no resol el problema occidental. No explica per què, en la "
    "tradició moralitzada de Cessolis, l’orfil no és tractat com un animal, sinó com un jutge. "
    "Tampoc explica per què en català antic pot aparèixer una frase com “don Johan, que volia "
    "esser Rey e ara és arfil”, on el contrast no pot ser entre rei i elefant, sinó entre "
    "sobirania i una funció subordinada. La frase només té sentit si arfil designa una "
    "categoria política: un home pròxim al rei, útil al poder, però ja no sobirà.\n\n"
    "La qüestió, per tant, no és només etimològica. És institucional. L’orfil sembla néixer, "
    "o almenys fixar-se, en el moment en què el tauler necessita donar un lloc nou a una figura "
    "que ha perdut el seu encaix dins la jerarquia feudal."
)
QUOTED = "“don Johan, que volia esser Rey e ara és arfil”"
#: Marcadors epistemològics que cap candidat no pot perdre ni endurir.
EPISTEMIC_MARKERS = ("pot tenir", "sembla", "almenys", "no resol", "no explica")

#: Predicatius nominals o adjectivals darrere d'una negació: mai un verb.
ELLIPTICAL = (
    ("Era un home poderós, però ja no sobirà.", "sobirà"),
    ("Continuava essent comte, però ja no rei.", "rei"),
    ("Era útil al monarca, però no independent.", "independent"),
    ("Va convidar el pare, però no el germà.", "germà"),
    ("El sofà és al menjador i el català és una llengua.", "sofà"),
)

STRUCTURAL = {
    TransformationFamily.REORDER,
    TransformationFamily.SUBORDINATION,
    TransformationFamily.COPULAR,
    TransformationFamily.IMPERSONAL,
    TransformationFamily.CLAUSE_SPLIT,
    TransformationFamily.CLAUSE_MERGE,
    TransformationFamily.COPULAR_MERGE,
}


# --- recursos --------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lexicon(paths: ProjectPaths) -> ClosedClassLexicon:
    return ClosedClassLexicon.load(paths.language())


@pytest.fixture(scope="module")
def analyzer(lexicon: ClosedClassLexicon) -> RuleBasedAnalyzer:
    return RuleBasedAnalyzer(lexicon=lexicon)


@pytest.fixture(scope="module")
def morphology(paths: ProjectPaths, lexicon: ClosedClassLexicon) -> CatalanMorphology:
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
def periphrastic(paths: ProjectPaths, lexicon: ClosedClassLexicon) -> PeriphrasticPastRule:
    irregulars = load_irregular_pasts(
        paths.language() / "transformations" / "passat_simple_irregular.yaml"
    )
    definition = RuleDefinition.from_mapping(
        {"rule_id": "verbal.simple_a_perifrastic", "engine": "periphrastic_past",
         "category": "verbal", "level": 3}
    )  # fmt: skip
    return PeriphrasticPastRule(
        definition,
        irregulars,
        direction="to_periphrastic",
        hints=_Hints.for_paths(paths).for_lexicon(lexicon),
    )


def _context(
    analyzer: RuleBasedAnalyzer,
    text: str,
    *,
    morphology: MorphologyProvider | None = None,
    syntax: SyntaxProvider | None = None,
) -> RuleContext:
    protector = default_protector(analyzer)
    sentence = analyzer.analyze(text).sentences[0]
    provider = syntax if syntax is not None else NullSyntax()
    return RuleContext(
        sentence=sentence,
        protected_spans=Protector.within(protector.protect(text), sentence.span),
        document_text=text,
        morphology=morphology if morphology is not None else NullMorphology(),
        lexicon=analyzer.lexicon,
        syntax=provider,
        analysis=provider.parse(sentence.text) if provider.available else None,
    )


def _outputs(rule: PeriphrasticPastRule, ctx: RuleContext) -> list[str]:
    return [t.apply(ctx.text) for t in rule.propose(ctx)]


# --- problema 2: «sobirà» → «va sobirar» ----------------------------------------------------


@pytest.mark.parametrize(("text", "word"), ELLIPTICAL)
def test_a_predicative_after_a_negation_is_never_a_verb_in_basic_mode(
    periphrastic: PeriphrasticPastRule, analyzer: RuleBasedAnalyzer, text: str, word: str
) -> None:
    """Sense cap recurs, la negació sola no és evidència: es conserva l'original."""
    ctx = _context(analyzer, text)
    assert _outputs(periphrastic, ctx) == []
    assert not any(f"va {word}" in t.text_after for t in periphrastic.propose(ctx))


@pytest.mark.parametrize(("text", "word"), ELLIPTICAL)
def test_a_predicative_after_a_negation_is_never_a_verb_with_resources(
    periphrastic: PeriphrasticPastRule,
    analyzer: RuleBasedAnalyzer,
    morphology: CatalanMorphology,
    parser: SyntaxProvider,
    text: str,
    word: str,
) -> None:
    ctx = _context(analyzer, text, morphology=morphology, syntax=parser)
    assert _outputs(periphrastic, ctx) == []
    tokens = tuple(ctx.sentence.tokens)
    index = next(i for i, t in enumerate(tokens) if t.text == word)
    evidence = periphrastic.evidence(ctx, tokens, index, set(), ctx.analysis)
    if word.endswith(("à", "í")):
        # S'assembla a un passat simple: la morfologia és qui el descarta.
        assert evidence is not None and evidence.verdict is Verdict.NOT_VERB
        assert "morfologia" in evidence.sources
    else:
        assert evidence is None  # ni tan sols s'assembla a un passat simple


def test_the_real_sentence_explains_why_sobira_is_not_transformed(
    periphrastic: PeriphrasticPastRule,
    analyzer: RuleBasedAnalyzer,
    morphology: CatalanMorphology,
    parser: SyntaxProvider,
) -> None:
    text = (
        "La frase només té sentit si arfil designa una categoria política: un home pròxim al "
        "rei, útil al poder, però ja no sobirà."
    )
    ctx = _context(analyzer, text, morphology=morphology, syntax=parser)
    assert _outputs(periphrastic, ctx) == []
    # El parser etiqueta «sobirà» com a verb: per això el descart s'explica.
    assert any("sobirà" in note and "morfologia" in note for note in ctx.notes)


def test_the_guesser_never_counts_as_lexical_evidence(
    paths: ProjectPaths, lexicon: ClosedClassLexicon
) -> None:
    internal = create_morphology_provider("internal", paths.language(), lexicon=lexicon)
    assert lexical_readings(internal, "sobirà").known is False
    assert lexical_readings(internal, "fou").only_past_verb


def test_the_dictionary_resolves_the_readings(morphology: CatalanMorphology) -> None:
    assert lexical_readings(morphology, "sobirà").known
    assert not lexical_readings(morphology, "sobirà").past_verb
    assert lexical_readings(morphology, "cantà").only_past_verb
    assert lexical_readings(morphology, "pagà").ambiguous
    assert lexical_readings(morphology, "cantarà").other_verb


# --- el passat simple real continua funcionant --------------------------------------------


def test_real_past_simple_forms_are_still_transformed(
    periphrastic: PeriphrasticPastRule, analyzer: RuleBasedAnalyzer
) -> None:
    """Sense recursos: irregulars, terminacions de plural i singular amb pronom segur."""
    assert _outputs(periphrastic, _context(analyzer, "El monument fou encarregat el 1507.")) == [
        "El monument va ser encarregat el 1507."
    ]
    assert _outputs(periphrastic, _context(analyzer, "Els mestres finalitzaren l'obra.")) == [
        "Els mestres van finalitzar l'obra."
    ]
    assert _outputs(periphrastic, _context(analyzer, "El consell es reuní i ho decidí.")) == [
        "El consell es va reunir i ho decidí.",
        "El consell es reuní i ho va decidir.",
    ]
    # Un futur amb un pronom al davant no és cap passat simple.
    assert _outputs(periphrastic, _context(analyzer, "No ho cantarà mai.")) == []


def test_real_past_simple_forms_with_the_dictionary(
    periphrastic: PeriphrasticPastRule,
    analyzer: RuleBasedAnalyzer,
    morphology: CatalanMorphology,
    parser: SyntaxProvider,
) -> None:
    ctx = _context(analyzer, "El poble cantà l'himne.", morphology=morphology, syntax=parser)
    proposals = list(periphrastic.propose(ctx))
    assert [t.text_after for t in proposals] == ["va cantar"]
    assert proposals[0].metadata["verbal_change"] == "simple_a_perifrastic"
    assert "morfologia" in proposals[0].metadata["evidence"]
    assert proposals[0].family is TransformationFamily.VERBAL
    ctx = _context(
        analyzer, "Els diputats aprovaren la llei.", morphology=morphology, syntax=parser
    )
    assert _outputs(periphrastic, ctx) == ["Els diputats van aprovar la llei."]


def test_parser_disagreement_lowers_the_confidence_but_the_dictionary_decides(
    periphrastic: PeriphrasticPastRule,
    analyzer: RuleBasedAnalyzer,
    morphology: CatalanMorphology,
    parser: SyntaxProvider,
) -> None:
    """«arribà» només pot ser un verb de passat; si el parser el pren per adjectiu,
    la transformació es manté amb menys confiança (el mode conservador la descarta)."""
    text = "El poble cantà l'himne i el rei arribà tard."
    ctx = _context(analyzer, text, morphology=morphology, syntax=parser)
    proposals = {t.text_before: t for t in periphrastic.propose(ctx)}
    assert set(proposals) == {"cantà", "arribà"}
    assert all(t.confidence <= 0.7 for t in proposals.values())
    disagreed = [t for t in proposals.values() if t.confidence < 0.7]
    assert CONSERVATIVE.min_confidence is not None
    for t in disagreed:
        assert t.confidence < CONSERVATIVE.min_confidence


# --- validació per classe de transformació ---------------------------------------------


def _verbal_candidate(text: str, before: str, after: str, change: str) -> Candidate:
    start = text.index(before)
    transformation = Transformation(
        "verbal.simple_a_perifrastic",
        before,
        after,
        Span(start, start + len(before)),
        TransformationType.MORPHOLOGICAL,
        0.7,
        SemanticRisk.LOW,
        "prova",
        {"category": "verbal", "verbal_change": change},
    )
    return Candidate.from_transformations(0, text, [transformation])


def test_the_verbal_validator_blocks_an_invented_verb(morphology: CatalanMorphology) -> None:
    validator = VerbalTransformationValidator(morphology)
    text = "Era un home poderós, però ja no sobirà."
    bad = _verbal_candidate(text, "sobirà", "va sobirar", "simple_a_perifrastic")
    result = validator.validate(bad, ValidationContext(text))
    assert not result.ok
    assert "sobirar" in result.summary and "no és un verb de passat" in result.summary
    good = _verbal_candidate(
        "El poble cantà l'himne.", "cantà", "va cantar", "simple_a_perifrastic"
    )
    assert validator.validate(good, ValidationContext("El poble cantà l'himne.")).ok
    reverse = _verbal_candidate(
        "El rei va sobirar el país.", "va sobirar", "sobirà", "perifrastic_a_simple"
    )
    assert not validator.validate(reverse, ValidationContext("El rei va sobirar el país.")).ok


def test_the_pipeline_never_produces_va_sobirar(project_root: Path) -> None:
    """En cap mode ni nivell, amb els recursos que hi hagi."""
    config = PipelineConfig(home=project_root, rule_set="parafrasi")
    for mode in (RewriteMode.CONSERVATIVE, RewriteMode.DEEP):
        result = build_pipeline(apply_mode(config, mode, 5)).run(
            "Era un home poderós, però ja no sobirà. Continuava essent comte, però ja no rei."
        )
        for sentence in result.sentences:
            for evaluated in sentence.candidates:
                assert "va sobirar" not in evaluated.candidate.text
                assert "va reir" not in evaluated.candidate.text


# --- mode profund: text real ----------------------------------------------------------------


@pytest.fixture(scope="module")
def deep_result(
    project_root: Path, morphology: CatalanMorphology, parser: SyntaxProvider
) -> ParaphraseResult:
    config = apply_mode(
        PipelineConfig(home=project_root, rule_set="parafrasi"), RewriteMode.DEEP, 5
    )
    pipeline = build_pipeline(config)
    assert pipeline.syntax.available
    return pipeline.run(REAL_TEXT)


def _all_candidate_texts(result: ParaphraseResult) -> Iterator[str]:
    for unit in (*result.sentences, *result.paragraphs):
        for evaluated in unit.candidates:
            yield evaluated.candidate.text


def test_real_text_never_turns_sobira_into_a_verb(deep_result: ParaphraseResult) -> None:
    assert "va sobirar" not in deep_result.output_text
    assert all("va sobirar" not in text for text in _all_candidate_texts(deep_result))
    sentence = next(s for s in deep_result.sentences if "ja no sobirà" in s.source_text)
    assert "ja no sobirà" in sentence.output_text
    assert any("sobirà" in note for note in sentence.notes), sentence.notes


def test_real_text_keeps_the_quotation_intact(deep_result: ParaphraseResult) -> None:
    assert QUOTED in deep_result.output_text
    assert all(QUOTED in text for text in _all_candidate_texts(deep_result) if "arfil”" in text)


def test_real_text_keeps_the_epistemic_force(deep_result: ParaphraseResult) -> None:
    output = deep_result.output_text.casefold()
    for marker in EPISTEMIC_MARKERS:
        assert marker in output, marker
    for forbidden in ("demostra", "confirma", "és evident", "sens dubte", "certament"):
        assert forbidden not in output


def test_real_text_gets_a_real_syntactic_alternative(deep_result: ParaphraseResult) -> None:
    structural = [
        evaluated
        for unit in (*deep_result.sentences, *deep_result.paragraphs)
        for evaluated in unit.candidates
        if evaluated.accepted and STRUCTURAL & set(evaluated.candidate.families)
    ]
    assert structural, "cap candidat amb una transformació sintàctica real"
    # I el motor n'ha triat almenys una: el resultat no és pràcticament idèntic.
    chosen = [
        unit.selected.candidate
        for unit in (*deep_result.sentences, *deep_result.paragraphs)
        if STRUCTURAL & set(unit.selected.candidate.families)
    ]
    assert chosen


def test_real_text_last_paragraph_is_restructured(deep_result: ParaphraseResult) -> None:
    """«…no és només etimològica. És institucional.» → «…, sinó també institucional.»."""
    paragraph = deep_result.paragraphs[-1]
    considered = {c.candidate.text for c in paragraph.candidates}
    assert any("sinó també institucional" in text for text in considered), considered
    assert "sinó també institucional" in paragraph.output_text
    assert paragraph.output_text != paragraph.source_text
    # Amb els canvis de frase i de paràgraf junts, el resultat no és pràcticament
    # idèntic a l'original.
    ratio = SequenceMatcher(a=paragraph.source_text, b=paragraph.output_text).ratio()
    assert ratio < 0.95, paragraph.output_text


def test_real_text_reports_signatures_and_evidence(deep_result: ParaphraseResult) -> None:
    summary = deep_result.paragraphs[-1].summary()
    assert summary["signature"] in {"COPULAR_MERGE", "MULTI_TRANSFORM(COPULAR_MERGE+REORDER)"}
    applied = summary["applied_rules"]
    assert isinstance(applied, list) and all("family" in rule for rule in applied)
    sentences = deep_result.to_dict()["sentences"]
    assert isinstance(sentences, list)
    sentence = next(s for s in sentences if "ja no sobirà" in s["source_text"])
    assert any("sobirà" in note for note in sentence["notes"])


# --- famílies, signatures i diversitat ----------------------------------------------------


def _make(
    before: str, after: str, start: int, rule_id: str, family: str, confidence: float = 0.8
) -> Transformation:
    return Transformation(
        rule_id=rule_id,
        text_before=before,
        text_after=after,
        changed_span=Span(start, start + len(before)),
        transformation_type=TransformationType.SYNTACTIC,
        confidence=confidence,
        semantic_risk=SemanticRisk.LOW,
        explanation=f"{before}→{after}",
        metadata={"family": family},
    )


def test_families_signatures_and_structural_degree() -> None:
    text = "gairebé sempre plou i sovint neva"
    lexical = _make("gairebé", "quasi", 0, "a", "LEXICAL", 0.9)
    reorder = _make("sovint neva", "neva sovint", 22, "b", "REORDER", 0.7)
    single = Candidate.from_transformations(0, text, [lexical])
    combined = Candidate.from_transformations(0, text, [lexical, reorder])
    assert Candidate.identity(0, text).signature == "ORIGINAL"
    assert single.signature == "LEXICAL" and not single.is_structural
    assert combined.signature == "MULTI_TRANSFORM(LEXICAL+REORDER)" and combined.is_structural
    assert single.structural_degree() < combined.structural_degree() <= 1.0
    assert TransformationFamily.CONNECTOR.weight < TransformationFamily.REORDER.weight
    assert TransformationFamily.REORDER.weight < TransformationFamily.COPULAR_MERGE.weight
    assert TransformationFamily.REPAIR.weight == 0.0
    assert TransformationFamily.CLAUSE_SPLIT.cross_sentence


def test_families_derive_from_the_rule_category() -> None:
    def build(**metadata: str) -> Transformation:
        return Transformation(
            rule_id="r",
            text_before="x",
            text_after="y",
            changed_span=Span(0, 1),
            transformation_type=TransformationType.SYNTACTIC,
            confidence=0.7,
            semantic_risk=SemanticRisk.LOW,
            explanation="e",
            metadata=metadata,
        )

    family = TransformationFamily
    assert build(category="ordre").family is family.REORDER
    assert build(category="divisio").family is family.CLAUSE_SPLIT
    assert build().family is family.SYNTACTIC
    assert build(family="IMPERSONAL").family is family.IMPERSONAL


def test_the_generator_keeps_one_candidate_per_signature() -> None:
    text = "gairebé sempre plou i sovint neva i de vegades pedrega"
    lexical = [
        _make("gairebé", "quasi", 0, "l1", "LEXICAL", 0.95),
        _make("sempre", "tothora", 8, "l2", "LEXICAL", 0.95),
        _make("sovint", "freqüentment", 22, "l3", "LEXICAL", 0.95),
    ]
    reorder = _make("de vegades pedrega", "pedrega de vegades", 36, "r", "REORDER", 0.6)
    generator = CandidateGenerator(max_transformations=2, max_candidates=4, max_depth=1)
    candidates = generator.generate(0, text, [*lexical, reorder])
    assert len(candidates) == 4
    assert candidates[0].is_identity
    signatures = {c.signature for c in candidates}
    assert "REORDER" in signatures, signatures
    assert "MULTI_TRANSFORM(LEXICAL+REORDER)" in signatures


def test_near_identical_candidates_are_dropped() -> None:
    """Dos textos que només difereixen en espais davant de puntuació són el mateix."""
    text = "Plou molt, i sortirem."
    spaced = _make("molt,", "molt ,", 5, "a", "PUNCTUATION")
    real = _make("sortirem", "marxarem", 13, "b", "LEXICAL")
    candidates = CandidateGenerator(max_depth=1).generate(0, text, [spaced, real])
    texts = [c.text for c in candidates]
    assert texts == [text, "Plou molt, i marxarem."]
    assert Candidate.identity(0, "Plou molt , i").normalized_text() == "Plou molt, i"


# --- puntuació del mode profund -----------------------------------------------------------

HEAD = "La qüestió, per tant,"
MOVED = "Per tant, la qüestió"


def _scored(
    weights: ScoringWeights, candidate: Candidate, validation: ValidationResult | None = None
) -> float:
    ctx = ScoringContext(validation, candidate.source_text)
    return CompositeScorer(weights).score(candidate, ctx).total


def test_structure_gives_the_advantage_only_in_deep_mode() -> None:
    text = "La qüestió, per tant, no és només etimològica."
    connector = Candidate.from_transformations(
        0, text, [_make("per tant", "així doncs", 12, "c", "CONNECTOR", 0.75)]
    )
    reorder = Candidate.from_transformations(0, text, [_make(HEAD, MOVED, 0, "r", "REORDER", 0.7)])
    conservative = ScoringWeights(structure=CONSERVATIVE.structure_gain)
    deep = ScoringWeights(structure=DEEP.structure_gain)
    assert CONSERVATIVE.structure_gain == 0.0 and DEEP.structure_gain > 0.0
    # Sense pes estructural, la confiança mana (el connector, més segur, guanya).
    assert _scored(conservative, connector) > _scored(conservative, reorder)
    # Amb pes estructural, la reredacció sintàctica real té avantatge.
    assert _scored(deep, reorder) > _scored(deep, connector)
    assert _scored(deep, reorder) > _scored(deep, Candidate.identity(0, text))


def test_structure_never_rescues_an_invalid_candidate() -> None:
    from parafrasi_cat.validation.result import ValidationDimension

    text = "La qüestió, per tant, no és només etimològica."
    reorder = Candidate.from_transformations(0, text, [_make(HEAD, MOVED, 0, "r", "REORDER", 0.9)])
    failed = ValidationResult.error("factual", "s'ha perdut una dada", ValidationDimension.FACTUAL)
    breakdown = CompositeScorer(ScoringWeights(structure=5.0)).score(
        reorder, ScoringContext(failed, text)
    )
    assert not breakdown.valid and breakdown.total == -1.0
    degree = breakdown.dimensions["grau_estructural"]
    assert degree is not None and degree > 0


def test_structure_is_scaled_by_grammaticality() -> None:
    from parafrasi_cat.validation.result import ValidationDimension

    text = "La qüestió, per tant, no és només etimològica."
    reorder = Candidate.from_transformations(0, text, [_make(HEAD, MOVED, 0, "r", "REORDER", 0.9)])
    clean = _scored(ScoringWeights(structure=0.35), reorder, ValidationResult.passed())
    warned = _scored(
        ScoringWeights(structure=0.35),
        reorder,
        ValidationResult.warning("grammar", "espais dobles", ValidationDimension.GRAMMAR),
    )
    assert warned < clean


def test_the_deep_mode_sets_the_structural_weight(project_root: Path) -> None:
    config = PipelineConfig(home=project_root, rule_set="parafrasi")
    assert apply_mode(config, RewriteMode.DEEP, 5).scoring.structure == DEEP.structure_gain
    assert apply_mode(config, RewriteMode.CONSERVATIVE, 3).scoring.structure == 0.0
    assert DEEP.to_dict()["structure_gain"] == DEEP.structure_gain


# --- famílies sintàctiques noves ------------------------------------------------------------


@pytest.fixture(scope="module")
def rule_set(paths: ProjectPaths) -> RuleSet:
    return build_rule_set(
        RuleSetConfig.load(paths.rules / "parafrasi.yaml"), default_registry(), paths
    )


def _sentence_rule(rule_set: RuleSet, rule_id: str) -> Rule:
    rule = rule_set.rule(rule_id)
    assert isinstance(rule, Rule), rule_id
    return rule


def test_new_families_are_declared_with_examples(rule_set: RuleSet) -> None:
    ids = set(rule_set.rule_ids)
    for rule_id in (
        "ordre.adverbial_interposada_a_inicial",
        "ordre.adverbial_final_a_inicial",
        "ordre.adverbial_inicial_a_final",
        "ordre.connector_medial_a_inicial",
        "ordre.connector_inicial_a_medial",
        "subordinada.causal_final_a_inicial",
        "subordinada.causal_inicial_a_final",
        "subordinada.relativa_copulativa_a_aposicio",
        "impersonal.es_a_hom",
        "fusio.copulativa",
    ):
        assert rule_id in ids, rule_id
    assert {r.level for r in rule_set.paragraph_rules} == {5}


def test_parser_only_rules_apply_with_the_parser(
    rule_set: RuleSet,
    analyzer: RuleBasedAnalyzer,
    morphology: CatalanMorphology,
    parser: SyntaxProvider,
) -> None:
    """Els exemples de les regles que exigeixen l'analitzador, comprovats amb ell."""
    for definition in rule_set.definitions:
        if as_mapping(definition.conditions, "syntax").get("requires_parser") is not True:
            continue
        rule = _sentence_rule(rule_set, definition.rule_id)
        for example in definition.examples:
            ctx = _context(analyzer, example.input, morphology=morphology, syntax=parser)
            produced = [t.apply(ctx.text) for t in rule.propose(ctx)]
            if example.output is None:
                assert produced == [], (definition.rule_id, example.input, produced)
            else:
                assert example.output in produced, (definition.rule_id, example.input, produced)


def test_structural_rules_use_the_parser_on_the_real_sentences(
    rule_set: RuleSet,
    analyzer: RuleBasedAnalyzer,
    morphology: CatalanMorphology,
    parser: SyntaxProvider,
) -> None:
    cases = {
        "El roc, encara que tingui un nom menys evident, pot ser assimilat a la funció de "
        "veguer, oficial o executor de la força reial.": (
            "ordre.adverbial_interposada_a_inicial",
            "Encara que tingui un nom menys evident, el roc pot ser assimilat",
        ),
        "Aquesta explicació pot tenir algun valor remot per a una capa oriental del nom, però "
        "no resol el problema occidental.": (
            "divisio.coordinada_pero",
            "del nom. Tanmateix, no resol el problema occidental.",
        ),
        "La qüestió, per tant, no és només etimològica.": (
            "ordre.connector_medial_a_inicial",
            "Per tant, la qüestió no és només etimològica.",
        ),
        "La regla no funciona perquè el text és antic.": (
            "subordinada.causal_final_a_inicial",
            "Com que el text és antic, la regla no funciona.",
        ),
    }
    for text, (rule_id, expected) in cases.items():
        ctx = _context(analyzer, text, morphology=morphology, syntax=parser)
        produced = [t.apply(ctx.text) for t in _sentence_rule(rule_set, rule_id).propose(ctx)]
        assert any(expected in p for p in produced), (rule_id, produced)
    # Un pronom feble dins de la subordinada la deixa on és: no pot precedir l'antecedent.
    text = (
        "El cavaller és reconeixible perquè el cavall, l’armament i la funció militar el fan "
        "transparent."
    )
    ctx = _context(analyzer, text, morphology=morphology, syntax=parser)
    causal = _sentence_rule(rule_set, "subordinada.causal_final_a_inicial")
    assert list(causal.propose(ctx)) == []


def test_a_purpose_clause_is_not_a_causal_one(
    rule_set: RuleSet,
    analyzer: RuleBasedAnalyzer,
) -> None:
    ctx = _context(analyzer, "Ho expliquem perquè ho entenguin.")
    causal = _sentence_rule(rule_set, "subordinada.causal_final_a_inicial")
    assert list(causal.propose(ctx)) == []


def test_impersonal_alternation_keeps_the_epistemic_class(
    rule_set: RuleSet,
    analyzer: RuleBasedAnalyzer,
    morphology: CatalanMorphology,
    parser: SyntaxProvider,
) -> None:
    ctx = _context(
        analyzer, "Es considera que el text és antic.", morphology=morphology, syntax=parser
    )
    impersonal = _sentence_rule(rule_set, "impersonal.es_a_hom")
    produced = [t.apply(ctx.text) for t in impersonal.propose(ctx)]
    assert produced == ["Hom considera que el text és antic."]
    text = "La gent es creu que és fàcil."
    ctx = _context(analyzer, text, morphology=morphology, syntax=parser)
    assert list(impersonal.propose(ctx)) == []


def test_the_web_service_reports_families_and_evidence(project_root: Path) -> None:
    from parafrasi_cat.web import RewriteService
    from parafrasi_cat.web.service import RewriteRequest

    service = RewriteService(ProjectPaths(project_root))
    data = service.rewrite(
        RewriteRequest("La qüestió, per tant, no és només etimològica. És institucional.",
                       mode=RewriteMode.DEEP, level=5)
    )  # fmt: skip
    candidates = [c for unit in data["units"] for c in unit["candidates"]]
    assert all("signature" in c and "structural_degree" in c for c in candidates)
    assert any(c["signature"] != "ORIGINAL" for c in candidates)
    assert all("family" in rule for c in candidates for rule in c["rules"])
    assert not re.search(r"va \w+ar\b.*sobirar", data["output_text"])
