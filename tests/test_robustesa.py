"""Robustesa davant les limitacions conegudes: errors nous, confiança i longitud.

Els deu casos que ha de sostenir la versió endurida:

1. un error que ja hi era a l'original no bloqueja el candidat;
2. un error nou introduït per una transformació sí que el bloqueja;
3. una discordança generada pel motor es detecta;
4. una discordança inequívocament reparable per morfologia es repara;
5. amb més d'una solució possible no es repara: el candidat es descarta;
6. el text fragmentari no activa transformacions sintàctiques agressives;
7. el nivell 5 respecta ``max_sentence_length``;
8. amb una empremta de frases curtes, el nivell 5 evita fusions excessives;
9. amb una empremta de frases llargues, una fusió segura continua sent candidata;
10. sense recursos opcionals el motor funciona, i amb tots s'activa el mode complet.

Els que necessiten el parser, la morfologia o LanguageTool se salten si el
recurs no està instal·lat; la resta s'executen sempre.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parafrasi_cat import ParaphraseResult, PipelineConfig, build_pipeline
from parafrasi_cat.adapters.languagetool import (
    LanguageToolClient,
    LanguageToolMatch,
    LanguageToolValidator,
    MatchSeverity,
    classify,
)
from parafrasi_cat.adapters.status import (
    ComponentStatus,
    LinguisticMode,
    LinguisticResources,
)
from parafrasi_cat.analyzer import ClosedClassLexicon, RuleBasedAnalyzer
from parafrasi_cat.candidates import Candidate
from parafrasi_cat.candidates.repair import REPAIR_RULE_ID, AgreementRepair
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import SemanticRisk, Transformation, TransformationType
from parafrasi_cat.morphology.catalan import CatalanMorphology
from parafrasi_cat.morphology.features import LexicalEntry, MorphFeatures
from parafrasi_cat.morphology.provider import DictionaryMorphology, MorphologyProvider
from parafrasi_cat.pipeline.pipeline import FRAGMENT_MAX_LEVEL
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.style.corpus import load_corpus
from parafrasi_cat.style.observations import StyleResources
from parafrasi_cat.style.profiler import build_fingerprint
from parafrasi_cat.syntax import SpacySyntax, SyntaxProvider
from parafrasi_cat.validation import ValidationContext
from parafrasi_cat.validation.agreement import AgreementValidator, find_disagreements

#: Text de dues frases que el nivell 5 fusiona si res no ho impedeix.
PARAGRAPH = (
    "La primera referència itàlica és el monument funerari d’Oddo Altoviti, encarregat el 1507 "
    "i finalitzat el 1516. En aquest sarcòfag fet per l’escultor Benedetto da Rovezzano hi ha la "
    "presència de dos cranis acompanyats de dos ossos creuats, així com dues serps també creuades."
)
FUSION_MARK = ", i en aquest sarcòfag"

CORRECT = "El sarcòfag presenta dos cranis."
PLURAL_SUBJECT = "El sarcòfag"
PLURAL_FORM = "Els sarcòfags"

#: Fragment nominal: cap verb conjugat, cap estructura per transformar amb seguretat.
FRAGMENT = "Sarcòfag de marbre amb dues serps creuades."

#: Mateix incís entre guions en un fragment i en una oració completa. La regla
#: «puntuacio.guions_a_comes» és de nivell 3: només ha d'actuar a la segona.
DASHED_FRAGMENT = "Làpida de pedra — obra d'un taller local — amb dues serps."
DASHED_SENTENCE = "La làpida de pedra — obra d'un taller local — mostra dues serps."
STRUCTURAL_RULE = "puntuacio.guions_a_comes"

#: Text amb un nom propi que LanguageTool marca com a error d'ortografia; el motor
#: no l'ha escrit i no l'ha de fer servir per descartar res.
PRE_EXISTING = "El monument funerari de Oddo Altoviti es conserva a Florència."


@pytest.fixture(scope="module")
def parser() -> SpacySyntax:
    found = SpacySyntax()
    if not found.available:
        pytest.skip(
            f"El parser sintàctic no està instal·lat ({found.failure}). "
            "Executeu: python scripts/install_parser.py"
        )
    return found


@pytest.fixture(scope="module")
def morphology(project_root: Path) -> CatalanMorphology:
    found = CatalanMorphology.discover(project_root / "resources" / "ca")
    if found is None:
        pytest.skip(
            "La morfologia de Softcatalà no està importada. "
            "Executeu: python scripts/install_morphology.py"
        )
    return found


@pytest.fixture(scope="module")
def languagetool(project_root: Path) -> LanguageToolClient:
    found = LanguageToolClient.discover(project_root)
    if not found.available:
        pytest.skip(
            "LanguageTool no està instal·lat. Executeu: python scripts/install_languagetool.py"
        )
    return found


def transformed(source: str, before: str, after: str, rule_id: str = "prova.plural") -> Candidate:
    """Candidat amb una única transformació explícita, com les que fa la canonada."""
    start = source.index(before)
    transformation = Transformation(
        rule_id=rule_id,
        text_before=before,
        text_after=after,
        changed_span=Span(start, start + len(before)),
        transformation_type=TransformationType.LEXICAL,
        confidence=0.9,
        semantic_risk=SemanticRisk.LOW,
        explanation="transformació de prova",
    )
    return Candidate.from_transformations(0, source, [transformation])


# --- 1 i 2: errors de l'original contra errors nous -------------------------------------------


def test_the_classification_only_blocks_new_errors_inside_the_change() -> None:
    """La gravetat depèn de si l'error és nou i d'on cau; sense LanguageTool instal·lat."""
    agreement = LanguageToolMatch(
        "CONCORD_SUBJECTE_VERB",
        "Possible error de concordança.",
        offset=0,
        length=5,
        issue_type="uncategorized",
        category="CONCORDANCES_SUBJECT_VERB",
    )
    assert classify(agreement, introduced=False, inside_change=True) is MatchSeverity.INFORMATIONAL
    assert classify(agreement, introduced=True, inside_change=True) is MatchSeverity.BLOCKING
    assert classify(agreement, introduced=True, inside_change=False) is MatchSeverity.STRONG_PENALTY

    spelling = LanguageToolMatch(
        "MORFOLOGIK_RULE_CA_ES", "Possible error ortogràfic.", 0, 4, "misspelling", "TYPOS"
    )
    assert classify(spelling, introduced=True, inside_change=True) is MatchSeverity.STRONG_PENALTY
    assert classify(spelling, introduced=True, inside_change=False) is MatchSeverity.WARNING

    style = LanguageToolMatch("ESTIL", "Qüestió d'estil.", 0, 3, "style", "ESTIL")
    assert classify(style, introduced=True, inside_change=True) is MatchSeverity.WARNING
    assert classify(style, introduced=True, inside_change=False) is MatchSeverity.INFORMATIONAL

    assert MatchSeverity.STRONG_PENALTY.weight > MatchSeverity.WARNING.weight
    assert not MatchSeverity.INFORMATIONAL.penalizes


def test_a_pre_existing_error_does_not_reject_the_candidate(
    languagetool: LanguageToolClient,
) -> None:
    """L'error del nom propi ja hi era: el candidat no s'ha de descartar per això."""
    validator = LanguageToolValidator(languagetool)
    candidate = transformed(PRE_EXISTING, "es conserva", "es manté", "prova.lexical")
    found = validator.report(candidate, PRE_EXISTING)
    assert found, "LanguageTool hauria de marcar el nom propi"
    assert not any(item.introduced for item in found)
    assert all(item.severity is MatchSeverity.INFORMATIONAL for item in found)
    assert validator.validate(candidate, ValidationContext(PRE_EXISTING)).ok


def test_a_new_error_inside_the_change_rejects_the_candidate(
    languagetool: LanguageToolClient,
) -> None:
    """Una discordança que no hi era, i que ha creat una regla, invalida el candidat."""
    validator = LanguageToolValidator(languagetool)
    candidate = transformed(CORRECT, PLURAL_SUBJECT, PLURAL_FORM)
    found = validator.report(candidate, CORRECT)
    blocking = [item for item in found if item.severity is MatchSeverity.BLOCKING]
    assert blocking, found
    assert blocking[0].introduced and blocking[0].inside_change
    result = validator.validate(candidate, ValidationContext(CORRECT))
    assert not result.ok
    assert "prova.plural" in result.errors[0].message


# --- 3, 4 i 5: concordança detectada, reparada o descartada ------------------------------------


def test_an_engine_made_disagreement_is_detected(parser: SpacySyntax) -> None:
    validator = AgreementValidator(parser)
    candidate = transformed(CORRECT, PLURAL_SUBJECT, PLURAL_FORM)
    result = validator.validate(candidate, ValidationContext(CORRECT))
    assert not result.ok
    message = result.errors[0].message
    assert "prova.plural" in message and "discordança" in message


def test_a_disagreement_of_the_author_is_not_counted(parser: SpacySyntax) -> None:
    """Si la discordança ja hi era, el candidat no en respon."""
    source = "Els sarcòfags presenta dos cranis."
    validator = AgreementValidator(parser)
    candidate = transformed(source, "dos cranis", "dos cranis humans", "prova.lexical")
    assert find_disagreements(parser.parse(source))
    assert validator.validate(candidate, ValidationContext(source)).ok


def test_a_distant_disagreement_is_caught_by_the_syntax_layer(
    parser: SpacySyntax, morphology: CatalanMorphology
) -> None:
    """Amb el verb lluny del canvi, qui la detecta i la repara és el parser.

    LanguageTool no arriba a tot arreu, i el seu criteri de proximitat evita
    falsos positius; per això la concordança té el seu propi validador local.
    """
    source = "El sarcòfag de marbre blanc presenta dos cranis."
    candidate = transformed(source, PLURAL_SUBJECT, PLURAL_FORM)
    result = AgreementValidator(parser).validate(candidate, ValidationContext(source))
    assert not result.ok
    repaired = AgreementRepair(parser, morphology).repair(candidate)
    assert repaired.text == "Els sarcòfags de marbre blanc presenten dos cranis."


@pytest.mark.parametrize(
    "sentence",
    [
        "La majoria dels autors accepten aquesta datació.",
        "El conjunt de làpides mostra una gran homogeneïtat.",
        "Una part dels documents s'han perdut.",
    ],
)
def test_collective_subjects_are_left_alone(parser: SpacySyntax, sentence: str) -> None:
    """La concordança *ad sensum* dels col·lectius és correcta: no és cap error."""
    assert not find_disagreements(parser.parse(sentence))


def test_an_unambiguous_disagreement_is_repaired(
    parser: SpacySyntax, morphology: CatalanMorphology
) -> None:
    """La morfologia local només admet «presenten»: es corregeix i queda registrat."""
    repair = AgreementRepair(parser, morphology)
    assert repair.available
    candidate = transformed(CORRECT, PLURAL_SUBJECT, PLURAL_FORM)
    repaired = repair.repair(candidate)
    assert repaired.text == "Els sarcòfags presenten dos cranis."
    added = repaired.transformations[-1]
    assert added.rule_id == REPAIR_RULE_ID
    assert (added.text_before, added.text_after) == ("presenta", "presenten")
    assert added.transformation_type is TransformationType.MORPHOLOGICAL
    assert "prova.plural" in added.explanation
    assert not find_disagreements(parser.parse(repaired.text))


def test_an_ambiguous_disagreement_is_not_repaired(parser: SpacySyntax) -> None:
    """Amb més d'una forma possible no es repara res: el candidat es descarta."""
    ambiguous: MorphologyProvider = DictionaryMorphology(
        [
            LexicalEntry("és", "ser", MorphFeatures(pos="verb", number="sg", person="3")),
            LexicalEntry(
                "presenta",
                "presentar",
                MorphFeatures(pos="verb", number="sg", person="3", tense="pres", mood="ind"),
            ),
            LexicalEntry(
                "presenten",
                "presentar",
                MorphFeatures(pos="verb", number="pl", person="3", tense="pres", mood="ind"),
            ),
            LexicalEntry(
                "presentin",
                "presentar",
                MorphFeatures(pos="verb", number="pl", person="3", tense="pres", mood="ind"),
            ),
        ]
    )
    repair = AgreementRepair(parser, ambiguous)
    candidate = transformed(CORRECT, PLURAL_SUBJECT, PLURAL_FORM)
    assert repair.repair(candidate).text == candidate.text
    assert not AgreementValidator(parser).validate(candidate, ValidationContext(CORRECT)).ok


# --- 6: text fragmentari ----------------------------------------------------------------------


def test_fragmentary_text_does_not_trigger_structural_transformations(
    parser: SpacySyntax,
) -> None:
    """Sense una anàlisi fiable no s'autoritza res estructural, i es diu per què."""
    analysis = parser.parse(FRAGMENT)
    assert not analysis.confident
    assert analysis.reasons

    pipeline = build_pipeline(PipelineConfig(rule_set="parafrasi", level=5))
    result = pipeline.run(FRAGMENT)
    notes = " ".join(result.notes)
    assert "poc fiable" in notes
    assert f"nivell {FRAGMENT_MAX_LEVEL}" in notes
    assert FRAGMENT_MAX_LEVEL < 3, "el nivell 3 és on comencen les transformacions estructurals"
    for transformation in result.transformations:
        assert pipeline.rule_set.rule(transformation.rule_id).level <= FRAGMENT_MAX_LEVEL


def test_the_same_structure_is_transformed_only_in_a_complete_sentence(
    parser: SpacySyntax,
) -> None:
    """Contrast amb el mateix incís: al fragment no s'hi toca; a l'oració, sí."""
    pipeline = build_pipeline(PipelineConfig(rule_set="parafrasi", level=5))
    assert pipeline.rule_set.rule(STRUCTURAL_RULE).level == 3

    fragment = pipeline.run(DASHED_FRAGMENT)
    assert not parser.parse(DASHED_FRAGMENT).confident
    assert fragment.output_text == DASHED_FRAGMENT
    assert STRUCTURAL_RULE not in [t.rule_id for t in fragment.transformations]

    complete = pipeline.run(DASHED_SENTENCE)
    assert parser.parse(DASHED_SENTENCE).confident
    assert STRUCTURAL_RULE in [t.rule_id for t in complete.transformations]
    assert not complete.notes


# --- 7, 8 i 9: longitud de frase al nivell 5 ---------------------------------------------------


def rewrite(**options: object) -> ParaphraseResult:
    config = PipelineConfig(rule_set="parafrasi", level=5, **options)  # type: ignore[arg-type]
    return build_pipeline(config).run(PARAGRAPH)


def fingerprint_file(
    project_root: Path, destination: Path, style: str, lexicon: ClosedClassLexicon
) -> Path:
    """Empremta calculada d'un corpus d'exemple, desada com fa la interfície."""
    paths = ProjectPaths(project_root)
    analyzer = RuleBasedAnalyzer(lexicon=lexicon)
    resources = StyleResources.load(paths, lexicon=lexicon)
    corpus = load_corpus(project_root / "corpus" / "exemples" / style)
    fingerprint = build_fingerprint(corpus, resources, analyzer, name=style)
    return fingerprint.save(destination / f"{style}.json")


def test_the_fusion_is_a_candidate_when_nothing_limits_the_length() -> None:
    """Punt de partida: sense preferències de longitud, el nivell 5 proposa la fusió."""
    result = rewrite()
    assert any(FUSION_MARK in text for text in result.paragraphs[0].alternatives)


def test_level_5_respects_the_authors_maximum_sentence_length(tmp_path: Path) -> None:
    preferences = tmp_path / "curt.yml"
    preferences.write_text(
        "name: autor de frase curta\nmax_sentence_length: 25\n", encoding="utf-8"
    )
    result = rewrite(preferences=str(preferences))
    assert not any(FUSION_MARK in text for text in result.paragraphs[0].alternatives)
    notes = " ".join(result.notes)
    assert "no s'ha fusionat" in notes and "el límit és 25" in notes


def test_a_short_sentence_fingerprint_avoids_excessive_fusion(
    project_root: Path, tmp_path: Path, lexicon: ClosedClassLexicon
) -> None:
    """Amb un autor de frase curta, el nivell 5 no allarga: reestructura d'altres maneres."""
    profile = fingerprint_file(project_root, tmp_path, "concis", lexicon)
    result = rewrite(style_profile=str(profile))
    assert not any(FUSION_MARK in text for text in result.paragraphs[0].alternatives)
    assert any("empremta de l'autor" in note for note in result.notes)


def test_a_long_sentence_fingerprint_keeps_the_fusion_available(
    project_root: Path, tmp_path: Path, lexicon: ClosedClassLexicon
) -> None:
    """Amb un autor de períodes llargs, la mateixa fusió segura continua sent candidata."""
    profile = fingerprint_file(project_root, tmp_path, "academic", lexicon)
    result = rewrite(style_profile=str(profile))
    assert any(FUSION_MARK in text for text in result.paragraphs[0].alternatives)


# --- 10: modes lingüístics --------------------------------------------------------------------


def test_the_engine_works_without_any_optional_resource() -> None:
    """Mode bàsic: sense morfologia, sense parser i sense LanguageTool."""
    config = PipelineConfig(
        rule_set="parafrasi", level=5, syntax="none", morphology="internal", languagetool=False
    )
    pipeline = build_pipeline(config)
    assert not pipeline.syntax.available
    assert not pipeline.repair.available
    assert "languagetool" not in [v.validator_id for v in pipeline.validators]
    assert "concordanca" not in [v.validator_id for v in pipeline.validators]
    result = pipeline.run(PARAGRAPH)
    assert result.output_text and "Oddo Altoviti" in result.output_text


def component(name: str, *, active: bool) -> ComponentStatus:
    return ComponentStatus(name, "actiu" if active else "no instal·lat", active, "prova")


def test_all_resources_present_activate_the_full_linguistic_mode() -> None:
    full = LinguisticResources(
        morphology=component("Morfologia catalana", active=True),
        syntax=component("Parser sintàctic català", active=True),
        languagetool=component("LanguageTool local", active=True),
        java=component("Java", active=True),
    )
    assert full.mode is LinguisticMode.FULL
    assert full.installable == ()
    assert full.to_dict()["mode"] == {
        "id": "complet",
        "label": "Mode lingüístic complet actiu",
        "detail": LinguisticMode.FULL.detail,
        "full": True,
        "missing": [],
        "installable": [],
    }


def test_a_missing_resource_falls_back_to_the_basic_mode() -> None:
    basic = LinguisticResources(
        morphology=component("Morfologia catalana", active=False),
        syntax=component("Parser sintàctic català", active=True),
        languagetool=component("LanguageTool local", active=False),
        java=component("Java", active=True),
    )
    assert basic.mode is LinguisticMode.BASIC
    assert basic.installable == ("morphology", "languagetool")
    assert "Mode bàsic" in basic.mode.label
    assert basic.mode.label in basic.summary()


def test_the_syntax_provider_protocol_is_satisfied(parser: SpacySyntax) -> None:
    assert isinstance(parser, SyntaxProvider)
