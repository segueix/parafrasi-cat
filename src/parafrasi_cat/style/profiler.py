"""Construcció de l'empremta estilística a partir d'un corpus.

Recorre els documents, n'extreu les :class:`DocumentObservations` i les
agrega amb estadístics robustos (mediana, MAD, pesos limitats per
document) perquè cap text excepcional domini el perfil.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path

from parafrasi_cat.analyzer.analysis import Analyzer
from parafrasi_cat.core.errors import ResourceError
from parafrasi_cat.style.corpus import Corpus, CorpusDocument
from parafrasi_cat.style.fingerprint import SCHEMA_VERSION, FeatureStat, StyleFingerprint
from parafrasi_cat.style.observations import (
    DocumentObservations,
    DocumentObserver,
    StyleResources,
    StyleSettings,
    VariantGroup,
)
from parafrasi_cat.style.statistics import (
    confidence,
    iqr,
    mad,
    mean,
    median,
    percentile,
    robust_average,
    robust_location,
    robust_rate,
    shares,
)

#: Proporció mínima i observacions mínimes per declarar una variant «preferida».
PREFERRED_MIN_SHARE = 0.6
PREFERRED_MIN_OBSERVATIONS = 5

#: Distància a partir de la qual una característica del corpus de validació es
#: considera divergent respecte del corpus principal.
VALIDATION_DIVERGENCE = 0.4

_APPROXIMATE_FACTOR = 0.6
_PUNCTUATION_KEYS = (
    "comma",
    "semicolon",
    "colon",
    "parenthesis",
    "dash",
    "quote",
    "question",
    "exclamation",
    "ellipsis",
)
_METHOD = (
    "recomptes deterministes basats en regles i llistes editables; "
    "estadístics robustos (mediana ponderada a partir de cinc documents, mitjana amb pesos "
    "limitats amb menys, desviació absoluta mediana entre documents)"
)


def observe_corpus(
    documents: Iterable[CorpusDocument], resources: StyleResources, analyzer: Analyzer
) -> list[DocumentObservations]:
    observer = DocumentObserver(resources)
    return [observer.observe(analyzer.analyze(doc.text), doc.name) for doc in documents]


def build_fingerprint(
    corpus: Corpus,
    resources: StyleResources,
    analyzer: Analyzer,
    *,
    name: str = "autor",
    description: str = "",
    language: str = "ca",
) -> StyleFingerprint:
    """Construeix l'empremta del corpus principal i, si n'hi ha, valida amb el de validació."""
    main_documents = corpus.main
    if not main_documents:
        raise ResourceError("El corpus principal no conté cap document amb text")
    main = observe_corpus(main_documents, resources, analyzer)
    features = aggregate(main, resources.settings, resources.variant_groups)
    fingerprint = StyleFingerprint(
        name=name,
        description=description,
        language=language,
        generator=_generator(main_documents),
        corpus=_corpus_summary(main_documents, main, corpus),
        features=features,
        validation=None,
        schema_version=SCHEMA_VERSION,
    )
    validation_documents = corpus.validation
    if not validation_documents:
        return fingerprint
    validation = observe_corpus(validation_documents, resources, analyzer)
    validation_fingerprint = StyleFingerprint(
        name=f"{name} (validació)",
        description="",
        language=language,
        generator=_generator(validation_documents),
        corpus=_corpus_summary(validation_documents, validation, None),
        features=aggregate(validation, resources.settings, resources.variant_groups),
    )
    from parafrasi_cat.style.compare import compare_fingerprints

    comparison = compare_fingerprints(fingerprint, validation_fingerprint)
    divergent = [
        item.path
        for item in sorted(comparison.items, key=lambda i: (-i.distance, i.path))
        if item.weight > 0 and item.distance >= VALIDATION_DIVERGENCE
    ]
    validation_section: dict[str, object] = {
        "n_documents": len(validation_documents),
        "n_sentences": sum(o.n_sentences for o in validation),
        "n_words": sum(o.n_words for o in validation),
        "documents": _document_entries(validation_documents, validation),
        "distance": comparison.distance,
        "divergence_threshold": VALIDATION_DIVERGENCE,
        "divergent_features": divergent,
        "feature_distances": {
            item.path: item.distance for item in comparison.items if item.weight > 0
        },
    }
    return StyleFingerprint(
        name=fingerprint.name,
        description=fingerprint.description,
        language=fingerprint.language,
        generator=fingerprint.generator,
        corpus=fingerprint.corpus,
        features=fingerprint.features,
        validation=validation_section,
        schema_version=SCHEMA_VERSION,
    )


def _generator(documents: Sequence[CorpusDocument]) -> dict[str, object]:
    from parafrasi_cat import __version__

    digest = hashlib.sha256("\n".join(d.sha256 for d in documents).encode("utf-8")).hexdigest()
    return {
        "tool": "parafrasi-cat",
        "version": __version__,
        "method": _METHOD,
        "deterministic": True,
        "uses_models": False,
        "corpus_hash": digest[:12],
    }


def _document_entries(
    documents: Sequence[CorpusDocument], observations: Sequence[DocumentObservations]
) -> list[dict[str, object]]:
    return [
        {
            "name": doc.name,
            "role": doc.role.value,
            "sha256": doc.sha256,
            "paragraphs": obs.n_paragraphs,
            "sentences": obs.n_sentences,
            "words": obs.n_words,
        }
        for doc, obs in zip(documents, observations, strict=True)
    ]


def _corpus_summary(
    documents: Sequence[CorpusDocument],
    observations: Sequence[DocumentObservations],
    corpus: Corpus | None,
) -> dict[str, object]:
    root = corpus.root if corpus is not None else None
    return {
        "root": None if root is None else Path(root).as_posix(),
        "n_documents": len(documents),
        "n_paragraphs": sum(o.n_paragraphs for o in observations),
        "n_sentences": sum(o.n_sentences for o in observations),
        "n_words": sum(o.n_words for o in observations),
        "documents": _document_entries(documents, observations),
        "excluded": [e.to_dict() for e in corpus.excluded] if corpus is not None else [],
    }


# --- Agregació ----------------------------------------------------------------------


def aggregate(
    observations: Sequence[DocumentObservations],
    settings: StyleSettings,
    variant_groups: Sequence[VariantGroup] = (),
) -> dict[str, object]:
    """Agrega les observacions de tots els documents en el diccionari ``features``."""
    if not observations:
        raise ResourceError("No hi ha observacions per agregar")
    features: dict[str, object] = {}
    features["sentence_length"] = _sentence_length(observations)
    features["sentence_length_distribution"] = _sentence_distribution(observations, settings)
    features["paragraph_length_sentences"] = _stat(
        robust_location([o.paragraph_sentences for o in observations]), "frases per paràgraf"
    )
    features["paragraph_length_words"] = _stat(
        robust_location([o.paragraph_words for o in observations]), "paraules per paràgraf"
    )
    features["punctuation"] = _punctuation(observations)
    features["connectors"] = _connectors(observations, settings)
    features["recurrent_expressions"] = _recurrent_expressions(observations, settings)
    features["impersonal"] = _impersonal(observations, settings)
    features["first_person"] = _first_person(observations, settings)
    features["passive"] = _passive(observations, settings)
    features["lexical_repetition"] = _lexical_repetition(observations, settings)
    features["word_class_density"] = _word_classes(observations)
    features["variant_preferences"] = _variants(observations, variant_groups, settings)
    return features


def _stat(summary: object, unit: str, **kwargs: object) -> dict[str, object]:
    from parafrasi_cat.style.statistics import RobustSummary

    assert isinstance(summary, RobustSummary)
    examples = kwargs.get("examples", ())
    note = kwargs.get("note", "")
    factor = kwargs.get("confidence_factor", 1.0)
    assert isinstance(examples, tuple) and isinstance(note, str) and isinstance(factor, float)
    return FeatureStat.from_summary(
        summary, unit, examples=examples, note=note, confidence_factor=factor
    ).to_dict()


def _sentence_length(observations: Sequence[DocumentObservations]) -> dict[str, object]:
    return _stat(
        robust_location([o.sentence_lengths for o in observations]),
        "paraules per frase (sense clítics)",
    )


def _sentence_distribution(
    observations: Sequence[DocumentObservations], settings: StyleSettings
) -> dict[str, object]:
    lengths = [float(n) for o in observations for n in o.sentence_lengths]
    counts: dict[str, int] = {}
    for low, high in settings.sentence_length_bins:
        label = f"{low}-{high}" if high is not None else f"{low}+"
        counts[label] = sum(1 for n in lengths if n >= low and (high is None or n <= high))
    return {
        "unit": "proporció de frases",
        "n_observations": len(lengths),
        "n_documents": sum(1 for o in observations if o.sentence_lengths),
        "confidence": confidence(len(lengths), sum(1 for o in observations if o.sentence_lengths)),
        "mean": mean(lengths),
        "median": median(lengths),
        "mad": mad(lengths),
        "iqr": iqr(lengths),
        "p10": percentile(lengths, 10),
        "p90": percentile(lengths, 90),
        "min": min(lengths) if lengths else 0.0,
        "max": max(lengths) if lengths else 0.0,
        "counts": counts,
        "shares": shares({k: float(v) for k, v in counts.items()}),
    }


def _rate_stat(
    observations: Sequence[DocumentObservations],
    counts: Sequence[float],
    denominator: str,
    unit: str,
    *,
    examples: tuple[str, ...] = (),
    note: str = "",
    confidence_factor: float = 1.0,
) -> dict[str, object]:
    if denominator == "words":
        denominators = [float(o.n_words) for o in observations]
        scale = 100.0
    elif denominator == "sentences":
        denominators = [float(o.n_sentences) for o in observations]
        scale = 100.0 if unit.startswith("per 100") else 1.0
    elif denominator == "content":
        denominators = [float(o.n_content_words) for o in observations]
        scale = 100.0
    else:  # pragma: no cover - ús intern
        raise ValueError(denominator)
    return _stat(
        robust_rate(list(counts), denominators, scale),
        unit,
        examples=examples,
        note=note,
        confidence_factor=confidence_factor,
    )


def _punctuation(observations: Sequence[DocumentObservations]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key in _PUNCTUATION_KEYS:
        counts = [float(o.punctuation.get(key, 0)) for o in observations]
        result[key] = {
            "per_100_words": _rate_stat(observations, counts, "words", "per 100 paraules"),
            "per_sentence": _rate_stat(observations, counts, "sentences", "per frase"),
        }
    comma_bins: Counter[str] = Counter()
    for o in observations:
        for n in o.commas_per_sentence:
            comma_bins["3+" if n >= 3 else str(n)] += 1
    endings: Counter[str] = Counter()
    for o in observations:
        endings.update(o.sentence_endings)
    result["commas_per_sentence_shares"] = shares(
        {k: float(comma_bins.get(k, 0)) for k in ("0", "1", "2", "3+")}
    )
    result["sentence_endings_shares"] = shares(
        {
            k: float(endings.get(k, 0))
            for k in ("period", "question", "exclamation", "ellipsis", "none")
        }
    )
    return result


def _examples(items: Iterable[str], limit: int) -> tuple[str, ...]:
    chosen: list[str] = []
    for item in items:
        if item and item not in chosen:
            chosen.append(item)
        if len(chosen) >= limit:
            break
    return tuple(chosen)


def _connectors(
    observations: Sequence[DocumentObservations], settings: StyleSettings
) -> dict[str, object]:
    limit = settings.examples_per_feature
    counts = [float(len(o.connectors)) for o in observations]
    all_hits = [hit for o in observations for hit in o.connectors]
    positions = Counter(hit.position for hit in all_hits)
    initial = [hit for hit in all_hits if hit.position == "initial"]
    functions = Counter(hit.function or "altres" for hit in all_hits)
    registers = Counter(hit.register or "desconegut" for hit in all_hits)
    by_form: Counter[str] = Counter(hit.form for hit in all_hits)
    docs_by_form: dict[str, set[str]] = {}
    for o in observations:
        for hit in o.connectors:
            docs_by_form.setdefault(hit.form, set()).add(o.name)
    total_words = sum(o.n_words for o in observations)
    top: list[dict[str, object]] = []
    for form, count in sorted(by_form.items(), key=lambda item: (-item[1], item[0]))[:20]:
        hits = [hit for hit in all_hits if hit.form == form]
        top.append(
            {
                "form": form,
                "function": hits[0].function or "altres",
                "register": hits[0].register or "desconegut",
                "count": count,
                "share": count / len(all_hits) if all_hits else 0.0,
                "share_in_function": count / functions[hits[0].function or "altres"],
                "per_100_words": count / total_words * 100 if total_words else 0.0,
                "documents": len(docs_by_form[form]),
                "positions": shares(
                    {k: float(v) for k, v in Counter(h.position for h in hits).items()}
                ),
                "examples": list(_examples((h.example for h in hits), limit)),
            }
        )
    return {
        "per_100_words": _rate_stat(
            observations,
            counts,
            "words",
            "per 100 paraules",
            examples=_examples((h.example for h in all_hits), limit),
        ),
        "per_sentence": _rate_stat(observations, counts, "sentences", "per frase"),
        "position_shares": shares(
            {k: float(positions.get(k, 0)) for k in ("initial", "medial", "final")}
        ),
        "initial_with_comma_share": (
            sum(1 for hit in initial if hit.with_comma) / len(initial) if initial else None
        ),
        "by_function_shares": shares({k: float(v) for k, v in sorted(functions.items())}),
        "by_register_shares": shares({k: float(v) for k, v in sorted(registers.items())}),
        "top": top,
    }


def _recurrent_expressions(
    observations: Sequence[DocumentObservations], settings: StyleSettings
) -> dict[str, object]:
    total: Counter[str] = Counter()
    documents: Counter[str] = Counter()
    examples: dict[str, str] = {}
    for o in observations:
        total.update(o.ngrams)
        for text in o.ngrams:
            documents[text] += 1
            examples.setdefault(text, o.ngram_examples.get(text, ""))
    min_documents = min(settings.ngram_min_documents, len(observations))
    kept = {
        text: count
        for text, count in total.items()
        if count >= settings.ngram_min_count and documents[text] >= min_documents
    }
    # Un n-grama contingut en un de més llarg amb el mateix recompte és redundant.
    redundant: set[str] = set()
    for text, count in kept.items():
        for other, other_count in kept.items():
            if other != text and len(other) > len(text) and text in other and other_count == count:
                redundant.add(text)
                break
    total_words = sum(o.n_words for o in observations)
    ordered = sorted(
        ((t, c) for t, c in kept.items() if t not in redundant),
        key=lambda item: (-item[1], -len(item[0].split()), item[0]),
    )[: settings.ngram_max_items]
    return {
        "unit": "aparicions al corpus",
        "min_count": settings.ngram_min_count,
        "min_documents": min_documents,
        "n_observations": sum(c for _, c in ordered),
        "n_documents": len(observations),
        "confidence": confidence(sum(c for _, c in ordered), len(observations)),
        "items": [
            {
                "text": text,
                "count": count,
                "documents": documents[text],
                "per_100_words": count / total_words * 100 if total_words else 0.0,
                "example": examples.get(text, ""),
            }
            for text, count in ordered
        ],
    }


def _impersonal(
    observations: Sequence[DocumentObservations], settings: StyleSettings
) -> dict[str, object]:
    limit = settings.examples_per_feature
    all_hits = [hit for o in observations for hit in o.impersonal]
    counts = [float(len(o.impersonal)) for o in observations]
    total_sentences = sum(o.n_sentences for o in observations)
    kinds = Counter(hit.kind for hit in all_hits)
    by_type = {
        kind: {
            "count": count,
            "share": count / len(all_hits) if all_hits else 0.0,
            "per_100_sentences": count / total_sentences * 100 if total_sentences else 0.0,
            "examples": list(_examples((h.example for h in all_hits if h.kind == kind), limit)),
        }
        for kind, count in sorted(kinds.items(), key=lambda item: (-item[1], item[0]))
    }
    return {
        "per_100_sentences": _rate_stat(
            observations,
            counts,
            "sentences",
            "per 100 frases",
            examples=_examples((h.example for h in all_hits), limit),
            note=(
                "«es + verb» inclou les construccions reflexes de tercera persona; "
                "les altres estructures es detecten per llistes de formes"
            ),
        ),
        "by_type": by_type,
    }


def _first_person(
    observations: Sequence[DocumentObservations], settings: StyleSettings
) -> dict[str, object]:
    limit = settings.examples_per_feature
    result: dict[str, object] = {}
    for kind in ("singular", "plural"):
        hits = [hit for o in observations for hit in o.first_person if hit.kind == kind]
        counts = [float(sum(1 for h in o.first_person if h.kind == kind)) for o in observations]
        sure = sum(1 for h in hits if h.extra == "sure")
        approximate = len(hits) - sure
        factor = 1.0 if not hits else (sure + _APPROXIMATE_FACTOR * approximate) / len(hits)
        result[kind] = {
            "per_100_sentences": _rate_stat(
                observations,
                counts,
                "sentences",
                "per 100 frases",
                examples=_examples((h.example for h in hits), limit),
                note="pronoms i possessius segurs; formes verbals per terminació (aproximades)",
                confidence_factor=round(factor, 3),
            ),
            "n_sure": sure,
            "n_approximate": approximate,
        }
    return result


def _passive(
    observations: Sequence[DocumentObservations], settings: StyleSettings
) -> dict[str, object]:
    limit = settings.examples_per_feature
    sure = [hit for o in observations for hit in o.passive if hit.kind == "sure"]
    ambiguous = [hit for o in observations for hit in o.passive if hit.kind != "sure"]
    counts = [float(sum(1 for h in o.passive if h.kind == "sure")) for o in observations]
    return {
        "per_100_sentences": _rate_stat(
            observations,
            counts,
            "sentences",
            "per 100 frases",
            examples=_examples((h.example for h in sure), limit),
            note=(
                "passiva perifràstica detectada amb confiança: auxiliar «ser» no present, "
                "«ha estat» + participi, o participi amb complement agent"
            ),
        ),
        "with_agent_count": sum(1 for h in sure if h.extra == "agent"),
        "ambiguous_present_count": len(ambiguous),
        "ambiguous_examples": list(_examples((h.example for h in ambiguous), limit)),
    }


def _lexical_repetition(
    observations: Sequence[DocumentObservations], settings: StyleSettings
) -> dict[str, object]:
    sizes = [float(o.n_content_words) for o in observations]
    ttr: list[float] = []
    msttr: list[float] = []
    hapax: list[float] = []
    near: list[float] = []
    for o in observations:
        tokens = o.content_tokens
        if not tokens:
            ttr.append(0.0)
            msttr.append(0.0)
            hapax.append(0.0)
            near.append(0.0)
            continue
        counter = Counter(tokens)
        ttr.append(len(counter) / len(tokens))
        hapax.append(sum(1 for c in counter.values() if c == 1) / len(counter))
        segment = settings.segment_size
        segments = [tokens[i : i + segment] for i in range(0, len(tokens), segment)]
        segments = [s for s in segments if len(s) >= segment // 2] or [tokens]
        msttr.append(mean([len(set(s)) / len(s) for s in segments]))
        window = settings.near_window
        repeated = sum(1 for i, t in enumerate(tokens) if t in tokens[max(0, i - window) : i])
        near.append(repeated / len(tokens))
    total: Counter[str] = Counter()
    docs: Counter[str] = Counter()
    for o in observations:
        total.update(o.content_tokens)
        docs.update(set(o.content_tokens))
    total_content = sum(total.values())
    top_words = [
        {
            "form": form,
            "count": count,
            "per_100_content_words": count / total_content * 100 if total_content else 0.0,
            "documents": docs[form],
        }
        for form, count in sorted(total.items(), key=lambda item: (-item[1], item[0]))[
            : settings.top_words
        ]
    ]
    return {
        "type_token_ratio": _stat(
            robust_average(ttr, sizes),
            "formes diferents / paraules de contingut",
            note="depèn de la mida del document; vegeu msttr",
        ),
        "msttr": _stat(
            robust_average(msttr, sizes),
            f"TTR mitjana per segments de {settings.segment_size} paraules de contingut",
        ),
        "hapax_share": _stat(robust_average(hapax, sizes), "formes que apareixen un sol cop"),
        "near_repetition": _stat(
            robust_average([n * 100 for n in near], sizes),
            f"per 100 paraules de contingut (repetides dins de {settings.near_window} paraules)",
        ),
        "top_words": top_words,
    }


def _word_classes(observations: Sequence[DocumentObservations]) -> dict[str, object]:
    note = "aproximat: per lexicó de classes tancades, terminacions i context immediat"
    result: dict[str, object] = {}
    for key, label in (
        ("verb", "verbs_per_100_words"),
        ("noun", "nouns_per_100_words"),
        ("function", "function_words_per_100_words"),
    ):
        counts = [float(o.word_classes.get(key, 0)) for o in observations]
        result[label] = _rate_stat(
            observations,
            counts,
            "words",
            "per 100 paraules",
            note=note,
            confidence_factor=_APPROXIMATE_FACTOR,
        )
    return result


def _variants(
    observations: Sequence[DocumentObservations],
    groups: Sequence[VariantGroup],
    settings: StyleSettings,
) -> dict[str, object]:
    limit = settings.examples_per_feature
    result: dict[str, object] = {}
    for group in groups:
        counts: Counter[str] = Counter()
        docs: Counter[str] = Counter()
        examples: dict[str, list[str]] = {}
        docs_with_any = 0
        for o in observations:
            found = o.variants.get(group.id, {})
            if found:
                docs_with_any += 1
            for variant_id, items in found.items():
                counts[variant_id] += len(items)
                docs[variant_id] += 1
                examples.setdefault(variant_id, []).extend(items)
        total = sum(counts.values())
        variant_shares = shares({v: float(counts.get(v, 0)) for v in group.variant_ids})
        preferred: str | None = None
        if total >= PREFERRED_MIN_OBSERVATIONS:
            best = max(
                group.variant_ids, key=lambda v: (variant_shares[v], -group.variant_ids.index(v))
            )
            if variant_shares[best] >= PREFERRED_MIN_SHARE:
                preferred = best
        result[group.id] = {
            "description": group.description,
            "n_observations": total,
            "n_documents": docs_with_any,
            "confidence": confidence(total, docs_with_any),
            "preferred": preferred,
            "variants": {
                variant_id: {
                    "count": counts.get(variant_id, 0),
                    "share": variant_shares[variant_id],
                    "documents": docs.get(variant_id, 0),
                    "examples": list(_examples(examples.get(variant_id, []), limit)),
                }
                for variant_id in group.variant_ids
            },
        }
    return result
