"""Validadors de preservació factual, un per tipus de contingut.

Comproven, independentment dels fragments protegits que hagin vist les
regles, que tot el que els detectors troben a l'original (noms propis,
dates, citacions, text entre cometes) continua al candidat, i que la
terminologia protegida per l'usuari es conserva. Són la segona línia de
defensa del principi «el contingut original és intocable».
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from parafrasi_cat.analyzer.analysis import Analyzer
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon
from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.core.text import phrase_pattern
from parafrasi_cat.protected.detectors import (
    CitationDetector,
    DateDetector,
    Detector,
    ProperNounDetector,
    QuotedTextDetector,
    RomanNumeralDetector,
)
from parafrasi_cat.validation.base import ValidationContext
from parafrasi_cat.validation.result import ValidationDimension, ValidationResult


class DetectorInvariantValidator:
    """Tot fragment que ``detector`` troba a l'original ha de continuar al candidat.

    Es compara el text exacte de cada fragment (moure'l de lloc és permès;
    alterar-lo, no). Amb ``by_detection`` el detector també s'aplica al
    candidat i es comparen els recomptes (així «IV» no es confon amb el «IV»
    de «XIV»); sense, n'hi ha prou que el text del fragment hi aparegui (útil
    per als noms propis, que l'heurística no detecta en totes les posicions).
    Un fragment que apareix més vegades al candidat que a l'original també és
    sospitós: es marca com a error perquè pot haver-se duplicat una dada.
    """

    def __init__(
        self,
        detector: Detector,
        validator_id: str,
        label: str,
        *,
        dimension: ValidationDimension = ValidationDimension.FACTUAL,
        allow_extra: bool = True,
        by_detection: bool = True,
    ) -> None:
        self._detector = detector
        self._validator_id = validator_id
        self._label = label
        self._dimension = dimension
        self._allow_extra = allow_extra
        self._by_detection = by_detection

    @property
    def validator_id(self) -> str:
        return self._validator_id

    @property
    def dimension(self) -> ValidationDimension:
        return self._dimension

    def validate(self, candidate: Candidate, ctx: ValidationContext) -> ValidationResult:
        found = Counter(p.text for p in self._detector.detect(ctx.source_text) if p.text.strip())
        if not found:
            return ValidationResult.passed()
        if self._by_detection:
            after = Counter(p.text for p in self._detector.detect(candidate.text))
        else:
            after = Counter({text: candidate.text.count(text) for text in found})
        lost = [text for text, n in found.items() if after[text] < n]
        if lost:
            listed = ", ".join(f"«{t}»" for t in lost)
            return ValidationResult.error(
                self._validator_id,
                f"S'ha alterat o perdut {self._label}: {listed}",
                self._dimension,
            )
        if not self._allow_extra:
            extra = [text for text, n in found.items() if after[text] > n]
            if extra:
                listed = ", ".join(f"«{t}»" for t in extra)
                return ValidationResult.error(
                    self._validator_id, f"S'ha duplicat {self._label}: {listed}", self._dimension
                )
        return ValidationResult.passed()


class ProperNounValidator(DetectorInvariantValidator):
    """Els noms propis detectats a l'original han d'aparèixer intactes al candidat."""

    def __init__(
        self, analyzer: Analyzer | None = None, *, lexicon: ClosedClassLexicon | None = None
    ) -> None:
        super().__init__(
            ProperNounDetector(analyzer, lexicon=lexicon),
            "proper_nouns",
            "un nom propi",
            by_detection=False,
        )


class DateValidator(DetectorInvariantValidator):
    """Les dates (numèriques, textuals i amb era) s'han de conservar exactament."""

    def __init__(self) -> None:
        super().__init__(DateDetector(), "dates", "una data", allow_extra=False)


class RomanNumeralValidator(DetectorInvariantValidator):
    """Els números romans s'han de conservar exactament."""

    def __init__(self) -> None:
        super().__init__(
            RomanNumeralDetector(), "roman_numerals", "un número romà", allow_extra=False
        )


class CitationValidator(DetectorInvariantValidator):
    """Les referències bibliogràfiques s'han de conservar exactament."""

    def __init__(self) -> None:
        super().__init__(CitationDetector(), "citations", "una citació", allow_extra=False)


class QuotedTextValidator(DetectorInvariantValidator):
    """El text entre cometes s'ha de conservar exactament."""

    def __init__(self) -> None:
        super().__init__(
            QuotedTextDetector(), "quoted_text", "un text entre cometes", allow_extra=False
        )


class ProtectedTermValidator:
    """La terminologia protegida per l'usuari s'ha de conservar tal com era.

    Cada terme es compta com a paraula o locució sencera, sense distingir
    majúscules, i les ocurrències del candidat han de ser almenys les de
    l'original; a més, cap ocurrència original no pot haver canviat de forma
    (majúscules, apòstrofs).
    """

    validator_id = "protected_terms"
    dimension = ValidationDimension.TERMINOLOGY

    def __init__(self, terms: Iterable[str]) -> None:
        self._terms = tuple(dict.fromkeys(t.strip() for t in terms if t.strip()))
        self._patterns = tuple((term, phrase_pattern(term)) for term in self._terms)

    @property
    def terms(self) -> tuple[str, ...]:
        return self._terms

    def validate(self, candidate: Candidate, ctx: ValidationContext) -> ValidationResult:
        problems: list[str] = []
        for term, pattern in self._patterns:
            before = [m.group(0) for m in pattern.finditer(ctx.source_text)]
            if not before:
                continue
            after = [m.group(0) for m in pattern.finditer(candidate.text)]
            if len(after) < len(before):
                problems.append(f"«{term}» ha desaparegut o s'ha alterat")
                continue
            if Counter(before) - Counter(after):
                problems.append(f"«{term}» ha canviat de forma")
        if problems:
            return ValidationResult.error(
                self.validator_id,
                "Terminologia protegida: " + "; ".join(problems),
                self.dimension,
            )
        return ValidationResult.passed()


def factual_validators(
    analyzer: Analyzer | None = None, *, lexicon: ClosedClassLexicon | None = None
) -> tuple[DetectorInvariantValidator, ...]:
    """Els validadors factuals estàndard: noms, dates, romans, citacions, cometes."""
    return (
        ProperNounValidator(analyzer, lexicon=lexicon),
        DateValidator(),
        RomanNumeralValidator(),
        CitationValidator(),
        QuotedTextValidator(),
    )
