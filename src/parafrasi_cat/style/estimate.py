"""Estimació d'un perfil d'estil a partir d'un corpus de l'autor."""

from __future__ import annotations

from collections.abc import Iterable
from statistics import mean, pstdev

from parafrasi_cat.analyzer.analysis import Analyzer
from parafrasi_cat.style.metrics import compute_style_metrics
from parafrasi_cat.style.profile import StyleProfile


def estimate_profile(
    texts: Iterable[str],
    analyzer: Analyzer,
    *,
    name: str = "autor",
    description: str = "Perfil estimat automàticament a partir del corpus de l'autor",
) -> StyleProfile:
    """Deriva un perfil d'estil de les mètriques d'un conjunt de textos.

    Només s'estimen la longitud mitjana de frase i la seva tolerància
    (una desviació estàndard, amb un mínim de 4 paraules). La resta de
    paràmetres conserven els valors per defecte i es poden editar a mà.
    """
    lengths: list[float] = []
    for text in texts:
        metrics = compute_style_metrics(text, analyzer)
        if metrics.n_sentences:
            lengths.append(metrics.mean_sentence_length)
    if not lengths:
        return StyleProfile(name=name, description=description)
    target = mean(lengths)
    tolerance = max(4.0, pstdev(lengths)) if len(lengths) > 1 else 8.0
    return StyleProfile(
        name=name,
        description=description,
        target_sentence_length=round(target, 2),
        sentence_length_tolerance=round(tolerance, 2),
    )
