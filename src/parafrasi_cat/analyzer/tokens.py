"""Tokenització basada en regles per al català."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from parafrasi_cat.core.spans import Span


class TokenKind(StrEnum):
    WORD = "word"
    """Paraula ordinària (inclou mots amb guionet i amb ela geminada)."""

    CLITIC = "clitic"
    """Article o pronom elidit (l', d', s'...) o enclític apostrofat ('n, 'ls...)."""

    NUMBER = "number"
    PUNCT = "punct"
    SPACE = "space"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Token:
    """Unitat mínima de text amb la seva posició relativa a la frase."""

    text: str
    span: Span
    kind: TokenKind

    @property
    def is_word(self) -> bool:
        """Cert per a paraules i clítics (unitats amb contingut lèxic)."""
        return self.kind in (TokenKind.WORD, TokenKind.CLITIC)

    @property
    def is_lexical(self) -> bool:
        """Cert per a paraules, clítics i nombres."""
        return self.is_word or self.kind is TokenKind.NUMBER

    @property
    def is_punct(self) -> bool:
        return self.kind is TokenKind.PUNCT

    def to_dict(self) -> dict[str, object]:
        return {"text": self.text, "span": self.span.to_dict(), "kind": self.kind.value}


# Ordre de les alternatives: primer nombres, després proclítics apostrofats
# (l', d', s', m', n', t'), paraules (amb guionet o punt volat), enclítics
# apostrofats ('n, 'ls...), espais, puntuació i, finalment, qualsevol resta.
_TOKEN_RE = re.compile(
    r"""
    (?P<number>\d+(?:[.,]\d+)*)
    |(?P<proclitic>(?<![^\W\d_])[lLdDsSmMnNtT]['’](?=[^\W\d_]))
    |(?P<word>[^\W\d_]+(?:[·\-][^\W\d_]+)*)
    |(?P<enclitic>['’](?:ls|ns|l|n|m|s|t)(?![^\W\d_]))
    |(?P<space>\s+)
    |(?P<punct>[^\w\s])
    |(?P<other>\w+)
    """,
    re.VERBOSE,
)

_GROUP_KINDS: dict[str, TokenKind] = {
    "number": TokenKind.NUMBER,
    "proclitic": TokenKind.CLITIC,
    "word": TokenKind.WORD,
    "enclitic": TokenKind.CLITIC,
    "space": TokenKind.SPACE,
    "punct": TokenKind.PUNCT,
    "other": TokenKind.OTHER,
}


class Tokenizer:
    """Tokenitzador determinista basat en expressions regulars.

    Conserva les posicions de cada token respecte del text d'entrada, de
    manera que qualsevol token es pot localitzar exactament al text original.
    """

    def __init__(self, *, keep_spaces: bool = False) -> None:
        self._keep_spaces = keep_spaces

    def tokenize(self, text: str) -> tuple[Token, ...]:
        tokens: list[Token] = []
        for match in _TOKEN_RE.finditer(text):
            group = match.lastgroup
            if group is None:  # pragma: no cover - el patró sempre assigna un grup
                continue
            kind = _GROUP_KINDS[group]
            if kind is TokenKind.SPACE and not self._keep_spaces:
                continue
            tokens.append(Token(match.group(0), Span(match.start(), match.end()), kind))
        return tuple(tokens)
