"""Segmentació de text en frases."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from parafrasi_cat.analyzer.tokens import Token, Tokenizer
from parafrasi_cat.core.spans import Span

#: Abreviatures habituals en català (sense punt final, en minúscules) després
#: de les quals un punt no marca final de frase.
DEFAULT_ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "sr",
        "sra",
        "srs",
        "sres",
        "dr",
        "dra",
        "drs",
        "dres",
        "prof",
        "profa",
        "p",
        "pp",
        "pàg",
        "pàgs",
        "núm",
        "núms",
        "art",
        "arts",
        "cap",
        "caps",
        "vol",
        "vols",
        "s",
        "ss",
        "st",
        "sta",
        "sts",
        "stes",
        "ca",
        "c",
        "ed",
        "eds",
        "fig",
        "figs",
        "aprox",
        "av",
        "pl",
        "ptge",
        "ctra",
        "tel",
        "ex",
        "cf",
        "vid",
        "op",
        "cit",
        "ibid",
        "ibíd",
        "íd",
        "id",
        "màx",
        "mín",
        "seg",
        "trad",
        "ap",
        "apt",
        "esc",
        "dept",
        "dpt",
        "col",
        "coord",
        "dir",
        "et",
        "al",
        "loc",
        "ms",
        "tít",
        "ll",
        "v",
        "vv",
        "vg",
        "vgr",
        "n",
        "nre",
        "adm",
        "admdor",
        "a",
        "ac",
        "dc",
        "hble",
        "mn",
        "mons",
        "il·lm",
        "il·lma",
        "excm",
        "excma",
        "rev",
        "revda",
    }
)

#: Abreviatures que sovint tanquen una frase: si van seguides de majúscula,
#: sí que es consideren final de frase.
_SENTENCE_FINAL_OK: frozenset[str] = frozenset({"etc"})

_BOUNDARY_RE = re.compile(r"[.!?…]+[\"»”’)\]]*")
_LINE_BREAK_RE = re.compile(r"\n+")
_PRECEDING_WORD_RE = re.compile(r"([^\W\d_]+(?:[·\-][^\W\d_]+)*)$")
_OPENERS = '«“"([‘'


@dataclass(frozen=True, slots=True)
class Sentence:
    """Una frase amb el seu text, la posició al document i els tokens.

    Els intervals dels tokens són relatius al text de la frase; ``span`` és
    relatiu al document sencer.
    """

    index: int
    text: str
    span: Span
    tokens: tuple[Token, ...]

    @property
    def words(self) -> tuple[Token, ...]:
        """Tokens amb contingut lèxic (paraules, clítics i nombres)."""
        return tuple(token for token in self.tokens if token.is_lexical)

    def absolute(self, span: Span) -> Span:
        """Converteix un interval relatiu a la frase en un de relatiu al document."""
        return span.shift(self.span.start)

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "text": self.text,
            "span": self.span.to_dict(),
            "tokens": [token.to_dict() for token in self.tokens],
        }


class SentenceSplitter:
    """Segmentador de frases basat en puntuació, salts de línia i abreviatures.

    Criteris:

    - ``.``, ``!``, ``?`` i ``…`` (seguits opcionalment de cometes o parèntesis
      de tancament) marquen un final de frase si van seguits d'espai i la
      següent unitat comença amb majúscula, dígit o signe d'obertura.
    - Un punt després d'una abreviatura coneguda o d'una inicial (una sola
      lletra majúscula) no tanca la frase.
    - Un salt de línia sempre tanca la frase.
    """

    def __init__(
        self,
        abbreviations: Iterable[str] = DEFAULT_ABBREVIATIONS,
        tokenizer: Tokenizer | None = None,
    ) -> None:
        self._abbreviations = frozenset(a.lower().rstrip(".") for a in abbreviations)
        self._tokenizer = tokenizer or Tokenizer()

    @property
    def abbreviations(self) -> frozenset[str]:
        return self._abbreviations

    def boundaries(self, text: str) -> list[int]:
        """Posicions (exclusives) on acaba una frase."""
        cuts: set[int] = set()
        for match in _BOUNDARY_RE.finditer(text):
            end = match.end()
            if end < len(text) and not text[end].isspace():
                continue
            next_index = _next_non_space(text, end)
            if next_index is not None:
                following = text[next_index]
                if not (following.isupper() or following.isdigit() or following in _OPENERS):
                    continue
            if "." in match.group(0) and self._is_abbreviation(text, match.start()):
                continue
            cuts.add(end)
        for match in _LINE_BREAK_RE.finditer(text):
            cuts.add(match.start())
        return sorted(cuts)

    def split(self, text: str) -> tuple[Sentence, ...]:
        sentences: list[Sentence] = []
        start = 0
        for cut in [*self.boundaries(text), len(text)]:
            segment = text[start:cut]
            sentence = self._build(len(sentences), segment, start)
            if sentence is not None:
                sentences.append(sentence)
            start = cut
        return tuple(sentences)

    def _build(self, index: int, segment: str, offset: int) -> Sentence | None:
        stripped = segment.strip()
        if not stripped:
            return None
        leading = len(segment) - len(segment.lstrip())
        begin = offset + leading
        span = Span(begin, begin + len(stripped))
        return Sentence(index, stripped, span, self._tokenizer.tokenize(stripped))

    def _is_abbreviation(self, text: str, boundary_start: int) -> bool:
        match = _PRECEDING_WORD_RE.search(text, 0, boundary_start)
        if match is None:
            return False
        word = match.group(1)
        if len(word) == 1 and word.isupper():
            return True  # inicial d'un nom: «J. Verdaguer»
        lowered = word.lower()
        if lowered in _SENTENCE_FINAL_OK:
            return False
        return lowered in self._abbreviations


def _next_non_space(text: str, index: int) -> int | None:
    while index < len(text):
        if not text[index].isspace():
            return index
        index += 1
    return None
