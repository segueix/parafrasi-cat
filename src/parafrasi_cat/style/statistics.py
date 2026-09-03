"""Estadística robusta senzilla per a l'anàlisi estilomètrica.

Totes les funcions són deterministes i només fan servir la biblioteca
estàndard. Els valors «robustos» es basen en la mediana i en la desviació
absoluta mediana (MAD), de manera que un sol text excepcional no domini el
perfil. Quan un corpus té pocs documents, el pes de cada document es limita
(``capped_weights``) en lloc de deixar que el més llarg mani.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

#: Constant de suavització de la confiança: amb ``k`` observacions la
#: confiança base és 0,5.
CONFIDENCE_K = 10.0

#: Factor de limitació del pes d'un document: cap document pesa més de
#: ``factor`` vegades la mida mediana dels documents.
WEIGHT_CAP_FACTOR = 3.0

#: Nombre mínim de documents per fer servir la mediana ponderada entre
#: documents; amb menys, la mediana és massa grollera (un tret present a la
#: meitat dels textos donaria zero) i s'usa la mitjana amb pesos limitats.
MEDIAN_MIN_DOCUMENTS = 5


def mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def percentile(values: Sequence[float], p: float) -> float:
    """Percentil ``p`` (0-100) amb interpolació lineal."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * max(0.0, min(100.0, p)) / 100.0
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return float(ordered[low])
    fraction = position - low
    return ordered[low] + (ordered[high] - ordered[low]) * fraction


def mad(values: Sequence[float]) -> float:
    """Desviació absoluta mediana (sense escalar)."""
    if not values:
        return 0.0
    center = median(values)
    return median([abs(v - center) for v in values])


def iqr(values: Sequence[float]) -> float:
    return percentile(values, 75) - percentile(values, 25)


def trimmed_mean(values: Sequence[float], proportion: float = 0.1) -> float:
    """Mitjana retallada: descarta la proporció indicada a cada extrem."""
    if not values:
        return 0.0
    ordered = sorted(values)
    cut = int(len(ordered) * proportion)
    kept = ordered[cut : len(ordered) - cut] or ordered
    return sum(kept) / len(kept)


def weighted_median(values: Sequence[float], weights: Sequence[float]) -> float:
    """Mediana ponderada (el primer valor que acumula la meitat del pes)."""
    if not values:
        return 0.0
    if len(values) != len(weights):
        raise ValueError("values i weights han de tenir la mateixa longitud")
    pairs = sorted(zip(values, weights, strict=True), key=lambda pair: pair[0])
    total = sum(w for _, w in pairs)
    if total <= 0:
        return median(values)
    accumulated = 0.0
    for value, weight in pairs:
        accumulated += weight
        if accumulated >= total / 2.0:
            return float(value)
    return float(pairs[-1][0])


def capped_weights(sizes: Sequence[float], factor: float = WEIGHT_CAP_FACTOR) -> list[float]:
    """Pesos proporcionals a la mida, limitats a ``factor`` × mida mediana."""
    if not sizes:
        return []
    cap = factor * median(sizes)
    if cap <= 0:
        return [1.0 for _ in sizes]
    return [min(float(size), cap) for size in sizes]


def confidence(n_observations: int, n_documents: int, k: float = CONFIDENCE_K) -> float:
    """Confiança (0-1) d'una estimació a partir del nombre d'observacions i documents.

    ``n / (n + k)`` creix amb les observacions; el factor ``1 - 0,5 / d``
    penalitza els perfils basats en un sol document (×0,5) o en pocs (×0,75
    amb dos, ×0,875 amb quatre).
    """
    if n_observations <= 0 or n_documents <= 0:
        return 0.0
    base = n_observations / (n_observations + k)
    factor = 1.0 - 0.5 / n_documents
    return round(base * factor, 3)


@dataclass(frozen=True, slots=True)
class RobustSummary:
    """Resum robust d'una quantitat mesurada document a document."""

    value: float
    pooled: float
    variability: float
    per_document_min: float
    per_document_median: float
    per_document_max: float
    n_documents: int
    n_observations: int

    def per_document(self) -> dict[str, float]:
        return {
            "min": self.per_document_min,
            "median": self.per_document_median,
            "max": self.per_document_max,
        }


def robust_rate(
    counts: Sequence[float], denominators: Sequence[float], scale: float = 100.0
) -> RobustSummary:
    """Taxa robusta (``count / denominador × scale``) entre documents.

    A partir de ``MEDIAN_MIN_DOCUMENTS`` documents el valor és la mediana
    ponderada de les taxes per document (pesos limitats); amb menys, la
    mitjana ponderada amb pesos limitats. ``pooled`` és la taxa global sense
    cap correcció.
    """
    if len(counts) != len(denominators):
        raise ValueError("counts i denominators han de tenir la mateixa longitud")
    rates: list[float] = []
    sizes: list[float] = []
    total_count = 0.0
    total_denominator = 0.0
    for count, denominator in zip(counts, denominators, strict=True):
        total_count += count
        total_denominator += denominator
        if denominator > 0:
            rates.append(count / denominator * scale)
            sizes.append(denominator)
    pooled = total_count / total_denominator * scale if total_denominator > 0 else 0.0
    if not rates:
        return RobustSummary(0.0, pooled, 0.0, 0.0, 0.0, 0.0, 0, int(total_count))
    weights = capped_weights(sizes)
    if len(rates) >= MEDIAN_MIN_DOCUMENTS:
        value = weighted_median(rates, weights)
    else:
        value = sum(r * w for r, w in zip(rates, weights, strict=True)) / sum(weights)
    return RobustSummary(
        value=value,
        pooled=pooled,
        variability=mad(rates),
        per_document_min=min(rates),
        per_document_median=median(rates),
        per_document_max=max(rates),
        n_documents=len(rates),
        n_observations=int(total_count),
    )


def robust_location(samples_per_document: Sequence[Sequence[float]]) -> RobustSummary:
    """Localització robusta d'una magnitud mesurada per unitat (p. ex. longitud de frase).

    Cada mostra pesa ``min(1, cap / n_doc)`` de manera que un document amb
    moltíssimes unitats no domini la mediana global.
    """
    documents = [list(samples) for samples in samples_per_document if samples]
    if not documents:
        return RobustSummary(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0)
    sizes = [float(len(doc)) for doc in documents]
    cap = WEIGHT_CAP_FACTOR * median(sizes)
    values: list[float] = []
    weights: list[float] = []
    for doc in documents:
        weight = min(1.0, cap / len(doc)) if cap > 0 else 1.0
        values.extend(float(v) for v in doc)
        weights.extend(weight for _ in doc)
    medians = [median(doc) for doc in documents]
    return RobustSummary(
        value=weighted_median(values, weights),
        pooled=median(values),
        variability=mad(values),
        per_document_min=min(medians),
        per_document_median=median(medians),
        per_document_max=max(medians),
        n_documents=len(documents),
        n_observations=len(values),
    )


def shares(counts: Mapping[str, float]) -> dict[str, float]:
    """Proporcions (0-1) d'un recompte per clau; buit si el total és zero."""
    total = float(sum(counts.values()))
    if total <= 0:
        return {key: 0.0 for key in counts}
    return {key: value / total for key, value in counts.items()}


def total_variation(p: Mapping[str, float], q: Mapping[str, float]) -> float:
    """Distància de variació total entre dues distribucions de proporcions (0-1)."""
    keys = set(p) | set(q)
    if not keys:
        return 0.0
    return 0.5 * sum(abs(p.get(key, 0.0) - q.get(key, 0.0)) for key in keys)


def relative_difference(a: float, b: float) -> float:
    """Diferència relativa ``|a - b| / (|a| + |b|)`` (0 = iguals, 1 = un dels dos és zero)."""
    denominator = abs(a) + abs(b)
    if denominator == 0:
        return 0.0
    return abs(a - b) / denominator


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    set_a, set_b = set(a), set(b)
    if not set_a and not set_b:
        return 1.0
    return len(set_a & set_b) / len(set_a | set_b)


def round_floats(value: object, digits: int = 4) -> object:
    """Arrodoneix recursivament els nombres decimals d'una estructura JSON."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        rounded = round(value, digits)
        return 0.0 if rounded == 0 else rounded
    if isinstance(value, dict):
        return {str(k): round_floats(v, digits) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [round_floats(v, digits) for v in value]
    return value


def robust_average(values: Sequence[float], sizes: Sequence[float]) -> RobustSummary:
    """Promig robust d'un valor mesurat per document (p. ex. una ràtio), ponderat per mida.

    A partir de ``MEDIAN_MIN_DOCUMENTS`` documents, mediana ponderada amb
    pesos limitats; amb menys, mitjana ponderada. ``pooled`` és la mitjana
    ponderada sense límit.
    """
    if len(values) != len(sizes):
        raise ValueError("values i sizes han de tenir la mateixa longitud")
    pairs = [(float(v), float(s)) for v, s in zip(values, sizes, strict=True) if s > 0]
    if not pairs:
        return RobustSummary(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0)
    vals = [v for v, _ in pairs]
    raw_sizes = [s for _, s in pairs]
    weights = capped_weights(raw_sizes)
    pooled = sum(v * s for v, s in pairs) / sum(raw_sizes)
    if len(vals) >= MEDIAN_MIN_DOCUMENTS:
        value = weighted_median(vals, weights)
    else:
        value = sum(v * w for v, w in zip(vals, weights, strict=True)) / sum(weights)
    return RobustSummary(
        value=value,
        pooled=pooled,
        variability=mad(vals),
        per_document_min=min(vals),
        per_document_median=median(vals),
        per_document_max=max(vals),
        n_documents=len(vals),
        n_observations=int(sum(raw_sizes)),
    )
