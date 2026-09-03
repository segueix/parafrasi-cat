"""Càrrega del corpus d'un autor: corpus principal, de validació i textos exclosos.

Els documents són fitxers de text pla (``.txt`` o ``.md``, UTF-8) dins d'un
directori, llegits en ordre determinista (per nom). Els fitxers
``README.md`` i els buits s'ometen. Un fitxer ``exclosos.txt`` dins del
directori del corpus pot llistar noms o patrons (``fnmatch``) a excloure, un
per línia; l'ordre ``style build`` accepta també ``--exclude``.
"""

from __future__ import annotations

import fnmatch
import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from parafrasi_cat.core.errors import ResourceError

TEXT_EXTENSIONS: tuple[str, ...] = (".txt", ".md")
EXCLUSION_LIST_FILE = "exclosos.txt"
_HASH_LENGTH = 12


class CorpusRole(StrEnum):
    MAIN = "main"
    """Corpus principal: el que defineix l'empremta."""

    VALIDATION = "validation"
    """Corpus de validació: es compara amb l'empremta per mesurar-ne l'estabilitat."""


@dataclass(frozen=True, slots=True)
class CorpusDocument:
    """Un text del corpus amb el seu nom relatiu, el paper i un resum criptogràfic."""

    name: str
    path: Path
    text: str
    role: CorpusRole = CorpusRole.MAIN

    @property
    def sha256(self) -> str:
        """Prefix del SHA-256 del text: identifica el contingut sense desar-lo."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:_HASH_LENGTH]


@dataclass(frozen=True, slots=True)
class ExcludedDocument:
    name: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class Corpus:
    """Documents carregats, per paper, amb la llista dels exclosos."""

    documents: tuple[CorpusDocument, ...]
    excluded: tuple[ExcludedDocument, ...] = ()
    root: Path | None = None

    @property
    def main(self) -> tuple[CorpusDocument, ...]:
        return tuple(d for d in self.documents if d.role is CorpusRole.MAIN)

    @property
    def validation(self) -> tuple[CorpusDocument, ...]:
        return tuple(d for d in self.documents if d.role is CorpusRole.VALIDATION)

    def __len__(self) -> int:
        return len(self.documents)


def read_document(
    path: str | Path, name: str | None = None, role: CorpusRole = CorpusRole.MAIN
) -> CorpusDocument:
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ResourceError(f"No s'ha pogut llegir el document «{file}»: {exc}") from exc
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return CorpusDocument(name=name or file.name, path=file, text=text, role=role)


def list_text_files(
    directory: str | Path, extensions: Sequence[str] = TEXT_EXTENSIONS
) -> list[Path]:
    """Fitxers de text del directori (recursiu), ordenats per ruta relativa."""
    base = Path(directory)
    if not base.is_dir():
        raise ResourceError(f"El directori de corpus «{base}» no existeix")
    files = [
        p
        for p in base.rglob("*")
        if p.is_file() and p.suffix.lower() in extensions and p.name.lower() != "readme.md"
    ]
    return sorted(files, key=lambda p: p.relative_to(base).as_posix())


def read_exclusion_list(directory: str | Path) -> tuple[str, ...]:
    file = Path(directory) / EXCLUSION_LIST_FILE
    if not file.is_file():
        return ()
    patterns: list[str] = []
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            patterns.append(line)
    return tuple(patterns)


def load_corpus(
    main_dir: str | Path,
    *,
    validation_dir: str | Path | None = None,
    exclude: Iterable[str | Path] = (),
    extensions: Sequence[str] = TEXT_EXTENSIONS,
) -> Corpus:
    """Carrega el corpus principal i, si s'indica, el de validació.

    ``exclude`` admet rutes de fitxer, rutes de directori (s'exclou tot el
    contingut) i patrons ``fnmatch`` sobre el nom relatiu (``esborrany*``).
    """
    base = Path(main_dir)
    excluded_paths: set[Path] = set()
    excluded_dirs: list[Path] = []
    patterns: list[str] = list(read_exclusion_list(base))
    for item in exclude:
        candidate = Path(item)
        if candidate.is_dir():
            excluded_dirs.append(candidate.resolve())
        elif candidate.is_file():
            excluded_paths.add(candidate.resolve())
        else:
            patterns.append(str(item))

    documents: list[CorpusDocument] = []
    excluded: list[ExcludedDocument] = []

    def collect(directory: Path, role: CorpusRole) -> None:
        for file in list_text_files(directory, extensions):
            name = file.relative_to(directory).as_posix()
            if role is CorpusRole.VALIDATION:
                name = f"validation/{name}"
            resolved = file.resolve()
            if resolved in excluded_paths or any(resolved.is_relative_to(d) for d in excluded_dirs):
                excluded.append(ExcludedDocument(name, "exclòs explícitament"))
                continue
            if file.name == EXCLUSION_LIST_FILE:
                continue
            matched = next(
                (p for p in patterns if fnmatch.fnmatch(name, p) or fnmatch.fnmatch(file.name, p)),
                None,
            )
            if matched is not None:
                excluded.append(ExcludedDocument(name, f"coincideix amb el patró «{matched}»"))
                continue
            document = read_document(file, name, role)
            if not document.text.strip():
                excluded.append(ExcludedDocument(name, "document buit"))
                continue
            documents.append(document)

    collect(base, CorpusRole.MAIN)
    if validation_dir is not None:
        collect(Path(validation_dir), CorpusRole.VALIDATION)
    return Corpus(tuple(documents), tuple(excluded), root=base)


def corpus_from_texts(
    texts: Iterable[str], *, prefix: str = "text", role: CorpusRole = CorpusRole.MAIN
) -> Corpus:
    """Corpus en memòria (útil per a proves i per a l'API)."""
    documents = tuple(
        CorpusDocument(name=f"{prefix}-{i + 1}", path=Path(f"{prefix}-{i + 1}"), text=t, role=role)
        for i, t in enumerate(texts)
        if t.strip()
    )
    return Corpus(documents)
