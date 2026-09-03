"""Garantia estructural: el paquet no pot obrir connexions de xarxa ni fer telemetria."""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_MODULES = {
    "socket",
    "ssl",
    "http",
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
    "openai",
    "anthropic",
    "transformers",
    "torch",
    "tensorflow",
}


def imported_modules(file: Path) -> set[str]:
    tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    return modules


def test_package_has_no_network_or_model_imports(project_root: Path) -> None:
    package = project_root / "src" / "parafrasi_cat"
    files = list(package.rglob("*.py"))
    assert files
    for file in files:
        forbidden = imported_modules(file) & FORBIDDEN_MODULES
        assert not forbidden, f"{file} importa mòduls prohibits: {forbidden}"


def test_declared_dependencies_are_local_only(project_root: Path) -> None:
    import tomllib

    data = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = [d.lower() for d in data["project"]["dependencies"]]
    assert all(d.startswith("pyyaml") for d in dependencies)
