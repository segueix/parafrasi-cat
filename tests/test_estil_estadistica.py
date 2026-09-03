"""Estadística robusta del mòdul d'estil."""

from __future__ import annotations

import pytest

from parafrasi_cat.style.statistics import (
    capped_weights,
    confidence,
    iqr,
    jaccard,
    mad,
    median,
    percentile,
    relative_difference,
    robust_average,
    robust_location,
    robust_rate,
    round_floats,
    shares,
    total_variation,
    trimmed_mean,
    weighted_median,
)


def test_location_and_spread() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 100.0]
    assert median(values) == 3.0
    assert median([]) == 0.0
    assert median([2.0, 4.0]) == 3.0
    assert percentile(values, 0) == 1.0 and percentile(values, 100) == 100.0
    assert percentile(values, 50) == 3.0
    assert percentile([5.0], 90) == 5.0
    assert mad(values) == 1.0
    assert iqr([1.0, 2.0, 3.0, 4.0]) == pytest.approx(1.5)
    assert trimmed_mean(values, 0.2) == 3.0
    assert trimmed_mean([], 0.1) == 0.0


def test_weighted_median_and_capped_weights() -> None:
    assert weighted_median([1.0, 2.0, 10.0], [1.0, 1.0, 1.0]) == 2.0
    assert weighted_median([1.0, 2.0, 10.0], [1.0, 1.0, 5.0]) == 10.0
    assert weighted_median([], []) == 0.0
    assert weighted_median([3.0, 4.0], [0.0, 0.0]) == 3.5
    with pytest.raises(ValueError):
        weighted_median([1.0], [1.0, 2.0])
    # Un document deu vegades més gran que la mediana queda limitat a tres vegades.
    assert capped_weights([100.0, 100.0, 1000.0]) == [100.0, 100.0, 300.0]
    assert capped_weights([]) == []
    assert capped_weights([0.0, 0.0]) == [1.0, 1.0]


def test_confidence_grows_with_observations_and_documents() -> None:
    assert confidence(0, 3) == 0.0
    assert confidence(10, 1) == pytest.approx(0.25)
    assert confidence(10, 2) == pytest.approx(0.375)
    assert confidence(10, 4) < confidence(40, 4) < confidence(400, 8) < 1.0
    assert confidence(5, 0) == 0.0


def test_robust_rate_is_not_dominated_by_one_document() -> None:
    # Quatre documents normals i un d'excepcional amb moltíssims punts i coma.
    counts = [1.0, 2.0, 1.0, 2.0, 60.0]
    words = [100.0, 100.0, 100.0, 100.0, 100.0]
    summary = robust_rate(counts, words, 100.0)
    assert summary.n_documents == 5 and summary.n_observations == 66
    assert summary.value == 2.0  # mediana ponderada
    assert summary.pooled == pytest.approx(13.2)
    assert summary.per_document()["max"] == 60.0
    assert summary.variability == pytest.approx(0.0, abs=1.0)
    # Amb menys de cinc documents s'usa la mitjana amb pesos limitats.
    few = robust_rate([0.0, 1.0, 0.0, 1.0], [50.0, 50.0, 50.0, 50.0], 100.0)
    assert few.value == pytest.approx(1.0)
    # Documents sense denominador s'ignoren; sense cap dada el resum és zero.
    assert robust_rate([3.0], [0.0]).n_documents == 0
    with pytest.raises(ValueError):
        robust_rate([1.0], [1.0, 2.0])


def test_robust_location_caps_large_documents() -> None:
    short = [[5.0, 6.0, 7.0], [5.0, 6.0, 7.0], [5.0, 6.0, 7.0], [5.0, 6.0, 7.0]]
    long = [[40.0] * 300]
    summary = robust_location([*short, *long])
    assert summary.value == 7.0
    assert summary.n_documents == 5 and summary.n_observations == 312
    assert summary.per_document()["median"] == 6.0
    assert robust_location([[]]).n_documents == 0


def test_robust_average() -> None:
    summary = robust_average([0.5, 0.6, 0.9], [100.0, 100.0, 1000.0])
    assert 0.5 < summary.value < 0.9
    assert summary.pooled == pytest.approx((50 + 60 + 900) / 1200)
    assert robust_average([], []).n_observations == 0
    with pytest.raises(ValueError):
        robust_average([1.0], [])


def test_distributions_and_distances() -> None:
    assert shares({"a": 3, "b": 1}) == {"a": 0.75, "b": 0.25}
    assert shares({"a": 0}) == {"a": 0.0}
    assert total_variation({"a": 1.0}, {"b": 1.0}) == 1.0
    assert total_variation({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}) == 0.0
    assert total_variation({}, {}) == 0.0
    assert relative_difference(2.0, 2.0) == 0.0
    assert relative_difference(0.0, 3.0) == 1.0
    assert relative_difference(0.0, 0.0) == 0.0
    assert jaccard(["a", "b"], ["b", "c"]) == pytest.approx(1 / 3)
    assert jaccard([], []) == 1.0
    assert round_floats({"x": 1.23456789, "y": [0.000001, True, "t"]}) == {
        "x": 1.2346,
        "y": [0.0, True, "t"],
    }
