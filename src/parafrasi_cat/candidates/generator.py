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

Garanties: els candidats es dedupliquen pel text, es descarten els que
superen ``max_change_ratio`` i mai no s'aplica la mateixa regla dues vegades
sobre el mateix segment.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.core.errors import ConfigError, TransformationError
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import SemanticRisk, Transformation

ExpandFn = Callable[[str], Iterable[Transformation]]
"""Donat el text d'un candidat, retorna les transformacions que les regles hi proposen."""

CHAINED_RULES_KEY = "chained_rules"


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
    ) -> None:
        if max_transformations < 1 or max_candidates < 1 or max_depth < 1 or beam_width < 1:
            raise ConfigError("Els límits del generador de candidats han de ser almenys 1")
        if not 0.0 < max_change_ratio <= 1.0:
            raise ConfigError("max_change_ratio ha d'estar entre 0 (exclòs) i 1")
        self._max_transformations = max_transformations
        self._max_candidates = max_candidates
        self._max_depth = max_depth
        self._max_change_ratio = max_change_ratio
        self._beam_width = beam_width

    @property
    def max_transformations(self) -> int:
        return self._max_transformations

    @property
    def max_depth(self) -> int:
        return self._max_depth

    def generate(
        self,
        sentence_index: int,
        source_text: str,
        proposals: Iterable[Transformation],
        *,
        expand: ExpandFn | None = None,
    ) -> tuple[Candidate, ...]:
        candidates: list[Candidate] = [Candidate.identity(sentence_index, source_text)]
        seen: set[str] = {source_text}

        ordered = sorted(
            (p for p in proposals if not p.is_identity and p.can_apply_to(source_text)),
            key=lambda t: (-t.confidence, t.semantic_risk.level, t.changed_span.start),
        )

        # Nivell 1: un candidat per transformació.
        for transformation in ordered:
            self._add(candidates, seen, sentence_index, source_text, (transformation,))

        # Nivell 1b: combinacions de transformacions compatibles.
        frontier: list[tuple[int, ...]] = [(i,) for i in range(len(ordered))]
        for _size in range(2, self._max_transformations + 1):
            next_frontier: list[tuple[int, ...]] = []
            for combo in frontier:
                for j in range(combo[-1] + 1, len(ordered)):
                    if len(candidates) >= self._max_candidates:
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
                    ):
                        next_frontier.append(chosen)
            frontier = next_frontier
            if not frontier:
                break

        # Nivell 2+: reaplicació de regles sobre els millors candidats.
        if expand is not None and self._max_depth >= 2:
            for _depth in range(2, self._max_depth + 1):
                beam = sorted(
                    (c for c in candidates if not c.is_identity),
                    key=lambda c: -sum(t.confidence for t in c.transformations),
                )[: self._beam_width]
                added = 0
                for base in beam:
                    if len(candidates) >= self._max_candidates:
                        break
                    for proposal in expand(base.text):
                        composed = self.compose(base, proposal)
                        if composed is None:
                            continue
                        if self._add_candidate(candidates, seen, composed):
                            added += 1
                        if len(candidates) >= self._max_candidates:
                            break
                if not added:
                    break

        return tuple(candidates[: self._max_candidates])

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
    ) -> bool:
        if len(candidates) >= self._max_candidates:
            return False
        try:
            candidate = Candidate.from_transformations(sentence_index, source_text, transformations)
        except TransformationError:
            return False
        return self._add_candidate(candidates, seen, candidate)

    def _add_candidate(
        self, candidates: list[Candidate], seen: set[str], candidate: Candidate
    ) -> bool:
        if candidate.text in seen or len(candidates) >= self._max_candidates:
            return False
        if candidate.change_ratio() > self._max_change_ratio:
            return False
        seen.add(candidate.text)
        candidates.append(candidate)
        return True


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
