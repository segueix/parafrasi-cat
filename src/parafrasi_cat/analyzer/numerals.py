"""Números romans: reconeixement, valor i regles de context.

Una sola lletra (I, V, X, L, C, D, M) només es considera numeral si el context
ho confirma («segle X», «Jaume I», «capítol V»), per evitar confondre-la amb
la conjunció «I» o amb una sigla.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.text import LETTER

ROMAN_CORE = r"M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})"

_FULL_RE = re.compile(rf"(?=[MDCLXVI])(?:{ROMAN_CORE})(?P<ordinal>è)?\Z")
_WORD_BEFORE_RE = re.compile(rf"({LETTER}+(?:[·\-'’]{LETTER}+)*)\.?\s*\Z")

#: Paraules que, immediatament abans d'una sola lletra romana, confirmen que
#: es tracta d'un numeral: «segle X», «capítol V», «volum I», «papa Pius X».
ROMAN_CONTEXT_WORDS: frozenset[str] = frozenset(
    {
        "segle",
        "segles",
        "s",
        "ss",
        "capítol",
        "capítols",
        "cap",
        "volum",
        "volums",
        "vol",
        "tom",
        "toms",
        "part",
        "parts",
        "llibre",
        "llibres",
        "acte",
        "actes",
        "escena",
        "escenes",
        "títol",
        "títols",
        "annex",
        "annexos",
        "article",
        "articles",
        "art",
        "secció",
        "seccions",
        "apartat",
        "apartats",
        "papa",
        "rei",
        "reina",
        "emperador",
        "emperadriu",
        "comte",
        "comtessa",
        "duc",
        "duquessa",
        "fase",
        "fases",
        "nivell",
        "nivells",
        "grau",
        "graus",
        "classe",
        "tipus",
        "categoria",
        "fitxa",
        "lliçó",
        "lliçons",
        "unitat",
        "unitats",
        "quadre",
        "quadres",
        "taula",
        "taules",
        "figura",
        "figures",
        "mapa",
        "mapes",
        "làmina",
        "làmines",
        "cant",
        "cants",
        "número",
        "núm",
        "n",
        "concili",
        "dinastia",
        "legió",
        "districte",
        "regió",
    }
)

_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


@dataclass(frozen=True, slots=True)
class RomanNumeral:
    """Un número romà localitzat dins d'un text."""

    text: str
    value: int
    span: Span
    ordinal: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "value": self.value,
            "span": self.span.to_dict(),
            "ordinal": self.ordinal,
        }


def is_roman_numeral(text: str) -> bool:
    """Cert si ``text`` és un número romà en majúscules (opcionalment ordinal: XXIè)."""
    return _FULL_RE.match(text) is not None


def roman_to_int(text: str) -> int:
    """Converteix un número romà en enter. Llança ``ValueError`` si no és vàlid."""
    if not is_roman_numeral(text):
        raise ValueError(f"No és un número romà vàlid: «{text}»")
    core = text.rstrip("è")
    total = 0
    for index, char in enumerate(core):
        value = _VALUES[char]
        if index + 1 < len(core) and _VALUES[core[index + 1]] > value:
            total -= value
        else:
            total += value
    return total


def context_allows_single_letter(preceding_text: str) -> bool:
    """Cert si la paraula anterior justifica que una sola lletra sigui un numeral."""
    match = _WORD_BEFORE_RE.search(preceding_text)
    if match is None:
        return False
    word = match.group(1)
    return word.lower() in ROMAN_CONTEXT_WORDS or word[0].isupper()


def looks_like_roman_numeral(text: str, preceding_text: str = "") -> bool:
    """Cert si ``text`` és un número romà acceptable en aquest context."""
    if not is_roman_numeral(text):
        return False
    if len(text.rstrip("è")) > 1:
        return True
    return context_allows_single_letter(preceding_text)
