"""Fase 7: proves completes de principi a fi, tal com les veu la interfície local.

Es fan a través de :class:`RewriteService`, que és el que crida la pàgina web,
i en tots dos modes. Comproven les dues garanties fonamentals del motor: cap
dada del text original no es perd ni s'altera, i el grau de certesa es manté.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from parafrasi_cat.core.text import phrase_pattern
from parafrasi_cat.pipeline.modes import RewriteMode
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.validation import EpistemicLexicon
from parafrasi_cat.validation.epistemic import EPISTEMOLOGY_FILE
from parafrasi_cat.web import RewriteService
from parafrasi_cat.web.service import JsonDict, RewriteRequest

ALTOVITI = (
    "La primera referència itàlica és el monument funerari d’Oddo Altoviti, encarregat el 1507 "
    "i finalitzat el 1516. En aquest sarcòfag fet per l’escultor Benedetto da Rovezzano hi ha la "
    "presència de dos cranis acompanyats de dos ossos creuats, així com dues serps també creuades."
)
FACTS = ("Oddo Altoviti", "1507", "1516", "Benedetto da Rovezzano", "dos cranis")
#: Relacions completes: no n'hi ha prou de conservar el nom, cal conservar el modificador.
RELATIONS = (("dos ossos", "creuats"), ("dues serps", "creuades"))

EPISTEMIC = (
    "Aquesta documentació permet plantejar que l'església podria haver existit abans del 1050, "
    "però no es pot demostrar."
)
HEDGES = ("permet plantejar", "podria", "no es pot demostrar")
#: Formulacions de certesa superior que cap candidat acceptat no pot introduir.
FORBIDDEN_CERTAINTY = (
    "demostra",
    "demostren",
    "confirma",
    "confirmen",
    "prova",
    "queda demostrat",
    "és evident",
    "sens dubte",
    "certament",
    "l'església existia",
    "l'església va existir",
)

#: Còpula sense invertir els sintagmes: «constituir» té direcció i aquesta variant és falsa.
WRONG_COPULA = "La primera referència itàlica constitueix el monument funerari d’Oddo Altoviti"
RIGHT_COPULA = "constitueix la primera referència itàlica"

MODES = (RewriteMode.CONSERVATIVE, RewriteMode.DEEP)


def relation_kept(text: str, head: str, modifier: str) -> bool:
    """Cert si ``head`` continua seguit del seu modificador (amb «també» opcional entremig)."""
    pattern = rf"(?<![^\W\d_]){re.escape(head)}(?:\s+també)?\s+{re.escape(modifier)}(?![^\W\d_])"
    return re.search(pattern, text) is not None


@pytest.fixture(scope="module")
def service(project_root: Path) -> RewriteService:
    return RewriteService(ProjectPaths(project_root))


@pytest.fixture(scope="module")
def results(service: RewriteService) -> dict[RewriteMode, JsonDict]:
    return {mode: service.rewrite(RewriteRequest(ALTOVITI, mode=mode, level=5)) for mode in MODES}


@pytest.fixture(scope="module")
def epistemic_results(service: RewriteService) -> dict[RewriteMode, JsonDict]:
    return {mode: service.rewrite(RewriteRequest(EPISTEMIC, mode=mode, level=5)) for mode in MODES}


def accepted_candidates(result: JsonDict) -> list[tuple[str, str]]:
    """Parelles (text original de la unitat, text del candidat) de tots els candidats acceptats."""
    pairs: list[tuple[str, str]] = []
    for unit in result["units"]:
        for candidate in unit["candidates"]:
            if candidate["accepted"]:
                pairs.append((unit["source_text"], candidate["text"]))
    return pairs


# --- cas Altoviti -------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_altoviti_keeps_every_fact(results: dict[RewriteMode, JsonDict], mode: RewriteMode) -> None:
    result = results[mode]
    pairs = accepted_candidates(result)
    assert pairs, mode
    for source, text in pairs:
        numbers = re.findall(r"\d+", source)
        assert re.findall(r"\d+", text) == numbers, (mode, text)
        for fact in FACTS:
            if fact in source:
                assert fact in text, (mode, fact, text)
    for fact in FACTS:
        assert fact in str(result["output_text"]), (mode, fact)


@pytest.mark.parametrize("mode", MODES)
def test_altoviti_keeps_complete_relations(
    results: dict[RewriteMode, JsonDict], mode: RewriteMode
) -> None:
    # La comprovació mira la relació sencera, no només el substantiu.
    assert relation_kept(ALTOVITI, "dos ossos", "creuats")
    assert relation_kept(ALTOVITI, "dues serps", "creuades")
    assert not relation_kept("dos ossos i dues serps creuades", "dos ossos", "creuats")
    checked = 0
    for source, text in accepted_candidates(results[mode]):
        for head, modifier in RELATIONS:
            if relation_kept(source, head, modifier):
                assert relation_kept(text, head, modifier), (mode, head, modifier, text)
                checked += 1
    assert checked >= 2
    for head, modifier in RELATIONS:
        assert relation_kept(str(results[mode]["output_text"]), head, modifier), (mode, head)


@pytest.mark.parametrize("mode", MODES)
def test_altoviti_never_reverses_the_copula(
    results: dict[RewriteMode, JsonDict], mode: RewriteMode
) -> None:
    for _source, text in accepted_candidates(results[mode]):
        assert not text.startswith(WRONG_COPULA), (mode, text)
    assert WRONG_COPULA not in str(results[mode]["output_text"])


def test_altoviti_offers_the_correct_constitueix_variant(
    results: dict[RewriteMode, JsonDict],
) -> None:
    # La variant amb «constitueix» només és acceptable amb els sintagmes invertits.
    texts = [text for _source, text in accepted_candidates(results[RewriteMode.DEEP])]
    correct = [text for text in texts if RIGHT_COPULA in text]
    assert correct, "cap variant correcta amb «constitueix»"
    for text in correct:
        assert text.startswith("El monument funerari d’Oddo Altoviti"), text
        assert "Oddo Altoviti" in text


def test_altoviti_protects_the_expected_spans(
    results: dict[RewriteMode, JsonDict],
) -> None:
    # Des de la 1.3.1 la partícula «da» forma part del nom: «Benedetto da Rovezzano» és un
    # sol tram protegit (abans eren dos trams i la partícula quedava exposada al motor verbal).
    for mode in MODES:
        protected = {span["text"] for span in results[mode]["protected_spans"]}
        assert {"Oddo Altoviti", "1507", "1516", "Benedetto da Rovezzano"} <= protected, mode


def test_deep_mode_reaches_further_without_losing_anything(
    results: dict[RewriteMode, JsonDict],
) -> None:
    conservative = results[RewriteMode.CONSERVATIVE]
    deep = results[RewriteMode.DEEP]
    assert conservative["level"] == 3 and deep["level"] == 5
    assert conservative["level_capped"] is True
    assert int(str(deep["n_candidates"])) > int(str(conservative["n_candidates"]))
    # El mode profund arriba a la fase de paràgraf; el conservador no.
    assert any(unit["kind"] == "paragraph" for unit in deep["units"])
    assert all(unit["kind"] == "sentence" for unit in conservative["units"])
    # I tots dos conserven exactament els mateixos fragments protegits.
    assert [s["text"] for s in conservative["protected_spans"]] == [
        s["text"] for s in deep["protected_spans"]
    ]


# --- cas epistemològic --------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_epistemic_text_never_gains_certainty(
    epistemic_results: dict[RewriteMode, JsonDict], mode: RewriteMode
) -> None:
    result = epistemic_results[mode]
    pairs = accepted_candidates(result)
    assert pairs, mode
    for source, text in pairs:
        for hedge in HEDGES:
            if hedge in source:
                assert hedge in text, (mode, hedge, text)
        for forbidden in FORBIDDEN_CERTAINTY:
            before = len(phrase_pattern(forbidden).findall(source))
            after = len(phrase_pattern(forbidden).findall(text))
            assert after <= before, (mode, forbidden, text)
    output = str(result["output_text"])
    for hedge in HEDGES:
        assert hedge in output, (mode, hedge)


@pytest.mark.parametrize("mode", MODES)
def test_epistemic_profile_is_unchanged(
    epistemic_results: dict[RewriteMode, JsonDict],
    mode: RewriteMode,
    paths: ProjectPaths,
) -> None:
    """El validador epistemològic mateix confirma que cap candidat no en canvia el perfil."""
    lexicon = EpistemicLexicon.load(paths.language() / EPISTEMOLOGY_FILE)
    for source, text in accepted_candidates(epistemic_results[mode]):
        assert lexicon.change(source, text) is None, (mode, text)
    # I la comprovació sap detectar-ho quan sí que hi ha un canvi.
    assert lexicon.change(EPISTEMIC, EPISTEMIC.replace("podria haver existit", "va existir"))


def test_epistemic_text_can_still_be_rephrased(
    epistemic_results: dict[RewriteMode, JsonDict],
) -> None:
    """El bloqueig és de certesa, no de reescriptura: el mode profund hi troba variants."""
    texts = [text for _source, text in accepted_candidates(epistemic_results[RewriteMode.DEEP])]
    alternatives = [text for text in texts if text != EPISTEMIC and text not in ALTOVITI]
    assert alternatives
    assert any("Tanmateix" in text or "Però" in text for text in alternatives)
