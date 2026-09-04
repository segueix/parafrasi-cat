"""Servidor web local de ``parafrasi-cat`` (només biblioteca estàndard).

El servidor es lliga a l'amfitrió local i serveix una única pàgina i una API
JSON que crida :class:`~parafrasi_cat.web.service.RewriteService`. No hi ha
cap dependència externa, cap recurs remot i cap enviament de dades: el text
no surt mai del procés que executa aquest servidor.

Com que el navegador hi accedeix des de l'ordinador mateix, la capçalera
``Host`` es comprova per evitar que una pàgina externa hi arribi per
reassignació de noms (*DNS rebinding*).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from parafrasi_cat.core.errors import ParafrasiError
from parafrasi_cat.web.service import FeedbackRequest, RewriteRequest, RewriteService

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_BODY_BYTES = 1_000_000

STATIC_DIR = Path(__file__).resolve().parent / "static"

#: Fitxers que es poden servir, amb el tipus de contingut. La llista tancada
#: evita qualsevol accés fora del directori.
STATIC_FILES: dict[str, str] = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "estil.css": "text/css; charset=utf-8",
}

#: Amfitrions acceptats a la capçalera ``Host``.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"})


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
        **kwargs: Any,
    ) -> None:
        self._service = service
        self._quiet = quiet
        super().__init__(*args, **kwargs)

    # -- utilitats -------------------------------------------------------------------------

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signatura heretada
        if not self._quiet:
            super().log_message(format, *args)

    def _host_is_local(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip()
        return host in LOCAL_HOSTS or not host

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
        if not self._host_is_local():
            self._send_error_json(
                "Aquest servidor només accepta peticions locals", HTTPStatus.FORBIDDEN
            )
            return
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        try:
            route(path)
        except ParafrasiError as exc:
            self._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
        except (ValueError, KeyError) as exc:
            self._send_error_json(f"Petició no vàlida: {exc}", HTTPStatus.BAD_REQUEST)
        except OSError as exc:
            self._send_error_json(
                f"Error d'entrada/sortida: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR
            )

    def _get(self, path: str) -> None:
        if path == "/":
            self._static("index.html")
        elif path.startswith("/static/"):
            self._static(path[len("/static/") :])
        elif path == "/api/options":
            self._send_json(self._service.options())
        elif path == "/api/feedback":
            self._send_json(self._service.feedback_summary())
        elif path == "/api/resources":
            self._send_json(self._service.resources())
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
        if path == "/api/rewrite":
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
) -> ThreadingHTTPServer:
    """Crea el servidor sense engegar-lo (el port 0 en tria un de lliure)."""
    handler = partial(RequestHandler, service=service or RewriteService(), quiet=quiet)
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def serve(
    service: RewriteService | None = None,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    quiet: bool = False,
    on_start: Callable[[str], None] | None = None,
) -> None:
    """Engega el servidor i el manté actiu fins que s'interromp amb Ctrl+C."""
    server = build_server(service, host=host, port=port, quiet=quiet)
    url = f"http://{host}:{server.server_address[1]}/"
    if on_start is not None:
        on_start(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - interacció
        pass
    finally:
        server.shutdown()
        server.server_close()
