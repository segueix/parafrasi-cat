"""Fase 7: modes de reescriptura, servei local, servidor web i registre de traçabilitat."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest
import yaml

from parafrasi_cat.core import ConfigError, SemanticRisk
from parafrasi_cat.pipeline import PipelineConfig, apply_mode, level_label, mode_settings
from parafrasi_cat.pipeline.builder import build_validators
from parafrasi_cat.pipeline.modes import (
    CONSERVATIVE,
    DEEP,
    PROTECTED_FIELDS,
    RewriteMode,
)
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.web import HistoryLog, RewriteService, word_diff
from parafrasi_cat.web.history import HistoryEntry
from parafrasi_cat.web.server import LOCAL_HOSTS, STATIC_FILES, build_server
from parafrasi_cat.web.service import FeedbackRequest, RewriteRequest

TEXT = "En aquest sarcòfag fet per l’escultor hi ha la presència de dos cranis."


# --- modes -------------------------------------------------------------------------------


def test_mode_settings_and_level_cap() -> None:
    assert mode_settings("conservador") is CONSERVATIVE
    assert mode_settings(RewriteMode.DEEP) is DEEP
    assert CONSERVATIVE.max_semantic_risk is SemanticRisk.LOW
    assert CONSERVATIVE.min_confidence == 0.75
    assert CONSERVATIVE.max_transformations_per_sentence == 1
    assert CONSERVATIVE.candidate_depth == 1
    assert CONSERVATIVE.max_level == 3
    assert DEEP.max_semantic_risk is SemanticRisk.MEDIUM
    assert DEEP.min_confidence is None and DEEP.max_level == 5
    assert DEEP.candidate_depth == 2
    # El mode retalla el nivell demanat, mai no l'amplia.
    assert CONSERVATIVE.level_for(5) == 3 and CONSERVATIVE.level_for(2) == 2
    assert CONSERVATIVE.level_for(None) == 3
    assert DEEP.level_for(5) == 5 and DEEP.level_for(None) == 5 and DEEP.level_for(1) == 1
    with pytest.raises(ConfigError):
        DEEP.level_for(6)
    with pytest.raises(ConfigError):
        RewriteMode.parse("mig")
    assert DEEP.to_dict()["max_level"] == 5 and CONSERVATIVE.to_dict()["id"] == "conservador"
    assert level_label(3) == "3 · sintaxi" and level_label(5) == "5 · paràgraf"
    with pytest.raises(ConfigError):
        level_label(0)


def test_modes_never_relax_protections(paths: ProjectPaths) -> None:
    base = PipelineConfig(
        rule_set="parafrasi",
        protected_terms=("Reial Acadèmia",),
        dictionaries=("historia",),
        preferences="author",
        feedback=Path("preferences/feedback.yml"),
    )
    conservative = apply_mode(base, "conservador", 5)
    deep = apply_mode(base, "profund", 5)
    for field in PROTECTED_FIELDS:
        assert getattr(conservative, field) == getattr(base, field), field
        assert getattr(deep, field) == getattr(base, field), field
    # El mode profund arriba més lluny, però amb el mateix envoltant de seguretat.
    assert conservative.level == 3 and deep.level == 5
    assert conservative.max_semantic_risk is SemanticRisk.LOW
    assert deep.max_semantic_risk is SemanticRisk.MEDIUM
    # I la llista de validadors és idèntica en tots dos modes.
    from parafrasi_cat.analyzer import ClosedClassLexicon, RuleBasedAnalyzer
    from parafrasi_cat.rules import RuleSet, RuleSetConfig

    lexicon = ClosedClassLexicon.load(paths.language())
    analyzer = RuleBasedAnalyzer(lexicon=lexicon)
    empty = RuleSet(RuleSetConfig.empty(), ())
    ids = [
        [v.validator_id for v in build_validators(config, paths, analyzer, lexicon, empty, ("x",))]
        for config in (conservative, deep)
    ]
    assert ids[0] == ids[1]
    assert {"protected_spans", "protected_terms", "epistemic", "numeric_invariants"} <= set(ids[0])


def test_conservative_keeps_the_original_when_nothing_is_clearly_safe(
    service: RewriteService,
) -> None:
    long_text = (
        "La primera referència itàlica és el monument funerari d’Oddo Altoviti, "
        "encarregat el 1507 i finalitzat el 1516."
    )
    conservative = service.rewrite(RewriteRequest(long_text, mode=RewriteMode.CONSERVATIVE))
    deep = service.rewrite(RewriteRequest(long_text, mode=RewriteMode.DEEP))
    assert conservative["output_text"] == long_text
    assert conservative["changed"] is False
    assert deep["changed"] is True
    # El mode conservador avalua menys candidats i no combina transformacions.
    assert conservative["n_candidates"] < deep["n_candidates"]
    for unit in conservative["units"]:
        for candidate in unit["candidates"]:
            assert len(candidate["rules"]) <= 1
            for rule in candidate["rules"]:
                assert rule["semantic_risk"] in ("none", "low")
                assert rule["confidence"] >= 0.75


def test_conservative_still_applies_a_clearly_safe_change(service: RewriteService) -> None:
    request = RewriteRequest(
        "Van trobar un fèretre de pedra a la cripta.",
        mode=RewriteMode.CONSERVATIVE,
        dictionaries=("historia",),
    )
    result = service.rewrite(request)
    assert result["output_text"] == "Van trobar un sarcòfag de pedra a la cripta."
    assert result["mode"]["id"] == "conservador"


# --- diferències -------------------------------------------------------------------------


def test_word_diff() -> None:
    parts = word_diff("hi ha la presència de dos cranis", "apareixen dos cranis")
    assert [(p.op, p.text) for p in parts] == [
        ("delete", "hi ha la presència de"),
        ("insert", "apareixen"),
        ("equal", " dos cranis"),
    ]
    assert word_diff("igual", "igual") == (word_diff("igual", "igual")[0],)
    assert [p.op for p in word_diff("igual", "igual")] == ["equal"]
    assert "".join(p.text for p in word_diff("a b", "a b") if p.op != "insert") == "a b"
    assert word_diff("", "") == ()
    assert [p.to_dict() for p in word_diff("a", "a b")] == [
        {"op": "equal", "text": "a"},
        {"op": "insert", "text": " b"},
    ]


# --- servei ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def service(project_root: Path) -> RewriteService:
    return RewriteService(ProjectPaths(project_root))


def test_options_list_every_selector(service: RewriteService) -> None:
    options = service.options()
    assert [level["level"] for level in options["levels"]] == [1, 2, 3, 4, 5]
    assert [mode["id"] for mode in options["modes"]] == ["conservador", "profund"]
    profiles = {profile["id"]: profile for profile in options["style_profiles"]}
    assert "default" in profiles and profiles["default"]["kind"] == "profile"
    assert all("error" not in profile for profile in profiles.values())
    dictionaries = {item["id"]: item for item in options["dictionaries"]}
    assert {"historia", "escacs", "medieval", "general", "noms_propis"} <= set(dictionaries)
    assert dictionaries["historia"]["n_entries"] >= 1
    assert dictionaries["historia"]["n_protected"] >= 1
    assert all("error" not in item for item in dictionaries.values())
    preferences = [item["id"] for item in options["preferences"]]
    assert "author" in preferences and "feedback" not in preferences
    assert options["history"]["enabled"] is False
    assert options["version"] and options["rule_set"] == "parafrasi"


def test_options_report_the_linguistic_mode_and_its_installers(service: RewriteService) -> None:
    """La interfície ha de poder dir en quin mode treballa i què li falta."""
    options = service.options()
    mode = options["resources"]["mode"]
    assert mode["id"] in ("complet", "basic")
    assert mode["full"] is (mode["id"] == "complet")
    assert mode["label"].startswith("Mode lingüístic complet" if mode["full"] else "Mode bàsic")
    installers = options["installers"]
    assert {"morphology", "parser", "languagetool"} <= set(installers)
    for component in mode["installable"]:
        info = installers[component]
        assert info["origin"] and info["license"] and info["approximate_size_mb"]
        assert info["offline_after_install"] is True


def test_nothing_is_downloaded_without_an_explicit_confirmation(
    service: RewriteService,
) -> None:
    response = service.install_component("morphology", confirmed=False)
    assert response["started"] is False
    assert "confirmar" in response["message"]
    assert response["origin"].startswith("https://github.com/Softcatala/")


def test_rewrite_exposes_everything_the_interface_shows(service: RewriteService) -> None:
    result = service.rewrite(
        RewriteRequest(TEXT, mode=RewriteMode.DEEP, level=3, dictionaries=("historia",))
    )
    assert result["source_text"] == TEXT and result["changed"] is True
    assert result["level"] == 3 and result["level_capped"] is False
    assert result["level_label"] == "3 · sintaxi"
    assert result["dictionaries"] == ["historia"]
    assert any(span["text"] == "sarcòfag" for span in result["protected_spans"])
    assert all(
        {"text", "kind", "label", "start", "end"} <= set(s) for s in result["protected_spans"]
    )
    unit = result["units"][0]
    assert unit["unit_id"] == "s0" and unit["kind"] == "sentence" and unit["label"] == "Frase 1"
    assert unit["source_text"] == TEXT
    identity = unit["candidates"][0]
    assert identity["is_identity"] and identity["rules"] == []
    changed = next(c for c in unit["candidates"] if not c["is_identity"] and c["accepted"])
    assert changed["candidate_id"].startswith("s0-")
    assert isinstance(changed["score"]["total"], float)
    assert set(changed["score"]["dimensions"]) and "explanation" in changed["score"]
    selected = next(c for c in unit["candidates"] if c["selected"])
    assert selected["accepted"] and selected["score"]["total"] > 0
    assert changed["rules"] and changed["rules"][0]["rule_id"]
    assert changed["rules"][0]["semantic_risk"] in ("none", "low", "medium", "high")
    assert any(part["op"] != "equal" for part in changed["diff"])
    assert "".join(p["text"] for p in changed["diff"] if p["op"] != "delete") == changed["text"]
    assert "".join(p["text"] for p in changed["diff"] if p["op"] != "insert") == unit["source_text"]
    assert isinstance(changed["warnings"], list) and isinstance(changed["errors"], list)
    assert any(c["selected"] for c in unit["candidates"])


def test_level_is_capped_by_the_mode(service: RewriteService) -> None:
    result = service.rewrite(RewriteRequest(TEXT, mode=RewriteMode.CONSERVATIVE, level=5))
    assert result["level"] == 3 and result["requested_level"] == 5
    assert result["level_capped"] is True
    assert result["mode"]["max_level"] == 3


def test_request_validation() -> None:
    with pytest.raises(ConfigError):
        RewriteRequest("   ")
    with pytest.raises(ConfigError):
        RewriteRequest("x" * 20001)
    with pytest.raises(ConfigError):
        RewriteRequest.from_mapping({"text": "hola", "level": "alt"})
    with pytest.raises(ConfigError):
        RewriteRequest.from_mapping({"text": "hola", "mode": "mig"})
    with pytest.raises(ConfigError):
        RewriteRequest.from_mapping({"text": "hola", "dictionaries": 3})
    request = RewriteRequest.from_mapping(
        {"text": "hola", "level": "3", "dictionaries": ["historia"], "mode": "conservador"}
    )
    assert request.level == 3 and request.dictionaries == ("historia",)
    assert request.mode is RewriteMode.CONSERVATIVE
    assert RewriteRequest.from_mapping({"text": "hola"}).level is None
    assert RewriteRequest.from_mapping({"text": "hola", "level": ""}).level is None
    with pytest.raises(ConfigError):
        FeedbackRequest(verdict="meh")


def test_introduced_variants_bridge_candidates_and_feedback(service: RewriteService) -> None:
    assert service.introduced_variants(TEXT, TEXT) == ()
    changed = TEXT.replace("fet per", "obra de").replace("hi ha la presència de", "apareixen")
    variants = service.introduced_variants(TEXT, changed)
    assert "obra de" in variants and "apareix" in variants
    assert "fet per" not in variants


# --- feedback i historial aïllats en un projecte temporal -------------------------------


@pytest.fixture
def temporary_project(tmp_path: Path, project_root: Path) -> ProjectPaths:
    """Arrel de projecte amb els recursos enllaçats i preferències escrivibles."""
    root = tmp_path / "projecte"
    root.mkdir()
    for name in ("resources", "rules", "dictionaries", "corpus", "style"):
        (root / name).symlink_to(project_root / name, target_is_directory=True)
    (root / "preferences").mkdir()
    (root / "preferences" / "author.yml").write_text(
        yaml.safe_dump(
            {"name": "prova", "preferred_variants": {"obra de": 1.0}, "feedback": "feedback.yml"},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return ProjectPaths(root)


def test_feedback_is_recorded_for_the_variants_a_candidate_introduces(
    temporary_project: ProjectPaths,
) -> None:
    service = RewriteService(temporary_project)
    changed = TEXT.replace("fet per", "obra de")
    response = service.record_feedback(
        FeedbackRequest(verdict="preferred", text=changed, source_text=TEXT, preferences="author")
    )
    assert [item["variant"] for item in response["recorded"]] == ["obra de"]
    assert response["recorded"][0]["preferred"] == 1
    assert response["recorded"][0]["weight"] == pytest.approx(0.625)
    file = temporary_project.preferences / "feedback.yml"
    assert file.is_file()
    assert yaml.safe_load(file.read_text(encoding="utf-8"))["variants"]["obra de"]["preferred"] == 1
    # Un segon vot s'acumula, no substitueix.
    again = service.record_feedback(FeedbackRequest(verdict="preferred", variants=("obra de",)))
    assert again["recorded"][0]["preferred"] == 2
    summary = service.feedback_summary()
    assert summary["variants"][0]["variant"] == "obra de"
    assert summary["variants"][0]["preferred"] == 2
    # Un candidat sense cap variant coneguda no registra res.
    empty = service.record_feedback(
        FeedbackRequest(verdict="rejected", text=TEXT, source_text=TEXT)
    )
    assert empty["recorded"] == [] and "no s'ha registrat res" in empty["message"]


def test_feedback_invalidates_the_pipeline_cache(temporary_project: ProjectPaths) -> None:
    service = RewriteService(temporary_project)
    request = RewriteRequest(TEXT, preferences="author")
    service.rewrite(request)
    assert service._pipelines  # noqa: SLF001 - comprovació de la cau interna
    service.record_feedback(FeedbackRequest(verdict="rejected", variants=("obra de",)))
    assert not service._pipelines  # noqa: SLF001


def test_history_is_optional_and_writes_nothing_when_disabled(tmp_path: Path) -> None:
    file = tmp_path / "registre.jsonl"
    log = HistoryLog(file)
    assert log.enabled is False and log.status()["exists"] is False
    assert log.append({"source_text": "text confidencial"}) is None
    assert not file.exists()
    assert log.entries() == () and len(log) == 0

    log.enable()
    entry = log.append({"source_text": "text", "config": {"mode": "profund", "level": 5}})
    assert entry is not None and entry.entry_id and entry.timestamp
    assert file.is_file()
    stored = log.entries()
    assert len(stored) == 1 and stored[0].source_text == "text"
    assert stored[0].summary()["mode"] == "profund"
    assert json.loads(file.read_text(encoding="utf-8").splitlines()[0])["source_text"] == "text"

    log.enable(False)
    assert log.append({"source_text": "no s'ha de desar"}) is None
    assert len(log.entries()) == 1

    log.enable()
    log.append(HistoryEntry("id2", "2026-01-01T00:00:00+00:00", "segon", final_text="editat"))
    assert [e.entry_id for e in log] == [stored[0].entry_id, "id2"]
    exported = log.export(tmp_path / "export.json")
    assert len(json.loads(exported.read_text(encoding="utf-8"))) == 2
    assert len(json.loads(log.export_json())) == 2
    assert log.status()["n_entries"] == 2
    log.clear()
    assert log.entries() == () and not file.exists()


def test_history_reports_a_corrupt_file(tmp_path: Path) -> None:
    from parafrasi_cat.core import ResourceError

    file = tmp_path / "registre.jsonl"
    file.write_text('{"source_text": "ok"}\nno és json\n', encoding="utf-8")
    with pytest.raises(ResourceError):
        HistoryLog(file, enabled=True).entries()


def test_service_history_round_trip(temporary_project: ProjectPaths, tmp_path: Path) -> None:
    file = tmp_path / "registre.jsonl"
    log = HistoryLog(file)
    service = RewriteService(temporary_project, history=log)
    # Un registre buit té longitud 0: el servei l'ha de conservar igualment.
    assert service.history is log
    assert service.options()["history"]["path"] == str(file)
    assert service.save_history({"source_text": "text"})["saved"] is False
    assert service.set_history_enabled(True)["enabled"] is True
    saved = service.save_history(
        {
            "source_text": TEXT,
            "config": {"mode": "profund", "level": 5, "dictionaries": ["historia"]},
            "result": {"output_text": "..."},
            "final_text": "text editat a mà",
            "feedback": [{"verdict": "preferred", "variant": "obra de"}],
        }
    )
    assert saved["saved"] is True and saved["entry_id"]
    assert file.is_file(), "el registre s'ha d'escriure al fitxer indicat"
    assert not (temporary_project.root / "history").exists()
    listed = service.history_entries()
    assert listed["n_entries"] == 1
    assert listed["entries"][0]["mode"] == "profund"
    assert listed["entries"][0]["n_feedback"] == 1
    exported = json.loads(service.history_export())
    assert exported[0]["final_text"] == "text editat a mà"
    assert exported[0]["config"]["dictionaries"] == ["historia"]


# --- servidor ----------------------------------------------------------------------------


@pytest.fixture
def history_file(tmp_path: Path) -> Path:
    return tmp_path / "registre.jsonl"


@pytest.fixture
def server_url(temporary_project: ProjectPaths, history_file: Path) -> Iterator[str]:
    service = RewriteService(temporary_project, history=HistoryLog(history_file))
    server = build_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def fetch(
    url: str, payload: object = None, headers: dict[str, str] | None = None
) -> tuple[int, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers or {})
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
            if "json" in response.headers.get("Content-Type", ""):
                return response.status, json.loads(body)
            return response.status, body
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_server_serves_the_page_and_static_files(server_url: str) -> None:
    status, body = fetch(f"{server_url}/")
    assert status == HTTPStatus.OK
    assert isinstance(body, bytes) and b"<title>parafrasi-cat</title>" in body
    # La pàgina no carrega res de fora: cap URL absoluta als fitxers estàtics.
    for name in STATIC_FILES:
        status, content = fetch(f"{server_url}/static/{name}")
        assert status == HTTPStatus.OK and isinstance(content, bytes) and content
        assert b"http://" not in content and b"https://" not in content
    assert fetch(f"{server_url}/static/../secret")[0] == HTTPStatus.NOT_FOUND
    assert fetch(f"{server_url}/static/altre.js")[0] == HTTPStatus.NOT_FOUND
    assert fetch(f"{server_url}/inexistent")[0] == HTTPStatus.NOT_FOUND


def test_server_api(server_url: str) -> None:
    status, options = fetch(f"{server_url}/api/options")
    assert status == HTTPStatus.OK and isinstance(options, dict)
    assert [mode["id"] for mode in options["modes"]] == ["conservador", "profund"]

    status, result = fetch(
        f"{server_url}/api/rewrite",
        {"text": TEXT, "mode": "profund", "level": 3, "dictionaries": ["historia"]},
    )
    assert status == HTTPStatus.OK and isinstance(result, dict)
    assert result["changed"] is True and result["units"]

    status, error = fetch(f"{server_url}/api/rewrite", {"text": ""})
    assert status == HTTPStatus.BAD_REQUEST and error["error"]
    status, error = fetch(f"{server_url}/api/rewrite", {"text": "hola", "mode": "mig"})
    assert status == HTTPStatus.BAD_REQUEST
    assert fetch(f"{server_url}/api/desconegut", {})[0] == HTTPStatus.NOT_FOUND


def test_server_feedback_and_history(server_url: str, history_file: Path) -> None:
    changed = TEXT.replace("fet per", "obra de")
    status, response = fetch(
        f"{server_url}/api/feedback",
        {"verdict": "preferred", "text": changed, "source_text": TEXT},
    )
    assert status == HTTPStatus.OK and isinstance(response, dict)
    assert [item["variant"] for item in response["recorded"]] == ["obra de"]
    assert fetch(f"{server_url}/api/feedback")[1]["variants"][0]["variant"] == "obra de"

    assert fetch(f"{server_url}/api/history")[1]["enabled"] is False
    assert fetch(f"{server_url}/api/history", {"source_text": TEXT})[1]["saved"] is False
    assert not history_file.exists(), "amb el registre desactivat no s'ha d'escriure res"
    assert fetch(f"{server_url}/api/history/enabled", {"enabled": True})[1]["enabled"] is True
    assert fetch(f"{server_url}/api/history", {"source_text": TEXT})[1]["saved"] is True
    assert history_file.is_file(), "el registre s'ha d'escriure al fitxer indicat"
    status, listed = fetch(f"{server_url}/api/history")
    assert listed["n_entries"] == 1
    status, exported = fetch(f"{server_url}/api/history/export")
    assert status == HTTPStatus.OK and exported[0]["source_text"] == TEXT


def test_server_rejects_non_local_hosts(server_url: str) -> None:
    assert "localhost" in LOCAL_HOSTS and "127.0.0.1" in LOCAL_HOSTS
    status, _ = fetch(f"{server_url}/api/options", headers={"Host": "atacant.example"})
    assert status == HTTPStatus.FORBIDDEN
    status, _ = fetch(f"{server_url}/api/options", headers={"Host": "localhost:1234"})
    assert status == HTTPStatus.OK
