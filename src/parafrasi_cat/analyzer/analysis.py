"""Resultat de l'anàlisi d'un text i protocol dels analitzadors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from parafrasi_cat.analyzer.sentences import Sentence, SentenceSplitter
from parafrasi_cat.analyzer.tokens import Token


@dataclass(frozen=True, slots=True)
class Analysis:
    """Text analitzat: seqüència de frases amb tokens."""

    text: str
    sentences: tuple[Sentence, ...]

    @property
    def words(self) -> tuple[Token, ...]:
        return tuple(token for sentence in self.sentences for token in sentence.words)

    @property
    def n_sentences(self) -> int:
        return len(self.sentences)

    def to_dict(self) -> dict[str, object]:
        return {"text": self.text, "sentences": [s.to_dict() for s in self.sentences]}


@runtime_checkable
class Analyzer(Protocol):
    """Qualsevol component capaç d'analitzar un text.

    Els adaptadors d'eines externes (Apertium, FreeLing, etc.) han
    d'implementar aquest protocol per poder substituir l'analitzador bàsic.
    """

    def analyze(self, text: str) -> Analysis: ...


class RuleBasedAnalyzer:
    """Analitzador per defecte: segmentació i tokenització basades en regles."""

    def __init__(self, splitter: SentenceSplitter | None = None) -> None:
        self._splitter = splitter or SentenceSplitter()

    @property
    def splitter(self) -> SentenceSplitter:
        return self._splitter

    def analyze(self, text: str) -> Analysis:
        return Analysis(text=text, sentences=self._splitter.split(text))
