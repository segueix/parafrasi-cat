"""Identificació dels apòstrofs d'una frase i de la seva funció."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from parafrasi_cat.analyzer.clitics import Certainty, WeakPronoun
from parafrasi_cat.analyzer.tokens import Token, TokenKind, TokenSubkind
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.text import APOSTROPHES


class ApostropheKind(StrEnum):
    ARTICLE_OR_PRONOUN = "article_or_pronoun"
    """«l'»: article elidit (l'home) o pronom (l'he vist); sense context no es distingeix."""

    ELISION_PREPOSITION = "elision_preposition"
    """«d'»: la preposició «de» elidida (d'altra banda)."""

    PROCLITIC_PRONOUN = "proclitic_pronoun"
    """«m'», «t'», «s'», «n'» (i «l'» quan el context confirma que és pronom)."""

    ENCLITIC_PRONOUN = "enclitic_pronoun"
    """Apòstrof d'un pronom enclític: menja'n, porta'ls, dona-m'ho."""

    QUOTE = "quote"
    """Cometes simples tipogràfiques ‘…’."""

    ISOLATED = "isolated"
    """Apòstrof aïllat, sense mot al qual adherir-se."""

    OTHER = "other"
    """Apòstrof dins d'un mot no català (O'Neill)."""


@dataclass(frozen=True, slots=True)
class Apostrophe:
    """Un apòstrof localitzat dins d'una frase."""

    span: Span
    char: str
    kind: ApostropheKind
    token_index: int
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "span": self.span.to_dict(),
            "char": self.char,
            "kind": self.kind.value,
            "token_index": self.token_index,
            "note": self.note,
        }


def find_apostrophes(
    tokens: Sequence[Token], pronouns: Sequence[WeakPronoun] = ()
) -> tuple[Apostrophe, ...]:
    """Localitza i classifica tots els apòstrofs dels tokens d'una frase."""
    sure_pronoun_tokens = {p.token_index for p in pronouns if p.certainty is Certainty.SURE}
    found: list[Apostrophe] = []
    for index, token in enumerate(tokens):
        for offset, char in enumerate(token.text):
            if char not in APOSTROPHES:
                continue
            span = Span(token.span.start + offset, token.span.start + offset + 1)
            found.append(
                Apostrophe(span, char, _classify(token, index, sure_pronoun_tokens), index)
            )
    return tuple(found)


def _classify(token: Token, index: int, sure_pronoun_tokens: set[int]) -> ApostropheKind:
    if token.kind is TokenKind.CLITIC:
        if token.subkind is TokenSubkind.ENCLITIC:
            return ApostropheKind.ENCLITIC_PRONOUN
        letter = token.text[0].lower()
        if letter == "d":
            return ApostropheKind.ELISION_PREPOSITION
        if letter == "l":
            if index in sure_pronoun_tokens:
                return ApostropheKind.PROCLITIC_PRONOUN
            return ApostropheKind.ARTICLE_OR_PRONOUN
        return ApostropheKind.PROCLITIC_PRONOUN
    if token.kind is TokenKind.PUNCT:
        if token.subkind in (TokenSubkind.QUOTE_OPEN, TokenSubkind.QUOTE_CLOSE):
            return ApostropheKind.QUOTE
        return ApostropheKind.ISOLATED
    return ApostropheKind.OTHER
