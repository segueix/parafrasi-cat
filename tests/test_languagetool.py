"""Fase 8A: validació local amb LanguageTool i garantia de funcionament fora de línia.

Els tests d'integració se salten si LanguageTool no està instal·lat. Els que
comproven que el motor funciona sense ell, que l'adaptador no toca mai el text
i que no s'obre cap connexió s'executen sempre.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from parafrasi_cat import PipelineConfig, build_pipeline
from parafrasi_cat.adapters.languagetool import (
    DEFAULT_BLOCKING_CATEGORIES,
    LanguageToolClient,
    LanguageToolInstallation,
    LanguageToolMatch,
    LanguageToolValidator,
    find_installation,
    find_java,
    is_blocking,
)
from parafrasi_cat.adapters.status import resources_status
from parafrasi_cat.candidates import Candidate
from parafrasi_cat.pipeline.builder import build_languagetool_validator
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.validation import ValidationContext, ValidationSeverity

CORRECT = "Aquest sarcòfag presenta dos cranis."
INCORRECT = "Aquests sarcòfags presenta dos cranis."


@pytest.fixture(scope="module")
def client(project_root: Path) -> LanguageToolClient:
    found = LanguageToolClient.discover(project_root)
    if not found.available:
        pytest.skip(
            "LanguageTool no està instal·lat. Executeu: python scripts/install_languagetool.py"
        )
    return found


# --- opcional: el motor no en depèn ----------------------------------------------------------


def test_engine_works_without_languagetool(project_root: Path) -> None:
    """Sense LanguageTool el motor continua reescrivint amb els validadors interns."""
    config = PipelineConfig(rule_set="parafrasi", level=1)
    pipeline = build_pipeline(config)
    assert "languagetool" not in [v.validator_id for v in pipeline.validators]
    result = pipeline.run(CORRECT)
    assert result.output_text
    assert {"grammar", "protected_spans", "epistemic"} <= {
        v.validator_id for v in pipeline.validators
    }


def test_unavailable_client_says_so_and_stays_silent() -> None:
    empty = LanguageToolClient(None)
    assert empty.available is False
    assert "no instal·lat" in empty.describe()
    assert empty.check(INCORRECT) == ()
    assert empty.check_many([CORRECT, INCORRECT]) == ((), ())
    assert empty.check_many([]) == ()
    validator = LanguageToolValidator(empty)
    assert validator.available is False
    result = validator.validate(Candidate(0, CORRECT, INCORRECT), ValidationContext(CORRECT))
    assert result.ok and result.issues == ()


def test_validator_is_only_added_when_requested(project_root: Path) -> None:
    paths = ProjectPaths(project_root)
    assert build_languagetool_validator(PipelineConfig(), paths) is None
    requested = build_languagetool_validator(PipelineConfig(languagetool=True), paths)
    if find_installation(project_root) is None:
        assert requested is None  # demanat però no instal·lat: el motor continua igual
    else:
        assert requested is not None and requested.available


def test_detection_reports_a_readable_state(project_root: Path) -> None:
    status = resources_status(project_root)
    assert status.morphology.state in ("activa", "reserva")
    assert status.languagetool.state in ("actiu", "no instal·lat")
    assert status.java.state in ("disponible", "no instal·lat")
    for component in (status.morphology, status.languagetool, status.java):
        assert component.message and not component.message.startswith("Traceback")
    assert "Morfologia catalana" in status.summary()
    serialised = status.to_dict()["languagetool"]
    assert isinstance(serialised, dict) and serialised["state"] == status.languagetool.state
    # Sense Java no hi pot haver LanguageTool.
    if find_java() is None:
        assert not status.languagetool.active


# --- política de bloqueig ---------------------------------------------------------------------


def test_blocking_policy_covers_catalan_agreement_rules() -> None:
    """Les regles catalanes de concordança sovint no porten «issueType»."""
    agreement = LanguageToolMatch(
        rule_id="CONCORD_SUBJECTE_VERB",
        message="Possible error de concordança.",
        offset=0,
        length=5,
        issue_type="uncategorized",
        category="CONCORDANCES_SUBJECT_VERB",
    )
    assert is_blocking(agreement) and agreement.blocking
    grammar = LanguageToolMatch("SON_BONIC", "…", 0, 3, issue_type="grammar", category="CONFUSIONS")
    assert is_blocking(grammar)
    style = LanguageToolMatch("ESTIL", "…", 0, 3, issue_type="style", category="ESTIL")
    assert not is_blocking(style)
    assert "CONCORDANCES" in DEFAULT_BLOCKING_CATEGORIES
    assert style.to_dict()["rule_id"] == "ESTIL"
    assert agreement.describe().startswith("[CONCORD_SUBJECTE_VERB]")


# --- integració real (només si LanguageTool està instal·lat) ---------------------------------


def test_installation_is_local(client: LanguageToolClient) -> None:
    installation = client.installation
    assert isinstance(installation, LanguageToolInstallation)
    assert installation.jar.is_file() and installation.java.is_file()
    assert installation.jar.name == "languagetool-commandline.jar"
    assert "LanguageTool" in client.describe()


def test_agreement_error_is_detected(client: LanguageToolClient) -> None:
    bad, good = client.check_many([INCORRECT, CORRECT])
    assert any(match.blocking for match in bad), bad
    assert any("concordança" in match.message.lower() for match in bad)
    assert not any(match.blocking for match in good), good


def test_validator_discards_the_incorrect_candidate_only(client: LanguageToolClient) -> None:
    validator = LanguageToolValidator(client)
    rejected = validator.validate(Candidate(0, CORRECT, INCORRECT), ValidationContext(CORRECT))
    assert not rejected.ok
    assert rejected.errors[0].validator_id == "languagetool"
    assert rejected.errors[0].severity is ValidationSeverity.ERROR
    kept = validator.validate(
        Candidate(0, CORRECT, "En aquest sarcòfag apareixen dos cranis."),
        ValidationContext(CORRECT),
    )
    assert kept.ok
    # El candidat idèntic a l'original no es comprova mai.
    assert validator.validate(Candidate.identity(0, CORRECT), ValidationContext(CORRECT)).ok


def test_problems_already_in_the_original_do_not_penalise(client: LanguageToolClient) -> None:
    validator = LanguageToolValidator(client)
    result = validator.validate(
        Candidate(0, INCORRECT, INCORRECT + " "), ValidationContext(INCORRECT)
    )
    assert result.ok, [i.message for i in result.issues]


def test_languagetool_never_modifies_the_text(client: LanguageToolClient) -> None:
    """L'adaptador només informa: el text que entra és el que surt."""
    original = INCORRECT
    matches = client.check(original)
    assert matches and original == INCORRECT
    # Encara que LanguageTool proposi substitucions, el motor no les aplica.
    assert any(match.replacements for match in matches)
    validator = LanguageToolValidator(client)
    candidate = Candidate(0, CORRECT, INCORRECT)
    validator.validate(candidate, ValidationContext(CORRECT))
    assert candidate.text == INCORRECT
    config = PipelineConfig(rule_set="parafrasi", level=1, languagetool=True)
    result = build_pipeline(config).run(CORRECT)
    for evaluated in result.sentences[0].candidates:
        applied = {t.text_after for t in evaluated.candidate.transformations}
        assert all(not text.startswith("LanguageTool") for text in applied)


def test_batch_check_attributes_matches_to_the_right_text(client: LanguageToolClient) -> None:
    texts = [CORRECT, INCORRECT, CORRECT]
    results = client.check_many(texts)
    assert len(results) == 3
    assert not any(m.blocking for m in results[0])
    assert any(m.blocking for m in results[1])
    assert not any(m.blocking for m in results[2])
    for match in results[1]:
        assert 0 <= match.offset <= len(INCORRECT)


# --- fora de línia -----------------------------------------------------------------------------


def test_a_normal_rewrite_never_opens_a_network_connection(
    monkeypatch: pytest.MonkeyPatch, project_root: Path
) -> None:
    """Durant una sessió normal de parafraseig no s'intenta accedir a Internet."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("s'ha intentat obrir una connexió de xarxa")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)

    config = PipelineConfig(
        rule_set="parafrasi",
        level=3,
        dictionaries=("historia",),
        preferences="author",
        home=project_root,
    )
    result = build_pipeline(config).run(
        "En aquest sarcòfag fet per l’escultor hi ha la presència de dos cranis."
    )
    assert result.changed
    assert result.output_text
