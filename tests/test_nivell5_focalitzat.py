"""Prova focalitzada: «Reredacció automàtica» amb nivell 5 executa les regles entre frases.

La pregunta que respon aquest fitxer és estreta: quan es demana nivell 5 des de
la interfície, ¿la fase de paràgraf s'executa i les regles de fusió arriben a
proposar i a guanyar? La resposta és que sí, i que el que limita el resultat no
és ni la configuració ni l'execució, sinó la **cobertura** de les estratègies
de fusió, que són deliberadament estretes (vegeu
``resources/ca/transformations/fusio.yaml``): no fusionen si la segona frase
comença per connector, per demostratiu o per còpula, ni si les frases superen
la llargada que declara l'estratègia.

Aquí no s'amplia aquesta cobertura: només es documenta i es comprova.
"""

from __future__ import annotations

import pytest

from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.config import PipelineConfig
from parafrasi_cat.pipeline.modes import DEEP, MAX_LEVEL, apply_mode
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.web.service import RewriteRequest, RewriteService

#: Dues frases curtes i independents: l'estratègia «frases_curtes» hi arriba.
SHORT_PAIR = "El rei ocupa el centre. La reina es mou lliurement."

#: Fragment nominal anafòric: l'estratègia «aposicio_anaforica» hi arriba.
ANAPHORIC_PAIR = (
    "L'orfil va perdre el nom llatí durant el pas a les llengües romàniques. "
    "Un fet que explica la varietat de formes actuals."
)

#: Segona frase que comença per connector: cap estratègia no hi ha d'arribar.
CONNECTOR_PAIR = "El rei ocupa el centre. Però la reina es mou lliurement."


def pipeline_at(level: int):  # type: ignore[no-untyped-def]
    return build_pipeline(apply_mode(PipelineConfig(rule_set="parafrasi"), "profund", level))


def test_deep_mode_reaches_the_paragraph_level() -> None:
    """La configuració del mode profund arriba al nivell 5 i hi obre la cerca."""
    assert DEEP.max_level == MAX_LEVEL == 5
    config = apply_mode(PipelineConfig(rule_set="parafrasi"), "profund", 5)
    assert config.level == 5
    assert config.paragraph_beam_width > 1


def test_level_five_runs_the_between_sentence_rules() -> None:
    result = pipeline_at(5).run(SHORT_PAIR)
    assert result.paragraphs, "el nivell 5 ha d'obrir la fase de paràgraf"
    rules = {t.rule_id for p in result.paragraphs for t in p.transformations}
    assert "fusio.frases_compatibles" in rules
    assert result.output_text == "El rei ocupa el centre i la reina es mou lliurement."


def test_level_five_repairs_an_anaphoric_fragment() -> None:
    result = pipeline_at(5).run(ANAPHORIC_PAIR)
    rules = {t.rule_id for p in result.paragraphs for t in p.transformations}
    assert "fusio.frases_compatibles" in rules
    assert ", un fet que explica" in result.output_text


def test_level_four_does_not_run_them() -> None:
    """El límit és el nivell: amb 4, les mateixes frases no es fusionen."""
    result = pipeline_at(4).run(SHORT_PAIR)
    assert result.paragraphs == ()
    assert "i la reina" not in result.output_text


def test_coverage_is_what_limits_the_paragraph_level() -> None:
    """No és execució: la fase corre igualment, però cap estratègia no hi arriba.

    La segona frase comença per «Però», que és a ``skip_if_second_starts_with``:
    la fusió no es proposa i el paràgraf es queda com és.
    """
    result = pipeline_at(5).run(CONNECTOR_PAIR)
    assert result.paragraphs, "la fase de paràgraf s'executa igualment"
    assert not [t for p in result.paragraphs for t in p.transformations]


def test_the_interface_asks_for_level_five_and_gets_it(paths: ProjectPaths) -> None:
    """El camí sencer de la interfície: mode profund, nivell 5."""
    service = RewriteService(paths)
    response = service.rewrite(RewriteRequest(text=SHORT_PAIR, level=5))
    assert response["level"] == 5
    assert response["level_capped"] is False
    assert response["output_text"] == "El rei ocupa el centre i la reina es mou lliurement."


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5])
def test_every_level_is_reachable_from_the_interface(paths: ProjectPaths, level: int) -> None:
    service = RewriteService(paths)
    response = service.rewrite(RewriteRequest(text=SHORT_PAIR, level=level))
    assert response["level"] == level
