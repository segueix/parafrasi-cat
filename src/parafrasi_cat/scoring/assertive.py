"""Puntuació del llenguatge assertiu: més clar, mai més cert.

Quan l'opció «Llenguatge assertiu» és activa, cada candidat rep un bonus (o una
penalització) petit segons si, respecte de l'original:

- redueix la **redundància modal** (dos marcadors de la mateixa mena de
  prudència l'un al costat de l'altre: «sembla que podria», «potser podria»);
- fa **explícita la categoria** epistemològica amb un marcador explícit
  («hipòtesi», «permet plantejar», «no permet demostrar», «X detalla que»);
- fa servir el **marcador que l'autor prefereix** per a la categoria, segons
  el perfil epistemològic de la seva empremta (només si és prou fiable).

Tot això només ordena candidats igualment segurs: la validació epistemològica
ja ha descartat qualsevol candidat que canviï la força expressada, i cap bonus
no la pot rescatar. Sense l'opció, el component no existeix.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from parafrasi_cat.analyzer.lexicon import normalize_form
from parafrasi_cat.style.preferences import StylePreferences
from parafrasi_cat.validation.categories import EpistemicCategory
from parafrasi_cat.validation.epistemic import EpistemicLexicon, EpistemicProfile

#: Distància màxima (en caràcters) entre dos marcadors perquè comptin com a redundants.
REDUNDANCY_GAP = 32
#: Pes de cada senyal (la suma es limita a ±0,5 al voltant del punt neutre 0,5).
REDUNDANCY_WEIGHT = 0.25
EXPLICIT_WEIGHT = 0.2
PREFERENCE_WEIGHT = 0.2
_SENTENCE_END = ".!?…;"


@dataclass(frozen=True, slots=True)
class AssertiveAssessment:
    """Puntuació (0-1, 0,5 = neutre) i motius; categories de l'original i del candidat."""

    score: float = 0.5
    reasons: tuple[str, ...] = ()
    category_before: EpistemicCategory = EpistemicCategory.UNKNOWN
    category_after: EpistemicCategory = EpistemicCategory.UNKNOWN

    @property
    def delta(self) -> float:
        """Desviació respecte del punt neutre, entre −0,5 i +0,5."""
        return self.score - 0.5

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "reasons": list(self.reasons),
            "epistemic_class_original": self.category_before.value,
            "epistemic_class_candidate": self.category_after.value,
        }


class AssertiveEvaluator:
    """Compara la formulació epistemològica d'un candidat amb la de l'original."""

    def __init__(
        self, lexicon: EpistemicLexicon, preferences: StylePreferences | None = None
    ) -> None:
        self._lexicon = lexicon
        self._preferred: dict[EpistemicCategory, str] = {}
        if preferences is not None:
            for category in EpistemicCategory:
                marker = preferences.preferred_epistemic_marker(category.value)
                if marker:
                    self._preferred[category] = normalize_form(marker)

    @property
    def preferred_markers(self) -> Mapping[EpistemicCategory, str]:
        """Marcador preferit de l'autor per categoria (buit sense empremta fiable)."""
        return dict(self._preferred)

    def assess(self, source_text: str, text: str) -> AssertiveAssessment:
        before = self._lexicon.profile(source_text)
        after = self._lexicon.profile(text)
        if text == source_text:
            return AssertiveAssessment(0.5, (), before.dominant, after.dominant)
        reasons: list[str] = []
        delta = 0.0
        redundancy_before = _redundant_pairs(source_text, before)
        redundancy_after = _redundant_pairs(text, after)
        if redundancy_after < redundancy_before:
            delta += REDUNDANCY_WEIGHT
            reasons.append("redueix la doble modalització")
        elif redundancy_after > redundancy_before:
            delta -= REDUNDANCY_WEIGHT
            reasons.append("afegeix modalització redundant")
        explicit_before = len(before.explicit_markers)
        explicit_after = len(after.explicit_markers)
        if explicit_after > explicit_before:
            delta += EXPLICIT_WEIGHT
            reasons.append(
                "fa explícita la categoria epistemològica («"
                + "», «".join(m for m in after.explicit_markers if m not in before.explicit_markers)
                + "»)"
            )
        elif explicit_after < explicit_before:
            delta -= EXPLICIT_WEIGHT
            reasons.append("perd un marcador explícit")
        if self._preferred:
            preferred_before = _preferred_hits(before, self._preferred)
            preferred_after = _preferred_hits(after, self._preferred)
            if preferred_after > preferred_before:
                delta += PREFERENCE_WEIGHT
                reasons.append("fa servir el marcador que l'autor prefereix")
            elif preferred_after < preferred_before:
                delta -= PREFERENCE_WEIGHT
                reasons.append("deixa el marcador que l'autor prefereix")
        score = round(max(0.0, min(1.0, 0.5 + delta)), 4)
        return AssertiveAssessment(score, tuple(reasons), before.dominant, after.dominant)


def _redundant_pairs(text: str, profile: EpistemicProfile) -> int:
    """Parelles de marcadors comptats de prudència molt propers dins d'una mateixa frase."""
    hedging = [
        m
        for m in profile.matches
        if m.category in (EpistemicCategory.HYPOTHESIS, EpistemicCategory.INFERENCE)
    ]
    pairs = 0
    for first, second in zip(hedging, hedging[1:], strict=False):
        between = text[first.span.end : second.span.start]
        if len(between) <= REDUNDANCY_GAP and not any(c in _SENTENCE_END for c in between):
            pairs += 1
    return pairs


def _preferred_hits(profile: EpistemicProfile, preferred: Mapping[EpistemicCategory, str]) -> int:
    return sum(
        1
        for m in profile.matches
        if m.category in preferred and normalize_form(m.text) == preferred[m.category]
    )


__all__ = ["AssertiveAssessment", "AssertiveEvaluator"]
