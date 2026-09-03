"""Comparació de dues empremtes estilístiques.

Recorre les característiques de totes dues empremtes i, per a cada node
comparable, calcula una distància entre 0 (igual) i 1 (màximament diferent):

- característiques numèriques: diferència relativa ``|a - b| / (|a| + |b|)``;
- distribucions de proporcions (``*_shares``, ``variants``): distància de
  variació total;
- llistes d'elements més freqüents (``top``, ``items``, ``top_words``):
  1 − índex de Jaccard dels deu primers;
- variant preferida (``preferred``): 0 si coincideix, 1 si difereix, 0,5 si
  només una de les empremtes en té.

La distància global és la mitjana ponderada per la confiança mínima de cada
parell de nodes, de manera que les característiques poc observades pesen poc.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from parafrasi_cat.style.fingerprint import FeatureStat, StyleFingerprint, is_stat
from parafrasi_cat.style.statistics import jaccard, relative_difference, total_variation

_LIST_KEYS = frozenset({"top", "items", "top_words"})
_LIST_WEIGHT = 0.5
_TOP_N = 10

SIMILAR_THRESHOLD = 0.15
DIFFERENT_THRESHOLD = 0.4


@dataclass(frozen=True, slots=True)
class ComparisonItem:
    path: str
    kind: str
    a: object
    b: object
    distance: float
    weight: float

    @property
    def weighted(self) -> float:
        return self.distance * self.weight

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "kind": self.kind,
            "a": self.a,
            "b": self.b,
            "distance": round(self.distance, 4),
            "weight": round(self.weight, 4),
        }


@dataclass(frozen=True, slots=True)
class FingerprintComparison:
    a_name: str
    b_name: str
    distance: float
    items: tuple[ComparisonItem, ...]

    @property
    def label(self) -> str:
        return label_for(self.distance)

    def divergent(self, threshold: float = DIFFERENT_THRESHOLD) -> tuple[ComparisonItem, ...]:
        return tuple(
            sorted(
                (i for i in self.items if i.weight > 0 and i.distance >= threshold),
                key=lambda i: (-i.distance, i.path),
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "a": self.a_name,
            "b": self.b_name,
            "distance": round(self.distance, 4),
            "label": self.label,
            "items": [i.to_dict() for i in self.items],
        }

    def report(self, top: int = 15) -> str:
        lines = [
            f"=== Comparació d'empremtes: «{self.a_name}» i «{self.b_name}» ===",
            f"Distància global: {self.distance:.3f} ({self.label})",
            f"Característiques comparades: {sum(1 for i in self.items if i.weight > 0)}",
            "",
            "Característiques més divergents:",
        ]
        ranked = sorted(
            (i for i in self.items if i.weight > 0), key=lambda i: (-i.weighted, i.path)
        )
        if not ranked:
            lines.append("  (cap)")
        for item in ranked[:top]:
            lines.append(
                f"  {item.distance:.2f}  {item.path}  "
                f"[{_describe(item.a)} | {_describe(item.b)}]  (pes {item.weight:.2f})"
            )
        return "\n".join(lines)


def label_for(distance: float) -> str:
    if distance < SIMILAR_THRESHOLD:
        return "molt semblants"
    if distance < DIFFERENT_THRESHOLD:
        return "semblants amb diferències"
    return "clarament diferents"


def compare_fingerprints(a: StyleFingerprint, b: StyleFingerprint) -> FingerprintComparison:
    items: list[ComparisonItem] = []
    _walk(a.features, b.features, "", 1.0, items)
    total_weight = sum(i.weight for i in items)
    distance = sum(i.weighted for i in items) / total_weight if total_weight > 0 else 0.0
    return FingerprintComparison(a.name, b.name, round(distance, 4), tuple(items))


def _walk(
    a: object, b: object, path: str, parent_weight: float, items: list[ComparisonItem]
) -> None:
    if is_stat(a) and is_stat(b):
        assert isinstance(a, Mapping) and isinstance(b, Mapping)
        stat_a, stat_b = FeatureStat.from_dict(a), FeatureStat.from_dict(b)
        if stat_a.value is None or stat_b.value is None:
            return
        items.append(
            ComparisonItem(
                path,
                "stat",
                stat_a.value,
                stat_b.value,
                relative_difference(stat_a.value, stat_b.value),
                min(stat_a.confidence, stat_b.confidence),
            )
        )
        return
    if not isinstance(a, Mapping) or not isinstance(b, Mapping):
        return
    weight = min(_confidence(a), _confidence(b), parent_weight)
    for key in sorted(set(a.keys()) | set(b.keys())):
        if key not in a or key not in b:
            continue
        child_path = f"{path}.{key}" if path else str(key)
        value_a, value_b = a[key], b[key]
        if key == "variants" and isinstance(value_a, Mapping) and isinstance(value_b, Mapping):
            shares_a, shares_b = _variant_shares(value_a), _variant_shares(value_b)
            items.append(
                ComparisonItem(
                    child_path,
                    "shares",
                    shares_a,
                    shares_b,
                    total_variation(shares_a, shares_b),
                    weight,
                )
            )
        elif str(key).endswith("shares") and isinstance(value_a, Mapping):
            if not isinstance(value_b, Mapping):
                continue
            shares_a = _as_shares(value_a)
            shares_b = _as_shares(value_b)
            items.append(
                ComparisonItem(
                    child_path,
                    "shares",
                    shares_a,
                    shares_b,
                    total_variation(shares_a, shares_b),
                    weight,
                )
            )
        elif key in _LIST_KEYS and isinstance(value_a, Sequence) and isinstance(value_b, Sequence):
            names_a, names_b = _names(value_a), _names(value_b)
            if not names_a and not names_b:
                continue
            items.append(
                ComparisonItem(
                    child_path,
                    "list",
                    names_a,
                    names_b,
                    1.0 - jaccard(names_a, names_b),
                    weight * _LIST_WEIGHT,
                )
            )
        elif key == "preferred":
            if value_a is None and value_b is None:
                continue
            if value_a is None or value_b is None:
                distance = 0.5
            else:
                distance = 0.0 if value_a == value_b else 1.0
            items.append(
                ComparisonItem(child_path, "preferred", value_a, value_b, distance, weight)
            )
        else:
            _walk(value_a, value_b, child_path, weight, items)


def _confidence(node: Mapping[object, object]) -> float:
    value = node.get("confidence")
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return 1.0


def _as_shares(node: Mapping[object, object]) -> dict[str, float]:
    return {
        str(k): float(v)
        for k, v in node.items()
        if isinstance(v, int | float) and not isinstance(v, bool)
    }


def _variant_shares(node: Mapping[object, object]) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in node.items():
        if isinstance(value, Mapping):
            share = value.get("share")
            if isinstance(share, int | float) and not isinstance(share, bool):
                result[str(key)] = float(share)
    return result


def _names(items: Sequence[object]) -> list[str]:
    names: list[str] = []
    for item in items[:_TOP_N]:
        if isinstance(item, Mapping):
            name = item.get("form", item.get("text"))
            if name is not None:
                names.append(str(name))
    return names


def _describe(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3g}"
    if isinstance(value, Mapping):
        ordered = sorted(value.items(), key=lambda kv: (-float(kv[1]), str(kv[0])))
        return ", ".join(f"{k} {float(v):.0%}" for k, v in ordered[:2]) or "—"
    if isinstance(value, list | tuple):
        return ", ".join(str(v) for v in value[:3]) + ("…" if len(value) > 3 else "")
    if value is None:
        return "—"
    return str(value)
