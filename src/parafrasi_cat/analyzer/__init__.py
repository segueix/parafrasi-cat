"""Anàlisi superficial del text: segmentació en frases i tokenització.

En aquesta fase l'anàlisi és purament basada en regles i expressions
regulars. Els analitzadors més potents (morfosintàctics, sintàctics) s'han
d'integrar com a adaptadors que compleixin el protocol :class:`Analyzer`.
"""

from parafrasi_cat.analyzer.analysis import Analysis, Analyzer, RuleBasedAnalyzer
from parafrasi_cat.analyzer.sentences import (
    DEFAULT_ABBREVIATIONS,
    Sentence,
    SentenceSplitter,
)
from parafrasi_cat.analyzer.tokens import Token, Tokenizer, TokenKind

__all__ = [
    "DEFAULT_ABBREVIATIONS",
    "Analysis",
    "Analyzer",
    "RuleBasedAnalyzer",
    "Sentence",
    "SentenceSplitter",
    "Token",
    "TokenKind",
    "Tokenizer",
]
