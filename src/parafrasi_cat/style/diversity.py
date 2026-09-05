"""Diversitat estructural de paràgraf guiada per l'empremta de l'autor.

Aquesta capa només ordena candidats que ja han superat els validadors. No
inventa text ni força cap transformació: mira els patrons sintàctics abstractes
que el parser local ja calcula i penalitza, dins del component d'afinitat
sintàctica, una concentració de patrons més monòtona que la que mostra el
corpus de l'autor.

Funciona també amb empremtes 1.1/1.2 ja existents: fa servir ``patterns.top``
del ``syntactic_profile`` i no exigeix recrear l'empremta.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence

from parafrasi_cat.analyzer.analysis import Analyzer
from parafrasi_cat.style.adaptation import (
    COMPONENT_WEIGHTS,
    AdaptationContext,
    AuthorAffinity,
    AuthorAdaptation,
)
from parafrasi_cat.style.observations import StyleResources
from parafrasi_cat.style.preferences import StylePreferences
from parafrasi_cat.style.syntax_profile import SentenceSyntaxStats
from parafrasi_cat.syntax.analysis import SyntaxProvider

MIN_SENTENCES = 3
#: La diversitat és una part del component sintàctic, no un criteri dominant.
DIVERSITY_SHARE = 0.25
#: Evita que mostres petites facin oscil·lar massa la puntuació.
MIN_DENOMINATOR = 0.25


class DiversifiedAuthorAdaptation(AuthorAdaptation):
    """Adaptació autoral que també compara la diversitat de patrons del paràgraf."""

    def __init__(
        self,
        preferences: StylePreferences,
        analyzer: Analyzer,
        resources: StyleResources,
        *,
        explicit_forms: Iterable[str] = (),
        syntax: SyntaxProvider | None = None,
    ) -> None:
        super().__init__(
            preferences,
            analyzer,
            resources,
            explicit_forms=explicit_forms,
            syntax=syntax,
        )
        self._diversity_cache: dict[
            tuple[str, AdaptationContext | None, str | None], AuthorAffinity
        ] = {}

    def assess(
        self,
        text: str,
        *,
        context: AdaptationContext | None = None,
        source_text: str | None = None,
    ) -> AuthorAffinity:
        key = (text, context, source_text)
        cached = self._diversity_cache.get(key)
        if cached is not None:
            return cached

        base = super().assess(text, context=context, source_text=source_text)
        result = self._with_structural_diversity(base, text)
        self._diversity_cache[key] = result
        return result

    def _with_structural_diversity(self, base: AuthorAffinity, text: str) -> AuthorAffinity:
        # Sense component sintàctic fiable no afegim cap judici nou.
        if "sintaxi" not in base.components:
            return base
        unit = self.stats_of(text)
        stats = unit.syntax
        # Si alguna frase del paràgraf no té parse fiable, eliminar-la de la
        # seqüència crearia falses adjacències entre patrons. En aquest cas no
        # puntuem la diversitat: menys cobertura, mai una inferència dubtosa.
        if len(stats) < MIN_SENTENCES or len(stats) != unit.n_sentences:
            return base

        fingerprint = self.preferences.fingerprint
        profile = fingerprint.features.get("syntactic_profile")
        if not isinstance(profile, Mapping):
            return base
        diversity = structural_diversity_similarity(stats, profile)
        if diversity is None:
            return base
        diversity_score, details = diversity

        components = dict(base.components)
        current = components["sintaxi"]
        components["sintaxi"] = round(
            (1.0 - DIVERSITY_SHARE) * current + DIVERSITY_SHARE * diversity_score,
            4,
        )

        partials = {name: dict(values) for name, values in base.partials.items()}
        syntactic = partials.setdefault("sintaxi", {})
        syntactic["diversitat"] = round(diversity_score, 4)

        notes = dict(base.notes)
        detail = ", ".join(f"{name} {value:.2f}" for name, value in details.items())
        previous = notes.get("sintaxi", "")
        notes["sintaxi"] = "; ".join(part for part in (previous, f"diversitat {detail}") if part)

        weight = sum(COMPONENT_WEIGHTS[name] for name in components if name in COMPONENT_WEIGHTS)
        score = (
            sum(COMPONENT_WEIGHTS[name] * value for name, value in components.items()) / weight
            if weight
            else base.score
        )
        return AuthorAffinity(round(score, 4), components, notes, partials)


def structural_diversity_similarity(
    stats: Sequence[SentenceSyntaxStats], profile: Mapping[str, object]
) -> tuple[float, dict[str, float]] | None:
    """Semblança 0-1 de la diversitat local amb la distribució de l'autor.

    Mesura dues coses, només quan hi ha almenys tres frases:

    - **concentració**: quant domina un únic patró abstracte al paràgraf respecte
      del patró més freqüent del corpus de l'autor;
    - **ratxes**: quantes frases consecutives repeteixen exactament el mateix
      patró, comparat amb la repetició esperable a partir de les proporcions de
      patrons de l'autor.

    Només penalitza l'excés de monotonia. Ser més divers que el corpus no dona
    un premi addicional ni força canvis.
    """
    if len(stats) < MIN_SENTENCES or profile.get("available") is not True:
        return None
    if profile.get("confidence") == "low":
        return None
    patterns = profile.get("patterns")
    if not isinstance(patterns, Mapping):
        return None
    top = patterns.get("top")
    if not isinstance(top, list) or not top:
        return None

    author_shares: list[float] = []
    for item in top:
        if not isinstance(item, Mapping):
            continue
        share = item.get("share")
        if isinstance(share, int | float) and not isinstance(share, bool):
            author_shares.append(max(0.0, min(1.0, float(share))))
    if not author_shares:
        return None

    counts = Counter(stat.pattern for stat in stats)
    n = len(stats)
    candidate_peak = max(counts.values()) / n
    author_peak = max(author_shares)
    concentration_excess = max(0.0, candidate_peak - author_peak)
    concentration = 1.0 - min(
        1.0,
        concentration_excess / max(MIN_DENOMINATOR, 1.0 - author_peak),
    )

    candidate_repeats = sum(
        1
        for previous, current in zip(stats, stats[1:], strict=False)
        if previous.pattern == current.pattern
    ) / (n - 1)
    # Amb empremtes antigues no tenim una taxa de ratxes explícita. La suma de
    # p² aproxima la repetició esperable dels patrons coneguts. Per a la cua que
    # no entra a ``top`` prenem el cas més permissiu (tota la cua com un sol
    # patró), de manera que la penalització no sigui excessiva.
    known = min(1.0, sum(author_shares))
    residual = max(0.0, 1.0 - known)
    author_repeat = min(1.0, sum(share * share for share in author_shares) + residual**2)
    repeat_excess = max(0.0, candidate_repeats - author_repeat)
    runs = 1.0 - min(
        1.0,
        repeat_excess / max(MIN_DENOMINATOR, 1.0 - author_repeat),
    )

    score = 0.6 * concentration + 0.4 * runs
    return round(score, 4), {
        "concentracio": round(concentration, 4),
        "ratxes": round(runs, 4),
    }


__all__ = [
    "DiversifiedAuthorAdaptation",
    "structural_diversity_similarity",
]
