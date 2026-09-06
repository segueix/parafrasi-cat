"""Generació de múltiples candidats a partir de les transformacions proposades.

Estratègia:

1. Sempre s'inclou el candidat identitat.
2. Cada transformació proposada genera un candidat amb només aquest canvi.
3. Les transformacions compatibles (no solapades) es combinen fins a
   ``max_transformations`` per candidat.
4. Opcionalment (``max_depth`` ≥ 2), els millors candidats es reanalitzen i
   les regles s'hi tornen a aplicar (``expand``): les noves transformacions es
   reprojecten sobre el text original o s'encadenen amb la transformació que
   va produir el segment afectat.

Garanties: els candidats es dedupliquen pel text (i pel text normalitzat,
per no oferir dos candidats gairebé idèntics), es descarten els que superen
``max_change_ratio`` i mai no s'aplica la mateixa regla dues vegades sobre el
mateix segment.

Diversitat: la generació treballa sobre una reserva més ampla que el límit de
candidats, i la selecció final conserva primer el millor candidat de cada
signatura estructural (``REORDER``, ``CLAUSE_SPLIT``, ``COPULAR_MERGE``,
``MULTI_TRANSFORM(...)``...) abans d'omplir amb la resta. Així un canvi
sintàctic no queda fora per culpa de vint variants lèxiques, i el límit de
transformacions per candidat continua acotant la combinatòria.

Pressupostos explícits (per no ofegar la reredacció estructural):

- La reserva base (``pool_limit``) l'omplen les transformacions soltes i les
  seves combinacions. Amb moltes variants superficials s'omple sencera.
- L'expansió de segon nivell té un **pressupost propi** (``expansion_budget``)
  per damunt d'aquesta reserva: encara que les combinacions inicials la
  saturin, sempre queda marge per reaplicar regles sobre els millors candidats.
  Sense això, un text amb prou retocs lèxics deixava el segon nivell sense cap
  crida.
- El feix d'expansió s'ordena per **diversitat estructural** (grau estructural,
  després confiança acumulada, després ordre de generació) i reserva un lloc a
  cada signatura abans de repetir-ne cap: una reordenació prometedora ja no
  queda fora del feix perquè tres retocs lèxics sumin més confiança.

Admissió: si qui crida el generador li dona una funció d'admissió
(``admissible``), la selecció final la consulta abans d'ocupar cada plaça. La
funció retorna el candidat ja reparat i diu si supera la validació; els
candidats que no la superen no consumeixen plaça —les aprofita una alternativa
vàlida— però es conserven a part perquè el resultat continuï explicant per què
s'han descartat. La funció es consulta amb memòria cau i mandra: només per als
candidats que estan a punt d'entrar.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.core.errors import ConfigError, TransformationError
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import SemanticRisk, Transformation

ExpandFn = Callable[[str], Iterable[Transformation]]
"""Donat el text d'un candidat, retorna les transformacions que les regles hi proposen."""

CHAINED_RULES_KEY = "chained_rules"

DUPLICATE = "duplicat"
EXCESSIVE = "canvi excessiu"
BUDGET = "pressupost"
SAFETY = "seguretat"
SCORE = "puntuació"
DISCARD_REASONS = (DUPLICATE, EXCESSIVE, BUDGET, SAFETY, SCORE)


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    """Què en diuen la reparació, la validació i la puntuació d'un candidat."""

    candidate: Candidate
    """El candidat tal com queda després de reparar-lo (el mateix si no calia res)."""
    valid: bool = True
    total: float = 0.0
    reason: str = ""
    """Per què no és admissible, si no ho és."""


AdmissionFn = Callable[[Candidate], CandidateAssessment]
"""Repara, valida i puntua un candidat abans que ocupi una plaça."""


@dataclass(slots=True)
class GenerationTrace:
    """Comptes de la cerca de candidats: què s'ha generat i per què cau la resta."""

    proposals: int = 0
    generated: int = 0
    """Candidats entrats a la reserva de treball (sense l'identitat)."""
    expanded: int = 0
    """Candidats que ha aportat la reaplicació de regles (segon nivell)."""
    expansion_calls: int = 0
    """Textos sobre els quals s'han tornat a demanar propostes."""
    assessed: int = 0
    """Candidats reparats, validats i puntuats durant la selecció."""
    selected: int = 0
    truncated: bool = False
    """Cert si la cerca s'ha aturat perquè havia arribat al seu límit de treball."""
    discarded: dict[str, int] = field(default_factory=dict)

    def discard(self, reason: str) -> None:
        self.discarded[reason] = self.discarded.get(reason, 0) + 1

    def describe(self) -> str:
        parts = [f"{count} per {reason}" for reason, count in sorted(self.discarded.items())]
        detail = "; ".join(parts) if parts else "cap"
        limit = " · reserva plena" if self.truncated else ""
        return (
            f"{self.proposals} propostes · {self.generated} candidats "
            f"({self.expanded} per expansió en {self.expansion_calls} reanàlisis) · "
            f"{self.assessed} avaluats · {self.selected} conservats · "
            f"descartats: {detail}{limit}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "proposals": self.proposals,
            "generated": self.generated,
            "expanded": self.expanded,
            "expansion_calls": self.expansion_calls,
            "assessed": self.assessed,
            "selected": self.selected,
            "truncated": self.truncated,
            "discarded": dict(sorted(self.discarded.items())),
        }


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Candidats triats, els que ha rebutjat la validació i la traça de la cerca."""

    candidates: tuple[Candidate, ...]
    rejected: tuple[Candidate, ...] = ()
    """Candidats que no han superat l'admissió: no ocupen plaça, però s'expliquen."""
    trace: GenerationTrace = field(default_factory=GenerationTrace)


class CandidateGenerator:
    """Construeix candidats combinant i encadenant transformacions compatibles."""

    def __init__(
        self,
        *,
        max_transformations: int = 3,
        max_candidates: int = 20,
        max_depth: int = 2,
        max_change_ratio: float = 0.75,
        beam_width: int = 6,
        expansion_budget: int | None = None,
    ) -> None:
        if max_transformations < 1 or max_candidates < 1 or max_depth < 1 or beam_width < 1:
            raise ConfigError("Els límits del generador de candidats han de ser almenys 1")
        if not 0.0 < max_change_ratio <= 1.0:
            raise ConfigError("max_change_ratio ha d'estar entre 0 (exclòs) i 1")
        if expansion_budget is not None and expansion_budget < 0:
            raise ConfigError("expansion_budget no pot ser negatiu")
        self._max_transformations = max_transformations
        self._max_candidates = max_candidates
        self._max_depth = max_depth
        self._max_change_ratio = max_change_ratio
        self._beam_width = beam_width
        #: Reserva de treball: més ampla que el límit, perquè la selecció final
        #: pugui triar per diversitat i no pel primer que hagi arribat.
        self._pool_limit = max(max_candidates, min(4 * max_candidates, max_candidates + 60))
        #: Places reservades a l'expansió de segon nivell, **per damunt** de la
        #: reserva base: encara que les combinacions inicials la saturin, la
        #: reaplicació de regles sempre té marge per treballar.
        self._expansion_budget = (
            expansion_budget if expansion_budget is not None else max(4, beam_width * 2)
        )

    @property
    def max_transformations(self) -> int:
        return self._max_transformations

    @property
    def max_depth(self) -> int:
        return self._max_depth

    @property
    def max_candidates(self) -> int:
        """Candidats que la selecció final conserva, comptant l'original."""
        return self._max_candidates

    @property
    def pool_limit(self) -> int:
        """Candidats que la generació base pot arribar a construir."""
        return self._pool_limit

    @property
    def expansion_budget(self) -> int:
        """Places reservades a l'expansió, per damunt de la reserva base."""
        return self._expansion_budget

    @property
    def work_limit(self) -> int:
        """Sostre dur de candidats construïts en una crida."""
        return self._pool_limit + self._expansion_budget

    def generate(
        self,
        sentence_index: int,
        source_text: str,
        proposals: Iterable[Transformation],
        *,
        expand: ExpandFn | None = None,
        admissible: AdmissionFn | None = None,
    ) -> tuple[Candidate, ...]:
        """Candidats triats per a aquesta frase (drecera de :meth:`search`)."""
        return self.search(
            sentence_index, source_text, proposals, expand=expand, admissible=admissible
        ).candidates

    def search(
        self,
        sentence_index: int,
        source_text: str,
        proposals: Iterable[Transformation],
        *,
        expand: ExpandFn | None = None,
        admissible: AdmissionFn | None = None,
    ) -> GenerationResult:
        """Cerca completa: candidats, rebutjats per l'admissió i traça del que ha caigut."""
        trace = GenerationTrace()
        identity = Candidate.identity(sentence_index, source_text)
        candidates: list[Candidate] = [identity]
        seen: set[str] = {source_text, identity.normalized_text()}

        ordered = sorted(
            (p for p in proposals if not p.is_identity and p.can_apply_to(source_text)),
            key=lambda t: (-t.confidence, t.semantic_risk.level, t.changed_span.start),
        )
        trace.proposals = len(ordered)

        # Nivell 1: un candidat per transformació.
        for transformation in ordered:
            self._add(
                candidates, seen, sentence_index, source_text, (transformation,),
                self._pool_limit, trace,
            )  # fmt: skip

        # Nivell 1b: combinacions de transformacions compatibles.
        frontier: list[tuple[int, ...]] = [(i,) for i in range(len(ordered))]
        for _size in range(2, self._max_transformations + 1):
            next_frontier: list[tuple[int, ...]] = []
            for combo in frontier:
                for j in range(combo[-1] + 1, len(ordered)):
                    if len(candidates) >= self._pool_limit:
                        trace.truncated = True
                        break
                    if not all(_compatible(ordered[i], ordered[j]) for i in combo):
                        continue
                    chosen = (*combo, j)
                    if self._add(
                        candidates,
                        seen,
                        sentence_index,
                        source_text,
                        tuple(ordered[i] for i in chosen),
                        self._pool_limit,
                        trace,
                    ):
                        next_frontier.append(chosen)
            frontier = next_frontier
            if not frontier:
                break

        # Nivell 2+: reaplicació de regles sobre els millors candidats, amb el seu
        # pressupost propi per damunt de la reserva base.
        limit = self._pool_limit + self._expansion_budget
        if expand is not None and self._max_depth >= 2:
            for _depth in range(2, self._max_depth + 1):
                added = 0
                for base in self._expansion_beam(candidates):
                    if len(candidates) >= limit:
                        trace.truncated = True
                        break
                    trace.expansion_calls += 1
                    for proposal in expand(base.text):
                        composed = self.compose(base, proposal)
                        if composed is None:
                            continue
                        if self._add_candidate(candidates, seen, composed, limit, trace):
                            added += 1
                            trace.expanded += 1
                        if len(candidates) >= limit:
                            trace.truncated = True
                            break
                if not added:
                    break

        return self._select(candidates, admissible, trace)

    def _expansion_beam(self, candidates: Sequence[Candidate]) -> tuple[Candidate, ...]:
        """Candidats que val la pena reanalitzar, per diversitat abans que per confiança.

        Primer el millor de cada signatura estructural i després la resta per
        ordre de qualitat. Amb l'ordenació antiga (només la suma de confiances),
        tres retocs lèxics sempre desplaçaven una reordenació segura, que és
        justament la que més pot guanyar amb una segona passada.
        """
        others = [c for c in candidates if not c.is_identity]
        if not others:
            return ()
        position = {id(c): n for n, c in enumerate(others)}
        ranked = sorted(others, key=lambda c: _quality(c, position))
        beam: list[Candidate] = []
        signatures: set[str] = set()
        for candidate in ranked:
            if len(beam) >= self._beam_width:
                break
            if candidate.signature in signatures:
                continue
            signatures.add(candidate.signature)
            beam.append(candidate)
        for candidate in ranked:
            if len(beam) >= self._beam_width:
                break
            if candidate not in beam:
                beam.append(candidate)
        return tuple(beam)

    def select(self, candidates: Sequence[Candidate]) -> tuple[Candidate, ...]:
        """Redueix la reserva al límit conservant la diversitat."""
        return self._select(candidates, None, GenerationTrace()).candidates

    def _select(
        self,
        candidates: Sequence[Candidate],
        admissible: AdmissionFn | None,
        trace: GenerationTrace,
    ) -> GenerationResult:
        """Tria final: diversitat, admissió i límit explícit.

        Per ordre: l'identitat; el millor candidat de cada signatura estructural
        (per grau estructural i confiança acumulada); cada transformació solta
        (un candidat per regla, perquè cada canvi es pugui veure per separat); i
        la resta per la mateixa ordenació, fins al límit. L'ordre final és el
        de generació, i tot és determinista: només depèn dels candidats.

        Amb funció d'admissió, cada plaça es dona a un candidat que ja ha passat
        la reparació i la validació: els que no la passen no en gasten cap.
        """
        identity = [c for c in candidates if c.is_identity][:1]
        others = [c for c in candidates if not c.is_identity]
        trace.generated = len(others)
        position = {id(c): n for n, c in enumerate(others)}
        room = self._max_candidates - len(identity)
        ranked = sorted(others, key=lambda c: _quality(c, position))

        kept: list[tuple[int, Candidate]] = []
        rejected: list[Candidate] = []
        handled: set[int] = set()
        texts: set[str] = set()
        refused: set[str] = set()
        signatures: set[str] = set()
        rules: set[str] = set()

        def admit(candidate: Candidate) -> bool:
            if id(candidate) in handled:
                return False
            handled.add(id(candidate))
            if len(kept) >= room:
                # Ha entrat a la reserva, però l'han desplaçat candidats millors.
                trace.discard(SCORE)
                return False
            final = candidate
            if admissible is not None:
                trace.assessed += 1
                assessment = admissible(candidate)
                final = assessment.candidate
                if not assessment.valid:
                    trace.discard(SAFETY)
                    if final.text not in refused and len(rejected) < self._max_candidates:
                        refused.add(final.text)
                        rejected.append(final)
                    return False
            if final.text in texts:
                trace.discard(DUPLICATE)
                return False
            texts.add(final.text)
            signatures.add(candidate.signature)
            if candidate.n_transformations == 1:
                rules.add(candidate.transformations[0].rule_id)
            kept.append((position[id(candidate)], final))
            return True

        for candidate in ranked:  # una alternativa de cada signatura estructural
            if candidate.signature not in signatures:
                admit(candidate)
        for candidate in ranked:  # una alternativa de cada regla, vista per separat
            if (
                candidate.n_transformations == 1
                and candidate.transformations[0].rule_id not in rules
            ):
                admit(candidate)
        for candidate in ranked:  # la resta, per qualitat
            admit(candidate)

        if identity and admissible is not None:
            trace.assessed += 1
            identity = [admissible(identity[0]).candidate]
        kept.sort(key=lambda item: item[0])
        selected = (*identity, *(candidate for _, candidate in kept))
        trace.selected = len(selected)
        return GenerationResult(selected, tuple(rejected), trace)

    # --- composició en profunditat ---------------------------------------------------

    def compose(self, base: Candidate, proposal: Transformation) -> Candidate | None:
        """Projecta una transformació proposada sobre ``base.text`` cap al text original.

        Retorna ``None`` si la proposta repeteix una regla ja aplicada sobre el
        mateix segment, si trenca el límit d'una transformació anterior o si no
        es pot reprojectar de manera exacta.
        """
        if proposal.is_identity or not proposal.can_apply_to(base.text):
            return None
        if len(base.transformations) >= self._max_transformations:
            return None
        result_spans = base.result_spans()
        for previous, result_span in zip(base.transformations, result_spans, strict=True):
            if proposal.changed_span.overlaps(result_span) and _same_rule(previous, proposal):
                return None

        overlapping = [
            (previous, result_span)
            for previous, result_span in zip(base.transformations, result_spans, strict=True)
            if proposal.changed_span.overlaps(result_span)
        ]
        if not overlapping:
            return self._remap(base, proposal, result_spans)
        if len(overlapping) > 1:
            return None
        previous, result_span = overlapping[0]
        if not result_span.contains(proposal.changed_span):
            return None
        return self._chain(base, previous, result_span, proposal)

    def _remap(
        self, base: Candidate, proposal: Transformation, result_spans: tuple[Span, ...]
    ) -> Candidate | None:
        delta = sum(
            len(previous.text_after) - previous.changed_span.length
            for previous, result_span in zip(base.transformations, result_spans, strict=True)
            if result_span.end <= proposal.changed_span.start
        )
        source_span = Span(proposal.changed_span.start - delta, proposal.changed_span.end - delta)
        if source_span.end > len(base.source_text):
            return None
        if source_span.slice(base.source_text) != proposal.text_before:
            return None
        if any(source_span.overlaps(t.changed_span) for t in base.transformations):
            return None
        remapped = replace(proposal, changed_span=source_span)
        return self._build(base, (*base.transformations, remapped), proposal.apply(base.text))

    def _chain(
        self, base: Candidate, previous: Transformation, result_span: Span, proposal: Transformation
    ) -> Candidate | None:
        offset = proposal.changed_span.start - result_span.start
        inner = previous.text_after[offset : offset + proposal.changed_span.length]
        if inner != proposal.text_before:
            return None
        new_after = (
            previous.text_after[:offset]
            + proposal.text_after
            + previous.text_after[offset + proposal.changed_span.length :]
        )
        chained = [r for r in previous.metadata.get(CHAINED_RULES_KEY, "").split(",") if r]
        chained.append(proposal.rule_id)
        merged = Transformation(
            rule_id=previous.rule_id,
            text_before=previous.text_before,
            text_after=new_after,
            changed_span=previous.changed_span,
            transformation_type=previous.transformation_type,
            confidence=min(previous.confidence, proposal.confidence),
            semantic_risk=max(
                previous.semantic_risk, proposal.semantic_risk, key=lambda r: r.level
            ),
            explanation=f"{previous.explanation} A continuació, {proposal.explanation}",
            metadata={**previous.metadata, CHAINED_RULES_KEY: ",".join(chained)},
        )
        transformations = tuple(merged if t is previous else t for t in base.transformations)
        return self._build(base, transformations, proposal.apply(base.text))

    def _build(
        self, base: Candidate, transformations: tuple[Transformation, ...], expected: str
    ) -> Candidate | None:
        try:
            candidate = Candidate.from_transformations(
                base.sentence_index, base.source_text, transformations
            )
        except TransformationError:
            return None
        if candidate.text != expected:
            return None
        return candidate

    # --- utilitats ---------------------------------------------------------------------------

    def _add(
        self,
        candidates: list[Candidate],
        seen: set[str],
        sentence_index: int,
        source_text: str,
        transformations: tuple[Transformation, ...],
        limit: int,
        trace: GenerationTrace,
    ) -> bool:
        if len(candidates) >= limit:
            trace.truncated = True
            trace.discard(BUDGET)
            return False
        try:
            candidate = Candidate.from_transformations(sentence_index, source_text, transformations)
        except TransformationError:
            return False
        return self._add_candidate(candidates, seen, candidate, limit, trace)

    def _add_candidate(
        self,
        candidates: list[Candidate],
        seen: set[str],
        candidate: Candidate,
        limit: int,
        trace: GenerationTrace,
    ) -> bool:
        if len(candidates) >= limit:
            trace.truncated = True
            trace.discard(BUDGET)
            return False
        normalized = candidate.normalized_text()
        if candidate.text in seen or normalized in seen:
            trace.discard(DUPLICATE)  # gairebé idèntic a un candidat anterior: no aporta res
            return False
        if candidate.change_ratio() > self._max_change_ratio:
            trace.discard(EXCESSIVE)
            return False
        seen.add(candidate.text)
        seen.add(normalized)
        candidates.append(candidate)
        return True


def _quality(candidate: Candidate, position: dict[int, int]) -> tuple[float, float, int]:
    """Ordre de qualitat d'un candidat: estructura, després confiança, després ordre.

    El grau estructural mana perquè és el que distingeix una reredacció real
    d'un retoc; la confiança acumulada desempata dins de la mateixa mena de
    canvi, i l'ordre de generació fa que el desempat final sigui estable.
    """
    return (
        -candidate.structural_degree(),
        -sum(t.confidence for t in candidate.transformations),
        position[id(candidate)],
    )


def _compatible(first: Transformation, second: Transformation) -> bool:
    """Dues transformacions es poden combinar si no se solapen."""
    return not first.changed_span.overlaps(second.changed_span)


def _same_rule(previous: Transformation, proposal: Transformation) -> bool:
    chained = previous.metadata.get(CHAINED_RULES_KEY, "").split(",")
    return proposal.rule_id == previous.rule_id or proposal.rule_id in chained


def worst_risk(transformations: Iterable[Transformation]) -> SemanticRisk:
    """Risc semàntic més alt d'un conjunt de transformacions."""
    risk = SemanticRisk.NONE
    for transformation in transformations:
        if transformation.semantic_risk.exceeds(risk):
            risk = transformation.semantic_risk
    return risk
