"""Identificació d'expressions multiparaula registrades al lexicó.

Connectors («no obstant això»), marcadors discursius («d'altra banda»),
preposicions i conjuncions compostes («a partir de», «tot i que») i locucions
adverbials, incloses les llatines («a priori», «in situ»).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon, WordClass
from parafrasi_cat.analyzer.tokens import Token
from parafrasi_cat.core.spans import Span


@dataclass(frozen=True, slots=True)
class MultiwordExpression:
    """Una expressió multiparaula localitzada dins d'una frase."""

    text: str
    span: Span
    lemma: str
    word_class: WordClass
    function: str = ""
    origin: str = ""
    token_indices: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "span": self.span.to_dict(),
            "lemma": self.lemma,
            "word_class": self.word_class.value,
            "function": self.function,
            "origin": self.origin,
            "token_indices": list(self.token_indices),
        }


def find_multiword_expressions(
    text: str, tokens: Sequence[Token], lexicon: ClosedClassLexicon
) -> tuple[MultiwordExpression, ...]:
    """Cerca les expressions multiparaula del lexicó (més llargues primer, sense solapaments)."""
    found: list[MultiwordExpression] = []
    taken: list[Span] = []
    for entry, pattern in lexicon.multiword_patterns():
        for match in pattern.finditer(text):
            span = Span(match.start(), match.end())
            if any(span.overlaps(t) for t in taken):
                continue
            taken.append(span)
            indices = tuple(i for i, token in enumerate(tokens) if span.contains(token.span))
            found.append(
                MultiwordExpression(
                    text=match.group(0),
                    span=span,
                    lemma=entry.lemma,
                    word_class=entry.word_class,
                    function=entry.function,
                    origin=entry.origin,
                    token_indices=indices,
                )
            )
    found.sort(key=lambda e: e.span.start)
    return tuple(found)
