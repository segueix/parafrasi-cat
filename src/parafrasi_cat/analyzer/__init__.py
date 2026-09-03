"""Anàlisi lingüística superficial del català basada en regles.

Nivells d'anàlisi:

- paràgrafs (:class:`ParagraphSplitter`) i frases (:class:`SentenceSplitter`);
- tokens amb subcategoria (:class:`Tokenizer`): proclítics, enclítics, mots
  compostos, ordinals, números romans, abreviatures i puntuació classificada;
- anotacions: pronoms febles, apòstrofs, formes amb guionet, expressions
  multiparaula del lexicó de classes tancades.

Els analitzadors més potents (morfosintàctics, sintàctics) s'han d'integrar
com a adaptadors que compleixin el protocol :class:`Analyzer`.
"""

from parafrasi_cat.analyzer.analysis import Analysis, Analyzer, RuleBasedAnalyzer
from parafrasi_cat.analyzer.apostrophes import Apostrophe, ApostropheKind, find_apostrophes
from parafrasi_cat.analyzer.clitics import (
    Certainty,
    PronounAttachment,
    WeakPronoun,
    canonical_form,
    find_weak_pronouns,
)
from parafrasi_cat.analyzer.expressions import MultiwordExpression, find_multiword_expressions
from parafrasi_cat.analyzer.hyphens import HyphenatedForm, HyphenKind, find_hyphenated_forms
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon, LexiconEntry, WordClass
from parafrasi_cat.analyzer.numerals import (
    RomanNumeral,
    is_roman_numeral,
    looks_like_roman_numeral,
    roman_to_int,
)
from parafrasi_cat.analyzer.paragraphs import Paragraph, ParagraphSplitter
from parafrasi_cat.analyzer.sentences import (
    DEFAULT_ABBREVIATIONS,
    Sentence,
    SentenceSplitter,
)
from parafrasi_cat.analyzer.tokens import Token, Tokenizer, TokenKind, TokenSubkind

__all__ = [
    "DEFAULT_ABBREVIATIONS",
    "Analysis",
    "Analyzer",
    "Apostrophe",
    "ApostropheKind",
    "Certainty",
    "ClosedClassLexicon",
    "HyphenKind",
    "HyphenatedForm",
    "LexiconEntry",
    "MultiwordExpression",
    "Paragraph",
    "ParagraphSplitter",
    "PronounAttachment",
    "RomanNumeral",
    "RuleBasedAnalyzer",
    "Sentence",
    "SentenceSplitter",
    "Token",
    "TokenKind",
    "TokenSubkind",
    "Tokenizer",
    "WeakPronoun",
    "WordClass",
    "canonical_form",
    "find_apostrophes",
    "find_hyphenated_forms",
    "find_multiword_expressions",
    "find_weak_pronouns",
    "is_roman_numeral",
    "looks_like_roman_numeral",
    "roman_to_int",
]
