"""Ritme de frases: longitud, franges curta/mitjana/llarga, alternança i seqüència.

Respon a «com alterna aquest autor les frases?», no només «quant fan de
mitjana». Tot són recomptes deterministes sobre la seqüència de longituds de
cada document, en **tokens lingüístics per frase**: paraules, clítics i
xifres, sense puntuació. Les seqüències no s'encadenen d'un document a l'altre.

Què es guarda:

- estadístics de longitud (mitjana, mediana, desviació, coeficient de variació,
  mínim, màxim i percentils 10, 25, 50, 75 i 90);
- franges curta/mitjana/llarga amb llindars derivats del corpus (tercils) i,
  amb pocs exemples, uns llindars de reserva documentats;
- matriu de transició entre franges (recomptes i proporcions per fila);
- trigrames de franges observats;
- ratxes de la mateixa franja;
- correlació de retard 1 entre longituds consecutives i canvi absolut mitjà;
- paràgrafs, només si el corpus conserva la separació.

Res d'això no guarda text: només nombres.

Suficiència de mostra (documentada, determinista):

- ``high``: 40 frases o més en 2 documents o més;
- ``medium``: 15 frases o més;
- ``low``: la resta. Amb menys de 12 frases els llindars són els de reserva
  i la correlació de retard 1 és ``null`` amb menys de 6 parelles consecutives.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence

from parafrasi_cat.style.statistics import mean, median, percentile, relative_difference

BUCKETS: tuple[str, ...] = ("short", "medium", "long")
_INITIALS = {"short": "S", "medium": "M", "long": "L"}

#: Llindars de reserva quan el corpus és massa petit per calcular tercils.
FALLBACK_SHORT_MAX = 12
FALLBACK_LONG_MIN = 25

#: Frases mínimes per derivar els llindars del corpus (tercils).
MIN_SENTENCES_FOR_TERCILES = 12
#: Parelles consecutives mínimes per informar la correlació de retard 1.
MIN_PAIRS_FOR_CORRELATION = 6

UNIT = "tokens lingüístics per frase (paraules, clítics i xifres; sense puntuació)"


def confidence_level(n_sentences: int, n_documents: int) -> str:
    """``high``, ``medium`` o ``low`` segons frases i documents (criteri documentat)."""
    if n_sentences >= 40 and n_documents >= 2:
        return "high"
    if n_sentences >= 15:
        return "medium"
    return "low"


def stdev(values: Sequence[float]) -> float:
    """Desviació típica poblacional (0 amb menys de dos valors)."""
    if len(values) < 2:
        return 0.0
    center = mean(values)
    return math.sqrt(sum((v - center) ** 2 for v in values) / len(values))


def length_statistics(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {}
    center = mean(values)
    deviation = stdev(values)
    return {
        "mean": center,
        "median": median(values),
        "std": deviation,
        "cv": deviation / center if center else 0.0,
        "min": float(min(values)),
        "max": float(max(values)),
        "p10": percentile(values, 10),
        "p25": percentile(values, 25),
        "p50": percentile(values, 50),
        "p75": percentile(values, 75),
        "p90": percentile(values, 90),
    }


def thresholds_for(values: Sequence[float]) -> dict[str, object]:
    """Llindars curta/mitjana/llarga: tercils del corpus o reserva documentada."""
    if len(values) >= MIN_SENTENCES_FOR_TERCILES:
        short_max = math.floor(percentile(values, 100 / 3))
        long_min = math.ceil(percentile(values, 200 / 3))
        if long_min <= short_max + 1:
            long_min = short_max + 2
        return {"short_max": short_max, "long_min": long_min, "source": "tercils"}
    return {"short_max": FALLBACK_SHORT_MAX, "long_min": FALLBACK_LONG_MIN, "source": "reserva"}


def bucket_of(length: float, thresholds: Mapping[str, object]) -> str:
    short_max = _as_float(thresholds.get("short_max"), FALLBACK_SHORT_MAX)
    long_min = _as_float(thresholds.get("long_min"), FALLBACK_LONG_MIN)
    if length <= short_max:
        return "short"
    if length >= long_min:
        return "long"
    return "medium"


def bucket_sequences(
    sequences: Sequence[Sequence[int]], thresholds: Mapping[str, object]
) -> list[list[str]]:
    return [[bucket_of(n, thresholds) for n in sequence] for sequence in sequences]


def transition_counts(sequences: Sequence[Sequence[str]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for sequence in sequences:
        for previous, current in zip(sequence, sequence[1:], strict=False):
            counts[f"{previous}_to_{current}"] += 1
    return {f"{a}_to_{b}": counts.get(f"{a}_to_{b}", 0) for a in BUCKETS for b in BUCKETS}


def transition_shares(counts: Mapping[str, int]) -> dict[str, float]:
    """Proporcions per fila: de cada franja, cap on va la frase següent."""
    shares: dict[str, float] = {}
    for a in BUCKETS:
        row = sum(counts.get(f"{a}_to_{b}", 0) for b in BUCKETS)
        for b in BUCKETS:
            key = f"{a}_to_{b}"
            shares[key] = counts.get(key, 0) / row if row else 0.0
    return shares


def trigram_counts(sequences: Sequence[Sequence[str]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for sequence in sequences:
        for i in range(len(sequence) - 2):
            counts["-".join(_INITIALS[b] for b in sequence[i : i + 3])] += 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def run_statistics(sequences: Sequence[Sequence[str]]) -> dict[str, float]:
    """Ratxes de la mateixa franja.

    ``same_bucket_run_mean`` i ``_max`` són sobre totes les ratxes (una frase
    sola és una ratxa d'1). ``repeated_<franja>_run_rate`` és la proporció de
    frases d'aquella franja que tenen al costat una altra de la mateixa franja.
    """
    lengths: list[int] = []
    in_run: Counter[str] = Counter()
    total: Counter[str] = Counter()
    for sequence in sequences:
        if not sequence:
            continue
        current, size = sequence[0], 1
        for label in sequence[1:]:
            if label == current:
                size += 1
            else:
                lengths.append(size)
                if size > 1:
                    in_run[current] += size
                current, size = label, 1
        lengths.append(size)
        if size > 1:
            in_run[current] += size
        total.update(sequence)
    result: dict[str, float] = {
        "same_bucket_run_mean": mean([float(n) for n in lengths]) if lengths else 0.0,
        "same_bucket_run_max": float(max(lengths)) if lengths else 0.0,
    }
    for name in BUCKETS:
        result[f"repeated_{name}_run_rate"] = in_run[name] / total[name] if total[name] else 0.0
    return result


def lag1_correlation(sequences: Sequence[Sequence[int]]) -> float | None:
    """Correlació de Pearson entre cada longitud i la següent.

    ``None`` si no hi ha prou parelles consecutives o si no hi ha variació.
    """
    xs: list[float] = []
    ys: list[float] = []
    for sequence in sequences:
        for previous, current in zip(sequence, sequence[1:], strict=False):
            xs.append(float(previous))
            ys.append(float(current))
    if len(xs) < MIN_PAIRS_FOR_CORRELATION:
        return None
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    return sxy / math.sqrt(sxx * syy)


def absolute_changes(sequences: Sequence[Sequence[int]]) -> list[float]:
    return [
        float(abs(current - previous))
        for sequence in sequences
        for previous, current in zip(sequence, sequence[1:], strict=False)
    ]


def rhythm_profile(
    sequences: Sequence[Sequence[int]],
    *,
    n_documents: int,
    paragraphs: Sequence[Sequence[int]] = (),
) -> dict[str, object]:
    """Secció ``rhythm_profile`` de l'empremta a partir de les seqüències de longituds.

    ``sequences`` conté una seqüència per document; ``paragraphs``, si el
    corpus conserva la separació, una seqüència de longituds per paràgraf.
    """
    values = [float(n) for sequence in sequences for n in sequence]
    n_sentences = len(values)
    thresholds = thresholds_for(values)
    labelled = bucket_sequences(sequences, thresholds)
    bucket_totals = Counter(label for sequence in labelled for label in sequence)
    counts = transition_counts(labelled)
    trigrams = trigram_counts(labelled)
    n_trigrams = sum(trigrams.values())
    changes = absolute_changes(sequences)
    profile: dict[str, object] = {
        "unit": UNIT,
        "sample_size_sentences": n_sentences,
        "sample_size_documents": n_documents,
        "confidence": confidence_level(n_sentences, n_documents),
        "length": length_statistics(values),
        "buckets": {
            "thresholds": thresholds,
            "counts": {name: bucket_totals.get(name, 0) for name in BUCKETS},
            "shares": {
                name: (bucket_totals.get(name, 0) / n_sentences if n_sentences else 0.0)
                for name in BUCKETS
            },
        },
        "transitions": {
            "counts": counts,
            "shares": transition_shares(counts),
            "n_transitions": sum(counts.values()),
        },
        "trigrams": {
            "counts": trigrams,
            "shares": {k: v / n_trigrams for k, v in trigrams.items()} if n_trigrams else {},
            "n_trigrams": n_trigrams,
        },
        "runs": run_statistics(labelled),
        "alternation": {
            "lag1_sentence_length_correlation": lag1_correlation(sequences),
            "mean_absolute_sentence_length_change": mean(changes) if changes else None,
            "median_absolute_sentence_length_change": median(changes) if changes else None,
            "n_pairs": len(changes),
        },
        "paragraphs": _paragraph_profile(paragraphs, thresholds),
    }
    return profile


def _paragraph_profile(
    paragraphs: Sequence[Sequence[int]], thresholds: Mapping[str, object]
) -> dict[str, object]:
    useful = [list(p) for p in paragraphs if p]
    if len(useful) < 2:
        return {"available": False, "reason": "el corpus no conserva prou paràgrafs"}
    per_paragraph = [float(len(p)) for p in useful]
    tokens = [float(sum(p)) for p in useful]
    first = [float(p[0]) for p in useful]
    last = [float(p[-1]) for p in useful]
    return {
        "available": True,
        "n_paragraphs": len(useful),
        "sentences_per_paragraph": {
            "mean": mean(per_paragraph),
            "median": median(per_paragraph),
            "std": stdev(per_paragraph),
        },
        "paragraph_token_length": {"mean": mean(tokens), "std": stdev(tokens)},
        "first_sentence_length": _length_summary(first, thresholds),
        "last_sentence_length": _length_summary(last, thresholds),
    }


def _length_summary(values: Sequence[float], thresholds: Mapping[str, object]) -> dict[str, object]:
    buckets = Counter(bucket_of(v, thresholds) for v in values)
    return {
        "mean": mean(values),
        "median": median(values),
        "shares": {name: buckets.get(name, 0) / len(values) for name in BUCKETS},
    }


# --- semblança ----------------------------------------------------------------------------


def rhythm_similarity(
    lengths: Sequence[int], profile: Mapping[str, object]
) -> tuple[float | None, dict[str, float], str]:
    """Semblança (0-1) del ritme d'una seqüència de longituds amb un ``rhythm_profile``.

    Retorna la semblança, les puntuacions parcials i una nota curta. ``None``
    si el perfil no és fiable o la seqüència és massa curta per dir-ne res.
    Parcials: franges (proporcions), transicions (només amb 4 frases o més),
    canvi absolut mitjà, coeficient de variació i correlació de retard 1.
    """
    if profile.get("confidence") == "low" or len(lengths) < 2:
        return None, {}, ""
    buckets = profile.get("buckets")
    length = profile.get("length")
    alternation = profile.get("alternation")
    transitions = profile.get("transitions")
    if not all(isinstance(x, Mapping) for x in (buckets, length, alternation, transitions)):
        return None, {}, ""
    assert isinstance(buckets, Mapping) and isinstance(length, Mapping)
    assert isinstance(alternation, Mapping) and isinstance(transitions, Mapping)
    thresholds = buckets.get("thresholds")
    if not isinstance(thresholds, Mapping):
        return None, {}, ""
    labels = [bucket_of(n, thresholds) for n in lengths]
    partial: dict[str, float] = {}
    weights: dict[str, float] = {}

    author_shares = _float_map(buckets.get("shares"))
    own_counts = Counter(labels)
    own_shares = {name: own_counts.get(name, 0) / len(labels) for name in BUCKETS}
    partial["franges"] = 1.0 - _total_variation(own_shares, author_shares)
    weights["franges"] = 1.0

    if len(labels) >= 4:
        own_counts_t = transition_counts([labels])
        total = sum(own_counts_t.values()) or 1
        author_counts = _float_map(transitions.get("counts"))
        author_total = sum(author_counts.values()) or 1.0
        partial["transicions"] = 1.0 - _total_variation(
            {k: v / total for k, v in own_counts_t.items()},
            {k: v / author_total for k, v in author_counts.items()},
        )
        weights["transicions"] = 1.0

    values = [float(n) for n in lengths]
    changes = absolute_changes([list(lengths)])
    author_change = _number(alternation.get("mean_absolute_sentence_length_change"), None)
    if changes and author_change is not None:
        partial["canvi"] = 1.0 - relative_difference(mean(changes), author_change)
        weights["canvi"] = 1.0
    author_cv = _number(length.get("cv"), None)
    if len(values) >= 3 and author_cv is not None:
        deviation = stdev(values)
        cv = deviation / mean(values) if mean(values) else 0.0
        partial["variacio"] = 1.0 - relative_difference(cv, author_cv)
        weights["variacio"] = 1.0
    own_lag = lag1_correlation([list(lengths)])
    author_lag = _number(alternation.get("lag1_sentence_length_correlation"), None)
    if own_lag is not None and author_lag is not None:
        partial["retard"] = 1.0 - abs(own_lag - author_lag) / 2.0
        weights["retard"] = 0.5

    if not partial:
        return None, {}, ""
    score = sum(partial[k] * weights[k] for k in partial) / sum(weights.values())
    note = ", ".join(f"{k} {v:.2f}" for k, v in partial.items())
    return score, partial, note


def _total_variation(p: Mapping[str, float], q: Mapping[str, float]) -> float:
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys) if keys else 0.0


def _float_map(node: object) -> dict[str, float]:
    if not isinstance(node, Mapping):
        return {}
    return {
        str(k): float(v)
        for k, v in node.items()
        if isinstance(v, int | float) and not isinstance(v, bool)
    }


def _number(value: object, default: float | None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value)


def _as_float(value: object, default: float) -> float:
    number = _number(value, None)
    return default if number is None else number


__all__ = [
    "BUCKETS",
    "FALLBACK_LONG_MIN",
    "FALLBACK_SHORT_MAX",
    "MIN_PAIRS_FOR_CORRELATION",
    "MIN_SENTENCES_FOR_TERCILES",
    "UNIT",
    "absolute_changes",
    "bucket_of",
    "confidence_level",
    "lag1_correlation",
    "length_statistics",
    "rhythm_profile",
    "rhythm_similarity",
    "run_statistics",
    "stdev",
    "thresholds_for",
    "transition_counts",
    "transition_shares",
    "trigram_counts",
]
