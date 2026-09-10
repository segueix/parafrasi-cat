"""Càrrega del corpus d'un autor: corpus principal, de validació i textos exclosos.

Els documents són fitxers de text pla (``.txt`` o ``.md``, UTF-8) dins d'un
directori, llegits en ordre determinista (per nom). Els fitxers
``README.md`` i els buits s'ometen. Un fitxer ``exclosos.txt`` dins del
directori del corpus pot llistar noms o patrons (``fnmatch``) a excloure, un
per línia; l'ordre ``style build`` accepta també ``--exclude``.

**Duplicats.** Dos documents amb el mateix contingut compten una sola vegada,
encara que tinguin noms diferents. La comparació es fa sobre el text
normalitzat només en allò que no en canvia res (:func:`normalized_text`): final
de línia, espais al final de cada línia i línies en blanc al principi i al
final. No s'hi toca ni la puntuació, ni les majúscules, ni els espais interiors.

**Solapament entre corpus.** Un document que és al corpus principal i també al
de validació es conserva **al principal** i s'exclou del de validació: si no,
l'empremta es compararia amb un text que ella mateixa ha ajudat a definir i la
validació sortiria bona per construcció.

Cap fitxer original no es toca mai: excloure és no llegir-lo, no esborrar-lo.
Tampoc no s'hi dedueix autoria ni procedència: només es comparen continguts.
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

DUPLICATE_REASON = "duplicat de «{name}» (mateix contingut)"
OVERLAP_REASON = "ja és al corpus principal com a «{name}»: no pot validar-se a si mateix"


def normalized_text(text: str) -> str:
    """Text amb les diferències innòcues esborrades, per comparar continguts.

    Només s'hi normalitza el final de línia, l'espai al final de cada línia i
    les línies en blanc del principi i del final. Tota la resta —majúscules,
    puntuació, espais interiors— es conserva: dos textos que hi difereixin no
    són el mateix document.
    """
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in unified.split("\n")).strip("\n")


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

    @property
    def content_key(self) -> str:
        """Resum del text normalitzat: dos documents iguals el tenen idèntic."""
        digest = hashlib.sha256(normalized_text(self.text).encode("utf-8"))
        return digest.hexdigest()[:_HASH_LENGTH]


@dataclass(frozen=True, slots=True)
class ExcludedDocument:
    name: str
    reason: str
    duplicate_of: str = ""
    """Nom del document que ja aportava aquest contingut (buit si no és cap duplicat)."""

    def to_dict(self) -> dict[str, str]:
        entry = {"name": self.name, "reason": self.reason}
        if self.duplicate_of:
            entry["duplicate_of"] = self.duplicate_of
        return entry


@dataclass(frozen=True, slots=True)
class Corpus:
    """Documents carregats, per paper, amb la llista dels exclosos."""

    documents: tuple[CorpusDocument, ...]
    excluded: tuple[ExcludedDocument, ...] = ()
    root: Path | None = None
    corpus_type: str = ""
    """Mena de corpus que ha indicat qui el construeix («prosa d'investigació»…).

    És una etiqueta lliure: no canvia cap càlcul, només queda desada a
    l'empremta perquè es pugui saber amb quina mena de text s'ha fet.
    """

    @property
    def main(self) -> tuple[CorpusDocument, ...]:
        return tuple(d for d in self.documents if d.role is CorpusRole.MAIN)

    @property
    def validation(self) -> tuple[CorpusDocument, ...]:
        return tuple(d for d in self.documents if d.role is CorpusRole.VALIDATION)

    @property
    def duplicates(self) -> tuple[ExcludedDocument, ...]:
        """Documents exclosos per contingut repetit (dins d'un corpus o entre els dos)."""
        return tuple(e for e in self.excluded if e.duplicate_of)

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
    corpus_type: str = "",
) -> Corpus:
    """Carrega el corpus principal i, si s'indica, el de validació.

    ``exclude`` admet rutes de fitxer, rutes de directori (s'exclou tot el
    contingut) i patrons ``fnmatch`` sobre el nom relatiu (``esborrany*``).

    Els documents de contingut repetit s'exclouen: el primer per ordre de nom
    es conserva i la resta queda a :attr:`Corpus.excluded` amb el nom del que
    l'aporta. Un document del corpus de validació que ja sigui al principal
    s'exclou de la validació, no del principal.

    ``corpus_type`` és una etiqueta lliure («prosa d'investigació») que no
    canvia cap càlcul: només queda desada.
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
    seen: dict[str, tuple[str, CorpusRole]] = {}

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
            first = seen.get(document.content_key)
            if first is not None:
                previous, previous_role = first
                template = OVERLAP_REASON if previous_role is not role else DUPLICATE_REASON
                excluded.append(
                    ExcludedDocument(name, template.format(name=previous), duplicate_of=previous)
                )
                continue
            seen[document.content_key] = (name, role)
            documents.append(document)

    collect(base, CorpusRole.MAIN)
    if validation_dir is not None:
        collect(Path(validation_dir), CorpusRole.VALIDATION)
    return Corpus(tuple(documents), tuple(excluded), root=base, corpus_type=corpus_type)


def corpus_from_texts(
    texts: Iterable[str],
    *,
    prefix: str = "text",
    role: CorpusRole = CorpusRole.MAIN,
    corpus_type: str = "",
) -> Corpus:
    """Corpus en memòria (útil per a proves i per a l'API).

    Els textos repetits compten una sola vegada, amb el mateix criteri que
    :func:`load_corpus`: qui puja dues vegades el mateix document des de la
    interfície no infla el corpus sense adonar-se'n.
    """
    documents: list[CorpusDocument] = []
    excluded: list[ExcludedDocument] = []
    seen: dict[str, str] = {}
    for index, text in enumerate(texts):
        if not text.strip():
            continue
        name = f"{prefix}-{index + 1}"
        document = CorpusDocument(name=name, path=Path(name), text=text, role=role)
        first = seen.get(document.content_key)
        if first is not None:
            excluded.append(
                ExcludedDocument(name, DUPLICATE_REASON.format(name=first), duplicate_of=first)
            )
            continue
        seen[document.content_key] = name
        documents.append(document)
    return Corpus(tuple(documents), tuple(excluded), corpus_type=corpus_type)
