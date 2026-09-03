"""Segmentació de text en paràgrafs."""

from __future__ import annotations

import re
from dataclasses import dataclass

from parafrasi_cat.core.spans import Span

_BLANK_LINE_RE = re.compile(r"(?:\r?\n|\r)(?:[ \t\f\v]*(?:\r?\n|\r))+")
_ANY_LINE_BREAK_RE = re.compile(r"(?:\r?\n|\r)+")


@dataclass(frozen=True, slots=True)
class Paragraph:
    """Un paràgraf: bloc de text amb la seva posició al document."""

    index: int
    text: str
    span: Span

    def to_dict(self) -> dict[str, object]:
        return {"index": self.index, "text": self.text, "span": self.span.to_dict()}


class ParagraphSplitter:
    """Separa el text en paràgrafs.

    Per defecte, un paràgraf acaba en una línia en blanc (dos salts de línia,
    amb espais opcionals entremig). Amb ``split_on_single_newline`` qualsevol
    salt de línia tanca el paràgraf (útil per a textos amb una frase per línia).
    El text de cada paràgraf s'obté sense els espais que l'envolten; els
    intervals apunten al document original.
    """

    def __init__(self, *, split_on_single_newline: bool = False) -> None:
        self._separator = _ANY_LINE_BREAK_RE if split_on_single_newline else _BLANK_LINE_RE

    def split(self, text: str) -> tuple[Paragraph, ...]:
        paragraphs: list[Paragraph] = []
        start = 0
        for match in self._separator.finditer(text):
            self._append(paragraphs, text, start, match.start())
            start = match.end()
        self._append(paragraphs, text, start, len(text))
        return tuple(paragraphs)

    @staticmethod
    def _append(paragraphs: list[Paragraph], text: str, start: int, end: int) -> None:
        segment = text[start:end]
        stripped = segment.strip()
        if not stripped:
            return
        begin = start + (len(segment) - len(segment.lstrip()))
        paragraphs.append(Paragraph(len(paragraphs), stripped, Span(begin, begin + len(stripped))))
