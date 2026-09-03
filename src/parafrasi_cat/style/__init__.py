"""Anàlisi estilomètrica i perfils d'estil.

Un :class:`StyleProfile` descriu l'estil objectiu (longitud de frase,
connectors preferits, mots a evitar...). Les :class:`StyleMetrics` es
calculen sobre qualsevol text i el :class:`StyleEvaluator` mesura la
distància entre les mètriques d'un candidat i el perfil.

L'empremta estilística (:class:`StyleFingerprint`) és el resultat de
l'anàlisi del corpus d'un autor: un JSON explícit i editable que es
construeix amb :func:`build_fingerprint` (ordre ``parafrasi-cat style build``),
es compara amb :func:`compare_fingerprints` i es consulta amb
:class:`StylePreferences`. Tot es calcula amb regles i recomptes; no s'hi fa
servir cap model.
"""

from parafrasi_cat.style.compare import (
    ComparisonItem,
    FingerprintComparison,
    compare_fingerprints,
)
from parafrasi_cat.style.corpus import (
    Corpus,
    CorpusDocument,
    CorpusRole,
    ExcludedDocument,
    corpus_from_texts,
    load_corpus,
)
from parafrasi_cat.style.estimate import estimate_profile
from parafrasi_cat.style.evaluator import StyleDistance, StyleEvaluator
from parafrasi_cat.style.fingerprint import FeatureStat, StyleFingerprint
from parafrasi_cat.style.metrics import StyleMetrics, compute_style_metrics
from parafrasi_cat.style.observations import (
    DocumentObservations,
    DocumentObserver,
    StyleResources,
)
from parafrasi_cat.style.preferences import StylePreferences
from parafrasi_cat.style.profile import StyleProfile, load_style_profile
from parafrasi_cat.style.profiler import aggregate, build_fingerprint, observe_corpus

__all__ = [
    "ComparisonItem",
    "Corpus",
    "CorpusDocument",
    "CorpusRole",
    "DocumentObservations",
    "DocumentObserver",
    "ExcludedDocument",
    "FeatureStat",
    "FingerprintComparison",
    "StyleDistance",
    "StyleEvaluator",
    "StyleFingerprint",
    "StyleMetrics",
    "StylePreferences",
    "StyleProfile",
    "StyleResources",
    "aggregate",
    "build_fingerprint",
    "compare_fingerprints",
    "compute_style_metrics",
    "corpus_from_texts",
    "estimate_profile",
    "load_corpus",
    "load_style_profile",
    "observe_corpus",
]
