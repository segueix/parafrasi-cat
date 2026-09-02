"""Mètriques estilomètriques bàsiques."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

from parafrasi_cat.analyzer.analysis import Analysis, Analyzer
from parafrasi_cat.core.text import phrase_pattern

LONG_WORD_LENGTH = 7


@dataclass(frozen=True, slots=True)
class StyleMetrics:
    """Mesures superficials d'estil d'un text."""

    n_sentences: int
    n_words: int
    n_chars: int
    mean_sentence_length: float
    """Paraules per frase."""
    mean_word_length: float
    """Lletres per paraula."""
    type_token_ratio: float
    """Formes diferents / total de paraules (riquesa lèxica)."""
    long_word_ratio: float
    """Proporció de paraules de 7 lletres o més."""
    punctuation_density: float
    """Signes de puntuació per paraula."""
    connector_density: float
    """Connectors discursius per frase."""

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def compute_style_metrics(
    text: str | Analysis,
    analyzer: Analyzer,
    connectors: Iterable[str] = (),
) -> StyleMetrics:
    analysis = text if isinstance(text, Analysis) else analyzer.analyze(text)
    words = [t.text for t in analysis.words if t.is_word]
    n_sentences = analysis.n_sentences
    n_words = len(words)
    n_punct = sum(1 for s in analysis.sentences for t in s.tokens if t.is_punct)
    lowered = [w.lower() for w in words]
    connector_patterns = [phrase_pattern(c) for c in connectors if c.strip()]
    n_connectors = sum(len(p.findall(analysis.text)) for p in connector_patterns)
    return StyleMetrics(
        n_sentences=n_sentences,
        n_words=n_words,
        n_chars=len(analysis.text),
        mean_sentence_length=n_words / n_sentences if n_sentences else 0.0,
        mean_word_length=sum(len(w) for w in words) / n_words if n_words else 0.0,
        type_token_ratio=len(set(lowered)) / n_words if n_words else 0.0,
        long_word_ratio=(
            sum(1 for w in words if len(w) >= LONG_WORD_LENGTH) / n_words if n_words else 0.0
        ),
        punctuation_density=n_punct / n_words if n_words else 0.0,
        connector_density=n_connectors / n_sentences if n_sentences else 0.0,
    )
