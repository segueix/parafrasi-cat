"""Identificació de les formes amb guionet."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from parafrasi_cat.analyzer.tokens import Token, TokenKind, TokenSubkind
from parafrasi_cat.core.spans import Span


class HyphenKind(StrEnum):
    ENCLITIC_PRONOUNS = "enclitic_pronouns"
    """Verb amb pronoms enclítics: porta-ho, vés-te'n, dona-m'ho."""

    COMPOUND = "compound"
    """Mot compost o prefixat: sud-oest, pèl-roig, ex-president, Vila-seca."""

    NUMERIC_RANGE = "numeric_range"
    """Interval numèric: 1507-1516, 12-15."""

    SEPARATOR = "separator"
    """Guionet aïllat que fa de separador."""


@dataclass(frozen=True, slots=True)
class HyphenatedForm:
    """Una forma amb guionet localitzada dins d'una frase."""

    text: str
    span: Span
    kind: HyphenKind
    parts: tuple[str, ...]
    token_indices: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "span": self.span.to_dict(),
            "kind": self.kind.value,
            "parts": list(self.parts),
            "token_indices": list(self.token_indices),
        }


def find_hyphenated_forms(text: str, tokens: Sequence[Token]) -> tuple[HyphenatedForm, ...]:
    """Localitza mots compostos, verbs amb enclítics, intervals i guionets aïllats."""
    found: list[HyphenatedForm] = []
    n = len(tokens)
    index = 0
    while index < n:
        token = tokens[index]
        if token.kind is TokenKind.WORD and "-" in token.text:
            found.append(
                HyphenatedForm(
                    token.text,
                    token.span,
                    HyphenKind.COMPOUND,
                    tuple(token.text.split("-")),
                    (index,),
                )
            )
        if token.kind in (TokenKind.WORD, TokenKind.CLITIC) and (
            token.subkind is not TokenSubkind.ENCLITIC
        ):
            end = index + 1
            while (
                end < n
                and tokens[end].kind is TokenKind.CLITIC
                and tokens[end].subkind is TokenSubkind.ENCLITIC
                and tokens[end].span.start == tokens[end - 1].span.end
            ):
                end += 1
            chain = tokens[index + 1 : end]
            if chain and any(t.text.startswith("-") for t in chain):
                span = Span(token.span.start, tokens[end - 1].span.end)
                found.append(
                    HyphenatedForm(
                        span.slice(text),
                        span,
                        HyphenKind.ENCLITIC_PRONOUNS,
                        (token.text, *(t.text for t in chain)),
                        tuple(range(index, end)),
                    )
                )
                index = end
                continue
        if (
            token.kind is TokenKind.PUNCT
            and token.subkind is TokenSubkind.HYPHEN
            and 0 < index < n - 1
            and tokens[index - 1].kind is TokenKind.NUMBER
            and tokens[index + 1].kind is TokenKind.NUMBER
            and tokens[index - 1].span.end == token.span.start
            and token.span.end == tokens[index + 1].span.start
        ):
            span = Span(tokens[index - 1].span.start, tokens[index + 1].span.end)
            found.append(
                HyphenatedForm(
                    span.slice(text),
                    span,
                    HyphenKind.NUMERIC_RANGE,
                    (tokens[index - 1].text, tokens[index + 1].text),
                    (index - 1, index, index + 1),
                )
            )
        elif token.kind is TokenKind.PUNCT and token.subkind is TokenSubkind.HYPHEN:
            found.append(
                HyphenatedForm(token.text, token.span, HyphenKind.SEPARATOR, ("-",), (index,))
            )
        index += 1
    return tuple(found)
