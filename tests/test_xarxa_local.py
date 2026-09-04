"""v1.3: mode de xarxa local segur i idèntic al mode local.

El mode de xarxa local és només transport: el mateix motor, els mateixos
recursos i el mateix resultat. Els tests cobreixen els vuit casos demanats
—mode local sense codi, mode LAN amb codi, codi erroni, sessió, rutes sense
sessió, ruta amb sessió, Host inesperat i determinisme— i, a més, la paritat
lingüística exacta, el funcionament sense Internet i l'absència de qualsevol
client extern al codi del mode.
"""

from __future__ import annotations

import ast
import contextlib
import json
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from http import HTTPStatus
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from parafrasi_cat.resources import ProjectPaths, write_atomically
from parafrasi_cat.syntax.spacy_parser import SpacySyntax
from parafrasi_cat.web import HistoryLog, RewriteService
from parafrasi_cat.web import service as service_module
from parafrasi_cat.web.auth import (
    DEFAULT_SESSION_TTL,
    LOCAL_HOSTS,
    NETWORK_WARNING,
    PIN_DIGITS,
    PRIVACY_NOTES,
    PUBLIC_PATHS,
    SESSION_COOKIE,
    AccessMode,
    AccessPolicy,
    AttemptLimiter,
    ServerStatus,
    SessionStore,
    cookie_header,
    cookie_value,
    expired_cookie,
    generate_pin,
)
from parafrasi_cat.web.cli import build_policy, build_web_parser
from parafrasi_cat.web.server import LAN_HOST, STATIC_FILES, build_server

TEXT = "En aquest sarcòfag fet per l’escultor hi ha la presència de dos cranis."

#: Rutes de l'API que han d'exigir sessió en mode de xarxa local.
GUARDED_GET = ("/api/options", "/api/resources", "/api/feedback", "/api/history")
GUARDED_POST = (
    ("/api/rewrite", {"text": TEXT}),
    ("/api/feedback", {"verdict": "acceptable", "variants": ["obra de"]}),
    ("/api/history", {"source_text": TEXT}),
    ("/api/history/enabled", {"enabled": True}),
    ("/api/fingerprint", {"name": "prova", "texts": ["Un text propi."]}),
    ("/api/resources/install", {"component": "parser", "confirm": False}),
)


class Client:
    """Client HTTP mínim amb galetes, com el navegador del segon dispositiu."""

    def __init__(self, base: str) -> None:
        self.base = base
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(
        self,
        path: str,
        payload: object = None,
        *,
        headers: dict[str, str] | None = None,
        method: str | None = None,
    ) -> tuple[int, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base}{path}", data=data, headers=headers or {}, method=method
        )
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(request, timeout=120) as response:
                body = response.read()
                if "json" in response.headers.get("Content-Type", ""):
                    return response.status, json.loads(body)
                return response.status, body
        except urllib.error.HTTPError as error:
            body = error.read()
            try:
                return error.code, json.loads(body)
            except ValueError:
                return error.code, body

    @property
    def session_token(self) -> str | None:
        return next((c.value for c in self.jar if c.name == SESSION_COOKIE), None)


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory, project_root: Path) -> ProjectPaths:
    """Projecte temporal amb els recursos enllaçats i escriptura aïllada."""
    root = tmp_path_factory.mktemp("xarxa") / "projecte"
    root.mkdir()
    for name in ("resources", "rules", "dictionaries", "corpus", "style"):
        (root / name).symlink_to(project_root / name, target_is_directory=True)
    (root / "preferences").mkdir()
    return ProjectPaths(root)


def start(
    project: ProjectPaths, policy: AccessPolicy, attempts: AttemptLimiter | None = None
) -> Iterator[str]:
    service = RewriteService(project, history=HistoryLog(project.root / "registre.jsonl"))
    server = build_server(service, host="127.0.0.1", port=0, policy=policy, attempts=attempts)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def local_url(project: ProjectPaths) -> Iterator[str]:
    yield from start(project, AccessPolicy.local())


@pytest.fixture(scope="module")
def lan_policy() -> AccessPolicy:
    return AccessPolicy.lan()


@pytest.fixture(scope="module")
def lan_url(project: ProjectPaths, lan_policy: AccessPolicy) -> Iterator[str]:
    yield from start(project, lan_policy)


# --- A: mode local -----------------------------------------------------------------------


def test_local_mode_needs_no_code_and_behaves_as_before(local_url: str) -> None:
    client = Client(local_url)
    status, access = client.request("/api/access")
    assert status == HTTPStatus.OK
    assert access["mode"] == "local" and access["requires_authentication"] is False
    assert access["authenticated"] is True
    assert access["privacy"] == "El text no surt d'aquest ordinador."
    assert access["warning"] == ""
    assert client.request("/")[0] == HTTPStatus.OK
    assert b"<title>parafrasi-cat</title>" in client.request("/")[1]
    for path in GUARDED_GET:
        assert client.request(path)[0] == HTTPStatus.OK, path
    assert client.request("/api/rewrite", {"text": TEXT})[0] == HTTPStatus.OK
    assert client.session_token is None, "en mode local no cal cap sessió"


def test_the_default_policy_is_local_everywhere() -> None:
    assert AccessPolicy().mode is AccessMode.LOCAL
    assert AccessPolicy.local().requires_authentication is False
    parser = build_web_parser()
    assert parser.parse_args([]).lan is False
    assert build_policy(parser.parse_args([])).mode is AccessMode.LOCAL
    assert build_policy(parser.parse_args(["--lan"])).mode is AccessMode.LAN
    with pytest.raises(Exception, match="--lan"):
        build_policy(parser.parse_args(["--pin", "123456"]))


# --- B, C, D, E, F: mode de xarxa local ---------------------------------------------------


def test_lan_mode_serves_the_login_screen_instead_of_the_application(lan_url: str) -> None:
    client = Client(lan_url)
    status, body = client.request("/")
    assert status == HTTPStatus.OK
    assert b"Acc\xc3\xa9s local" in body and b"<title>parafrasi-cat" in body
    assert b"entrada.js" in body and b"app.js" not in body
    status, access = client.request("/api/access")
    assert access["mode"] == "lan" and access["requires_authentication"] is True
    assert access["authenticated"] is False
    assert access["privacy"] == PRIVACY_NOTES[AccessMode.LAN]
    assert "xarxa local" in access["privacy"] and "Internet" in access["privacy"]
    assert access["warning"] == NETWORK_WARNING
    # Els fitxers estàtics són els del paquet i no porten res privat.
    for name in STATIC_FILES:
        assert client.request(f"/static/{name}")[0] == HTTPStatus.OK, name


def test_every_api_route_is_refused_without_a_session(lan_url: str) -> None:
    client = Client(lan_url)
    for path in GUARDED_GET:
        status, error = client.request(path)
        assert status == HTTPStatus.UNAUTHORIZED, path
        assert "codi d'accés" in error["error"]
    for path, payload in GUARDED_POST:
        assert client.request(path, payload)[0] == HTTPStatus.UNAUTHORIZED, path
    assert client.request("/api/history/export")[0] == HTTPStatus.UNAUTHORIZED
    assert client.session_token is None


def test_a_wrong_code_is_refused_and_opens_no_session(
    lan_url: str, lan_policy: AccessPolicy
) -> None:
    client = Client(lan_url)
    wrong = "000000" if lan_policy.pin != "000000" else "111111"
    status, error = client.request("/api/access", {"pin": wrong})
    assert status == HTTPStatus.UNAUTHORIZED
    assert error["error"] == "El codi d'accés no és correcte"
    assert client.session_token is None
    assert client.request("/api/options")[0] == HTTPStatus.UNAUTHORIZED
    assert client.request("/api/access", {})[0] == HTTPStatus.UNAUTHORIZED


def test_the_right_code_opens_a_session_and_unlocks_the_application(
    lan_url: str, lan_policy: AccessPolicy
) -> None:
    client = Client(lan_url)
    status, access = client.request("/api/access", {"pin": lan_policy.pin})
    assert status == HTTPStatus.OK and access["authenticated"] is True
    assert lan_policy.pin not in json.dumps(access), "el codi no pot tornar mai al client"
    token = client.session_token
    assert token and len(token) >= 32
    status, body = client.request("/")
    assert status == HTTPStatus.OK and b"app.js" in body
    for path in GUARDED_GET:
        assert client.request(path)[0] == HTTPStatus.OK, path
    status, result = client.request("/api/rewrite", {"text": TEXT, "level": 3})
    assert status == HTTPStatus.OK and result["units"]
    # Tancar la sessió la invalida immediatament.
    assert client.request("/api/access/close", {})[0] == HTTPStatus.OK
    assert client.request("/api/options")[0] == HTTPStatus.UNAUTHORIZED


def test_a_stolen_or_invented_token_is_useless(lan_url: str) -> None:
    for token in ("", "x", "a" * 43, "../../etc/passwd"):
        client = Client(lan_url)
        status, _ = client.request("/api/options", headers={"Cookie": f"{SESSION_COOKIE}={token}"})
        assert status == HTTPStatus.UNAUTHORIZED, token


# --- G: capçalera Host ---------------------------------------------------------------------


def test_unexpected_hosts_are_refused_in_both_modes(
    local_url: str, lan_url: str, lan_policy: AccessPolicy
) -> None:
    for url in (local_url, lan_url):
        client = Client(url)
        for host in ("atacant.example", "parafrasi.example.com:8765", "255.255.255.256"):
            status, error = client.request("/api/access", headers={"Host": host})
            assert status == HTTPStatus.FORBIDDEN, (url, host)
            assert "xarxa local" in error["error"]
    # El mode local no accepta cap adreça de la LAN; el mode LAN, sí.
    assert AccessPolicy.local().host_allowed("192.168.1.40:8765") is False
    assert lan_policy.host_allowed("192.168.1.40:8765") is True
    assert lan_policy.host_allowed("10.0.0.7") is True
    assert lan_policy.host_allowed("[fe80::1]:8765") is True
    assert lan_policy.host_allowed("8.8.8.8") is False, "una IP pública no és la LAN"
    assert lan_policy.host_allowed("evil.example") is False, "un domini no és mai la LAN"
    for host in LOCAL_HOSTS:
        assert AccessPolicy.local().host_allowed(host) is True, host


# --- H: mateix resultat lingüístic ---------------------------------------------------------


def test_local_and_lan_produce_exactly_the_same_rewriting(
    local_url: str, lan_url: str, lan_policy: AccessPolicy
) -> None:
    """El mode de xarxa local és només transport: no toca res del motor."""
    payload = {
        "text": TEXT,
        "mode": "profund",
        "level": 5,
        "dictionaries": ["historia"],
        "languagetool": False,
    }
    local = Client(local_url)
    remote = Client(lan_url)
    assert remote.request("/api/access", {"pin": lan_policy.pin})[0] == HTTPStatus.OK

    status_local, result_local = local.request("/api/rewrite", payload)
    status_remote, result_remote = remote.request("/api/rewrite", payload)
    assert status_local == status_remote == HTTPStatus.OK
    assert result_local == result_remote

    # I les opcions que decideixen la qualitat també són les mateixes.
    options_local = local.request("/api/options")[1]
    options_remote = remote.request("/api/options")[1]
    for key in ("modes", "levels", "dictionaries", "preferences", "source_modes", "rule_set"):
        assert options_local[key] == options_remote[key], key
    assert options_local["resources"] == options_remote["resources"]


# --- sessions ------------------------------------------------------------------------------


def test_sessions_expire_and_never_touch_the_disk(tmp_path: Path) -> None:
    now = [1000.0]
    store = SessionStore(ttl_seconds=60, clock=lambda: now[0])
    token = store.create()
    assert store.valid(token) and len(store) == 1
    now[0] += 30
    assert store.valid(token), "fer-la servir n'allarga la vida"
    now[0] += 61
    assert not store.valid(token) and len(store) == 0
    other = store.create()
    store.revoke(other)
    assert not store.valid(other)
    store.create()
    store.clear()
    assert len(store) == 0
    assert not list(tmp_path.iterdir()), "cap sessió no s'escriu a disc"
    with pytest.raises(ValueError):
        SessionStore(ttl_seconds=0)


def test_codes_and_tokens_are_unpredictable() -> None:
    codes = {generate_pin() for _ in range(200)}
    assert len(codes) > 150, "el codi ha de canviar entre arrencades"
    assert all(len(code) == PIN_DIGITS and code.isdigit() for code in codes)
    tokens = {SessionStore().create() for _ in range(50)}
    assert len(tokens) == 50
    with pytest.raises(ValueError):
        generate_pin(3)
    policy = AccessPolicy.lan()
    assert policy.pin_matches(policy.pin) and policy.pin_matches(f" {policy.pin} ")
    assert not policy.pin_matches("") and not AccessPolicy.local().pin_matches("")


def test_the_session_cookie_is_locked_down() -> None:
    header = cookie_header("abc", DEFAULT_SESSION_TTL)
    assert "HttpOnly" in header and "SameSite=Strict" in header and "Path=/" in header
    assert f"Max-Age={int(DEFAULT_SESSION_TTL)}" in header
    assert cookie_value(f"altra=1; {SESSION_COOKIE}=abc; x=2") == "abc"
    assert cookie_value("altra=1") is None and cookie_value(None) is None
    assert "Max-Age=0" in expired_cookie()
    assert frozenset({"/api/access"}) == PUBLIC_PATHS


def test_the_startup_banner_shows_the_state_and_the_code() -> None:
    status = ServerStatus(
        mode=AccessMode.LAN,
        port=8765,
        components=(("LanguageTool", "actiu"), ("Parser", "actiu"), ("Morfologia", "activa")),
        pin="583214",
    )
    rendered = status.render()
    for expected in (
        "Mode: Xarxa local",
        "Port: 8765",
        "Autenticació: activa",
        "Motor: actiu",
        "LanguageTool: actiu",
        "Parser: actiu",
        "Morfologia: activa",
        "Codi d'accés: 583214",
    ):
        assert expected in rendered, expected
    local = ServerStatus(mode=AccessMode.LOCAL, port=8765).render()
    assert "Autenticació: no cal" in local and "Codi d'accés" not in local


# --- privacitat i aïllament ----------------------------------------------------------------


#: Mòduls que obririen una connexió cap enfora. Es comprova als imports, no a
#: la prosa: els comentaris del codi sí que poden dir que no n'hi ha cap.
OUTBOUND_MODULES = frozenset(
    {"urllib.request", "http.client", "requests", "httpx", "ftplib", "smtplib", "telnetlib"}
)


def imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_the_network_mode_adds_no_outbound_client() -> None:
    """El servidor només rep connexions: cap client extern, cap túnel, cap servei."""
    for name in ("auth.py", "server.py", "cli.py"):
        source = (Path("src/parafrasi_cat/web") / name).read_text(encoding="utf-8")
        assert not imported_modules(source) & OUTBOUND_MODULES, name
        # L'única URL del mòdul és la del servidor mateix, construïda amb l'amfitrió
        # on escolta: no hi ha cap adreça d'Internet escrita al codi.
        assert "https://" not in source, name
        for line in source.splitlines():
            if "http://" in line:
                assert 'f"http://{' in line, (name, line.strip())
        lowered = source.lower()
        for service in ("ngrok", "cloudflare", "tailscale", "upnp", "port forwarding", "tunnel"):
            assert service not in lowered, (name, service)
        assert "socket.create_connection" not in source, name
    server = (Path("src/parafrasi_cat/web") / "server.py").read_text(encoding="utf-8")
    assert "0.0.0.0" in server, "el mode LAN escolta a totes les interfícies"
    assert LAN_HOST == "0.0.0.0"


def test_the_documentation_never_claims_the_text_stays_on_one_machine_in_lan_mode() -> None:
    assert "no surt" not in PRIVACY_NOTES[AccessMode.LAN]
    assert "xarxa local" in PRIVACY_NOTES[AccessMode.LAN]
    assert "no surt d'aquest ordinador" in PRIVACY_NOTES[AccessMode.LOCAL]
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "cap text no surt mai de l'ordinador" not in readme
    assert "docs/chromebook-dual.md" in readme
    guide = Path("docs/chromebook-dual.md").read_text(encoding="utf-8")
    for expected in ("Crostini", "redirecció de ports", "codi d'accés", "IP"):
        assert expected.lower() in guide.lower(), expected


class LoopbackOnly(socket.socket):
    """Deixa connectar-se a aquesta màquina i barra qualsevol altra adreça."""

    def connect(self, address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise AssertionError(f"Intent de connexió externa a {address!r}")
        super().connect(address)


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Cap connexió sortint: només s'admet el bucle local d'aquesta màquina."""

    real_getaddrinfo = socket.getaddrinfo

    def only_local(host: object, *args: object, **kwargs: object) -> object:
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise AssertionError(f"Intent de resoldre un nom extern: {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(socket, "socket", LoopbackOnly)
    monkeypatch.setattr(socket, "getaddrinfo", only_local)
    yield


@pytest.mark.usefixtures("offline")
def test_the_lan_flow_works_without_internet(project: ProjectPaths) -> None:
    """Amb els recursos ja instal·lats, tot el circuit funciona sense sortir a fora."""
    policy = AccessPolicy.lan()
    server = build_server(
        RewriteService(project, history=HistoryLog(project.root / "offline.jsonl")),
        host="127.0.0.1",
        port=0,
        policy=policy,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = Client(f"http://127.0.0.1:{server.server_address[1]}")
        assert client.request("/api/access", {"pin": policy.pin})[0] == HTTPStatus.OK
        status, result = client.request("/api/rewrite", {"text": TEXT, "level": 3})
        assert status == HTTPStatus.OK and result["output_text"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_the_launcher_starts_the_network_mode() -> None:
    script = Path("start_parafrasi_lan.sh").read_text(encoding="utf-8")
    assert "web --lan" in script
    assert re.search(r"PYTHON\" -m pip install", script), "instal·la el paquet si cal"
    assert "Crostini" in script or "Redirecció de ports" in script
    assert "IP" in script and "contenidor Linux" in script
    for forbidden in ("git pull", "ngrok", "upnp"):
        assert forbidden not in script.lower(), forbidden


# --- correccions de la revisió -------------------------------------------------------------


def test_the_chromeos_addresses_are_reachable_in_lan_mode(lan_policy: AccessPolicy) -> None:
    """Crostini dona al contenidor una adreça 100.115.92.x i el nom penguin.linux.test.

    Cap de les dues no és «privada» per a :mod:`ipaddress`: la primera és
    espai compartit (RFC 6598) i la segona és un TLD reservat (RFC 6761).
    Sense aquest cas, obrir la interfície des del mateix Chromebook servidor
    amb l'adreça del contenidor donaria 403.
    """
    for host in (
        "100.115.92.2",
        "100.115.92.199:8765",
        "penguin.linux.test",
        "penguin.linux.test:8765",
        "penguin.linux.test.",
        "parafrasi.localhost",
        "equip.home.arpa",
    ):
        assert lan_policy.host_allowed(host) is True, host
    # L'espai compartit s'acaba abans de 100.128.0.0.
    assert lan_policy.host_allowed("100.128.0.1") is False
    # Un TLD reservat no obre la porta a un domini d'Internet que hi acabi.
    assert lan_policy.host_allowed("test") is False
    assert lan_policy.host_allowed("atacant.example.test.example") is False


def test_a_code_with_strange_characters_is_refused_without_crashing(lan_url: str) -> None:
    """``secrets.compare_digest`` peta amb text no ASCII: mai ha de sortir un 500."""
    for wrong in ("codi màgic", "123456 ", "０１２３４５", ""):
        client = Client(lan_url)
        status, _ = client.request("/api/access", {"pin": wrong})
        assert status == HTTPStatus.UNAUTHORIZED, wrong
        assert client.session_token is None
        assert client.request("/api/options")[0] == HTTPStatus.UNAUTHORIZED


def test_the_host_option_never_widens_the_check_in_lan_mode() -> None:
    """``--host`` és on escoltar, no què acceptar: no pot colar-hi un domini."""
    parser = build_web_parser()
    policy = build_policy(parser.parse_args(["--lan", "--host", "atacant.example"]))
    assert not policy.extra_hosts
    assert policy.host_allowed("atacant.example") is False
    assert policy.host_allowed("192.168.1.40") is True


def test_the_same_component_is_not_installed_twice_at_once(tmp_path: Path) -> None:
    """Dos navegadors alhora no han d'arrencar dos instal·ladors del mateix."""
    arrel = tmp_path / "projecte"
    (arrel / "scripts").mkdir(parents=True)
    (arrel / "scripts" / "install_parser.py").write_text("", encoding="utf-8")
    paths = ProjectPaths(root=arrel)
    service = RewriteService(paths, history=HistoryLog(arrel / "no.jsonl", enabled=False))
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        service._installers["parser"] = process
        segon = service.install_component("parser", True)
        assert segon["started"] is False
        assert segon["pid"] == process.pid
        assert "ja s'està instal·lant" in segon["message"]
    finally:
        process.kill()
        process.wait()


def test_the_saved_files_are_never_seen_half_written(tmp_path: Path) -> None:
    """Amb dos dispositius, un pot llegir mentre l'altre desa: cal escriptura atòmica."""
    target = tmp_path / "dades" / "fitxer.txt"
    write_atomically(target, "primera versió")
    assert target.read_text(encoding="utf-8") == "primera versió"

    llegit: list[str] = []
    parar = threading.Event()

    def llegir() -> None:
        while not parar.is_set():
            try:
                llegit.append(target.read_text(encoding="utf-8"))
            except FileNotFoundError:  # pragma: no cover - mai amb os.replace
                llegit.append("PERDUT")

    lector = threading.Thread(target=llegir, daemon=True)
    lector.start()
    for i in range(200):
        write_atomically(target, f"versió {i} " + "x" * 20_000)
    parar.set()
    lector.join(timeout=5)

    complets = {"primera versió", *(f"versió {i} " + "x" * 20_000 for i in range(200))}
    assert llegit, "el lector no ha arribat a llegir res"
    assert set(llegit) <= complets, "s'ha llegit un fitxer a mitges"
    assert not list(target.parent.glob(".*tmp")), "queda un fitxer temporal"


def test_a_flood_of_wrong_codes_stops_being_answered(project: ProjectPaths) -> None:
    """Sis xifres es proven totes en menys d'una hora si el servidor no s'atura."""
    limiter = AttemptLimiter(limit=3, lockout_seconds=30.0)
    with contextlib.contextmanager(start)(project, AccessPolicy.lan("123456"), limiter) as url:
        client = Client(url)
        codes = [client.request("/api/access", {"pin": "000000"})[0] for _ in range(5)]
        assert codes == [
            HTTPStatus.UNAUTHORIZED,
            HTTPStatus.UNAUTHORIZED,
            HTTPStatus.UNAUTHORIZED,
            HTTPStatus.TOO_MANY_REQUESTS,
            HTTPStatus.TOO_MANY_REQUESTS,
        ]
        # Mentre el pany està plegat, ni tan sols el codi bo no obre sessió.
        assert client.request("/api/access", {"pin": "123456"})[0] == HTTPStatus.TOO_MANY_REQUESTS
        assert client.session_token is None
        # Passada l'espera, tot torna a la normalitat.
        limiter.reset()
        assert client.request("/api/access", {"pin": "123456"})[0] == HTTPStatus.OK
        assert client.session_token is not None
        # I un encert esborra el compte dels errors anteriors.
        for _ in range(2):
            Client(url).request("/api/access", {"pin": "000000"})
        assert Client(url).request("/api/access", {"pin": "123456"})[0] == HTTPStatus.OK


def test_the_attempt_limiter_counts_across_connections() -> None:
    """Si el compte fos de cada connexió, n'hi hauria prou d'obrir-ne una de nova."""
    ara = [0.0]
    limiter = AttemptLimiter(limit=2, lockout_seconds=10.0, clock=lambda: ara[0])
    assert limiter.blocked_for() == 0
    limiter.record_failure()
    assert limiter.blocked_for() == 0
    limiter.record_failure()
    assert limiter.blocked_for() == 10.0
    ara[0] = 9.5
    assert limiter.blocked_for() == 0.5
    ara[0] = 10.0
    assert limiter.blocked_for() == 0
    limiter.record_failure()
    limiter.record_success()
    limiter.record_failure()
    assert limiter.blocked_for() == 0, "l'encert ha d'esborrar el compte"


def test_a_refused_request_does_not_derail_the_next_one_on_the_same_connection(
    lan_url: str,
) -> None:
    """El navegador reaprofita la connexió: el cos d'una petició refusada s'ha de llegir.

    Sense llegir-lo, la petició següent comença on s'havia quedat el cos i el
    servidor la veu com un mètode inventat: contesta 501 i tanca.
    """
    host, port = lan_url.removeprefix("http://").split(":")
    cos = json.dumps({"text": TEXT}).encode("utf-8")
    for capcalera, esperat in ((host, b"401"), ("atacant.example", b"403")):
        with socket.create_connection((host, int(port)), timeout=30) as canal:
            canal.sendall(
                b"POST /api/rewrite HTTP/1.1\r\nHost: %s\r\n"
                b"Content-Type: application/json\r\nContent-Length: %d\r\n\r\n%s"
                % (capcalera.encode(), len(cos), cos)
            )
            canal.sendall(b"GET / HTTP/1.1\r\nHost: %s\r\n\r\n" % host.encode())
            canal.settimeout(10)
            rebut = b""
            try:
                while b"</html>" not in rebut and b"501" not in rebut:
                    tros = canal.recv(65536)
                    if not tros:
                        break
                    rebut += tros
            except TimeoutError:  # pragma: no cover - només si el servidor no contesta
                pass
        assert rebut.startswith(b"HTTP/1.1 " + esperat), rebut[:80]
        assert b"501" not in rebut, "el cos no llegit ha desbaratat la connexió"
        assert b"HTTP/1.1 200 OK" in rebut, "la segona petició no s'ha servit"


def test_the_history_can_be_read_while_the_other_device_writes(tmp_path: Path) -> None:
    """Dos dispositius: un desa al registre mentre l'altre se'l baixa."""
    registre = HistoryLog(tmp_path / "registre.jsonl", enabled=True)
    llarg = "Text de prova. " * 2000
    parar = threading.Event()
    problemes: list[str] = []

    def llegir() -> None:
        while not parar.is_set():
            try:
                registre.entries()
            except Exception as exc:  # noqa: BLE001 - qualsevol error és el defecte
                problemes.append(str(exc))
                return

    lectors = [threading.Thread(target=llegir, daemon=True) for _ in range(3)]
    for lector in lectors:
        lector.start()
    for i in range(150):
        registre.append({"source_text": llarg, "final_text": f"{i}"})
    parar.set()
    for lector in lectors:
        lector.join(timeout=10)

    assert not problemes, problemes[:3]
    assert len(registre.entries()) == 150


def test_a_second_request_does_not_see_the_parser_as_missing_while_it_loads() -> None:
    """Carregar el model triga segons: qui arribi mentrestant ha d'esperar-lo.

    Sense pany, el segon fil veia la bandera «ja carregat» abans que hi hagués
    cap model i es pensava que el parser no hi era; una empremta creada en
    aquell moment sortia marcada com a feta sense anàlisi sintàctica.
    """

    class Lenta(SpacySyntax):
        """Fa veure que carrega un model, sense dependre de spaCy."""

        def __init__(self) -> None:
            super().__init__()
            self.carregues = 0

        def _load_model(self) -> object:
            self.carregues += 1
            time.sleep(0.4)
            return "model"

    proveidor = Lenta()
    vistos: list[bool] = []

    def mira(retard: float) -> None:
        time.sleep(retard)
        vistos.append(proveidor.available)

    fils = [threading.Thread(target=mira, args=(retard,)) for retard in (0.0, 0.1, 0.2)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=10)

    assert vistos == [True, True, True], "algú ha vist el parser com a no disponible"
    assert proveidor.carregues == 1, "el model s'ha carregat més d'un cop"


def test_a_pipeline_built_with_the_old_weights_is_not_kept(tmp_path: Path) -> None:
    """Valorar un candidat buida la memòria de canonades: cal que hi quedi buida.

    Amb dos dispositius, un pot demanar una reescriptura mentre l'altre desa
    una valoració. La canonada que s'estava construint duu els pesos vells i no
    s'ha de quedar a la memòria, o el segon dispositiu els arrossegaria.
    """
    paths = ProjectPaths(tmp_path)
    service = RewriteService(paths, history=HistoryLog(tmp_path / "no.jsonl", enabled=False))
    config = object()
    construint = threading.Event()
    seguir = threading.Event()

    def build_lent(_config: object) -> object:
        construint.set()
        seguir.wait(timeout=10)
        return "canonada vella"

    with mock.patch.object(service_module, "build_pipeline", build_lent):
        resultat: list[object] = []
        fil = threading.Thread(target=lambda: resultat.append(service.pipeline_for(config)))
        fil.start()
        assert construint.wait(timeout=10)
        # Arriba una valoració mentre l'altra petició encara construeix.
        with service._lock:
            service._pipelines.clear()
            service._pipeline_generation += 1
        seguir.set()
        fil.join(timeout=10)

    assert resultat == ["canonada vella"], "la petició en curs ha de rebre la seva canonada"
    assert service._pipelines == {}, "la canonada amb els pesos vells s'ha quedat a la memòria"
