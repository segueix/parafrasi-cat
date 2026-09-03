"""Puntuació d'un candidat segons les preferències explícites.

Per a cada forma coneguda (diccionaris, fitxer de preferències, feedback), es
compara quantes vegades apareix a l'original i al candidat. Una forma
introduïda aporta el seu pes; una forma eliminada, el pes canviat de signe.
La suma es limita a l'interval [−1, 1]. Si l'autor ha fixat una longitud
màxima de frase, un candidat que la superi rep una penalització de −1.

Cada resultat porta una explicació llegible («introdueix «obra de» … perquè
l'autor l'ha marcada com a preferida 4 vegades…») que el selector mostra.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from parafrasi_cat.analyzer.analysis import Analyzer
from parafrasi_cat.core.text import phrase_pattern
from parafrasi_cat.preferences.resolver import FormVerdict, PreferenceResolver

_WORD_RE = re.compile(r"[^\W\d_]+(?:['’·\-][^\W\d_]+)*|\d+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+(?=[^\W\d_a-zà-ÿ]|[«“(\d])")


@dataclass(frozen=True, slots=True)
class FormChange:
    """Una forma coneguda que el candidat introdueix o elimina."""

    verdict: FormVerdict
    delta: int

    @property
    def contribution(self) -> float:
        return self.delta * self.verdict.weight

    def describe(self) -> str:
        verb = "introdueix" if self.delta > 0 else "elimina"
        times = f" ({abs(self.delta)} vegades)" if abs(self.delta) > 1 else ""
        verdict = self.verdict
        return (
            f"{verb} «{verdict.form}»{times} [{self.contribution:+.2f}; "
            f"{verdict.source}: {verdict.reason}]"
        )


@dataclass(frozen=True, slots=True)
class PreferenceAssessment:
    """Resultat de l'avaluació de preferències d'un candidat."""

    score: float
    changes: tuple[FormChange, ...] = ()
    length_penalty: float = 0.0
    length_note: str = ""

    @property
    def applies(self) -> bool:
        """Cert si alguna preferència afecta el candidat."""
        return bool(self.changes) or self.length_penalty != 0.0

    @property
    def explanation(self) -> str:
        parts = [change.describe() for change in self.changes]
        if self.length_note:
            parts.append(self.length_note)
        return "; ".join(parts)

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "changes": [
                {
                    "form": c.verdict.form,
                    "delta": c.delta,
                    "weight": c.verdict.weight,
                    "level": c.verdict.level.value,
                    "source": c.verdict.source,
                    "reason": c.verdict.reason,
                }
                for c in self.changes
            ],
            "length_penalty": self.length_penalty,
            "explanation": self.explanation,
        }


class PreferenceEvaluator:
    """Compara les formes conegudes de l'original i del candidat i les puntua."""

    def __init__(
        self,
        resolver: PreferenceResolver,
        *,
        max_sentence_length: int | None = None,
        analyzer: Analyzer | None = None,
    ) -> None:
        self._resolver = resolver
        self._max_length = max_sentence_length
        self._analyzer = analyzer
        self._patterns = tuple((form, phrase_pattern(form)) for form in resolver.forms)

    @property
    def resolver(self) -> PreferenceResolver:
        return self._resolver

    @property
    def max_sentence_length(self) -> int | None:
        return self._max_length

    def assess(self, source_text: str, text: str) -> PreferenceAssessment:
        changes: list[FormChange] = []
        for form, pattern in self._patterns:
            after = len(pattern.findall(text))
            before = len(pattern.findall(source_text))
            if after == before:
                continue
            verdict = self._resolver.resolve(form)
            if verdict is None:  # pragma: no cover - totes les formes tenen veredicte
                continue
            changes.append(FormChange(verdict, after - before))
        changes.sort(key=lambda change: (-change.contribution, change.verdict.form))
        length_penalty, note = self._length_penalty(text)
        raw = sum(change.contribution for change in changes) + length_penalty
        score = max(-1.0, min(1.0, raw))
        return PreferenceAssessment(round(score, 4), tuple(changes), length_penalty, note)

    def sentence_lengths(self, text: str) -> tuple[int, ...]:
        """Paraules de cada frase del text (amb l'analitzador si n'hi ha)."""
        if self._analyzer is not None:
            analysis = self._analyzer.analyze(text)
            return tuple(len(sentence.words) for sentence in analysis.sentences)
        return tuple(
            len(_WORD_RE.findall(sentence))
            for sentence in _split_sentences(text)
            if sentence.strip()
        )

    def _length_penalty(self, text: str) -> tuple[float, str]:
        if self._max_length is None:
            return 0.0, ""
        longest = max(self.sentence_lengths(text), default=0)
        if longest > self._max_length:
            return -1.0, (
                f"una frase de {longest} paraules supera el màxim de {self._max_length} "
                "fixat per l'autor"
            )
        return 0.0, ""


def _split_sentences(text: str) -> Sequence[str]:
    return _SENTENCE_SPLIT_RE.split(text.strip())
