"""Garantia estructural: el paquet no obre connexions de xarxa ni fa telemetria.

El motor no pot importar cap mòdul de xarxa ni cap biblioteca de models. La
interfície local (``parafrasi_cat.web``) és l'única excepció, i només per a
``http.server``: un servidor que **escolta** a l'amfitrió local. Cap fitxer
del paquet, ni tan sols la interfície, pot importar un client que enviï dades
cap enfora (``urllib``, ``http.client``, ``requests``, ``socket``...).
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Clients i transports que enviarien dades fora de l'ordinador. Mai, enlloc.
OUTBOUND_MODULES = {
    "socket",
    "ssl",
    "http.client",
    "http.cookiejar",
    "urllib",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
    "ftplib",
    "smtplib",
    "telnetlib",
    "xmlrpc",
    "websocket",
    "websockets",
}

#: Biblioteques de models generatius o de serveis d'inferència. Mai, enlloc.
MODEL_MODULES = {
    "openai",
    "anthropic",
    "transformers",
    "torch",
    "tensorflow",
    "sentence_transformers",
    "llama_cpp",
    "onnxruntime",
}

FORBIDDEN_MODULES = OUTBOUND_MODULES | MODEL_MODULES | {"http"}

#: Únic permís, i només a la interfície local: escoltar peticions del navegador
#: d'aquest mateix ordinador. No obre cap connexió de sortida.
LOCAL_SERVER_ALLOWANCE = {"http", "http.server"}

#: Subpaquet de la interfície local.
LOCAL_INTERFACE = "web"


def imported_modules(file: Path) -> set[str]:
    """Mòduls importats, amb el nom sencer i el de primer nivell.

    Retorna les dues formes perquè es pugui distingir ``http.server`` (escolta)
    de ``http.client`` (envia).
    """
    tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
            modules.add(node.module.split(".")[0])
    return modules


def package_files(project_root: Path) -> list[Path]:
    files = list((project_root / "src" / "parafrasi_cat").rglob("*.py"))
    assert files
    return files


def is_local_interface(file: Path) -> bool:
    return LOCAL_INTERFACE in file.parts


def test_engine_has_no_network_or_model_imports(project_root: Path) -> None:
    """Tot el motor, fora de la interfície local, és net de xarxa i de models."""
    engine = [f for f in package_files(project_root) if not is_local_interface(f)]
    assert len(engine) > 40
    for file in engine:
        forbidden = imported_modules(file) & FORBIDDEN_MODULES
        assert not forbidden, f"{file} importa mòduls prohibits: {forbidden}"


def test_local_interface_only_listens(project_root: Path) -> None:
    """La interfície local només pot escoltar; no pot importar cap client."""
    interface = [f for f in package_files(project_root) if is_local_interface(f)]
    assert interface
    for file in interface:
        modules = imported_modules(file)
        forbidden = modules & FORBIDDEN_MODULES - LOCAL_SERVER_ALLOWANCE
        assert not forbidden, f"{file} importa mòduls prohibits: {forbidden}"
    server = project_root / "src" / "parafrasi_cat" / "web" / "server.py"
    assert "http.server" in imported_modules(server)


def test_no_outbound_client_anywhere(project_root: Path) -> None:
    """Cap fitxer del paquet no pot enviar dades enfora, ni el servidor local."""
    for file in package_files(project_root):
        outbound = imported_modules(file) & OUTBOUND_MODULES
        assert not outbound, f"{file} podria enviar dades fora: {outbound}"


def test_no_model_library_anywhere(project_root: Path) -> None:
    for file in package_files(project_root):
        models = imported_modules(file) & MODEL_MODULES
        assert not models, f"{file} importa una biblioteca de models: {models}"


def test_the_check_detects_a_forbidden_import(tmp_path: Path) -> None:
    """La comprovació sap distingir escoltar d'enviar."""
    listens = tmp_path / "escolta.py"
    listens.write_text("from http.server import HTTPServer\n", encoding="utf-8")
    assert imported_modules(listens) & FORBIDDEN_MODULES - LOCAL_SERVER_ALLOWANCE == set()
    assert not imported_modules(listens) & OUTBOUND_MODULES
    sends = tmp_path / "envia.py"
    sends.write_text("from http.client import HTTPSConnection\n", encoding="utf-8")
    assert imported_modules(sends) & OUTBOUND_MODULES == {"http.client"}
    imports = tmp_path / "importa.py"
    imports.write_text("import requests\nimport torch\n", encoding="utf-8")
    assert imported_modules(imports) & OUTBOUND_MODULES == {"requests"}
    assert imported_modules(imports) & MODEL_MODULES == {"torch"}


def test_declared_dependencies_are_local_only(project_root: Path) -> None:
    import tomllib

    data = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = [d.lower() for d in data["project"]["dependencies"]]
    assert all(d.startswith("pyyaml") for d in dependencies)
