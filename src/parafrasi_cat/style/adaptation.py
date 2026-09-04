"""Adaptació autoral: afinitat d'un candidat amb l'empremta real de l'autor.

Quan l'usuari indica que el text és un **esborrany generat amb un LLM**, el
motor afegeix aquesta capa. No pregunta «això sembla humà?»: pregunta
«aquest candidat s'assembla més a la manera d'escriure d'*aquest* autor?».
La referència és sempre l'empremta local de l'autor, calculada a partir dels
seus textos; no hi ha cap model genèric de «text humà», cap detector, cap
probabilitat ni cap aleatorietat.

Tot el que es mesura és estadística descriptiva determinista:

- distribució de la longitud de frase (franges, mediana i, amb el doble de pes,
  dispersió), per preferir un ritme com el de l'autor abans que una regularitat
  uniforme;
- sobreús de connectors respecte del corpus i familiaritat de cada connector;
- densitat de comes, punts i coma, dos punts, parèntesis i incisos;
- estabilitat terminològica: si l'autor i el document repeteixen un terme,
  substituir-lo per un sinònim ornamental resta;
- construccions impersonals i passives.

Cada component és una semblança entre 0 i 1, només si l'empremta té prou
observacions per sustentar-lo. L'afinitat global és una mitjana ponderada.
Les característiques pròpies de la frase (franja de longitud, connectors,
puntuació, terminologia) es mesuren sobre el candidat mateix; les que només
tenen sentit sobre un text sencer (dispersió del ritme, construccions) es
mesuren sobre tot el document amb el candidat posat al seu lloc.

La puntuació del motor la fa servir com un bonus o una penalització
*relatius a l'original*: mai no pot compensar una pèrdua factual, un canvi
epistemològic ni un error gramatical, perquè aquests invaliden el candidat
abans que cap estil compti.

Amb una empremta de l'esquema 1.1 s'hi afegeixen dos components més:

- **ritme**: la seqüència de longituds del document sencer (amb el candidat al
  seu lloc) comparada amb el perfil de ritme de l'autor: franges, transicions,
  canvi absolut mitjà, variació i correlació de retard 1;
- **sintaxi**: coordinació, subordinació, ordre del subjecte i dels
  complements, distància de dependències, profunditat i clàusules per frase
  del document, i familiaritat del patró abstracte de cada frase del candidat.
  Necessita el parser local, que només analitza.

Cap dels dos no s'aplica si l'empremta els marca amb confiança baixa: amb
poques frases no s'inventa cap patró.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from parafrasi_cat.analyzer.analysis import Analyzer
from parafrasi_cat.analyzer.lexicon import normalize_form
from parafrasi_cat.style.observations import DocumentObserver, StyleResources
from parafrasi_cat.style.preferences import StylePreferences
from parafrasi_cat.style.rhythm import rhythm_similarity
from parafrasi_cat.style.statistics import iqr, median, relative_difference, total_variation
from parafrasi_cat.style.syntax_profile import (
    SentenceSyntaxStats,
    observe_sentence_syntax,
    syntactic_similarity,
)
from parafrasi_cat.syntax.analysis import SyntaxProvider

#: Pes de cada component dins de l'afinitat global.
COMPONENT_WEIGHTS: Mapping[str, float] = {
    "longitud": 1.5,
    "ritme": 1.5,
    "sintaxi": 2.0,
    "connectors": 2.0,
    "puntuacio": 1.0,
    "terminologia": 1.0,
    "construccions": 1.0,
}

#: Signes de puntuació que es comparen amb l'autor (per frase).
PUNCTUATION_MARKS: tuple[str, ...] = ("comma", "semicolon", "colon", "parenthesis", "dash")

#: Dispersió mínima (en paraules) amb què es mesura la desviació de la mediana.
_MIN_SPREAD = 4.0

#: Diferència mínima de component que val la pena explicar.
_MIN_DELTA = 0.005

_LABELS = {
    "longitud": "longitud de frases",
    "ritme": "ritme de frases",
    "sintaxi": "estructura sintàctica",
    "connectors": "connectors",
    "puntuacio": "puntuació",
    "terminologia": "terminologia",
    "construccions": "construccions",
}


@dataclass(frozen=True, slots=True)
class UnitStats:
    """Recomptes d'un tros de text, sumables per obtenir els de tot el document."""

    lengths: tuple[int, ...] = ()
    n_words: int = 0
    punctuation: tuple[tuple[str, int], ...] = ()
    connectors: tuple[str, ...] = ()
    impersonal: int = 0
    passive: int = 0
    content: tuple[str, ...] = ()
    tokens: tuple[int, ...] = ()
    """Tokens lingüístics per frase, en ordre (la unitat del perfil de ritme)."""
    syntax: tuple[SentenceSyntaxStats, ...] = ()
    """Recomptes sintàctics de cada frase analitzada amb fiabilitat (buit sense parser)."""

    @property
    def n_sentences(self) -> int:
        return len(self.lengths)

    def punctuation_count(self, mark: str) -> int:
        return dict(self.punctuation).get(mark, 0)

    def __add__(self, other: UnitStats) -> UnitStats:
        marks = Counter(dict(self.punctuation))
        marks.update(dict(other.punctuation))
        return UnitStats(
            lengths=self.lengths + other.lengths,
            n_words=self.n_words + other.n_words,
            punctuation=tuple(sorted(marks.items())),
            connectors=self.connectors + other.connectors,
            impersonal=self.impersonal + other.impersonal,
            passive=self.passive + other.passive,
            content=self.content + other.content,
            tokens=self.tokens + other.tokens,
            syntax=self.syntax + other.syntax,
        )

    @classmethod
    def total(cls, parts: Iterable[UnitStats]) -> UnitStats:
        result = cls()
        for part in parts:
            result = result + part
        return result


@dataclass(frozen=True, slots=True)
class AdaptationContext:
    """La resta del document, en ordre: el que hi ha abans i després de la unitat."""

    before: UnitStats = UnitStats()
    after: UnitStats = UnitStats()

    @property
    def others(self) -> UnitStats:
        return self.before + self.after

    def around(self, own: UnitStats) -> UnitStats:
        """El document sencer amb la unitat al seu lloc (les seqüències conserven l'ordre)."""
        return self.before + own + self.after


@dataclass(frozen=True, slots=True)
class AuthorAffinity:
    """Afinitat d'un text amb l'empremta: global, per components i amb notes."""

    score: float
    components: dict[str, float] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    partials: dict[str, dict[str, float]] = field(default_factory=dict)
    """Puntuacions parcials dels components compostos (ritme, sintaxi)."""

    @property
    def available(self) -> bool:
        return bool(self.components)

    @property
    def rhythm_similarity_score(self) -> float | None:
        return self.components.get("ritme")

    @property
    def syntactic_similarity_score(self) -> float | None:
        return self.components.get("sintaxi")

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "components": dict(self.components),
            "notes": dict(self.notes),
            "partials": {k: dict(v) for k, v in self.partials.items()},
        }


class AuthorAdaptation:
    """Mesura com s'assembla un text a la manera d'escriure d'un autor concret.

    Es construeix amb les preferències d'una empremta. Cada avaluació pot
    rebre el *context* (els recomptes de la resta del document) perquè les
    característiques de document —ritme, densitats— es mesurin sobre tot el
    text i no sobre una frase sola.
    """

    def __init__(
        self,
        preferences: StylePreferences,
        analyzer: Analyzer,
        resources: StyleResources,
        *,
        explicit_forms: Iterable[str] = (),
        syntax: SyntaxProvider | None = None,
    ) -> None:
        self._preferences = preferences
        self._analyzer = analyzer
        self._observer = DocumentObserver(resources)
        self._bins = resources.settings.sentence_length_bins
        self._explicit = frozenset(normalize_form(form) for form in explicit_forms)
        self._syntax = syntax if syntax is not None and syntax.available else None
        self._stats_cache: dict[str, UnitStats] = {}
        self._affinity_cache: dict[
            tuple[str, AdaptationContext | None, str | None], AuthorAffinity
        ] = {}
        self._stable_terms = self._author_terms()
        fingerprint = preferences.fingerprint
        rhythm = fingerprint.features.get("rhythm_profile")
        self._rhythm: Mapping[str, object] | None = (
            rhythm
            if fingerprint.has_rhythm_profile
            and isinstance(rhythm, Mapping)
            and rhythm.get("confidence") != "low"
            else None
        )
        syntactic = fingerprint.features.get("syntactic_profile")
        self._syntactic: Mapping[str, object] | None = (
            syntactic
            if fingerprint.has_syntactic_profile
            and isinstance(syntactic, Mapping)
            and syntactic.get("confidence") != "low"
            and self._syntax is not None
            else None
        )

    @property
    def preferences(self) -> StylePreferences:
        return self._preferences

    @property
    def name(self) -> str:
        return self._preferences.name

    def active_components(self) -> tuple[str, ...]:
        """Components que l'empremta pot sustentar (les altres no es mesuren)."""
        prefs = self._preferences
        active: list[str] = []
        if prefs.is_reliable("sentence_length_distribution"):
            active.append("longitud")
        if prefs.is_reliable("connectors.per_sentence"):
            active.append("connectors")
        if prefs.is_reliable("punctuation.comma.per_sentence"):
            active.append("puntuacio")
        if prefs.is_reliable("lexical_repetition.near_repetition"):
            active.append("terminologia")
        if prefs.is_reliable("impersonal.per_100_sentences") or prefs.is_reliable(
            "passive.per_100_sentences"
        ):
            active.append("construccions")
        if self._rhythm is not None:
            active.append("ritme")
        if self._syntactic is not None:
            active.append("sintaxi")
        return tuple(active)

    @property
    def uses_parser(self) -> bool:
        """Cert si el component sintàctic està actiu (empremta amb perfil i parser present)."""
        return self._syntactic is not None

    def describe(self) -> str:
        components = ", ".join(_LABELS[c] for c in self.active_components()) or "cap"
        return f"adaptació a l'empremta «{self.name}»: {components}"

    # -- recomptes -----------------------------------------------------------------------

    def stats_of(self, text: str) -> UnitStats:
        """Recomptes d'un text (frase, paràgraf o document), amb memòria cau."""
        cached = self._stats_cache.get(text)
        if cached is not None:
            return cached
        analysis = self._analyzer.analyze(text)
        observations = self._observer.observe(analysis)
        syntax: list[SentenceSyntaxStats] = []
        if self._syntax is not None:
            for sentence in analysis.sentences:
                parsed = observe_sentence_syntax(self._syntax.parse(sentence.text))
                if parsed is not None:
                    syntax.append(parsed)
        stats = UnitStats(
            lengths=tuple(observations.sentence_lengths),
            n_words=observations.n_words,
            punctuation=tuple(sorted(observations.punctuation.items())),
            connectors=tuple(hit.form for hit in observations.connectors),
            impersonal=len(observations.impersonal),
            passive=len(observations.passive),
            content=tuple(observations.content_tokens),
            tokens=tuple(observations.sentence_tokens),
            syntax=tuple(syntax),
        )
        self._stats_cache[text] = stats
        return stats

    # -- afinitat -------------------------------------------------------------------------

    def assess(
        self,
        text: str,
        *,
        context: AdaptationContext | None = None,
        source_text: str | None = None,
    ) -> AuthorAffinity:
        """Afinitat de ``text`` amb l'autor.

        ``context`` és la resta del document, en ordre, si n'hi ha;
        ``source_text`` és el tros original que el text substitueix, per
        mesurar la terminologia que conserva.
        """
        key = (text, context, source_text)
        cached = self._affinity_cache.get(key)
        if cached is not None:
            return cached
        own = self.stats_of(text)
        document = own if context is None else context.around(own)
        others = None if context is None else context.others
        components: dict[str, float] = {}
        notes: dict[str, str] = {}
        partials: dict[str, dict[str, float]] = {}
        self._length(own, document, components, notes)
        self._rhythm_component(document, components, notes, partials)
        self._syntax_component(own, document, components, notes, partials)
        self._connectors(own, components, notes)
        self._punctuation(own, components, notes)
        self._terminology(own, others, source_text, components, notes)
        self._constructions(document, components, notes)
        weight = sum(COMPONENT_WEIGHTS[name] for name in components)
        score = (
            sum(COMPONENT_WEIGHTS[name] * value for name, value in components.items()) / weight
            if weight
            else 0.0
        )
        result = AuthorAffinity(round(score, 4), components, notes, partials)
        self._affinity_cache[key] = result
        return result

    def rhythm_similarity(self, lengths: Sequence[int]) -> float | None:
        """Semblança de ritme (0-1) d'una seqüència de longituds amb l'autor, o ``None``."""
        if self._rhythm is None:
            return None
        score, _, _ = rhythm_similarity(lengths, self._rhythm)
        return score

    def syntactic_similarity(self, text: str) -> float | None:
        """Semblança sintàctica (0-1) d'un text amb l'autor, o ``None`` sense perfil o parser."""
        if self._syntactic is None:
            return None
        stats = self.stats_of(text).syntax
        score, _, _ = syntactic_similarity(stats, self._syntactic)
        return score

    def explain(self, candidate: AuthorAffinity, baseline: AuthorAffinity) -> str:
        """Per què el candidat s'assembla més (o menys) a l'autor que l'original."""
        parts: list[str] = []
        for name in COMPONENT_WEIGHTS:
            if name not in candidate.components or name not in baseline.components:
                continue
            delta = candidate.components[name] - baseline.components[name]
            if abs(delta) < _MIN_DELTA:
                continue
            detail = _dominant_partial(
                candidate.partials.get(name, {}), baseline.partials.get(name, {})
            )
            parts.append(f"{_reason(name, delta, detail)} ({delta:+.2f})")
        if not parts:
            return "cap diferència d'estil mesurable respecte de l'original"
        return "; ".join(parts)

    # -- ritme i sintaxi -------------------------------------------------------------------------

    def _rhythm_component(
        self,
        document: UnitStats,
        components: dict[str, float],
        notes: dict[str, str],
        partials: dict[str, dict[str, float]],
    ) -> None:
        if self._rhythm is None:
            return
        score, partial, note = rhythm_similarity(document.tokens, self._rhythm)
        if score is None:
            return
        components["ritme"] = round(score, 4)
        partials["ritme"] = partial
        notes["ritme"] = note

    def _syntax_component(
        self,
        own: UnitStats,
        document: UnitStats,
        components: dict[str, float],
        notes: dict[str, str],
        partials: dict[str, dict[str, float]],
    ) -> None:
        """Taxes sobre el document sencer; familiaritat del patró sobre la unitat."""
        if self._syntactic is None or not own.syntax:
            return
        _, document_partial, _ = syntactic_similarity(document.syntax, self._syntactic)
        _, own_partial, _ = syntactic_similarity(own.syntax, self._syntactic)
        partial = {k: v for k, v in document_partial.items() if k != "patrons"}
        if "patrons" in own_partial:
            partial["patrons"] = own_partial["patrons"]
        if not partial:
            return
        components["sintaxi"] = round(sum(partial.values()) / len(partial), 4)
        partials["sintaxi"] = partial
        notes["sintaxi"] = ", ".join(f"{k} {v:.2f}" for k, v in partial.items())

    # -- components -------------------------------------------------------------------------

    def _length(
        self,
        own: UnitStats,
        document: UnitStats,
        components: dict[str, float],
        notes: dict[str, str],
    ) -> None:
        prefs = self._preferences
        if not prefs.is_reliable("sentence_length_distribution") or not own.lengths:
            return
        node = prefs.fingerprint.get("sentence_length_distribution")
        if not isinstance(node, Mapping):
            return
        lengths = [float(n) for n in own.lengths]
        author_median = _number(node.get("median"))
        author_spread = _number(node.get("iqr"))
        raw = node.get("shares")
        reference = (
            {
                str(k): float(v)
                for k, v in raw.items()
                if isinstance(v, int | float) and not isinstance(v, bool)
            }
            if isinstance(raw, Mapping)
            else {}
        )
        weighted: list[tuple[float, float]] = []  # (puntuació, pes)
        details: list[str] = []
        if reference and self._bins:
            if len(lengths) >= 3:
                # Distribució de franges del tros sencer contra la de l'autor: un text
                # amb totes les frases a la mateixa franja s'allunya d'un autor que les
                # reparteix, encara que la franja sigui la seva més habitual.
                similarity = 1.0 - total_variation(_bucket_shares(lengths, self._bins), reference)
                weighted.append((similarity, 1.0))
                details.append(f"franges {similarity:.2f}")
            else:
                # Amb una o dues frases no hi ha distribució: es mira si cada frase cau
                # en una franja habitual de l'autor.
                top = max(reference.values(), default=0.0)
                if top > 0:
                    typical = [reference.get(_bucket(n, self._bins), 0.0) / top for n in lengths]
                    weighted.append((sum(typical) / len(typical), 1.0))
                    details.append(f"franja habitual {sum(typical) / len(typical):.2f}")
        if author_median is not None:
            spread = max(author_spread or 0.0, _MIN_SPREAD)
            weighted.append((1.0 - _clip(abs(median(lengths) - author_median) / spread), 1.0))
            details.append(f"mediana {median(lengths):.0f} (autor {author_median:.0f})")
        rhythm_source = lengths if len(lengths) >= 3 else [float(n) for n in document.lengths]
        if author_spread is not None and len(rhythm_source) >= 3:
            # Ritme: una successió de frases d'igual longitud té una dispersió quasi
            # nul·la; si l'autor alterna, això l'allunya de l'empremta. Pesa el doble.
            spread_here = iqr(rhythm_source)
            weighted.append((1.0 - relative_difference(spread_here, author_spread), 2.0))
            details.append(f"dispersió {spread_here:.0f} (autor {author_spread:.0f})")
        if not weighted:
            return
        total_weight = sum(weight for _, weight in weighted)
        components["longitud"] = round(
            sum(score * weight for score, weight in weighted) / total_weight, 4
        )
        notes["longitud"] = ", ".join(details)

    def _connectors(
        self, own: UnitStats, components: dict[str, float], notes: dict[str, str]
    ) -> None:
        prefs = self._preferences
        author_rate = prefs.rate("connectors.per_sentence")
        if author_rate is None or not own.n_sentences:
            return
        rate = len(own.connectors) / own.n_sentences
        excess = max(0.0, rate - author_rate)
        scores = [1.0 - _clip(excess / max(author_rate, 0.5))]
        familiarity: list[float] = []
        for form in own.connectors:
            if normalize_form(form) in self._explicit:
                continue  # una preferència explícita mana sobre l'empremta
            share = prefs.connector_share(form)
            if share is not None:
                familiarity.append(share)
        if familiarity:
            scores.append(sum(familiarity) / len(familiarity))
        components["connectors"] = round(sum(scores) / len(scores), 4)
        notes["connectors"] = f"{rate:.2f} connectors per frase (autor {author_rate:.2f})" + (
            f"; familiaritat {sum(familiarity) / len(familiarity):.2f}" if familiarity else ""
        )

    def _punctuation(
        self, own: UnitStats, components: dict[str, float], notes: dict[str, str]
    ) -> None:
        prefs = self._preferences
        if not prefs.is_reliable("punctuation.comma.per_sentence") or not own.n_sentences:
            return
        scores: list[float] = []
        details: list[str] = []
        for mark in PUNCTUATION_MARKS:
            author = prefs.fingerprint.value(f"punctuation.{mark}.per_sentence") or 0.0
            rate = own.punctuation_count(mark) / own.n_sentences
            scores.append(1.0 - _clip(abs(author - rate) / max(author, 1.0)))
            if author or rate:
                details.append(f"{mark} {rate:.2f}/{author:.2f}")
        components["puntuacio"] = round(sum(scores) / len(scores), 4)
        notes["puntuacio"] = "per frase (text/autor): " + ", ".join(details)

    def _terminology(
        self,
        own: UnitStats,
        context: UnitStats | None,
        source_text: str | None,
        components: dict[str, float],
        notes: dict[str, str],
    ) -> None:
        if source_text is None or not self._preferences.is_reliable(
            "lexical_repetition.near_repetition"
        ):
            return
        source = self.stats_of(source_text)
        repeated = Counter(source.content)
        if context is not None:
            repeated.update(context.content)
        stable = self._stable_terms | {form for form, n in repeated.items() if n >= 2}
        present = stable & set(source.content)
        if not present:
            return
        kept = present & set(own.content)
        removed = present - kept
        components["terminologia"] = round(len(kept) / len(present), 4)
        notes["terminologia"] = f"conserva {len(kept)} de {len(present)} termes estables" + (
            f"; substitueix «{'», «'.join(sorted(removed))}»" if removed else ""
        )

    def _constructions(
        self, document: UnitStats, components: dict[str, float], notes: dict[str, str]
    ) -> None:
        prefs = self._preferences
        if not document.n_sentences:
            return
        scores: list[float] = []
        details: list[str] = []
        for label, author, count in (
            ("impersonals", prefs.rate("impersonal.per_100_sentences"), document.impersonal),
            ("passives", prefs.rate("passive.per_100_sentences"), document.passive),
        ):
            if author is None:
                continue
            rate = count / document.n_sentences * 100
            scores.append(1.0 - _clip(abs(author - rate) / max(author, 50.0)))
            details.append(f"{label} {rate:.0f}/{author:.0f}")
        if not scores:
            return
        components["construccions"] = round(sum(scores) / len(scores), 4)
        notes["construccions"] = "per 100 frases (text/autor): " + ", ".join(details)

    # -- auxiliars ----------------------------------------------------------------------------

    def _author_terms(self) -> frozenset[str]:
        """Termes que l'autor repeteix al seu corpus (``lexical_repetition.top_words``)."""
        node = self._preferences.fingerprint.get("lexical_repetition.top_words")
        if not isinstance(node, list):
            return frozenset()
        forms: set[str] = set()
        for item in node:
            if not isinstance(item, Mapping):
                continue
            documents = item.get("documents", 0)
            count = item.get("count", 0)
            if (
                isinstance(documents, int)
                and isinstance(count, int)
                and (documents >= 2 or count >= 3)
            ):
                forms.add(normalize_form(str(item.get("form", ""))))
        forms.discard("")
        return frozenset(forms)


_SYNTAX_REASONS = {
    "subordinacio": "estructura de subordinació més semblant",
    "coordinacio": "coordinació més semblant a la del teu corpus",
    "complements": "ordre dels complements més habitual en el teu corpus",
    "ordre_subjecte": "ordre del subjecte més habitual en el teu corpus",
    "patrons": "patrons de frase més habituals en el teu corpus",
    "distancia": "distància de dependències més semblant",
    "profunditat": "profunditat sintàctica més semblant",
    "clausules": "nombre de clàusules més semblant",
}
_RHYTHM_REASONS = {
    "variacio": "menys uniformitat de longitud",
    "franges": "proporció de frases curtes, mitjanes i llargues més propera",
    "transicions": "alternança de longituds més propera",
    "canvi": "canvis de longitud entre frases més semblants",
    "retard": "alternança de longituds més propera",
}


def _dominant_partial(candidate: Mapping[str, float], baseline: Mapping[str, float]) -> str:
    """Parcial que més ha canviat entre l'original i el candidat (buit si cap)."""
    deltas = {k: candidate[k] - baseline[k] for k in candidate if k in baseline}
    if not deltas:
        return ""
    return max(deltas, key=lambda k: (abs(deltas[k]), k))


def _reason(name: str, delta: float, detail: str = "") -> str:
    better = delta > 0
    if name == "ritme":
        if better and detail in _RHYTHM_REASONS:
            return _RHYTHM_REASONS[detail]
        return "ritme de frases " + ("més" if better else "menys") + " proper a la teva empremta"
    if name == "sintaxi":
        if better and detail in _SYNTAX_REASONS:
            return _SYNTAX_REASONS[detail]
        return (
            "estructura sintàctica "
            + ("més" if better else "menys")
            + " semblant a la del teu corpus"
        )
    if name == "longitud":
        return "longitud de frases " + ("més" if better else "menys") + " propera a l'empremta"
    if name == "connectors":
        return (
            "menys sobreús de connectors, o connectors més propis de l'autor"
            if better
            else "més connectors dels que fa servir l'autor, o menys habituals"
        )
    if name == "puntuacio":
        return "puntuació " + ("més" if better else "menys") + " semblant a la de l'autor"
    if name == "terminologia":
        return (
            "recupera terminologia estable"
            if better
            else "substitueix terminologia que l'autor manté"
        )
    return "construccions " + ("més" if better else "menys") + " pròximes al corpus"


def _bucket_shares(
    lengths: Sequence[float], bins: Sequence[tuple[int, int | None]]
) -> dict[str, float]:
    """Proporció de frases de cada franja de longitud (les mateixes que l'empremta)."""
    counts = {
        (f"{low}-{high}" if high is not None else f"{low}+"): sum(
            1 for n in lengths if n >= low and (high is None or n <= high)
        )
        for low, high in bins
    }
    total = sum(counts.values())
    return {key: (value / total if total else 0.0) for key, value in counts.items()}


def _bucket(length: float, bins: Sequence[tuple[int, int | None]]) -> str:
    """Etiqueta de la franja de longitud on cau una frase (com a l'empremta)."""
    for low, high in bins:
        if length >= low and (high is None or length <= high):
            return f"{low}-{high}" if high is not None else f"{low}+"
    return ""


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


__all__ = [
    "COMPONENT_WEIGHTS",
    "PUNCTUATION_MARKS",
    "AdaptationContext",
    "AuthorAdaptation",
    "AuthorAffinity",
    "UnitStats",
]
