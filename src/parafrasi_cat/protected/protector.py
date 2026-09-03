"""Orquestració dels detectors de fragments protegits."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from parafrasi_cat.analyzer.analysis import Analyzer, RuleBasedAnalyzer
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon
from parafrasi_cat.core.spans import Span
from parafrasi_cat.protected.detectors import (
    CitationDetector,
    DateDetector,
    Detector,
    NumberDetector,
    ProperNounDetector,
    QuotedTextDetector,
    RomanNumeralDetector,
    UserTermDetector,
)
from parafrasi_cat.protected.spans import ProtectedSpan, ProtectionKind


class Protector:
    """Executa un conjunt de detectors i unifica els resultats."""

    def __init__(self, detectors: Sequence[Detector]) -> None:
        self._detectors = tuple(detectors)

    @property
    def detectors(self) -> tuple[Detector, ...]:
        return self._detectors

    def protect(self, text: str) -> tuple[ProtectedSpan, ...]:
        """Retorna tots els fragments protegits del text, ordenats i sense duplicats.

        Els fragments de tipus diferent que se solapen es conserven tots dos:
        per a les regles només importa que la zona quedi protegida, i per a
        l'explicació és útil saber-ne tots els motius.
        """
        seen: set[tuple[int, int, ProtectionKind]] = set()
        spans: list[ProtectedSpan] = []
        for detector in self._detectors:
            for protected in detector.detect(text):
                key = (protected.start, protected.end, protected.kind)
                if key in seen:
                    continue
                seen.add(key)
                spans.append(protected)
        spans.sort(key=lambda p: (p.start, -p.end, p.kind.value))
        return tuple(spans)

    @staticmethod
    def within(spans: Iterable[ProtectedSpan], bounds: Span) -> tuple[ProtectedSpan, ...]:
        """Retalla i desplaça els fragments perquè siguin relatius a ``bounds``.

        Un fragment que travessa el límit (p. ex. una citació que abasta dues
        frases) es retalla al tros que cau dins de ``bounds``.
        """
        result: list[ProtectedSpan] = []
        for protected in spans:
            clipped = protected.span.clip(bounds)
            if clipped is None:
                continue
            offset = clipped.start - protected.start
            text = protected.text[offset : offset + clipped.length]
            result.append(
                ProtectedSpan(
                    clipped.shift(-bounds.start),
                    text,
                    protected.kind,
                    protected.detector_id,
                    protected.note,
                )
            )
        return tuple(result)


def default_protector(
    analyzer: Analyzer | None = None,
    *,
    user_terms: Iterable[str] = (),
    known_names: Iterable[str] = (),
    lexicon: ClosedClassLexicon | None = None,
) -> Protector:
    """Protector amb tots els detectors estàndard.

    Args:
        analyzer: Analitzador que fa servir el detector de noms propis.
        user_terms: Termes definits per l'usuari (coincidència sense distingir majúscules).
        known_names: Noms propis coneguts (coincidència exacta, distingint majúscules).
        lexicon: Lexicó de classes tancades per afinar el detector de noms propis;
            si no s'indica, s'agafa el de l'analitzador quan en té.
    """
    if lexicon is None and isinstance(analyzer, RuleBasedAnalyzer):
        lexicon = analyzer.lexicon
    detectors: list[Detector] = [
        QuotedTextDetector(),
        CitationDetector(),
        DateDetector(),
        RomanNumeralDetector(),
        NumberDetector(),
        ProperNounDetector(analyzer, lexicon=lexicon),
    ]
    names = tuple(known_names)
    if names:
        detectors.append(
            UserTermDetector(
                names,
                detector_id="proper_noun.dictionary",
                kind=ProtectionKind.PROPER_NOUN,
                ignore_case=False,
            )
        )
    terms = tuple(user_terms)
    if terms:
        detectors.append(UserTermDetector(terms))
    return Protector(detectors)
