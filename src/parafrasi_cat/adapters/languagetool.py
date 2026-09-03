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

import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.validation.base import ValidationContext
from parafrasi_cat.validation.result import (
    ValidationDimension,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)

#: Variable d'entorn que apunta al directori de LanguageTool.
ENV_HOME = "PARAFRASI_CAT_LANGUAGETOOL"

#: Noms del fitxer executable de la línia d'ordres dins de la distribució.
COMMANDLINE_JAR = "languagetool-commandline.jar"

#: Llocs on es busca la instal·lació, en ordre.
SEARCH_PATHS: tuple[str, ...] = (
    "vendor/languagetool",
    "vendor/LanguageTool",
    "~/.local/share/parafrasi-cat/languagetool",
    "/opt/languagetool",
    "/usr/local/share/languagetool",
)

#: Separador entre candidats en una comprovació per lots. És una línia en blanc:
#: LanguageTool la tracta com a canvi de paràgraf i no hi busca errors.
BATCH_SEPARATOR = "\n\n"

#: Tipus de problema que invaliden un candidat. La resta només el penalitzen.
DEFAULT_BLOCKING_ISSUE_TYPES: frozenset[str] = frozenset(
    {"grammar", "misspelling", "typographical", "inflection", "agreement"}
)

#: Categories que invaliden un candidat encara que el tipus sigui «uncategorized».
#: Les regles catalanes de concordança («CONCORD_SUBJECTE_VERB»,
#: «CONCORDANCES_DET_NOM»...) sovint no porten tipus, però la categoria sí que
#: les identifica, i una falta de concordança no és mai acceptable.
DEFAULT_BLOCKING_CATEGORIES: tuple[str, ...] = ("CONCORDANCES",)

DEFAULT_TIMEOUT = 120.0
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


class LanguageToolClient:
    """Executa LanguageTool localment i retorna els problemes que troba.

    No modifica mai cap text: només informa. Les substitucions que LanguageTool
    proposa es transporten com a informació, però el motor no les aplica.
    """

    def __init__(
        self,
        installation: LanguageToolInstallation | None = None,
        *,
        language: str = LANGUAGE,
        timeout: float = DEFAULT_TIMEOUT,
        extra_arguments: Sequence[str] = (),
    ) -> None:
        self._installation = installation
        self._language = language
        self._timeout = timeout
        self._extra = tuple(extra_arguments)

    @classmethod
    def discover(
        cls, root: str | Path | None = None, *, language: str = LANGUAGE, **kwargs: object
    ) -> LanguageToolClient:
        """Client amb la instal·lació que es trobi; no disponible si no n'hi ha cap."""
        return cls(find_installation(root), language=language, **kwargs)  # type: ignore[arg-type]

    @property
    def installation(self) -> LanguageToolInstallation | None:
        return self._installation

    @property
    def available(self) -> bool:
        """Cert si hi ha Java i una instal·lació local de LanguageTool."""
        return self._installation is not None

    def describe(self) -> str:
        if self._installation is None:
            return "LanguageTool no instal·lat: s'utilitzen només els validadors interns"
        return self._installation.describe()

    # -- comprovació ---------------------------------------------------------------------

    def check(self, text: str) -> tuple[LanguageToolMatch, ...]:
        """Problemes d'un sol text (buit si LanguageTool no està disponible)."""
        return self.check_many([text])[0]

    def check_many(self, texts: Sequence[str]) -> tuple[tuple[LanguageToolMatch, ...], ...]:
        """Comprova diversos textos amb una sola execució de LanguageTool.

        Els textos s'envien separats per una línia en blanc i els problemes es
        reparteixen segons la posició que LanguageTool en dona, de manera que
        només cal arrencar la màquina virtual una vegada per reescriptura.
        """
        if not texts:
            return ()
        if self._installation is None:
            return tuple(() for _ in texts)
        payload = BATCH_SEPARATOR.join(texts)
        matches = self._run(payload)
        return _split_by_offset(matches, texts)

    def _run(self, payload: str) -> tuple[LanguageToolMatch, ...]:
        assert self._installation is not None
        command = [
            str(self._installation.java),
            "-jar",
            str(self._installation.jar),
            "--language",
            self._language,
            "--json",
            "--encoding",
            "utf-8",
            *self._extra,
            "-",
        ]
        try:
            completed = subprocess.run(
                command,
                input=payload,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ()
        return _parse_json(completed.stdout)


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


def _split_by_offset(
    matches: Iterable[LanguageToolMatch], texts: Sequence[str]
) -> tuple[tuple[LanguageToolMatch, ...], ...]:
    """Reparteix els problemes entre els textos segons la seva posició al lot."""
    bounds: list[tuple[int, int]] = []
    cursor = 0
    for text in texts:
        bounds.append((cursor, cursor + len(text)))
        cursor += len(text) + len(BATCH_SEPARATOR)
    grouped: list[list[LanguageToolMatch]] = [[] for _ in texts]
    for match in matches:
        for index, (start, end) in enumerate(bounds):
            if start <= match.offset < end or (match.offset == start == end):
                grouped[index].append(
                    LanguageToolMatch(
                        rule_id=match.rule_id,
                        message=match.message,
                        offset=match.offset - start,
                        length=match.length,
                        issue_type=match.issue_type,
                        category=match.category,
                        replacements=match.replacements,
                    )
                )
                break
    return tuple(tuple(group) for group in grouped)


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
