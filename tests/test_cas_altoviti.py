"""Cas de prova principal: variants del text d'Oddo Altoviti sense alterar dades factuals."""

from __future__ import annotations

import json
import re
from collections import Counter

import pytest

from parafrasi_cat import ParaphraseResult, PipelineConfig, build_pipeline
from parafrasi_cat.cli import main

TEXT = (
    "La primera referència itàlica és el monument funerari d’Oddo Altoviti, encarregat el 1507 "
    "i finalitzat el 1516. En aquest sarcòfag fet per l’escultor Benedetto da Rovezzano hi ha la "
    "presència de dos cranis acompanyats de dos ossos creuats, així com dues serps també creuades."
)
FACTS = (
    "Oddo Altoviti",
    "1507",
    "1516",
    "Benedetto da Rovezzano",
    "dos cranis",
    "dos ossos",
    "dues serps",
)
#: Relacions completes (nom + modificador) que cap variant no pot trencar: no n'hi ha
#: prou de conservar «dos ossos» i «dues serps»; cal conservar que els ossos són
#: creuats i les serps, creuades. Només s'admet «també» entremig.
RELATIONS = (("dos ossos", "creuats"), ("dues serps", "creuades"))
NUMBERS = re.compile(r"\d+")


def relation_kept(text: str, head: str, modifier: str) -> bool:
    """Cert si ``head`` va seguit (com a màxim amb «també» entremig) de ``modifier``."""
    pattern = rf"(?<![^\W\d_]){re.escape(head)}(?:\s+també)?\s+{re.escape(modifier)}(?![^\W\d_])"
    return re.search(pattern, text) is not None


@pytest.fixture(scope="module")
def result() -> ParaphraseResult:
    return build_pipeline(PipelineConfig(rule_set="parafrasi")).run(TEXT)


MONUMENT = "el monument funerari d’Oddo Altoviti"
DATES = "encarregat el 1507 i finalitzat el 1516"
SARCOFAG = "sarcòfag fet per l’escultor Benedetto da Rovezzano"
CRANIS = "dos cranis acompanyats de dos ossos creuats, així com dues serps també creuades."
EXPECTED_FIRST = (
    f"El monument funerari d’Oddo Altoviti, {DATES}, és la primera referència itàlica.",
    f"El monument funerari d’Oddo Altoviti, {DATES}, constitueix la primera referència itàlica.",
    f"La primera referència itàlica correspon al monument funerari d’Oddo Altoviti, {DATES}.",
    f"La primera referència itàlica és {MONUMENT}, que fou {DATES}.",
)
#: «constituir» té direcció (X constitueix Y = X forma Y): sense invertir els sintagmes,
#: la variant amb «constitueix» no és una equivalència correcta d'aquesta frase.
WRONG_CONSTITUEIX = f"La primera referència itàlica constitueix {MONUMENT}"
EXPECTED_SECOND = (
    f"Aquest {SARCOFAG} presenta {CRANIS}",
    f"En aquest {SARCOFAG} apareixen {CRANIS}",
    f"En aquest sarcòfag obra de l’escultor Benedetto da Rovezzano hi ha la presència de {CRANIS}",
    f"En aquest sarcòfag realitzat per l’escultor Benedetto da Rovezzano hi ha {CRANIS}",
)


def test_requested_variants_are_generated(result: ParaphraseResult) -> None:
    first = result.alternatives(0)
    for expected in EXPECTED_FIRST:
        assert expected in first, expected
    assert not any(alt.startswith(WRONG_CONSTITUEIX) for alt in first)
    second = result.alternatives(1)
    for expected in EXPECTED_SECOND:
        assert expected in second, expected
    assert len(first) >= 6 and len(second) >= 8


def test_constitueix_keeps_its_direction() -> None:
    pipeline = build_pipeline(PipelineConfig(rule_set="parafrasi"))
    # Subjecte especificatiu («La causa principal és X»): cal invertir els sintagmes.
    specificational = pipeline.run("La causa principal és la sequera.").alternatives(0)
    assert "La sequera constitueix la causa principal." in specificational
    assert "La causa principal constitueix la sequera." not in specificational
    # Subjecte predicatiu («Aquests textos són la font principal»): substitució directa.
    predicational = pipeline.run("Aquests textos són la font principal.").alternatives(0)
    assert "Aquests textos constitueixen la font principal." in predicational
    assert "La font principal constitueix aquests textos." not in predicational
    assert not any(alt.startswith(WRONG_CONSTITUEIX) for alt in pipeline.run(TEXT).alternatives(0))


def test_every_candidate_keeps_the_facts(result: ParaphraseResult) -> None:
    for sentence in result.sentences:
        source_numbers = Counter(NUMBERS.findall(sentence.source_text))
        for evaluated in sentence.candidates:
            text = evaluated.candidate.text
            assert Counter(NUMBERS.findall(text)) == source_numbers, text
            for fact in FACTS:
                if fact in sentence.source_text:
                    assert fact in text, (fact, text)
        # Les propostes acceptades no toquen mai un fragment protegit de manera parcial.
        assert not any("protegit" in r.reason for r in sentence.rejected_proposals)
    assert [p.text for p in result.protected_spans] == [
        "Oddo Altoviti",
        "1507",
        "1516",
        "Benedetto",
        "Rovezzano",
    ]
    assert result.changed
    for fact in FACTS:
        assert fact in result.output_text


def test_every_candidate_keeps_complete_relations(result: ParaphraseResult) -> None:
    # La comprovació és sobre la relació sencera, no només sobre el substantiu.
    assert relation_kept(TEXT, "dos ossos", "creuats")
    assert relation_kept(TEXT, "dues serps", "creuades")  # amb «també» entremig
    assert not relation_kept("dos ossos i dues serps creuades", "dos ossos", "creuats")
    assert not relation_kept("dues serps, i dos ossos creuats", "dues serps", "creuades")
    assert not relation_kept("dos ossos", "dos ossos", "creuats")
    assert not relation_kept("dues serps creuats", "dues serps", "creuades")
    checked = 0
    for sentence in result.sentences:
        for head, modifier in RELATIONS:
            if not relation_kept(sentence.source_text, head, modifier):
                continue
            for evaluated in sentence.candidates:
                text = evaluated.candidate.text
                assert relation_kept(text, head, modifier), (head, modifier, text)
                checked += 1
            assert relation_kept(sentence.output_text, head, modifier)
    assert checked >= 2 * 8
    for head, modifier in RELATIONS:
        assert relation_kept(result.output_text, head, modifier)


def test_candidates_are_deduplicated_and_bounded(result: ParaphraseResult) -> None:
    for sentence in result.sentences:
        texts = [c.candidate.text for c in sentence.candidates]
        assert len(texts) == len(set(texts))
        assert len(texts) <= 20
        assert sentence.candidates[0].candidate.is_identity
        for evaluated in sentence.candidates:
            rules = evaluated.candidate.rule_ids
            assert len(evaluated.candidate.transformations) <= 3
            # Mai la mateixa regla dues vegades sobre segments solapats.
            spans = [t.changed_span for t in evaluated.candidate.transformations]
            for i, first in enumerate(spans):
                for j, second in enumerate(spans):
                    if i < j and rules[i] == rules[j]:
                        assert not first.overlaps(second)


def test_explanations_and_json(result: ParaphraseResult) -> None:
    report = result.explain()
    assert "copula.es_a_constitueix_invertit" in report or "Candidat no seleccionat" in report
    assert WRONG_CONSTITUEIX not in report
    for transformation in result.transformations:
        assert transformation.explanation and transformation.rule_id
        assert transformation.metadata.get("category")
    data = json.loads(result.to_json())
    assert data["sentences"][0]["alternatives"]
    assert data["paragraphs"][0]["candidates"]
    # La fase de paràgraf ha proposat la fusió anafòrica com a candidat.
    assert any(", i en aquest sarcòfag" in alt for alt in result.paragraphs[0].alternatives)


def test_low_risk_profile_excludes_medium_risk_rules() -> None:
    from parafrasi_cat.core import SemanticRisk

    config = PipelineConfig(rule_set="parafrasi", max_semantic_risk=SemanticRisk.LOW)
    result = build_pipeline(config).run(TEXT)
    first = result.sentences[0]
    # Les regles de risc mitjà (inversió amb «és», «correspon a») no entren en cap candidat...
    used = {rule_id for e in first.candidates for rule_id in e.candidate.rule_ids}
    assert not used & {
        "ordre.inversio_copula",
        "ordre.inversio_copula_amb_aposicio",
        "copula.es_a_correspon_a",
    }
    assert not any("correspon al" in alt for alt in first.alternatives)
    rejected = {r.transformation.rule_id: r.reason for r in first.rejected_proposals}
    assert "risc semàntic" in rejected["ordre.inversio_copula_amb_aposicio"]
    assert "risc semàntic" in rejected["copula.es_a_correspon_a"]
    # ...però la variant correcta amb «constitueix» (sintagmes invertits) és de risc baix.
    assert any(
        alt.endswith("constitueix la primera referència itàlica.") for alt in first.alternatives
    )
    assert not any(alt.startswith(WRONG_CONSTITUEIX) for alt in first.alternatives)


def test_cli_produces_variants(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--rules", "parafrasi", "--json", TEXT]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["changed"] is True
    assert "1507" in data["output_text"] and "Oddo Altoviti" in data["output_text"]
    assert len(data["sentences"][0]["alternatives"]) >= 6


def test_default_rule_set_is_still_identity() -> None:
    assert build_pipeline().run(TEXT).output_text == TEXT


# --- fase 8A: morfologia de Softcatalà i validació local de LanguageTool ---------------------


def test_generated_verb_forms_agree(result: ParaphraseResult) -> None:
    """Les formes verbals que generen les regles concorden amb el seu subjecte."""
    from parafrasi_cat.morphology.catalan import CatalanMorphology

    morphology = CatalanMorphology.discover("resources/ca")
    if morphology is None:
        pytest.skip("El recurs morfològic de Softcatalà no s'ha importat")
    # Cada forma verbal nova ha de ser una forma real del seu lema, no una invenció.
    checked = 0
    for sentence in result.sentences:
        for evaluated in sentence.candidates:
            for transformation in evaluated.candidate.transformations:
                after = transformation.text_after.split()
                for word in after:
                    stripped = word.strip(",.;:()«»'’")
                    if stripped in (
                        "constitueix",
                        "constitueixen",
                        "apareix",
                        "apareixen",
                        "presenta",
                        "presenten",
                        "correspon",
                        "corresponen",
                        "realitzat",
                        "realitzada",
                        "realitzats",
                        "realitzades",
                    ):
                        assert morphology.knows(stripped), stripped
                        checked += 1
    assert checked > 0
    # I les parelles singular/plural són les que dona el diccionari, no un mapatge.
    assert morphology.inflect_like("és", "constituir") == "constitueix"
    assert morphology.inflect_like("són", "constituir") == "constitueixen"


def test_singular_and_plural_subjects_get_the_right_verb() -> None:
    """El nombre del subjecte decideix la forma verbal generada."""
    pipeline = build_pipeline(PipelineConfig(rule_set="parafrasi", level=3))
    singular = pipeline.run("Aquest text és la font principal.").alternatives(0)
    plural = pipeline.run("Aquests textos són la font principal.").alternatives(0)
    assert any("constitueix la font" in alt for alt in singular), singular
    assert not any("constitueixen" in alt for alt in singular), singular
    assert any("constitueixen la font" in alt for alt in plural), plural
    assert not any("text constitueix" in alt for alt in plural), plural


def test_languagetool_only_validates_and_changes_nothing() -> None:
    """Amb LanguageTool actiu, el text de sortida no el toca ningú més que les regles."""
    from parafrasi_cat.adapters.languagetool import LanguageToolClient

    if not LanguageToolClient.discover(".").available:
        pytest.skip("LanguageTool no està instal·lat")
    plain = build_pipeline(PipelineConfig(rule_set="parafrasi", level=3)).run(TEXT)
    checked = build_pipeline(PipelineConfig(rule_set="parafrasi", level=3, languagetool=True)).run(
        TEXT
    )
    # Cada candidat acceptat amb LanguageTool també ho era sense: només se'n descarten.
    plain_texts = {c.candidate.text for s in plain.sentences for c in s.candidates if c.accepted}
    checked_texts = {
        c.candidate.text for s in checked.sentences for c in s.candidates if c.accepted
    }
    assert checked_texts <= plain_texts, checked_texts - plain_texts
    # I les dades protegides continuen intactes.
    for fact in FACTS:
        assert fact in checked.output_text, fact
    for head, modifier in RELATIONS:
        assert relation_kept(checked.output_text, head, modifier), (head, modifier)
    assert not checked.output_text.startswith(WRONG_CONSTITUEIX)
    assert [p.text for p in checked.protected_spans] == [p.text for p in plain.protected_spans]
