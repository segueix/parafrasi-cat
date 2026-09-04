"""v1.0: nivell 5 real, funcionament fora de línia i reutilització de components.

La prova de xarxa és la garantia central del projecte: durant una sessió normal
no s'ha d'obrir cap connexió que no sigui amb aquest mateix ordinador.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from parafrasi_cat import PipelineConfig, __version__, build_pipeline
from parafrasi_cat.adapters.languagetool import LOOPBACK_HOSTS, LanguageToolClient
from parafrasi_cat.preferences.feedback import FeedbackStore
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.web import HistoryLog, RewriteService
from parafrasi_cat.web.server import build_server
from parafrasi_cat.web.service import RewriteRequest

ALTOVITI = (
    "La primera referència itàlica és el monument funerari d’Oddo Altoviti, encarregat el 1507 "
    "i finalitzat el 1516. En aquest sarcòfag fet per l’escultor Benedetto da Rovezzano hi ha la "
    "presència de dos cranis acompanyats de dos ossos creuats, així com dues serps també creuades."
)
FACTS = ("Oddo Altoviti", "1507", "1516", "Benedetto da Rovezzano", "dos cranis")


# --- el nivell 5 és realment diferent del 4 --------------------------------------------------


@pytest.fixture(scope="module")
def levels(project_root: Path) -> dict[int, Any]:
    return {
        level: build_pipeline(PipelineConfig(rule_set="parafrasi", level=level, home=project_root))
        for level in (4, 5)
    }


def test_level_five_adds_the_paragraph_phase(levels: dict[int, Any]) -> None:
    """Cas 1: el nivell 4 treballa dins de la frase; el 5 reestructura el paràgraf."""
    assert levels[4].rule_set.paragraph_rules == ()
    assert len(levels[5].rule_set.paragraph_rules) == 2
    assert {r.level for r in levels[5].rule_set.paragraph_rules} == {5}
    only_five = set(levels[5].rule_set.rule_ids) - set(levels[4].rule_set.rule_ids)
    # Des de la 1.3.1 la fusió copulativa («no és només A. És B.» → «…, sinó també B») és la
    # segona regla de paràgraf exclusiva del nivell 5.
    assert only_five == {"fusio.frases_compatibles", "fusio.copulativa"}


def test_level_five_produces_paragraph_candidates(levels: dict[int, Any]) -> None:
    """Cas 2: sobre el mateix text, només el nivell 5 proposa reestructurar el paràgraf."""
    four = levels[4].run(ALTOVITI)
    five = levels[5].run(ALTOVITI)
    assert four.paragraphs == ()
    assert five.paragraphs and five.paragraphs[0].alternatives
    assert any(", i en aquest sarcòfag" in alt for alt in five.paragraphs[0].alternatives)
    assert five.n_candidates > four.n_candidates


def test_level_five_preserves_everything(levels: dict[int, Any]) -> None:
    """Reestructurar el paràgraf no relaxa cap protecció."""
    five = levels[5].run(ALTOVITI)
    units = [*five.sentences, *five.paragraphs]
    for unit in units:
        for evaluated in unit.candidates:
            if not evaluated.accepted:
                continue
            text = evaluated.candidate.text
            source = evaluated.candidate.source_text
            for fact in FACTS:
                if fact in source:
                    assert fact in text, (fact, text)
            assert "creuats" in text or "creuats" not in source
            assert not text.startswith("La primera referència itàlica constitueix el monument")
    for fact in FACTS:
        assert fact in five.output_text


# --- reutilització de components ---------------------------------------------------------------


def test_components_are_reused_across_rewrites(project_root: Path) -> None:
    """El model i el servidor s'han de carregar una vegada, no a cada reescriptura."""
    service = RewriteService(ProjectPaths(project_root))
    request = RewriteRequest(ALTOVITI, level=3)

    start = time.perf_counter()
    service.rewrite(request)
    first = time.perf_counter() - start

    start = time.perf_counter()
    service.rewrite(request)
    second = time.perf_counter() - start

    start = time.perf_counter()
    service.rewrite(request)
    third = time.perf_counter() - start

    # La primera paga la construcció de la canonada; les següents la reutilitzen.
    assert second < first, (first, second)
    assert third < first, (first, third)
    assert len(service._pipelines) == 1  # noqa: SLF001 - comprovació de la reutilització


def test_languagetool_server_is_started_once(project_root: Path) -> None:
    client = LanguageToolClient.discover(project_root)
    if not client.available:
        pytest.skip("LanguageTool no està instal·lat")
    try:
        assert client.start()
        server = client.server
        assert server is not None and server.running
        port = server.port
        client.check("Aquest sarcòfag presenta dos cranis.")
        client.check("Aquests sarcòfags presenta dos cranis.")
        # El mateix servidor i el mateix port: no s'arrenca cap màquina virtual nova.
        assert server.port == port and server.running
        # La memòria cau evita repetir la mateixa pregunta.
        before = client.statistics["checks"]
        client.check("Aquest sarcòfag presenta dos cranis.")
        assert client.statistics["checks"] == before
        assert client.statistics["cache_hits"] >= 1
    finally:
        client.close()
    assert client.server is not None and not client.server.running


# --- fora de línia -------------------------------------------------------------------------------


class LoopbackSocket(socket.socket):
    """Endoll que només deixa connectar amb aquest mateix ordinador."""

    def connect(self, address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else str(address)
        if str(host) not in LOOPBACK_HOSTS:
            raise AssertionError(f"s'ha intentat connectar fora de l'ordinador: {host}")
        super().connect(address)


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Bloqueja qualsevol connexió que no sigui de bucle local."""

    def no_internet(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("s'ha intentat accedir a Internet")

    real_create = socket.create_connection

    def guarded_create(address: Any, *args: Any, **kwargs: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else str(address)
        if str(host) not in LOOPBACK_HOSTS:
            raise AssertionError(f"s'ha intentat connectar fora de l'ordinador: {host}")
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", LoopbackSocket)
    monkeypatch.setattr(socket, "create_connection", guarded_create)
    monkeypatch.setattr(urllib.request, "urlopen", no_internet)
    yield


def test_full_session_works_offline(offline: None, project_root: Path, tmp_path: Path) -> None:
    """Amb la xarxa bloquejada, tot el flux normal continua funcionant."""
    paths = ProjectPaths(project_root)
    service = RewriteService(paths, history=HistoryLog(tmp_path / "registre.jsonl"))

    # Opcions, estat dels recursos i mode fora de línia.
    options = service.options()
    assert options["version"] == __version__
    assert options["resources"]["morphology"]["state"] in ("activa", "reserva")
    assert options["resources"]["syntax"]["state"] in ("activa", "reserva")

    # Candidats, morfologia, sintaxi, estil i diccionaris.
    result = service.rewrite(
        RewriteRequest(ALTOVITI, level=5, dictionaries=("historia",), style_profile="formal")
    )
    assert result["changed"] and result["units"]
    for fact in FACTS:
        assert fact in str(result["output_text"])
    candidate = next(c for u in result["units"] for c in u["candidates"] if not c["is_identity"])
    assert candidate["diff"] and candidate["score"] is not None

    # Feedback i exportació.
    feedback_file = tmp_path / "feedback.yml"
    store = FeedbackStore(path=feedback_file)
    store.record("obra de", "preferred")
    store.save()
    assert feedback_file.is_file()
    service.set_history_enabled(True)
    saved = service.save_history(
        {"source_text": ALTOVITI, "final_text": str(result["output_text"])}
    )
    assert saved["saved"]
    assert json.loads(service.history_export())[0]["final_text"]


def test_the_web_answers_offline(offline: None, project_root: Path, tmp_path: Path) -> None:
    """La interfície s'obre i respon amb la xarxa bloquejada."""
    service = RewriteService(ProjectPaths(project_root), history=HistoryLog(tmp_path / "h.jsonl"))
    server = build_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        connection = LoopbackSocket(socket.AF_INET, socket.SOCK_STREAM)
        connection.settimeout(30)
        connection.connect(("127.0.0.1", server.server_address[1]))
        connection.sendall(
            b"GET /api/options HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        )
        chunks = []
        while True:
            data = connection.recv(65536)
            if not data:
                break
            chunks.append(data)
        connection.close()
        body = b"".join(chunks)
        assert b"200 OK" in body
        payload = json.loads(body.split(b"\r\n\r\n", 1)[1].decode("utf-8"))
        assert payload["modes"] and payload["resources"]
        assert base.startswith("http://127.0.0.1")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_no_connection_leaves_the_computer(offline: None, project_root: Path) -> None:
    """Una reescriptura completa, amb tots els components, no surt de l'ordinador."""
    config = PipelineConfig(
        rule_set="parafrasi",
        level=5,
        dictionaries=("historia",),
        preferences="author",
        home=project_root,
        languagetool=LanguageToolClient.discover(project_root).available,
    )
    result = build_pipeline(config).run(ALTOVITI)
    assert result.output_text
    for fact in FACTS:
        assert fact in result.output_text
    with pytest.raises(AssertionError):
        LoopbackSocket(socket.AF_INET, socket.SOCK_STREAM).connect(("example.com", 80))
    with pytest.raises(AssertionError):
        socket.create_connection(("example.com", 80))
    with pytest.raises(AssertionError):
        urllib.request.urlopen("https://example.com")
