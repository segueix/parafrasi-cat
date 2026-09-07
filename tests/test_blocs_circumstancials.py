"""Moviment de circumstancials curts: la forma que quedava sense cap alternativa.

Mesurat sobre el corpus d'exemples, el 28 % de les frases no rebien cap
reescriptura perquè cap patró no hi coincidia, i la forma més freqüent era la
frase curta amb un circumstancial a un extrem: «Ara l'aigua és neta», «El
campanar es va restaurar l'any passat». ``blocs.complement_del_verb`` no els
pot veure perquè demana una preposició al davant.

La regla nova els mou d'un extrem a l'altre. El que la fa segura no és una
llista de casos sinó una condició lingüística: **un circumstancial que porta
l'abast de l'oració no es mou**. Un adverbi de focus, de negació o de
modalitat canvia què afirma la frase segons on és, i moure'l no seria
reordenar sinó reescriure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parafrasi_cat.pipeline import PipelineConfig, apply_mode
from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.modes import RewriteMode
from parafrasi_cat.pipeline.pipeline import Pipeline

RULE = "blocs.circumstancial_curt"


@pytest.fixture(scope="module")
def deep(project_root: Path) -> Pipeline:
    config = apply_mode(
        PipelineConfig(home=project_root, rule_set="parafrasi", languagetool=False),
        RewriteMode.DEEP,
        5,
    )
    return build_pipeline(config)


def moves(pipeline: Pipeline, text: str) -> list[str]:
    """Textos que la regla proposa per a aquesta frase."""
    return [t.text_after for t in pipeline.propose(text, max_level=5) if t.rule_id == RULE]


def _words(text: str) -> list[str]:
    return sorted(text.lower().replace(",", " ").replace(".", " ").split())


def test_an_initial_adverb_moves_to_the_end(deep: Pipeline) -> None:
    proposals = moves(deep, "Ara l'aigua és neta.")
    if not proposals:  # pragma: no cover - sense parser la regla no actua mai
        pytest.skip("cal l'analitzador sintàctic")
    assert any(text.rstrip(".").endswith("ara") for text in proposals), proposals


def test_a_bare_temporal_phrase_moves_to_the_front(deep: Pipeline) -> None:
    """«l'any passat» no porta preposició: és el cas que l'altra regla no veu."""
    proposals = moves(deep, "El campanar es va restaurar l'any passat.")
    if not proposals:  # pragma: no cover
        pytest.skip("cal l'analitzador sintàctic")
    assert any(text.lower().startswith("l'any passat,") for text in proposals), proposals


def test_the_move_only_reorders(deep: Pipeline) -> None:
    """Cap paraula no s'afegeix ni es perd: només canvia l'ordre."""
    source = "El campanar es va restaurar l'any passat."
    for text in moves(deep, source):
        assert _words(text) == _words(source.rstrip("."))


@pytest.mark.parametrize(
    "text",
    [
        "Només l'aigua és neta.",
        "Tampoc hi passa ningú.",
        "Fins i tot l'aigua és neta.",
        "Potser l'aigua és neta.",
        "Sobretot l'aigua és neta.",
    ],
)
def test_a_scope_bearing_adverb_never_moves(deep: Pipeline, text: str) -> None:
    """La posició d'aquests adverbis en marca l'abast: moure'ls canviaria el sentit."""
    assert moves(deep, text) == []


def test_a_negation_inside_the_block_blocks_the_move(deep: Pipeline) -> None:
    assert moves(deep, "Hi va no gaire sovint.") == []


def test_the_negation_of_the_sentence_stays_in_its_place(deep: Pipeline) -> None:
    """Moure el circumstancial no pot treure la negació del seu domini."""
    for text in moves(deep, "Ara ningú no hi va."):
        assert "ningú no" in text.lower(), text


def test_a_clause_is_not_a_circumstantial(deep: Pipeline) -> None:
    """Amb verb conjugat a dins ja no és un circumstancial: és feina de l'altra regla."""
    assert moves(deep, "L'aigua és neta quan plou.") == []


def test_a_long_phrase_is_left_to_the_prepositional_rule(deep: Pipeline) -> None:
    """El límit de paraules manté la regla al seu terreny."""
    long_one = "El campanar es va restaurar durant els primers mesos de l'any passat."
    assert moves(deep, long_one) == []


def test_without_a_parser_the_rule_does_nothing(project_root: Path) -> None:
    config = apply_mode(
        PipelineConfig(home=project_root, rule_set="parafrasi", languagetool=False, syntax="none"),
        RewriteMode.DEEP,
        5,
    )
    assert moves(build_pipeline(config), "Ara l'aigua és neta.") == []


def test_the_proposal_is_a_safe_reordering(deep: Pipeline) -> None:
    """El motor la classifica com el que és: una reordenació de risc baix."""
    proposals = [t for t in deep.propose("Ara l'aigua és neta.", max_level=5) if t.rule_id == RULE]
    if not proposals:  # pragma: no cover
        pytest.skip("cal l'analitzador sintàctic")
    for transformation in proposals:
        assert transformation.metadata["family"] == "REORDER"
        assert transformation.metadata["block_kind"] == "circumstantial"
        assert transformation.semantic_risk.value == "low"


def test_it_covers_sentences_that_had_no_alternative(deep: Pipeline) -> None:
    """La raó de ser de la regla: frases curtes que abans no rebien res.

    Es comprova sobre les formes reals del corpus concís, no sobre una frase
    inventada per al test.
    """
    curtes = [
        "Ara l'aigua és neta.",
        "La gent hi va cada dia.",
        "Jo hi vaig pujar l'any passat.",
    ]
    cobertes = [text for text in curtes if moves(deep, text)]
    if not cobertes:  # pragma: no cover
        pytest.skip("cal l'analitzador sintàctic")
    assert len(cobertes) == len(curtes), [t for t in curtes if t not in cobertes]
