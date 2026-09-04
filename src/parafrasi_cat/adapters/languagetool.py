"""Adaptador local de LanguageTool: només validació, mai reescriptura.

LanguageTool s'executa **sempre localment**, com un procés a part que llegeix
el text per l'entrada estàndard. No es fa servir mai l'API de languagetool.org
ni cap altre servei remot: aquest mòdul no importa cap client de xarxa, de
manera que no pot enviar text enlloc encara que algú ho volgués.

Responsabilitat, i només aquesta:

- comprovar gramàtica, concordança i puntuació d'un candidat;
- retornar els problemes trobats.

LanguageTool **no** genera la paràfrasi, no reescriu el text, no decideix el
contingut i no aplica cap correcció. El motor de candidats és qui decideix, a
partir dels seus informes, si un candidat es penalitza o es descarta.

És opcional: sense Java o sense LanguageTool instal·lat,
:class:`LanguageToolClient` diu que no està disponible i el motor continua amb
els seus validadors interns.

Llicència de LanguageTool: LGPL-2.1-or-later. Vegeu
``docs/recursos-linguistics.md`` i ``THIRD_PARTY_LICENSES.md``.
"""

from __future__ import annotations

import atexit
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.validation.base import ValidationContext
from parafrasi_cat.validation.result import (
    ValidationDimension,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)

#: Variable d'entorn que apunta al directori de LanguageTool.
ENV_HOME = "PARAFRASI_CAT_LANGUAGETOOL"

#: Fitxers de la distribució que fa servir l'adaptador.
COMMANDLINE_JAR = "languagetool-commandline.jar"
SERVER_JAR = "languagetool-server.jar"

#: Llocs on es busca la instal·lació, en ordre.
SEARCH_PATHS: tuple[str, ...] = (
    "vendor/languagetool",
    "vendor/LanguageTool",
    "~/.local/share/parafrasi-cat/languagetool",
    "/opt/languagetool",
    "/usr/local/share/languagetool",
)

#: Amfitrions de bucle local. El client no pot connectar-se enlloc més.
LOOPBACK = "127.0.0.1"
LOOPBACK_HOSTS: frozenset[str] = frozenset({LOOPBACK, "localhost", "::1"})

#: Tipus de problema que invaliden un candidat. La resta només el penalitzen.
DEFAULT_BLOCKING_ISSUE_TYPES: frozenset[str] = frozenset(
    {"grammar", "misspelling", "typographical", "inflection", "agreement"}
)

#: Categories que invaliden un candidat encara que el tipus sigui «uncategorized».
#: Les regles catalanes de concordança («CONCORD_SUBJECTE_VERB»,
#: «CONCORDANCES_DET_NOM»...) sovint no porten tipus, però la categoria sí que
#: les identifica, i una falta de concordança no és mai acceptable.
DEFAULT_BLOCKING_CATEGORIES: tuple[str, ...] = ("CONCORDANCES",)

DEFAULT_STARTUP_TIMEOUT = 120.0
DEFAULT_REQUEST_TIMEOUT = 60.0
LANGUAGE = "ca"


@dataclass(frozen=True, slots=True)
class LanguageToolMatch:
    """Un problema que LanguageTool ha trobat en un text."""

    rule_id: str
    message: str
    offset: int
    length: int
    issue_type: str = ""
    category: str = ""
    replacements: tuple[str, ...] = ()

    @property
    def blocking(self) -> bool:
        return is_blocking(self)

    def describe(self) -> str:
        return f"[{self.rule_id}] {self.message}"

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "message": self.message,
            "offset": self.offset,
            "length": self.length,
            "issue_type": self.issue_type,
            "category": self.category,
            "replacements": list(self.replacements),
        }


def is_blocking(
    match: LanguageToolMatch,
    *,
    issue_types: Iterable[str] = DEFAULT_BLOCKING_ISSUE_TYPES,
    categories: Iterable[str] = DEFAULT_BLOCKING_CATEGORIES,
) -> bool:
    """Cert si el problema ha d'invalidar el candidat en lloc de només penalitzar-lo."""
    if match.issue_type in frozenset(issue_types):
        return True
    return any(match.category.startswith(prefix) for prefix in categories)


@dataclass(frozen=True, slots=True)
class LanguageToolInstallation:
    """Una instal·lació local de LanguageTool trobada al sistema."""

    directory: Path
    jar: Path
    java: Path
    version: str = ""

    @property
    def server_jar(self) -> Path:
        """Jar del servidor local, al costat del de la línia d'ordres."""
        return self.jar.with_name(SERVER_JAR)

    def describe(self) -> str:
        version = f" {self.version}" if self.version else ""
        return f"LanguageTool{version} a {self.directory}"


def find_java(command: str | None = None) -> Path | None:
    """Ruta de l'intèrpret de Java, o ``None`` si no n'hi ha cap d'instal·lat."""
    if command:
        found = shutil.which(command)
        return Path(found) if found else None
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home).expanduser() / "bin" / "java"
        if candidate.is_file():
            return candidate
    found = shutil.which("java")
    return Path(found) if found else None


def find_installation(
    root: str | Path | None = None, *, java: str | None = None
) -> LanguageToolInstallation | None:
    """Cerca una instal·lació local de LanguageTool.

    Ordre: la variable d'entorn, després ``vendor/languagetool`` dins del
    projecte i, finalment, les ubicacions habituals del sistema. Retorna
    ``None`` si no n'hi ha cap o si no hi ha Java.
    """
    interpreter = find_java(java)
    if interpreter is None:
        return None
    for candidate in _candidate_directories(root):
        jar = _find_jar(candidate)
        if jar is not None:
            return LanguageToolInstallation(
                directory=candidate, jar=jar, java=interpreter, version=_read_version(candidate)
            )
    return None


def _candidate_directories(root: str | Path | None) -> list[Path]:
    directories: list[Path] = []
    from_env = os.environ.get(ENV_HOME)
    if from_env:
        directories.append(Path(from_env).expanduser())
    base = Path(root).expanduser() if root is not None else None
    for relative in SEARCH_PATHS:
        path = Path(relative).expanduser()
        if path.is_absolute():
            directories.append(path)
        elif base is not None:
            directories.append(base / path)
    return [d for d in directories if d.is_dir()]


def _find_jar(directory: Path) -> Path | None:
    """El jar de la línia d'ordres, també si hi ha un nivell de subdirectori."""
    direct = directory / COMMANDLINE_JAR
    if direct.is_file():
        return direct
    for child in sorted(directory.glob(f"*/{COMMANDLINE_JAR}")):
        if child.is_file():
            return child
    return None


def _read_version(directory: Path) -> str:
    """Versió declarada al manifest del jar desempaquetat, o el nom del directori."""
    manifest = directory / "META-INF" / "MANIFEST.MF"
    if manifest.is_file():
        for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Implementation-Version:"):
                return line.split(":", 1)[1].strip()
    changes = directory / "CHANGES.md"
    if changes.is_file():
        for line in changes.read_text(encoding="utf-8", errors="replace").splitlines()[:20]:
            found = re.search(r"\b(\d+\.\d+(?:\.\d+)?)\b", line)
            if found:
                return found.group(1)
    return directory.name


class LanguageToolServer:
    """Servidor local de LanguageTool: s'arrenca una vegada i es reutilitza.

    Es lliga sempre a l'amfitrió local i comprova que la màquina d'arribada
    és de bucle local abans de connectar-s'hi. No hi ha cap manera d'apuntar
    aquest client a un servei remot.
    """

    def __init__(
        self,
        installation: LanguageToolInstallation,
        *,
        host: str = LOOPBACK,
        port: int = 0,
        startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        if host not in LOOPBACK_HOSTS:
            raise ConfigError(f"LanguageTool només es pot lligar a l'amfitrió local, no a «{host}»")
        self._installation = installation
        self._host = host
        self._port = port
        self._startup_timeout = startup_timeout
        self._request_timeout = request_timeout
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._closed = False

    @property
    def port(self) -> int:
        return self._port

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    # -- cicle de vida ---------------------------------------------------------------------

    def start(self) -> bool:
        """Arrenca el servidor si no ho està. Retorna si ha quedat en marxa."""
        with self._lock:
            return self._start_locked()

    def _start_locked(self) -> bool:
        if self._closed:
            return False
        if self.running and self._healthy():
            return True
        self._stop_locked()
        self._port = self._port or _free_port(self._host)
        command = [
            str(self._installation.java),
            "-cp",
            str(self._installation.server_jar),
            "org.languagetool.server.HTTPServer",
            "--port",
            str(self._port),
        ]
        try:
            self._process = subprocess.Popen(  # noqa: S603 - ruta detectada al sistema
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            self._process = None
            return False
        atexit.register(self.close)
        deadline = time.monotonic() + self._startup_timeout
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                self._process = None
                return False
            if self._healthy():
                return True
            time.sleep(0.25)
        self._stop_locked()
        return False

    def _healthy(self) -> bool:
        try:
            self._get("/v2/languages")
        except (OSError, ValueError):
            return False
        return True

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - només si la JVM es penja
            process.kill()
            process.wait(timeout=10)

    def close(self) -> None:
        """Atura el servidor i no en deixa cap procés orfe."""
        self._closed = True
        self.stop()

    def __enter__(self) -> LanguageToolServer:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- comunicació (només bucle local) -----------------------------------------------------

    def _connection(self) -> http.client.HTTPConnection:
        if self._host not in LOOPBACK_HOSTS:  # pragma: no cover - invariant
            raise ConfigError("LanguageTool només accepta l'amfitrió local")
        return http.client.HTTPConnection(self._host, self._port, timeout=self._request_timeout)

    def _get(self, path: str) -> bytes:
        connection = self._connection()
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            body = response.read()
            if response.status != 200:
                raise ValueError(f"LanguageTool ha respost {response.status}")
            return body
        finally:
            connection.close()

    def check(self, text: str, language: str) -> tuple[LanguageToolMatch, ...]:
        """Demana la comprovació d'un text al servidor local."""
        with self._lock:
            if not self._start_locked():
                return ()
        payload = urlencode({"text": text, "language": language, "enabledOnly": "false"})
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}
        for attempt in range(2):
            connection = self._connection()
            try:
                connection.request(
                    "POST", "/v2/check", body=payload.encode("utf-8"), headers=headers
                )
                response = connection.getresponse()
                body = response.read()
                if response.status != 200:
                    raise ValueError(f"LanguageTool ha respost {response.status}")
                return _parse_json(body.decode("utf-8"))
            except (OSError, ValueError):
                if attempt == 0:
                    with self._lock:  # el servidor pot haver caigut: es torna a arrencar
                        self._stop_locked()
                        if not self._start_locked():
                            return ()
                    continue
                return ()
            finally:
                connection.close()
        return ()


def _free_port(host: str) -> int:
    """Port lliure de l'amfitrió local perquè el servidor no xoqui amb res."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


class LanguageToolClient:
    """Comprova textos amb LanguageTool local, reutilitzant el mateix servidor.

    No modifica mai cap text: només informa. Les substitucions que LanguageTool
    proposa es transporten com a informació, però el motor no les aplica.

    Manté una memòria cau per sessió, en memòria i mai a disc, amb clau
    (text, configuració, llengua). No afecta el determinisme: la mateixa
    pregunta ja donava la mateixa resposta.
    """

    def __init__(
        self,
        installation: LanguageToolInstallation | None = None,
        *,
        language: str = LANGUAGE,
        server: LanguageToolServer | None = None,
        cache: bool = True,
    ) -> None:
        self._installation = installation
        self._language = language
        self._server = server
        if server is None and installation is not None:
            self._server = LanguageToolServer(installation)
        self._cache: dict[tuple[str, str, str], tuple[LanguageToolMatch, ...]] = {}
        self._use_cache = cache
        self._checks = 0
        self._hits = 0

    @classmethod
    def discover(
        cls, root: str | Path | None = None, *, language: str = LANGUAGE, **kwargs: Any
    ) -> LanguageToolClient:
        """Client amb la instal·lació que es trobi; no disponible si no n'hi ha cap."""
        return cls(find_installation(root), language=language, **kwargs)

    @property
    def installation(self) -> LanguageToolInstallation | None:
        return self._installation

    @property
    def server(self) -> LanguageToolServer | None:
        return self._server

    @property
    def available(self) -> bool:
        """Cert si hi ha Java i una instal·lació local de LanguageTool."""
        return self._installation is not None and self._server is not None

    @property
    def signature(self) -> str:
        """Identificador de la configuració, per a la clau de la memòria cau."""
        if self._installation is None:
            return "cap"
        return f"{self._installation.directory}:{self._installation.version}"

    @property
    def statistics(self) -> dict[str, int]:
        """Comprovacions fetes i encerts de la memòria cau (per als informes)."""
        return {"checks": self._checks, "cache_hits": self._hits, "cached": len(self._cache)}

    def describe(self) -> str:
        if self._installation is None:
            return "LanguageTool no instal·lat: s'utilitzen només els validadors interns"
        return self._installation.describe()

    def start(self) -> bool:
        """Arrenca el servidor local per avançat, per no pagar-ho a la primera petició."""
        return self._server.start() if self._server is not None else False

    def close(self) -> None:
        """Atura el servidor local i buida la memòria cau."""
        if self._server is not None:
            self._server.close()
        self._cache.clear()

    def __enter__(self) -> LanguageToolClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- comprovació ---------------------------------------------------------------------

    def check(self, text: str) -> tuple[LanguageToolMatch, ...]:
        """Problemes d'un text (buit si LanguageTool no està disponible)."""
        if self._server is None or not text.strip():
            return ()
        key = (text, self.signature, self._language)
        if self._use_cache and key in self._cache:
            self._hits += 1
            return self._cache[key]
        matches = self._server.check(text, self._language)
        self._checks += 1
        if self._use_cache:
            self._cache[key] = matches
        return matches

    def check_many(self, texts: Sequence[str]) -> tuple[tuple[LanguageToolMatch, ...], ...]:
        """Comprova diversos textos reutilitzant el mateix servidor i la memòria cau."""
        return tuple(self.check(text) for text in texts)


def _parse_json(output: str) -> tuple[LanguageToolMatch, ...]:
    """Llegeix la sortida JSON de LanguageTool, tolerant amb el text del voltant."""
    start = output.find("{")
    if start < 0:
        return ()
    try:
        data = json.loads(output[start:])
    except ValueError:
        return ()
    if not isinstance(data, Mapping):
        return ()
    raw_matches = data.get("matches")
    if not isinstance(raw_matches, list):
        return ()
    matches: list[LanguageToolMatch] = []
    for item in raw_matches:
        if not isinstance(item, Mapping):
            continue
        rule = _sub_mapping(item, "rule")
        category = _sub_mapping(rule, "category")
        replacements = item.get("replacements")
        matches.append(
            LanguageToolMatch(
                rule_id=str(rule.get("id", "")),
                message=str(item.get("message", "")),
                offset=int(item.get("offset", 0) or 0),
                length=int(item.get("length", 0) or 0),
                issue_type=str(rule.get("issueType", "")),
                category=str(category.get("id", "")),
                replacements=tuple(
                    str(r.get("value", ""))
                    for r in (replacements if isinstance(replacements, list) else [])
                    if isinstance(r, Mapping)
                ),
            )
        )
    return tuple(matches)


def _sub_mapping(data: Mapping[str, object], key: str) -> Mapping[str, object]:
    """Subdiccionari d'una resposta JSON, o buit si no hi és o no ho és."""
    value = data.get(key)
    return value if isinstance(value, Mapping) else {}


class LanguageToolValidator:
    """Valida un candidat amb LanguageTool local, sense modificar-lo mai.

    Només compten els problemes **nous**: els que ja hi havia al text original
    no penalitzen el candidat, igual que fa el validador gramatical intern. Un
    problema de gramàtica, concordança o ortografia invalida el candidat; la
    resta queden com a advertiments que en baixen la puntuació.

    Si LanguageTool no està disponible, el validador no diu res i el motor
    continua amb els validadors interns.
    """

    validator_id = "languagetool"
    dimension = ValidationDimension.GRAMMAR

    def __init__(
        self,
        client: LanguageToolClient,
        *,
        blocking_issue_types: Iterable[str] = DEFAULT_BLOCKING_ISSUE_TYPES,
        blocking_categories: Iterable[str] = DEFAULT_BLOCKING_CATEGORIES,
    ) -> None:
        self._client = client
        self._blocking = frozenset(blocking_issue_types)
        self._categories = tuple(blocking_categories)
        self._source_cache: dict[str, frozenset[tuple[str, str]]] = {}

    @property
    def client(self) -> LanguageToolClient:
        return self._client

    @property
    def available(self) -> bool:
        return self._client.available

    def validate(self, candidate: Candidate, ctx: ValidationContext) -> ValidationResult:
        if not self._client.available or candidate.is_identity:
            return ValidationResult.passed()
        known = self._known_issues(ctx.source_text)
        issues: list[ValidationIssue] = []
        for match in self._client.check(candidate.text):
            if (match.rule_id, match.message) in known:
                continue  # el problema ja hi era a l'original
            severity = (
                ValidationSeverity.ERROR
                if is_blocking(match, issue_types=self._blocking, categories=self._categories)
                else ValidationSeverity.WARNING
            )
            issues.append(
                ValidationIssue(
                    self.validator_id,
                    severity,
                    f"LanguageTool: {match.message} ({match.rule_id})",
                    self.dimension,
                )
            )
        return ValidationResult(tuple(issues))

    def _known_issues(self, source_text: str) -> frozenset[tuple[str, str]]:
        cached = self._source_cache.get(source_text)
        if cached is None:
            cached = frozenset(
                (match.rule_id, match.message) for match in self._client.check(source_text)
            )
            self._source_cache[source_text] = cached
        return cached


@dataclass(frozen=True, slots=True)
class LanguageToolStatus:
    """Estat de LanguageTool per informar-ne la interfície."""

    available: bool
    java: str = ""
    directory: str = ""
    version: str = ""
    message: str = ""
    details: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "java": self.java,
            "directory": self.directory,
            "version": self.version,
            "message": self.message,
            "details": dict(self.details),
        }
