"""Resultat de l'anàlisi d'un text i protocol dels analitzadors."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable

from parafrasi_cat.analyzer.clitics import find_weak_pronouns
from parafrasi_cat.analyzer.expressions import find_multiword_expressions
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon, WordClass
from parafrasi_cat.analyzer.numerals import looks_like_roman_numeral
from parafrasi_cat.analyzer.paragraphs import Paragraph, ParagraphSplitter
from parafrasi_cat.analyzer.sentences import Sentence, SentenceSplitter
from parafrasi_cat.analyzer.tokens import Token, TokenKind, TokenSubkind


@dataclass(frozen=True, slots=True)
class Analysis:
    """Text analitzat: paràgrafs i seqüència de frases amb tokens i anotacions."""

    text: str
    sentences: tuple[Sentence, ...]
    paragraphs: tuple[Paragraph, ...] = ()

    @property
    def words(self) -> tuple[Token, ...]:
        return tuple(token for sentence in self.sentences for token in sentence.words)

    @property
    def n_sentences(self) -> int:
        return len(self.sentences)

    @property
    def n_paragraphs(self) -> int:
        return len(self.paragraphs)

    def sentences_of(self, paragraph: Paragraph | int) -> tuple[Sentence, ...]:
        index = paragraph if isinstance(paragraph, int) else paragraph.index
        return tuple(s for s in self.sentences if s.paragraph_index == index)

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "paragraphs": [p.to_dict() for p in self.paragraphs],
            "sentences": [s.to_dict() for s in self.sentences],
        }


@runtime_checkable
class Analyzer(Protocol):
    """Qualsevol component capaç d'analitzar un text.

    Els adaptadors d'eines externes (Apertium, FreeLing, etc.) han
    d'implementar aquest protocol per poder substituir l'analitzador bàsic.
    """

    def analyze(self, text: str) -> Analysis: ...


class RuleBasedAnalyzer:
    """Analitzador per defecte: paràgrafs, frases, tokens i anotacions basades en regles.

    Amb un :class:`ClosedClassLexicon` també identifica expressions multiparaula
    i fa servir les formes auxiliars del lexicó per resoldre els pronoms febles.
    """

    def __init__(
        self,
        splitter: SentenceSplitter | None = None,
        *,
        paragraph_splitter: ParagraphSplitter | None = None,
        lexicon: ClosedClassLexicon | None = None,
    ) -> None:
        self._splitter = splitter or SentenceSplitter()
        self._paragraphs = paragraph_splitter or ParagraphSplitter()
        self._lexicon = lexicon
        self._auxiliary_forms: frozenset[str] | None = (
            lexicon.forms_of(WordClass.AUXILIARY) if lexicon is not None else None
        )

    @property
    def splitter(self) -> SentenceSplitter:
        return self._splitter

    @property
    def lexicon(self) -> ClosedClassLexicon | None:
        return self._lexicon

    def analyze(self, text: str) -> Analysis:
        paragraphs = self._paragraphs.split(text)
        sentences: list[Sentence] = []
        for paragraph in paragraphs:
            for sentence in self._splitter.split(paragraph.text):
                sentences.append(
                    self.enrich(
                        replace(
                            sentence,
                            index=len(sentences),
                            span=sentence.span.shift(paragraph.span.start),
                            paragraph_index=paragraph.index,
                        )
                    )
                )
        return Analysis(text=text, sentences=tuple(sentences), paragraphs=paragraphs)

    def enrich(self, sentence: Sentence) -> Sentence:
        """Afegeix subcategories de tokens, pronoms febles i expressions multiparaula."""
        tokens = tuple(self._annotate_tokens(sentence))
        if self._auxiliary_forms is not None and self._auxiliary_forms:
            pronouns = find_weak_pronouns(tokens, auxiliary_forms=self._auxiliary_forms)
        else:
            pronouns = find_weak_pronouns(tokens)
        expressions = (
            find_multiword_expressions(sentence.text, tokens, self._lexicon)
            if self._lexicon is not None
            else ()
        )
        return replace(sentence, tokens=tokens, pronouns=pronouns, expressions=expressions)

    def _annotate_tokens(self, sentence: Sentence) -> list[Token]:
        tokens = list(sentence.tokens)
        abbreviations = self._splitter.abbreviations
        for index, token in enumerate(tokens):
            if token.kind is not TokenKind.WORD or token.subkind is not None:
                continue
            if looks_like_roman_numeral(token.text, sentence.text[: token.span.start]):
                tokens[index] = token.with_subkind(TokenSubkind.ROMAN_NUMERAL)
            elif (
                token.lower in abbreviations
                and index + 1 < len(tokens)
                and tokens[index + 1].text.startswith(".")
                and tokens[index + 1].span.start == token.span.end
            ):
                tokens[index] = token.with_subkind(TokenSubkind.ABBREVIATION)
        return tokens
