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
NUMBERS = re.compile(r"\d+")


@pytest.fixture(scope="module")
def result() -> ParaphraseResult:
    return build_pipeline(PipelineConfig(rule_set="parafrasi")).run(TEXT)


MONUMENT = "el monument funerari d’Oddo Altoviti"
DATES = "encarregat el 1507 i finalitzat el 1516"
SARCOFAG = "sarcòfag fet per l’escultor Benedetto da Rovezzano"
CRANIS = "dos cranis acompanyats de dos ossos creuats, així com dues serps també creuades."
EXPECTED_FIRST = (
    f"El monument funerari d’Oddo Altoviti, {DATES}, és la primera referència itàlica.",
    f"La primera referència itàlica constitueix {MONUMENT}, {DATES}.",
    f"La primera referència itàlica correspon al monument funerari d’Oddo Altoviti, {DATES}.",
    f"La primera referència itàlica és {MONUMENT}, que fou {DATES}.",
)
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
    second = result.alternatives(1)
    for expected in EXPECTED_SECOND:
        assert expected in second, expected
    assert len(first) >= 6 and len(second) >= 8


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
    assert "copula.es_a_constitueix" in report or "Candidat no seleccionat" in report
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
    first = result.alternatives(0)
    assert not any(alt.startswith("El monument funerari") for alt in first)  # inversió = risc mitjà
    assert any("constitueix" in alt for alt in first)
    reasons = [r.reason for r in result.sentences[0].rejected_proposals]
    assert any("risc semàntic" in reason for reason in reasons)


def test_cli_produces_variants(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--rules", "parafrasi", "--json", TEXT]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["changed"] is True
    assert "1507" in data["output_text"] and "Oddo Altoviti" in data["output_text"]
    assert len(data["sentences"][0]["alternatives"]) >= 6


def test_default_rule_set_is_still_identity() -> None:
    assert build_pipeline().run(TEXT).output_text == TEXT
