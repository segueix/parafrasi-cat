from __future__ import annotations

import pytest

from parafrasi_cat.core import Span, spans_overlap


def test_span_basics() -> None:
    span = Span(2, 5)
    assert span.length == 3
    assert not span.is_empty
    assert span.slice("abcdefg") == "cde"
    assert span.to_dict() == {"start": 2, "end": 5}
    assert Span(3, 3).is_empty


def test_span_validation() -> None:
    with pytest.raises(ValueError):
        Span(-1, 2)
    with pytest.raises(ValueError):
        Span(5, 2)


def test_overlaps_and_contains() -> None:
    assert Span(0, 5).overlaps(Span(4, 8))
    assert not Span(0, 5).overlaps(Span(5, 8))
    assert Span(0, 10).contains(Span(3, 7))
    assert not Span(0, 5).contains(Span(3, 7))
    assert Span(0, 5).contains_index(4)
    assert not Span(0, 5).contains_index(5)


def test_shift_and_clip() -> None:
    assert Span(2, 5).shift(10) == Span(12, 15)
    assert Span(2, 9).clip(Span(5, 20)) == Span(5, 9)
    assert Span(2, 4).clip(Span(5, 20)) is None
    assert Span(2, 4).clip(Span(0, 3)) == Span(2, 3)


def test_spans_overlap_collection() -> None:
    assert not spans_overlap([Span(0, 2), Span(2, 4), Span(6, 9)])
    assert spans_overlap([Span(6, 9), Span(0, 7)])
    assert not spans_overlap([])


def test_ordering() -> None:
    assert sorted([Span(3, 4), Span(0, 9), Span(0, 2)]) == [Span(0, 2), Span(0, 9), Span(3, 4)]
