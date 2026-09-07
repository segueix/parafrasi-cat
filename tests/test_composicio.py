"""Composició frase a frase: redaccions alternatives i sinònims clicables.

Aquesta pantalla treballa d'una altra manera que la resta del motor: no tria
res. De cada frase n'ofereix les redaccions segures més diferents entre elles
i, de cada redacció, els fragments que tenen alternativa. Qui decideix és la
persona que edita, i per això els sinònims s'agrupen per sentit en lloc
d'endevinar-lo.

El diccionari de sinònims és un component opcional que no es versiona. Els
tests no en depenen: se'n construeix un de petit amb l'importador real, de
manera que el format i les decisions de contingut (cap antònim, registre com a
dada) queden comprovats sense baixar res.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from parafrasi_cat.candidates import Candidate
from parafrasi_cat.compose import Composer, choose_options, distance
from parafrasi_cat.compose.options import DraftOption, SentenceDraft
from parafrasi_cat.core import ConfigError, SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.pipeline import PipelineConfig, apply_mode
from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.modes import RewriteMode
from parafrasi_cat.pipeline.pipeline import Pipeline
from parafrasi_cat.pipeline.result import EvaluatedCandidate
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.scoring.scorer import ScoreBreakdown
from parafrasi_cat.synonyms import CatalanThesaurus, SynonymSuggester
from parafrasi_cat.synonyms.suggester import (
    SOURCE_CONNECTOR,
    SOURCE_THESAURUS,
    connector_index,
)
from parafrasi_cat.validation.result import ValidationResult
from parafrasi_cat.web.service import ComposeRequest, RewriteService

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_sinonims import build as build_thesaurus  # noqa: E402 - l'script viu fora del paquet
from import_sinonims import parse_line  # noqa: E402

#: Un tros de diccionari amb el format real, prou per comprovar-ne les decisions.
SOURCE_LINES = """
-adj (cel): ras, serè, clar, sense núvols, ennuvolat (antònim)
-v: saber, conèixer, dominar, ignorar (antònim)
-n: casa, habitatge, domicili, estatge # xamba (col·loquial)
-adv: sovint, freqüentment, amb freqüència
-loc: a causa de, per raó de, arran de
-n (única): solitari
"""

PARAGRAPH = (
    "El cavaller és reconeixible perquè el cavall i la funció militar el fan transparent. "
    "El rei no necessita gaire justificació: és el centre del tauler."
)


# --- l'importador ------------------------------------------------------------------------


def test_the_importer_never_keeps_an_antonym() -> None:
    """Un antònim és el contrari, no un equivalent: no ha d'arribar mai al recurs."""
    group = parse_line("-adj (cel): ras, serè, clar, ennuvolat (antònim)")
    assert group is not None
    forms = [member.form for member in group.members]
    assert "ennuvolat" not in forms
    assert forms == ["ras", "serè", "clar"]
    assert group.pos == "adj"
    assert group.sense == "cel"


def test_the_importer_keeps_the_register_as_data() -> None:
    """El registre s'anota; no filtra res. Qui tria ha de poder veure-ho."""
    group = parse_line("-n: casa, habitatge # xamba (col·loquial)")
    assert group is not None
    marked = {member.form: (member.register, member.secondary) for member in group.members}
    assert marked["casa"] == ("", False)
    assert marked["xamba"] == ("col·loquial", True)


def test_the_importer_drops_groups_without_an_alternative() -> None:
    """Un grup d'una sola forma no ofereix res, i un antònim no en fa dues."""
    assert parse_line("-n (única): solitari") is None
    assert parse_line("-adj: clar, fosc (antònim)") is None
    assert parse_line("no és una entrada") is None


# --- el recurs ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def thesaurus(tmp_path_factory: pytest.TempPathFactory) -> CatalanThesaurus:
    directory = tmp_path_factory.mktemp("sinonims")
    source = directory / "sinonims.txt"
    source.write_text(SOURCE_LINES.strip() + "\n", encoding="utf-8")
    output = directory / "sinonims.sqlite"
    build_thesaurus(source, output, {"source_repository": "prova", "license": "CC-BY-4.0"})
    return CatalanThesaurus(output)


def test_the_thesaurus_answers_without_the_form_itself(thesaurus: CatalanThesaurus) -> None:
    groups = thesaurus.groups("casa")
    assert len(groups) == 1
    forms = [member.form for member in groups[0].members]
    assert "casa" not in forms
    assert {"habitatge", "domicili", "estatge", "xamba"} == set(forms)


def test_the_thesaurus_filters_by_category(thesaurus: CatalanThesaurus) -> None:
    assert thesaurus.groups("saber", pos="verb")
    assert thesaurus.groups("saber", pos="noun") == ()
    assert thesaurus.groups("inexistent") == ()
    assert thesaurus.knows("ras") and not thesaurus.knows("inexistent")


def test_the_group_says_which_sense_it_is(thesaurus: CatalanThesaurus) -> None:
    """Sense la glossa, qui tria no pot distingir dos sentits d'una mateixa paraula."""
    group = thesaurus.groups("ras")[0]
    assert group.sense == "cel"
    assert group.label == "adjectiu · cel"


# --- el suggeridor -----------------------------------------------------------------------


@pytest.fixture(scope="module")
def pipeline(project_root: Path) -> Pipeline:
    config = apply_mode(
        PipelineConfig(home=project_root, rule_set="parafrasi", languagetool=False),
        RewriteMode.DEEP,
        5,
    )
    return build_pipeline(config)


@pytest.fixture(scope="module")
def suggester(pipeline: Pipeline, thesaurus: CatalanThesaurus) -> SynonymSuggester:
    return SynonymSuggester(
        pipeline.analyzer,
        morphology=pipeline.morphology,
        thesaurus=thesaurus,
        connectors=connector_index(pipeline.rule_set.sentence_rules),
        syntax=pipeline.syntax,
        guarded=("no", "mai", "potser", "sens dubte"),
    )


def _forms(suggester: SynonymSuggester, text: str, fragment: str) -> list[str]:
    for token in suggester.options(text):
        if token.text == fragment:
            return [option.text for option in token.options]
    return []


def test_a_connector_offers_its_equivalence_class(suggester: SynonymSuggester) -> None:
    """Els connectors surten de les regles actives: res que el motor no pogués escriure."""
    options = _forms(suggester, "Tanmateix, no plou.", "Tanmateix")
    assert "No obstant això" in options
    assert "Així i tot" in options
    token = next(t for t in suggester.options("Tanmateix, no plou.") if t.text == "Tanmateix")
    assert token.groups[0].source == SOURCE_CONNECTOR


def test_a_negation_gets_no_synonyms(suggester: SynonymSuggester) -> None:
    """Canviar una negació no és canviar la forma: és canviar el que el text afirma."""
    assert _forms(suggester, "Tanmateix, no plou.", "no") == []
    assert _forms(suggester, "Potser plou.", "Potser") == []


def test_a_protected_fragment_offers_nothing(
    suggester: SynonymSuggester, pipeline: Pipeline
) -> None:
    text = "La casa de Joan Ras és al carrer."
    protected = pipeline.protector.protect(text)
    assert protected, "el nom propi hauria d'estar protegit"
    covered = [
        token.text
        for token in suggester.options(text, protected)
        if any(p.span.overlaps(Span(token.start, token.end)) for p in protected)
    ]
    assert covered == []


def test_a_proposal_agrees_with_the_form_it_replaces(suggester: SynonymSuggester) -> None:
    """«sabem» no pot dur «conèixer»: ha de dur «coneixem»."""
    options = _forms(suggester, "Ho sabem tot.", "sabem")
    if not options:  # pragma: no cover - sense morfologia importada no s'ofereix res
        pytest.skip("cal la morfologia de Softcatalà per flexionar els sinònims")
    assert "coneixem" in options
    assert "conèixer" not in options


def test_a_multiword_locution_is_matched_whole(suggester: SynonymSuggester) -> None:
    options = _forms(suggester, "Ho fem a causa de la pluja.", "a causa de")
    assert "per raó de" in options


def test_the_senses_are_kept_apart(suggester: SynonymSuggester) -> None:
    """Cada grup de significat és un grup a la llista: no es barregen mai."""
    token = next(t for t in suggester.options("La casa és gran.") if t.text == "casa")
    assert len(token.groups) >= 1
    for group in token.groups:
        assert group.label
        assert group.source == SOURCE_THESAURUS


def test_without_any_source_nothing_is_offered(pipeline: Pipeline) -> None:
    empty = SynonymSuggester(pipeline.analyzer)
    assert not empty.available
    assert empty.options("La casa és gran.") == ()


# --- la tria de redaccions ---------------------------------------------------------------


def _evaluated(text: str, signature_source: str, total: float) -> EvaluatedCandidate:
    start = text.index(signature_source) if signature_source in text else 0
    transformation = Transformation(
        rule_id="prova.regla",
        text_before=text[start : start + len(signature_source)] or text,
        text_after="X",
        changed_span=Span(start, start + max(1, len(signature_source))),
        transformation_type=TransformationType.CONNECTOR,
        confidence=0.8,
        semantic_risk=SemanticRisk.LOW,
        explanation="prova",
        metadata={"category": "connector"},
    )
    candidate = Candidate(0, text, text.replace(signature_source, "X", 1), (transformation,))
    return EvaluatedCandidate(
        candidate, ValidationResult.passed(), ScoreBreakdown(total, {}, "prova")
    )


def test_the_distance_puts_the_architecture_first() -> None:
    base = Candidate(0, "a", "El rei descansa avui.", ())
    same = Candidate(0, "a", "El rei descansa ara.", ())
    assert distance(base, base) == 0.0
    assert 0.0 < distance(base, same) < 1.0


def test_the_choice_prefers_the_most_different(pipeline: Pipeline) -> None:
    """Amb tres candidats, no s'agafen els dos que s'assemblen més."""
    result = pipeline.run("El cavaller és reconeixible perquè la funció militar el fa clar.")
    sentence = result.sentences[0]
    picked = choose_options(sentence.candidates, 2)
    assert len(picked) <= 2
    for evaluated in picked:
        assert evaluated.accepted
        assert not evaluated.candidate.is_identity
    texts = [e.candidate.text for e in picked]
    assert len(texts) == len(set(texts))


def test_the_choice_is_deterministic(pipeline: Pipeline) -> None:
    result = pipeline.run(PARAGRAPH)
    first = [e.candidate.text for e in choose_options(result.sentences[0].candidates, 3)]
    second = [e.candidate.text for e in choose_options(result.sentences[0].candidates, 3)]
    assert first == second


def test_the_identity_never_counts_as_a_rewrite() -> None:
    identity = EvaluatedCandidate(
        Candidate(0, "El rei descansa.", "El rei descansa.", ()),
        ValidationResult.passed(),
        ScoreBreakdown(0.0, {}, "original"),
    )
    assert choose_options([identity], 3) == ()
    assert choose_options([], 3) == ()


# --- el composant ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def composer(pipeline: Pipeline, suggester: SynonymSuggester) -> Composer:
    return Composer(pipeline, suggester, wanted=3)


def test_the_original_is_always_available(composer: Composer) -> None:
    """Qui escriu ha de poder quedar-se el seu text i, tot i així, editar-hi paraules."""
    draft = composer.compose(PARAGRAPH)
    assert draft.n_sentences == 2
    for sentence in draft.sentences:
        originals = [option for option in sentence.options if option.original]
        assert len(originals) == 1
        assert originals[0] is sentence.options[-1]
        assert originals[0].text == sentence.source_text


def test_it_says_when_there_are_not_three_rewrites(composer: Composer) -> None:
    """No s'omple la llista: si el motor no en troba tres, es diu."""
    draft = composer.compose(PARAGRAPH)
    for sentence in draft.sentences:
        if sentence.n_rewrites < composer.wanted:
            assert sentence.note
        else:
            assert not sentence.note


def test_the_paragraph_is_rebuilt_exactly(composer: Composer) -> None:
    """Sense triar res, el paràgraf muntat ha de ser idèntic a l'entrada."""
    draft = composer.compose(PARAGRAPH)
    assert draft.assemble() == PARAGRAPH
    chosen = {draft.sentences[0].index: "Frase nova."}
    assembled = draft.assemble(chosen)
    assert assembled.startswith("Frase nova.")
    assert draft.sentences[1].source_text in assembled


def test_every_rewrite_passed_the_validators(composer: Composer, pipeline: Pipeline) -> None:
    """La pantalla no relaxa res: el que s'ofereix ja ha passat la validació."""
    draft = composer.compose(PARAGRAPH)
    for sentence in draft.sentences:
        result = next(s for s in pipeline.run(PARAGRAPH).sentences if s.index == sentence.index)
        accepted = {e.candidate.text for e in result.candidates if e.accepted}
        for option in sentence.options:
            assert option.text in accepted


def test_the_composition_is_deterministic(composer: Composer) -> None:
    first = composer.compose(PARAGRAPH).to_dict()
    second = composer.compose(PARAGRAPH).to_dict()
    assert first == second


# --- el servei i l'API -------------------------------------------------------------------


def test_the_request_rejects_an_impossible_number_of_options() -> None:
    with pytest.raises(ConfigError):
        ComposeRequest.from_mapping({"text": "Plou.", "wanted": 0})
    with pytest.raises(ConfigError):
        ComposeRequest.from_mapping({"text": "Plou.", "wanted": 99})
    with pytest.raises(ConfigError):
        ComposeRequest.from_mapping({"text": "  "})
    assert ComposeRequest.from_mapping({"text": "Plou.", "wanted": "2"}).wanted == 2


def test_the_service_returns_what_the_screen_needs(project_root: Path) -> None:
    service = RewriteService(ProjectPaths(project_root))
    payload = service.compose(ComposeRequest.from_mapping({"text": PARAGRAPH, "wanted": 3}))
    assert payload["n_sentences"] == 2
    assert payload["wanted"] == 3
    assert "state" in payload["thesaurus"]
    for sentence in payload["sentences"]:
        assert sentence["options"], "cada frase ha de portar com a mínim l'original"
        for option in sentence["options"]:
            assert set(option) >= {"option_id", "text", "original", "tokens", "summary"}
            for token in option["tokens"]:
                assert token["end"] > token["start"]
                assert option["text"][token["start"] : token["end"]] == token["text"]
                assert token["groups"], "un fragment sense grups no s'hauria d'oferir"


def test_the_token_spans_allow_a_safe_substitution(project_root: Path) -> None:
    """La interfície talla i enganxa per posicions: han de quadrar amb el text."""
    service = RewriteService(ProjectPaths(project_root))
    payload = service.compose(ComposeRequest.from_mapping({"text": PARAGRAPH}))
    option = payload["sentences"][0]["options"][0]
    text = option["text"]
    for token in option["tokens"]:
        replacement = token["groups"][0]["options"][0]["text"]
        edited = text[: token["start"]] + replacement + text[token["end"] :]
        assert edited != text
        assert edited.startswith(text[: token["start"]])


def test_the_options_and_draft_serialise_without_losing_anything() -> None:
    option = DraftOption(option_id="s0-o", text="Plou.", original=True, summary="cap canvi")
    draft = SentenceDraft(index=0, source_text="Plou.", options=(option,), note="nota")
    data = draft.to_dict()
    assert data["n_rewrites"] == 0
    assert data["note"] == "nota"
    assert data["options"][0]["option_id"] == "s0-o"
    assert data["options"][0]["editable"] is False


# --- la ruta HTTP ------------------------------------------------------------------------


def test_the_route_answers_over_http(project_root: Path, tmp_path: Path) -> None:
    """La pantalla parla amb el servidor local: la ruta ha d'existir i respondre."""
    import json
    import threading
    import urllib.request

    from parafrasi_cat.web import HistoryLog
    from parafrasi_cat.web.server import build_server

    service = RewriteService(
        ProjectPaths(project_root), history=HistoryLog(tmp_path / "registre.jsonl")
    )
    server = build_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/api/compose"
        request = urllib.request.Request(  # noqa: S310 - servidor local del test
            url,
            data=json.dumps({"text": PARAGRAPH, "wanted": 2}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            assert response.status == 200
            payload = json.loads(response.read())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert payload["n_sentences"] == 2
    assert payload["wanted"] == 2
    assert all(sentence["options"] for sentence in payload["sentences"])


def test_the_interface_ships_the_composition_screen() -> None:
    """La pestanya, les plantilles i el desplegable han de ser al fitxer que se serveix."""
    from parafrasi_cat.web.server import STATIC_DIR

    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for marca in (
        'id="pestanya-compon"',
        'id="vista-compon"',
        'id="frases"',
        'id="compon-final"',
        'id="plantilla-frase"',
        'id="plantilla-redaccio"',
        'id="desplegable"',
    ):
        assert marca in html, marca
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "/api/compose" in script
    assert "thesaurus" in script
