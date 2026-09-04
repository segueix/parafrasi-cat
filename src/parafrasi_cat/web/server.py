"""Servidor web local de ``parafrasi-cat`` (només biblioteca estàndard).

El servidor serveix una única pàgina i una API JSON que crida
:class:`~parafrasi_cat.web.service.RewriteService`. No hi ha cap dependència
externa, cap recurs remot i cap client de xarxa: el servidor només **rep**
connexions i no n'obre cap.

Dos modes d'accés, decidits per la :class:`~parafrasi_cat.web.auth.AccessPolicy`:

- **local** (per defecte): es lliga a l'amfitrió local, no demana res i el
  text no surt d'aquest ordinador;
- **xarxa local**: també l'obren altres dispositius de la mateixa Wi-Fi, amb
  codi d'accés i sessió. El text circula per la LAN entre el navegador i
  aquest ordinador, i enlloc més.

En tots dos casos la capçalera ``Host`` es comprova per evitar que una pàgina
d'Internet hi arribi per reassignació de noms (*DNS rebinding*).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from parafrasi_cat.core.errors import ParafrasiError
from parafrasi_cat.web.auth import (
    LOCAL_HOSTS,
    PUBLIC_PATHS,
    AccessPolicy,
    AttemptLimiter,
    SessionStore,
    cookie_header,
    cookie_value,
    expired_cookie,
)
from parafrasi_cat.web.service import FeedbackRequest, RewriteRequest, RewriteService

DEFAULT_HOST = "127.0.0.1"
#: Amfitrió del mode de xarxa local: totes les interfícies d'aquesta màquina.
LAN_HOST = "0.0.0.0"  # noqa: S104 - és justament el que demana el mode de xarxa local
DEFAULT_PORT = 8765
MAX_BODY_BYTES = 1_000_000

STATIC_DIR = Path(__file__).resolve().parent / "static"

#: Fitxers que es poden servir, amb el tipus de contingut. La llista tancada
#: evita qualsevol accés fora del directori.
STATIC_FILES: dict[str, str] = {
    "index.html": "text/html; charset=utf-8",
    "entrada.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "entrada.js": "text/javascript; charset=utf-8",
    "estil.css": "text/css; charset=utf-8",
}
#: ``LOCAL_HOSTS`` es reexporta des de ``web.auth``: qui decideix què
#: s'accepta és la política d'accés, però el nom es continua llegint aquí.
__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "LAN_HOST",
    "LOCAL_HOSTS",
    "STATIC_FILES",
    "RequestHandler",
    "build_server",
    "serve",
]


class RequestHandler(BaseHTTPRequestHandler):
    """Encaminador mínim: fitxers estàtics i API JSON."""

    protocol_version = "HTTP/1.1"
    server_version = "parafrasi-cat"
    sys_version = ""

    def __init__(
        self,
        *args: Any,
        service: RewriteService,
        quiet: bool = True,
        policy: AccessPolicy | None = None,
        sessions: SessionStore | None = None,
        attempts: AttemptLimiter | None = None,
        **kwargs: Any,
    ) -> None:
        self._service = service
        self._quiet = quiet
        self._policy = policy or AccessPolicy.local()
        self._sessions = sessions if sessions is not None else SessionStore()
        # Compartit entre connexions: si fos de la instància, n'hi hauria prou
        # d'obrir una connexió nova per tornar a començar a comptar.
        self._attempts = attempts if attempts is not None else AttemptLimiter()
        super().__init__(*args, **kwargs)

    # -- utilitats -------------------------------------------------------------------------

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signatura heretada
        if not self._quiet:
            super().log_message(format, *args)

    def _host_allowed(self) -> bool:
        return self._policy.host_allowed(self.headers.get("Host"))

    def _session_token(self) -> str | None:
        return cookie_value(self.headers.get("Cookie"))

    def _authenticated(self) -> bool:
        """Cert si no cal autenticar-se o si la sessió és vàlida."""
        if not self._policy.requires_authentication:
            return True
        return self._sessions.valid(self._session_token())

    def _send(self, status: HTTPStatus, body: bytes, content_type: str, **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # La pàgina és local i no ha de carregar res de fora.
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, data: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _send_error_json(self, message: str, status: HTTPStatus) -> None:
        self._send_json({"error": message}, status)

    def _drain_body(self) -> None:
        """Llegeix i llença el cos d'una petició que no s'encaminarà.

        La connexió es reaprofita (HTTP/1.1): si el cos es queda al canal, la
        petició següent el llegeix com si en fos l'inici i el servidor perd el
        fil. Passa amb el 403 de la capçalera ``Host`` i amb el 401 de sessió,
        que contesten abans de mirar-se el cos.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True
            return
        if length <= 0:
            return
        if length > MAX_BODY_BYTES:
            # No val la pena empassar-se'l: es talla la connexió.
            self.close_connection = True
            return
        remaining = length
        while remaining > 0:
            block = self.rfile.read(min(remaining, 65536))
            if not block:
                self.close_connection = True
                return
            remaining -= len(block)

    def _read_json(self) -> Mapping[str, object]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError(f"El cos de la petició supera {MAX_BODY_BYTES} bytes")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("El cos de la petició ha de ser un objecte JSON")
        return {str(key): value for key, value in data.items()}

    # -- encaminament ----------------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - signatura heretada
        self._handle(self._get)

    def do_HEAD(self) -> None:  # noqa: N802 - signatura heretada
        self._handle(self._get)

    def do_POST(self) -> None:  # noqa: N802 - signatura heretada
        self._handle(self._post)

    def _handle(self, route: Callable[[str], None]) -> None:
        if not self._host_allowed():
            self._drain_body()
            self._send_error_json(
                "Aquest servidor només accepta peticions de la xarxa local",
                HTTPStatus.FORBIDDEN,
            )
            return
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        try:
            if not self._allowed_without_session(path):
                self._drain_body()
                self._require_session(path)
                return
            route(path)
        except ParafrasiError as exc:
            self._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
        except (ValueError, KeyError) as exc:
            self._send_error_json(f"Petició no vàlida: {exc}", HTTPStatus.BAD_REQUEST)
        except OSError as exc:
            self._send_error_json(
                f"Error d'entrada/sortida: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR
            )

    def _allowed_without_session(self, path: str) -> bool:
        """Cert si la ruta es pot servir sense sessió oberta.

        Els fitxers estàtics són els mateixos que es distribueixen amb el
        paquet i no contenen res privat; tota la informació passa per l'API,
        que sí que exigeix sessió en mode de xarxa local.
        """
        if self._authenticated():
            return True
        return path in PUBLIC_PATHS or path.startswith("/static/")

    def _require_session(self, path: str) -> None:
        """Sense sessió: la pantalla d'entrada per a la pàgina, un 401 per a l'API."""
        if path == "/":
            self._static("entrada.html")
            return
        self._send_error_json(
            "Cal introduir el codi d'accés d'aquest ordinador", HTTPStatus.UNAUTHORIZED
        )

    def _access_state(self) -> dict[str, object]:
        return {**self._policy.to_dict(), "authenticated": self._authenticated()}

    def _open_session(self, data: Mapping[str, object]) -> None:
        """Comprova el codi d'accés i, si és correcte, obre una sessió."""
        if not self._policy.requires_authentication:
            self._send_json({**self._access_state(), "authenticated": True})
            return
        espera = self._attempts.blocked_for()
        if espera > 0:
            self._send_error_json(
                "Hi ha hagut massa intents erronis. Torneu-ho a provar d'aquí "
                f"{int(espera) + 1} segons.",
                HTTPStatus.TOO_MANY_REQUESTS,
            )
            return
        pin = str(data.get("pin") or "")
        if not self._policy.pin_matches(pin):
            self._attempts.record_failure()
            self._send_error_json("El codi d'accés no és correcte", HTTPStatus.UNAUTHORIZED)
            return
        self._attempts.record_success()
        token = self._sessions.create()
        body = json.dumps({**self._policy.to_dict(), "authenticated": True}).encode("utf-8")
        self._send(
            HTTPStatus.OK,
            body,
            "application/json; charset=utf-8",
            **{"Set-Cookie": cookie_header(token, self._sessions.ttl_seconds)},
        )

    def _close_session(self) -> None:
        self._sessions.revoke(self._session_token())
        body = json.dumps({**self._policy.to_dict(), "authenticated": False}).encode("utf-8")
        self._send(
            HTTPStatus.OK,
            body,
            "application/json; charset=utf-8",
            **{"Set-Cookie": expired_cookie()},
        )

    def _get(self, path: str) -> None:
        if path == "/":
            self._static("index.html")
        elif path == "/api/access":
            self._send_json(self._access_state())
        elif path.startswith("/static/"):
            self._static(path[len("/static/") :])
        elif path == "/api/options":
            self._send_json(self._service.options())
        elif path == "/api/feedback":
            self._send_json(self._service.feedback_summary())
        elif path == "/api/resources":
            self._send_json(self._service.resources())
        elif path == "/api/fingerprint/summary":
            query = parse_qs(urlsplit(self.path).query)
            reference = (query.get("id") or [""])[0]
            if not reference:
                self._send_error_json("Cal indicar l'empremta («id»)", HTTPStatus.BAD_REQUEST)
                return
            self._send_json(self._service.fingerprint_summary(reference))
        elif path == "/api/history":
            self._send_json(self._service.history_entries())
        elif path == "/api/history/export":
            body = self._service.history_export().encode("utf-8")
            self._send(
                HTTPStatus.OK,
                body,
                "application/json; charset=utf-8",
                **{"Content-Disposition": 'attachment; filename="historial.json"'},
            )
        else:
            self._send_error_json(f"Ruta desconeguda: {path}", HTTPStatus.NOT_FOUND)

    def _post(self, path: str) -> None:
        if path == "/api/access":
            self._open_session(self._read_json())
        elif path == "/api/access/close":
            self._close_session()
        elif path == "/api/rewrite":
            request = RewriteRequest.from_mapping(self._read_json())
            self._send_json(self._service.rewrite(request))
        elif path == "/api/feedback":
            request_data = self._read_json()
            self._send_json(
                self._service.record_feedback(FeedbackRequest.from_mapping(request_data))
            )
        elif path == "/api/history":
            self._send_json(self._service.save_history(self._read_json()))
        elif path == "/api/history/enabled":
            enabled = bool(self._read_json().get("enabled", False))
            self._send_json(self._service.set_history_enabled(enabled))
        elif path == "/api/resources/install":
            data = self._read_json()
            component = str(data.get("component", "languagetool"))
            confirmed = bool(data.get("confirm", False))
            self._send_json(self._service.install_component(component, confirmed))
        elif path == "/api/fingerprint":
            data = self._read_json()
            texts = data.get("texts")
            self._send_json(
                self._service.create_fingerprint(
                    str(data.get("name", "autor")),
                    [str(t) for t in texts] if isinstance(texts, list) else [],
                    source_mode=str(data.get("source_mode") or "own"),
                )
            )
        else:
            self._send_error_json(f"Ruta desconeguda: {path}", HTTPStatus.NOT_FOUND)

    def _static(self, name: str) -> None:
        content_type = STATIC_FILES.get(name)
        if content_type is None:
            self._send_error_json(f"Fitxer desconegut: {name}", HTTPStatus.NOT_FOUND)
            return
        self._send(HTTPStatus.OK, (STATIC_DIR / name).read_bytes(), content_type)


def build_server(
    service: RewriteService | None = None,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    quiet: bool = True,
    policy: AccessPolicy | None = None,
    sessions: SessionStore | None = None,
    attempts: AttemptLimiter | None = None,
) -> ThreadingHTTPServer:
    """Crea el servidor sense engegar-lo (el port 0 en tria un de lliure).

    Sense política, el servidor és local i no demana cap codi d'accés: el
    comportament de sempre.
    """
    handler = partial(
        RequestHandler,
        service=service or RewriteService(),
        quiet=quiet,
        policy=policy or AccessPolicy.local(),
        sessions=sessions if sessions is not None else SessionStore(),
        attempts=attempts if attempts is not None else AttemptLimiter(),
    )
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def serve(
    service: RewriteService | None = None,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    quiet: bool = False,
    policy: AccessPolicy | None = None,
    on_start: Callable[[str], None] | None = None,
) -> None:
    """Engega el servidor i el manté actiu fins que s'interromp amb Ctrl+C."""
    server = build_server(service, host=host, port=port, quiet=quiet, policy=policy)
    # A la LAN el servidor escolta a totes les interfícies, però l'adreça que
    # cal escriure al navegador d'un altre dispositiu no la sap: la diu la
    # configuració de xarxa del sistema, no el procés.
    shown = DEFAULT_HOST if host == LAN_HOST else host
    url = f"http://{shown}:{server.server_address[1]}/"
    if on_start is not None:
        on_start(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - interacció
        pass
    finally:
        server.shutdown()
        server.server_close()
