"""Perfil sintàctic de l'autor: com construeix i encadena les frases.

Es calcula amb el parser local ja integrat (spaCy, model català entrenat
sobre UD Catalan AnCora), que **només analitza**: aporta dependències,
categories, lemes i trets, i el motor en fa recomptes. No es guarda cap
frase: només estadístics, distribucions i patrons abstractes.

Etiquetes que dona el parser real (Universal Dependencies): ``acl``,
``advcl``, ``ccomp``, ``xcomp``, ``csubj``, ``conj``, ``cc``, ``nmod``,
``amod``, ``appos``, ``cop``, ``nsubj``, ``obj``, ``iobj``, ``obl``,
``expl:pass``... No hi ha ``acl:relcl`` ni ``nsubj:pass``: les relatives es
reconeixen per un pronom relatiu dins de la clàusula, i les passives per un
participi amb auxiliar «ser» o per ``expl:pass``. Quan un cas és dubtós, no es
compta: precisió abans que cobertura.

Suficiència de mostra (documentada, determinista): ``high`` amb 40 frases o
més en 2 documents o més; ``medium`` amb 15 o més; ``low`` la resta.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from parafrasi_cat.style.rhythm import confidence_level, stdev
from parafrasi_cat.style.statistics import mean, median, percentile
from parafrasi_cat.syntax.analysis import SentenceSyntax, SyntaxToken

#: Relacions que obren una clàusula subordinada.
SUBORDINATE_DEPS = frozenset({"acl", "advcl", "ccomp", "xcomp", "csubj"})
#: Complements del nucli que es miren per l'ordre (no s'hi compten adverbis solts).
COMPLEMENT_DEPS = frozenset({"obl", "advcl"})
#: Lemes d'auxiliar que, amb un participi, formen una passiva perifràstica.
PASSIVE_AUXILIARIES = frozenset({"ser", "ésser", "esser"})
#: Nombre màxim d'elements d'un patró abstracte.
MAX_PATTERN_ELEMENTS = 6
TOP_PATTERNS = 12

SUBORDINATE_TYPES: tuple[str, ...] = ("relative", "adverbial", "complement", "infinitival", "other")
COORDINATION_TYPES: tuple[str, ...] = (
    "nominal",
    "clausal",
    "adjectival",
    "adverbial",
    "other",
)


@dataclass(frozen=True, slots=True)
class SentenceSyntaxStats:
    """Recomptes sintàctics d'una frase (cap text, només nombres i etiquetes)."""

    n_tokens: int
    clause_count: int
    subordinates: tuple[str, ...]
    subordination_depth_max: int
    parse_depth_max: int
    parse_depth_mean: float
    coordinations: tuple[tuple[str, int], ...]
    coordination_depth_max: int
    conjunctions: tuple[str, ...]
    nominal_modifiers: int
    adjectival_modifiers: int
    appositions: int
    copular: int
    passive: int
    subjects_before: int
    subjects_after: int
    objects_before: int
    objects_after: int
    complements_preposed: int
    complements_postposed: int
    initial_oblique: bool
    initial_temporal: bool
    initial_locative: bool
    dependency_distances: tuple[int, ...]
    pattern: str

    @property
    def n_subordinates(self) -> int:
        return len(self.subordinates)

    @property
    def n_coordinations(self) -> int:
        return len(self.coordinations)


def observe_sentence_syntax(analysis: SentenceSyntax) -> SentenceSyntaxStats | None:
    """Recomptes d'una frase analitzada; ``None`` si l'anàlisi no és fiable."""
    if not analysis.confident:
        return None
    tokens = [t for t in analysis.tokens if t.pos != "PUNCT"]
    if not tokens:
        return None
    by_index = {t.index: t for t in analysis.tokens}
    root = analysis.root
    if root is None:
        return None

    def ancestors(token: SyntaxToken) -> list[SyntaxToken]:
        chain: list[SyntaxToken] = []
        current = token
        seen = {token.index}
        while not current.is_root:
            current = by_index[current.head]
            if current.index in seen:
                break
            seen.add(current.index)
            chain.append(current)
        return chain

    def children(token: SyntaxToken) -> list[SyntaxToken]:
        return [t for t in analysis.tokens if t.head == token.index and t.index != token.index]

    clause_heads = [t for t in tokens if t.dep in SUBORDINATE_DEPS]
    # Un verb coordinat amb un altre predicat és una clàusula coordinada (UD
    # coordina predicats, no oracions): «existia…, però no es pot demostrar».
    coordinated_clauses = [t for t in tokens if t.dep == "conj" and t.pos in ("VERB", "AUX")]
    subordinate_types = tuple(_subordinate_type(t, children(t)) for t in clause_heads)
    depths = [len(ancestors(t)) for t in tokens]
    subordination_depths = [
        sum(1 for a in ancestors(t) if a.dep in SUBORDINATE_DEPS) + 1 for t in clause_heads
    ]
    coordinations: list[tuple[str, int]] = []
    for token in tokens:
        conjuncts = [c for c in children(token) if c.dep == "conj"]
        if conjuncts:
            coordinations.append((_coordination_type(token), 1 + len(conjuncts)))
    coordination_depths = [
        sum(1 for a in ancestors(t) if a.dep == "conj") + 1 for t in tokens if t.dep == "conj"
    ]
    conjunctions = tuple(t.lemma.lower() for t in tokens if t.dep == "cc")

    subjects_before = subjects_after = objects_before = objects_after = 0
    for token in tokens:
        if token.dep == "nsubj":
            if token.index < token.head:
                subjects_before += 1
            else:
                subjects_after += 1
        elif token.dep == "obj":
            if token.index < token.head:
                objects_before += 1
            else:
                objects_after += 1
    root_complements = [c for c in children(root) if c.dep in COMPLEMENT_DEPS]
    preposed = sum(1 for c in root_complements if c.index < root.index)
    first = tokens[0]
    first_chain = [first, *ancestors(first)]
    initial_constituent = next(
        (
            t
            for t in first_chain
            if t.dep in COMPLEMENT_DEPS and t.head == root.index and t.index != root.index
        ),
        None,
    )
    passive = sum(1 for t in tokens if _is_passive(t, children(t)))
    distances = tuple(abs(t.index - t.head) for t in tokens if not t.is_root)
    return SentenceSyntaxStats(
        n_tokens=len(tokens),
        clause_count=1 + len(clause_heads) + len(coordinated_clauses),
        subordinates=subordinate_types,
        subordination_depth_max=max(subordination_depths, default=0),
        parse_depth_max=max(depths, default=0),
        parse_depth_mean=mean([float(d) for d in depths]) if depths else 0.0,
        coordinations=tuple(coordinations),
        coordination_depth_max=max(coordination_depths, default=0),
        conjunctions=conjunctions,
        nominal_modifiers=sum(1 for t in tokens if t.dep == "nmod"),
        adjectival_modifiers=sum(1 for t in tokens if t.dep == "amod"),
        appositions=sum(1 for t in tokens if t.dep == "appos"),
        copular=sum(1 for t in tokens if t.dep == "cop"),
        passive=passive,
        subjects_before=subjects_before,
        subjects_after=subjects_after,
        objects_before=objects_before,
        objects_after=objects_after,
        complements_preposed=preposed,
        complements_postposed=len(root_complements) - preposed,
        initial_oblique=initial_constituent is not None,
        initial_temporal=initial_constituent is not None and initial_constituent.adv_type == "Tim",
        initial_locative=initial_constituent is not None and initial_constituent.adv_type == "Loc",
        dependency_distances=distances,
        pattern=_pattern(analysis, root, clause_heads, subordinate_types, coordinated_clauses),
    )


def _subordinate_type(head: SyntaxToken, dependents: Sequence[SyntaxToken]) -> str:
    if any(d.pron_type == "Rel" for d in dependents):
        return "relative"
    if head.dep == "advcl":
        return "adverbial"
    if head.dep == "acl":
        if any(d.dep == "mark" for d in dependents):
            return "adverbial"
        return "infinitival" if head.verb_form == "Inf" else "other"
    if head.dep == "xcomp":
        return "infinitival" if head.verb_form in ("Inf", None) else "complement"
    return "infinitival" if head.verb_form == "Inf" else "complement"


def _coordination_type(head: SyntaxToken) -> str:
    if head.pos in ("NOUN", "PROPN", "PRON", "NUM"):
        return "nominal"
    if head.pos in ("VERB", "AUX"):
        return "clausal"
    if head.pos == "ADJ":
        return "adjectival"
    if head.pos == "ADV":
        return "adverbial"
    return "other"


def _is_passive(token: SyntaxToken, dependents: Sequence[SyntaxToken]) -> bool:
    if any(d.dep == "expl:pass" for d in dependents):
        return True
    if token.pos != "VERB" or token.verb_form != "Part":
        return False
    return any(d.dep == "aux" and d.lemma.lower() in PASSIVE_AUXILIARIES for d in dependents)


_PATTERN_LABELS = {
    "relative": "REL",
    "adverbial": "ADV",
    "complement": "COMP",
    "infinitival": "INF",
    "other": "SUB",
}


def _pattern(
    analysis: SentenceSyntax,
    root: SyntaxToken,
    clause_heads: Sequence[SyntaxToken],
    types: Sequence[str],
    coordinated: Sequence[SyntaxToken],
) -> str:
    """Patró abstracte: nucli, subordinades, coordinacions i complements anteposats, en ordre."""
    elements: list[tuple[int, str]] = [(root.index, "MAIN")]
    elements.extend(
        (head.index, _PATTERN_LABELS[kind]) for head, kind in zip(clause_heads, types, strict=True)
    )
    elements.extend((t.index, "COORD") for t in coordinated)
    for token in analysis.tokens:
        if token.head == root.index and token.dep == "obl" and token.index < root.index:
            elements.append((token.index, "TEMP" if token.adv_type == "Tim" else "OBL"))
    labels: list[str] = []
    for _, label in sorted(elements):
        if labels and labels[-1] == label:
            continue
        labels.append(label)
    if len(labels) > MAX_PATTERN_ELEMENTS:
        labels = [*labels[: MAX_PATTERN_ELEMENTS - 1], "…"]
    return " + ".join(labels)


# --- agregació ----------------------------------------------------------------------


def unavailable_profile(reason: str) -> dict[str, object]:
    return {"available": False, "reason": reason}


def syntactic_profile(
    stats: Sequence[SentenceSyntaxStats],
    *,
    n_documents: int,
    parser: str,
    skipped_sentences: int = 0,
    impersonal_sentences: int = 0,
) -> dict[str, object]:
    """Secció ``syntactic_profile`` de l'empremta a partir dels recomptes per frase."""
    n = len(stats)
    if n == 0:
        return unavailable_profile("cap frase amb una anàlisi sintàctica fiable")
    n_tokens = sum(s.n_tokens for s in stats)
    per_thousand = 1000.0 / n_tokens if n_tokens else 0.0

    def rate(total: int) -> dict[str, float]:
        return {"per_sentence": total / n, "per_1000_tokens": total * per_thousand}

    subordinates = [kind for s in stats for kind in s.subordinates]
    coordinations = [c for s in stats for c in s.coordinations]
    distances = [float(d) for s in stats for d in s.dependency_distances]
    clause_counts = [float(s.clause_count) for s in stats]
    depths = [float(s.parse_depth_max) for s in stats]
    subordination_depths = [s.subordination_depth_max for s in stats]
    patterns = Counter(s.pattern for s in stats)
    by_sub_type = Counter(subordinates)
    by_coord_type = Counter(kind for kind, _ in coordinations)
    sizes = Counter("4+" if size >= 4 else str(size) for _, size in coordinations)
    conjunctions = Counter(c for s in stats for c in s.conjunctions)
    n_subjects = sum(s.subjects_before + s.subjects_after for s in stats)
    n_objects = sum(s.objects_before + s.objects_after for s in stats)
    n_complements = sum(s.complements_preposed + s.complements_postposed for s in stats)

    def share(part: int, whole: int) -> float | None:
        return part / whole if whole else None

    return {
        "available": True,
        "parser": parser,
        "sample_size_sentences": n,
        "sample_size_tokens": n_tokens,
        "sample_size_documents": n_documents,
        "skipped_sentences": skipped_sentences,
        "confidence": confidence_level(n, n_documents),
        "rates": {
            "coordination_rate": rate(len(coordinations)),
            "subordination_rate": rate(len(subordinates)),
            "relative_clause_rate": rate(by_sub_type["relative"]),
            "adverbial_clause_rate": rate(by_sub_type["adverbial"]),
            "complement_clause_rate": rate(by_sub_type["complement"]),
            "infinitival_clause_rate": rate(by_sub_type["infinitival"]),
            "nominal_modifier_rate": rate(sum(s.nominal_modifiers for s in stats)),
            "adjectival_modifier_rate": rate(sum(s.adjectival_modifiers for s in stats)),
            "apposition_rate": rate(sum(s.appositions for s in stats)),
            "passive_rate": rate(sum(s.passive for s in stats)),
            "impersonal_rate": rate(impersonal_sentences),
            "copular_structure_rate": rate(sum(s.copular for s in stats)),
        },
        "coordination": {
            "per_sentence": len(coordinations) / n,
            "per_1000_tokens": len(coordinations) * per_thousand,
            "sentences_with_coordination_share": sum(1 for s in stats if s.coordinations) / n,
            "by_type": {
                kind: (by_coord_type[kind] / len(coordinations) if coordinations else 0.0)
                for kind in COORDINATION_TYPES
            },
            "group_size_shares": {
                key: (sizes[key] / len(coordinations) if coordinations else 0.0)
                for key in ("2", "3", "4+")
            },
            "mean_group_size": mean([float(size) for _, size in coordinations])
            if coordinations
            else 0.0,
            "max_depth": max((s.coordination_depth_max for s in stats), default=0),
            "conjunctions": {
                form: {"count": count, "share": count / sum(conjunctions.values())}
                for form, count in sorted(conjunctions.items(), key=lambda i: (-i[1], i[0]))[:10]
            },
        },
        "subordination": {
            "per_sentence": len(subordinates) / n,
            "sentences_with_subordination_share": sum(1 for s in stats if s.subordinates) / n,
            "depth_max": max(subordination_depths, default=0),
            "depth_mean": mean([float(d) for d in subordination_depths if d > 0])
            if any(subordination_depths)
            else 0.0,
            "depth_distribution": {
                key: sum(1 for d in subordination_depths if _depth_key(d) == key) / n
                for key in ("0", "1", "2", "3+")
            },
            "by_type": {
                kind: {"count": by_sub_type[kind], "per_sentence": by_sub_type[kind] / n}
                for kind in SUBORDINATE_TYPES
            },
        },
        "order": {
            "subject_before_verb_rate": share(sum(s.subjects_before for s in stats), n_subjects),
            "subject_after_verb_rate": share(sum(s.subjects_after for s in stats), n_subjects),
            "object_before_verb_rate": share(sum(s.objects_before for s in stats), n_objects),
            "object_after_verb_rate": share(sum(s.objects_after for s in stats), n_objects),
            "preposed_complement_rate": share(
                sum(s.complements_preposed for s in stats), n_complements
            ),
            "postposed_complement_rate": share(
                sum(s.complements_postposed for s in stats), n_complements
            ),
            "sentence_initial_oblique_rate": sum(1 for s in stats if s.initial_oblique) / n,
            "sentence_initial_temporal_rate": sum(1 for s in stats if s.initial_temporal) / n,
            "sentence_initial_locative_rate": sum(1 for s in stats if s.initial_locative) / n,
            "n_subjects": n_subjects,
            "n_objects": n_objects,
            "n_complements": n_complements,
        },
        "dependency_distance": {
            "mean_dependency_distance": mean(distances) if distances else 0.0,
            "median_dependency_distance": median(distances) if distances else 0.0,
            "dependency_distance_std": stdev(distances),
            "dependency_distance_p90": percentile(distances, 90) if distances else 0.0,
            "max_dependency_distance": max(distances) if distances else 0.0,
            "n_dependencies": len(distances),
        },
        "complexity": {
            "mean_clause_count": mean(clause_counts),
            "median_clause_count": median(clause_counts),
            "clauses_per_sentence": mean(clause_counts),
            "simple_sentence_ratio": sum(1 for c in clause_counts if c == 1) / n,
            "complex_sentence_ratio": sum(1 for c in clause_counts if c > 1) / n,
            "clause_count_distribution": {
                key: sum(1 for c in clause_counts if _clause_key(c) == key) / n
                for key in ("1", "2", "3", "4+")
            },
            "mean_parse_depth": mean(depths),
            "median_parse_depth": median(depths),
            "parse_depth_std": stdev(depths),
            "maximum_observed_parse_depth": max(depths) if depths else 0.0,
        },
        "patterns": {
            "n_distinct": len(patterns),
            "top": [
                {"pattern": pattern, "count": count, "share": count / n}
                for pattern, count in sorted(patterns.items(), key=lambda i: (-i[1], i[0]))[
                    :TOP_PATTERNS
                ]
            ],
        },
    }


def _depth_key(depth: int) -> str:
    return "3+" if depth >= 3 else str(depth)


def _clause_key(count: float) -> str:
    return "4+" if count >= 4 else str(int(count))


# --- semblança ----------------------------------------------------------------------------


def syntactic_similarity(
    stats: Sequence[SentenceSyntaxStats], profile: Mapping[str, object]
) -> tuple[float | None, dict[str, float], str]:
    """Semblança (0-1) de l'estructura d'un text amb un ``syntactic_profile``.

    Parcials, cadascun 0-1: coordinació i subordinació per frase, ordre del
    subjecte, complements anteposats, distància de dependències, profunditat,
    clàusules per frase i familiaritat dels patrons abstractes. ``None`` si el
    perfil no és fiable o no hi ha cap frase analitzada.
    """
    if not stats or profile.get("confidence") == "low" or not profile.get("available"):
        return None, {}, ""
    n = len(stats)
    coordination = _mapping(profile.get("coordination"))
    subordination = _mapping(profile.get("subordination"))
    order = _mapping(profile.get("order"))
    distance = _mapping(profile.get("dependency_distance"))
    complexity = _mapping(profile.get("complexity"))
    patterns = _mapping(profile.get("patterns"))
    partial: dict[str, float] = {}

    def closeness(author: object, own: float, floor: float) -> float | None:
        value = _number(author)
        if value is None:
            return None
        return 1.0 - min(1.0, abs(value - own) / max(value, floor))

    checks = (
        (
            "coordinacio",
            coordination.get("per_sentence"),
            sum(s.n_coordinations for s in stats) / n,
            0.5,
        ),
        (
            "subordinacio",
            subordination.get("per_sentence"),
            sum(s.n_subordinates for s in stats) / n,
            0.5,
        ),
        ("distancia", distance.get("mean_dependency_distance"), _mean_distance(stats), 1.0),
        (
            "profunditat",
            complexity.get("mean_parse_depth"),
            mean([float(s.parse_depth_max) for s in stats]),
            2.0,
        ),
        (
            "clausules",
            complexity.get("clauses_per_sentence"),
            mean([float(s.clause_count) for s in stats]),
            1.0,
        ),
    )
    for name, author, own, floor in checks:
        value = closeness(author, own, floor)
        if value is not None:
            partial[name] = value
    subjects = sum(s.subjects_before + s.subjects_after for s in stats)
    if subjects and _number(order.get("subject_before_verb_rate")) is not None:
        own_rate = sum(s.subjects_before for s in stats) / subjects
        author_rate = _number(order.get("subject_before_verb_rate")) or 0.0
        partial["ordre_subjecte"] = 1.0 - abs(own_rate - author_rate)
    complements = sum(s.complements_preposed + s.complements_postposed for s in stats)
    if complements and _number(order.get("preposed_complement_rate")) is not None:
        own_rate = sum(s.complements_preposed for s in stats) / complements
        author_rate = _number(order.get("preposed_complement_rate")) or 0.0
        partial["complements"] = 1.0 - abs(own_rate - author_rate)
    top = patterns.get("top")
    if isinstance(top, list) and top:
        shares = {
            str(item.get("pattern")): float(item.get("share", 0.0))
            for item in top
            if isinstance(item, Mapping)
        }
        best = max(shares.values(), default=0.0)
        if best > 0:
            familiarity = [shares.get(s.pattern, 0.0) / best for s in stats]
            partial["patrons"] = min(1.0, sum(familiarity) / len(familiarity))
    if not partial:
        return None, {}, ""
    score = sum(partial.values()) / len(partial)
    note = ", ".join(f"{k} {v:.2f}" for k, v in partial.items())
    return score, partial, note


def _mean_distance(stats: Sequence[SentenceSyntaxStats]) -> float:
    distances = [float(d) for s in stats for d in s.dependency_distances]
    return mean(distances) if distances else 0.0


def _mapping(node: object) -> Mapping[str, object]:
    return node if isinstance(node, Mapping) else {}


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


__all__ = [
    "COORDINATION_TYPES",
    "SUBORDINATE_DEPS",
    "SUBORDINATE_TYPES",
    "SentenceSyntaxStats",
    "observe_sentence_syntax",
    "syntactic_profile",
    "syntactic_similarity",
    "unavailable_profile",
]
