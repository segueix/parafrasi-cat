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
    assert len(levels[5].rule_set.paragraph_rules) == 3
    assert {r.level for r in levels[5].rule_set.paragraph_rules} == {5}
    only_five = set(levels[5].rule_set.rule_ids) - set(levels[4].rule_set.rule_ids)
    # El nivell 5 incorpora les dues fusions i la reparació contextual d'un fragment
    # nominal anafòric («... . Un fet que...» → «... . Aquest fet...»).
    assert only_five == {
        "fusio.frases_compatibles",
        "fusio.repara_fragment_anaforic",
        "fusio.copulativa",
    }


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

    # Una reescriptura completa tampoc no toca Internet.
    request = RewriteRequest(ALTOVITI, level=5)
    result = service.rewrite(request)
    assert result["output_text"]

    # El registre local continua funcionant sense xarxa.
    history = service.history
    history.enable()
    saved = history.append({"text": ALTOVITI, "result": result["output_text"]})
    assert saved
    assert history.status()["n_entries"] >= 1

    # El servidor web local és permès perquè només escolta a loopback.
    server = build_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        with urllib.request.urlopen(f"http://{host}:{port}/api/options", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            assert payload["version"] == __version__
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_feedback_persistence_offline(offline: None, project_root: Path, tmp_path: Path) -> None:
    """El feedback continua sent un fitxer local versionable i no necessita xarxa."""
    store = FeedbackStore(tmp_path / "feedback.yaml")
    store.record("variant.prova", "preferred")
    store.record("variant.prova", "acceptable")
    loaded = FeedbackStore.load(store.path)
    assert loaded.variants["variant.prova"].preferred == 1
    assert loaded.variants["variant.prova"].acceptable == 1
