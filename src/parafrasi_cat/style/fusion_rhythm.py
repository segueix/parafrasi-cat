"""Ritme d'una fusió: una frase resultant massa llarga o massa carregada paga.

Una fusió pot ser correcta, segura i estructural i, tot i així, deixar una
frase que l'autor no escriuria mai: setanta paraules amb quatre subordinades
quan l'autor en fa de vint-i-cinc. Abans de premiar una fusió, es mesura la
frase que en resulta contra l'empremta real de l'autor:

- **longitud**: percentil respecte de la distribució de l'empremta (mediana,
  rang interquartílic i percentil 90); sense empremta, la longitud objectiu
  del perfil d'estil amb la seva tolerància;
- **clàusules**: verbs conjugats (amb analitzador) o marcadors de clàusula;
- **relatives** i **subordinació consecutiva**: dues relatives seguides;
- **profunditat** de subordinació (amb analitzador);
- **comes**: densitat respecte de la de l'autor.

El resultat és una penalització entre 0 i 1 que la puntuació resta i que
rebaixa el bonus estructural; mai no invalida (la longitud màxima de
seguretat continua sent cosa del validador i de la regla de fusió).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from parafrasi_cat.analyzer.analysis import Analyzer
from parafrasi_cat.analyzer.sentences import Sentence
from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.style.degradation import sentence_shape
from parafrasi_cat.style.preferences import StylePreferences
from parafrasi_cat.style.profile import StyleProfile
from parafrasi_cat.syntax.analysis import CLAUSE_DEPS, SentenceSyntax, SyntaxProvider

#: Pesos dels senyals dins de la penalització (la suma es limita a 1).
CLAUSE_WEIGHT = 0.5
RELATIVE_WEIGHT = 0.3
DEPTH_WEIGHT = 0.3
COMMA_WEIGHT = 0.3
#: Clàusules i profunditat a partir de les quals una frase fusionada es considera carregada.
CLAUSE_LIMIT = 3
DEPTH_LIMIT = 3
_MIN_SPREAD = 6.0


@dataclass(frozen=True, slots=True)
class RhythmAssessment:
    """Penalització (0-1) de les frases fusionades d'un candidat, amb detalls."""

    penalty: float = 0.0
    reasons: tuple[str, ...] = ()
    details: dict[str, float] = field(default_factory=dict)

    @property
    def penalised(self) -> bool:
        return self.penalty > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "penalty": self.penalty,
            "reasons": list(self.reasons),
            "details": dict(self.details),
        }


class FusionRhythm:
    """Valora la frase que resulta d'una fusió contra el ritme de l'autor."""

    def __init__(
        self,
        analyzer: Analyzer,
        syntax: SyntaxProvider | None = None,
        preferences: StylePreferences | None = None,
        profile: StyleProfile | None = None,
    ) -> None:
        self._analyzer = analyzer
        self._syntax = syntax if syntax is not None and syntax.available else None
        self._long, self._hard, self._source = _length_limits(preferences, profile)
        self._comma_rate = _comma_rate(preferences)

    @property
    def long_threshold(self) -> float | None:
        """Paraules a partir de les quals una frase fusionada comença a pagar."""
        return self._long

    def assess(self, candidate: Candidate) -> RhythmAssessment:
        merges = [t for t in candidate.transformations if t.family.cross_sentence and _is_merge(t)]
        if not merges:
            return RhythmAssessment()
        sentences = self._analyzer.analyze(candidate.text).sentences
        spans = candidate.result_spans()
        worst = RhythmAssessment()
        for transformation, span in zip(candidate.transformations, spans, strict=True):
            if transformation not in merges:
                continue
            sentence = next((s for s in sentences if s.span.start <= span.start < s.span.end), None)
            if sentence is None:
                continue
            assessment = self._assess_sentence(sentence)
            if assessment.penalty > worst.penalty:
                worst = assessment
        return worst

    def _assess_sentence(self, sentence: Sentence) -> RhythmAssessment:
        words = len(sentence.words)
        parsed: SentenceSyntax | None = None
        if self._syntax is not None:
            analysis = self._syntax.parse(sentence.text)
            parsed = analysis if analysis.confident else None
        shape = sentence_shape(sentence, parsed)
        clauses = (
            len([t for t in parsed.tokens if t.is_finite_verb])
            if parsed is not None
            else 1 + shape.relatives + sentence.text.count(" i ") + sentence.text.count(" però ")
        )
        depth = _subordination_depth(parsed) if parsed is not None else 0
        commas = sum(1 for t in sentence.tokens if t.text == ",")
        reasons: list[str] = []
        penalty = 0.0
        details: dict[str, float] = {
            "words": float(words),
            "clauses": float(clauses),
            "relatives": float(shape.relatives),
            "depth": float(depth),
            "commas": float(commas),
        }
        if self._long is not None and self._hard is not None:
            details["long_threshold"] = self._long
            if words > self._long:
                length = min(1.0, (words - self._long) / max(1.0, self._hard - self._long))
                penalty += length
                reasons.append(
                    f"la frase fusionada té {words} paraules i {self._source} en situa el llindar "
                    f"en {self._long:.0f}"
                )
        if clauses > CLAUSE_LIMIT:
            penalty += CLAUSE_WEIGHT * min(1.0, (clauses - CLAUSE_LIMIT) / CLAUSE_LIMIT)
            reasons.append(f"acumula {clauses} clàusules")
        if shape.relatives >= 2:
            penalty += RELATIVE_WEIGHT
            reasons.append(f"encadena {shape.relatives} relatives")
        if depth >= DEPTH_LIMIT:
            penalty += DEPTH_WEIGHT
            reasons.append(f"subordinació de profunditat {depth}")
        comma_limit = max(3.0, 2.0 * self._comma_rate) if self._comma_rate is not None else 4.0
        if commas > comma_limit:
            penalty += COMMA_WEIGHT * min(1.0, (commas - comma_limit) / 4.0)
            reasons.append(f"{commas} comes en una sola frase")
        return RhythmAssessment(round(min(1.0, penalty), 4), tuple(reasons), details)


def _is_merge(transformation: object) -> bool:
    kind = getattr(transformation, "transformation_type", None)
    return getattr(kind, "value", "") == "sentence_merge"


def _length_limits(
    preferences: StylePreferences | None, profile: StyleProfile | None
) -> tuple[float | None, float | None, str]:
    """Llindar (comença a pagar) i límit dur (paga tot) segons l'empremta o el perfil."""
    if preferences is not None and preferences.is_reliable("sentence_length_distribution"):
        node = preferences.fingerprint.get("sentence_length_distribution")
        if isinstance(node, Mapping):
            median = _number(node.get("median"))
            iqr = _number(node.get("iqr"))
            p90 = _number(node.get("p90"))
            if median is not None:
                spread = max(iqr or 0.0, _MIN_SPREAD)
                long = max(p90 or 0.0, median + spread)
                hard = max(2.0 * median, long + spread)
                return long, hard, "l'empremta de l'autor"
    if profile is not None:
        tolerance = max(profile.sentence_length_tolerance, _MIN_SPREAD)
        target = profile.target_sentence_length
        return target + tolerance, target + 3.0 * tolerance, "el perfil d'estil"
    return None, None, ""


def _comma_rate(preferences: StylePreferences | None) -> float | None:
    if preferences is None:
        return None
    return preferences.fingerprint.value("punctuation.comma.per_sentence")


def _subordination_depth(analysis: SentenceSyntax) -> int:
    by_index = {t.index: t for t in analysis.tokens}
    deepest = 0
    for token in analysis.tokens:
        depth = 0
        current = token
        seen = {token.index}
        while not current.is_root:
            if current.dep in CLAUSE_DEPS:
                depth += 1
            parent = by_index.get(current.head)
            if parent is None or parent.index in seen:
                break
            seen.add(parent.index)
            current = parent
        deepest = max(deepest, depth)
    return deepest


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


__all__ = ["FusionRhythm", "RhythmAssessment"]
