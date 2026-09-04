"""Garantia estructural: el paquet no obre connexions de xarxa ni fa telemetria.

El motor no pot importar cap mòdul de xarxa ni cap biblioteca de models. Hi ha
dues excepcions, totes dues de bucle local i comprovades:

- ``parafrasi_cat.web`` fa servir ``http.server`` per **escoltar** el navegador
  d'aquest mateix ordinador;
- ``parafrasi_cat.adapters.languagetool`` fa servir ``http.client`` i ``socket``
  per parlar amb el servidor de LanguageTool que ell mateix arrenca, sempre a
  l'amfitrió local i amb una comprovació explícita de l'adreça.

Cap fitxer del paquet no pot importar un client que descarregui res d'Internet
(``urllib.request``, ``requests``, ``httpx``...). A més, un test en temps
d'execució comprova que durant una sessió normal no s'obre cap connexió que no
sigui de bucle local.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Clients que descarregarien res d'Internet. Mai, enlloc del paquet.
#: «urllib.parse» no hi és: només manipula cadenes i no obre cap connexió.
OUTBOUND_MODULES = {
    "ssl",
    "http.cookiejar",
    "urllib.request",
    "urllib.error",
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

#: Transports de xarxa que només es poden fer servir contra el bucle local.
#: «urllib» hi és perquè «urllib.parse» n'arrossega el nom de primer nivell;
#: «urllib.request» continua prohibit i es comprova a part.
LOOPBACK_MODULES = {"socket", "http", "http.server", "http.client", "urllib", "urllib.parse"}

FORBIDDEN_MODULES = OUTBOUND_MODULES | MODEL_MODULES | {"http", "socket", "urllib"}

#: Fitxers on es permet un transport de bucle local, amb el motiu.
LOOPBACK_ALLOWED: dict[str, str] = {
    "web/server.py": "escolta el navegador d'aquest ordinador",
    "adapters/languagetool.py": "parla amb el servidor local de LanguageTool",
}


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


def loopback_reason(file: Path) -> str:
    """Motiu pel qual el fitxer pot fer servir un transport de bucle local."""
    suffix = "/".join(file.parts[-2:])
    return LOOPBACK_ALLOWED.get(suffix, "")


def test_engine_has_no_network_or_model_imports(project_root: Path) -> None:
    """Tot el motor, fora dels dos fitxers de bucle local, és net de xarxa."""
    engine = [f for f in package_files(project_root) if not loopback_reason(f)]
    assert len(engine) > 40
    for file in engine:
        forbidden = imported_modules(file) & FORBIDDEN_MODULES
        assert not forbidden, f"{file} importa mòduls prohibits: {forbidden}"


def test_loopback_transports_are_declared_and_justified(project_root: Path) -> None:
    """Els dos fitxers que fan servir la xarxa només poden parlar amb aquest ordinador."""
    allowed = [f for f in package_files(project_root) if loopback_reason(f)]
    assert len(allowed) == len(LOOPBACK_ALLOWED)
    for file in allowed:
        modules = imported_modules(file)
        forbidden = modules & FORBIDDEN_MODULES - LOOPBACK_MODULES
        assert not forbidden, f"{file} importa mòduls prohibits: {forbidden}"
        assert not modules & OUTBOUND_MODULES, file
    server = project_root / "src" / "parafrasi_cat" / "web" / "server.py"
    assert "http.server" in imported_modules(server)
    adapter = project_root / "src" / "parafrasi_cat" / "adapters" / "languagetool.py"
    source = adapter.read_text(encoding="utf-8")
    # L'adaptador comprova explícitament que l'adreça és de bucle local.
    assert "LOOPBACK_HOSTS" in source
    assert 'LOOPBACK = "127.0.0.1"' in source
    assert source.count("LOOPBACK_HOSTS") >= 3


def test_no_outbound_client_anywhere(project_root: Path) -> None:
    """Cap fitxer del paquet no pot descarregar res d'Internet."""
    for file in package_files(project_root):
        outbound = imported_modules(file) & OUTBOUND_MODULES
        assert not outbound, f"{file} podria descarregar d'Internet: {outbound}"


def test_no_model_library_anywhere(project_root: Path) -> None:
    for file in package_files(project_root):
        models = imported_modules(file) & MODEL_MODULES
        assert not models, f"{file} importa una biblioteca de models: {models}"


def test_the_check_detects_a_forbidden_import(tmp_path: Path) -> None:
    """La comprovació sap distingir un transport local d'una descàrrega."""
    local = tmp_path / "local.py"
    local.write_text("from http.server import HTTPServer\nimport socket\n", encoding="utf-8")
    assert imported_modules(local) & FORBIDDEN_MODULES - LOOPBACK_MODULES == set()
    assert not imported_modules(local) & OUTBOUND_MODULES
    downloads = tmp_path / "baixa.py"
    downloads.write_text("import urllib.request\n", encoding="utf-8")
    assert imported_modules(downloads) & OUTBOUND_MODULES == {"urllib.request"}
    # «urllib.parse» no compta: no obre cap connexió.
    parses = tmp_path / "analitza.py"
    parses.write_text("from urllib.parse import urlencode\n", encoding="utf-8")
    assert not imported_modules(parses) & OUTBOUND_MODULES
    imports = tmp_path / "importa.py"
    imports.write_text("import requests\nimport torch\n", encoding="utf-8")
    assert imported_modules(imports) & OUTBOUND_MODULES == {"requests"}
    assert imported_modules(imports) & MODEL_MODULES == {"torch"}


def test_declared_dependencies_are_local_only(project_root: Path) -> None:
    import tomllib

    data = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = [d.lower() for d in data["project"]["dependencies"]]
    assert all(d.startswith("pyyaml") for d in dependencies)
