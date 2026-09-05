"""Cerca en feix d'arquitectures alternatives de paràgraf (nivell 5, mode profund).

Frase per frase, la canonada tria un candidat i el paràgraf es reconstrueix amb
aquests guanyadors locals: un òptim local que fa desaparèixer massa aviat les
alternatives. Un candidat que queda segon en una frase pot ser el que permet
una fusió segura amb la frase següent o el que dona al paràgraf sencer el
ritme de l'autor, i el nivell 5 no arribava a veure-ho.

Aquí, en lloc d'un sol text intermedi, es conserven uns quants candidats
**segurs i diversos** de cada frase (l'original, el millor local i el millor de
cada signatura estructural) i es construeixen arquitectures de paràgraf amb
una cerca en feix determinista i acotada:

1. es parteix del paràgraf buit;
2. per a cada frase, cada estat viu s'estén amb cada candidat conservat de la
   frase; sobre el text resultant s'apliquen les regles de paràgraf (fusió...)
   al darrer parell de frases, de manera que una fusió que un candidat local
   fa possible es puntua en el mateix moment en què és possible;
3. els estats es puntuen (suma de les puntuacions locals més la puntuació de
   les transformacions de paràgraf) i es poden: es conserva el millor, el
   millor estat de cada candidat de la frase acabada d'afegir (perquè cap
   alternativa local no mori abans d'haver pogut combinar-se) i la resta per
   puntuació, fins a l'amplada del feix;
4. sobre les arquitectures completes, s'hi afegeixen sempre la de tots els
   guanyadors locals i l'original, es validen contra el paràgraf original, es
   puntuen globalment (amb l'afinitat de l'autor mesurada sobre el paràgraf
   sencer, no frase a frase) i se'n tria la millor.

No hi ha producte cartesià: el nombre d'estats vius és fix, els textos i les
signatures es dedupliquen i tot és determinista. Cap element del feix no pot
rescatar un candidat que la validació hagi invalidat.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from parafrasi_cat.analyzer.paragraphs import Paragraph
from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.candidates.generator import CandidateGenerator
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import Transformation
from parafrasi_cat.pipeline.result import (
    EvaluatedCandidate,
    ParagraphResult,
    RejectedProposal,
    SentenceResult,
)
from parafrasi_cat.protected.spans import ProtectedSpan
from parafrasi_cat.rules.base import ParagraphContext, ParagraphRule
from parafrasi_cat.scoring.scorer import ScoreBreakdown, Scorer, ScoringContext
from parafrasi_cat.style.adaptation import AdaptationContext, AuthorAdaptation
from parafrasi_cat.validation.base import ValidationContext, Validator
from parafrasi_cat.validation.result import ValidationResult

ProtectedConflict = Callable[[Span, str], str | None]
RejectionReason = Callable[[Transformation, str, ProtectedConflict], str | None]
ContextFactory = Callable[[str], ParagraphContext]

AFFINITY_COMPONENT = "afinitat_autor"
_SHORT = 60


def _shorten(text: str, limit: int = _SHORT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass(frozen=True, slots=True)
class LocalOption:
    """Un candidat de frase conservat per al feix, i per què."""

    sentence_index: int
    evaluated: EvaluatedCandidate
    reason: str

    @property
    def candidate(self) -> Candidate:
        return self.evaluated.candidate

    @property
    def total(self) -> float:
        return self.evaluated.score.total if self.evaluated.score is not None else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "sentence_index": self.sentence_index,
            "signature": self.candidate.signature,
            "text": self.candidate.text,
            "total": self.total,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class BeamState:
    """Un prefix de paràgraf: els candidats triats fins ara i el text que en resulta.

    ``paragraph`` és el candidat de paràgraf del prefix: ``source_text`` és el
    text intermedi (els candidats de frase, sense transformacions de
    paràgraf), ``text`` el text actual i ``transformations`` les
    transformacions de paràgraf aplicades, relatives al text intermedi.
    """

    options: tuple[LocalOption, ...]
    paragraph: Candidate
    local_total: float
    paragraph_score: ScoreBreakdown | None = None
    validation: ValidationResult | None = None
    kept_for: str = ""

    @property
    def partial_total(self) -> float:
        paragraph = self.paragraph_score.total if self.paragraph_score is not None else 0.0
        return round(self.local_total + paragraph, 4)

    @property
    def n_transformations(self) -> int:
        return sum(o.candidate.n_transformations for o in self.options) + len(
            self.paragraph.transformations
        )

    @property
    def signatures(self) -> tuple[str, ...]:
        return tuple(o.candidate.signature for o in self.options)

    def describe(self) -> str:
        rules = ", ".join(t.rule_id for t in self.paragraph.transformations) or "cap"
        return f"[{' | '.join(self.signatures)}] + paràgraf: {rules}"


@dataclass(frozen=True, slots=True)
class PrunedState:
    """Un estat que ha quedat fora del feix, i per què."""

    signatures: tuple[str, ...]
    paragraph_rules: tuple[str, ...]
    partial_total: float
    reason: str
    text: str

    def to_dict(self) -> dict[str, object]:
        return {
            "signatures": list(self.signatures),
            "paragraph_rules": list(self.paragraph_rules),
            "partial_total": self.partial_total,
            "reason": self.reason,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class ParagraphAlternative:
    """Una arquitectura completa de paràgraf, validada i puntuada globalment."""

    state: BeamState
    evaluated: EvaluatedCandidate
    origin: str
    local_total: float
    paragraph_total: float
    affinity_delta: float | None
    global_total: float

    @property
    def valid(self) -> bool:
        return self.evaluated.accepted

    def to_dict(self) -> dict[str, object]:
        return {
            "origin": self.origin,
            "signatures": list(self.state.signatures),
            "choices": [
                {
                    "sentence_index": o.sentence_index,
                    "signature": o.candidate.signature,
                    "reason": o.reason,
                    "text": o.candidate.text,
                }
                for o in self.state.options
            ],
            "paragraph_rules": [t.rule_id for t in self.state.paragraph.transformations],
            "local_total": self.local_total,
            "paragraph_total": self.paragraph_total,
            "affinity_delta": self.affinity_delta,
            "global_total": self.global_total,
            "valid": self.valid,
            "rejection_reason": self.evaluated.rejection_reason,
            "text": self.evaluated.candidate.text,
        }


@dataclass(frozen=True, slots=True)
class ParagraphSearch:
    """Traça completa de la cerca: què s'ha conservat, què s'ha podat i què ha guanyat."""

    beam_width: int
    candidates_per_sentence: int
    options: tuple[tuple[LocalOption, ...], ...]
    alternatives: tuple[ParagraphAlternative, ...]
    selected: int
    explored: int
    pruned: tuple[PrunedState, ...] = ()

    @property
    def winner(self) -> ParagraphAlternative:
        return self.alternatives[self.selected]

    @property
    def local_winner_total(self) -> float:
        """Puntuació global de l'arquitectura formada pels guanyadors locals."""
        for alternative in self.alternatives:
            if alternative.origin == "guanyadors locals":
                return alternative.global_total
        return self.winner.global_total  # pragma: no cover - sempre hi és

    def to_dict(self) -> dict[str, object]:
        return {
            "beam_width": self.beam_width,
            "candidates_per_sentence": self.candidates_per_sentence,
            "options": [[o.to_dict() for o in group] for group in self.options],
            "alternatives": [a.to_dict() for a in self.alternatives],
            "selected": self.selected,
            "explored": self.explored,
            "pruned": [p.to_dict() for p in self.pruned],
        }


@dataclass(frozen=True, slots=True)
class BeamSettings:
    beam_width: int = 6
    candidates_per_sentence: int = 3
    max_pruned_recorded: int = 24


class ParagraphBeam:
    """Cerca en feix d'arquitectures de paràgraf, determinista i acotada."""

    def __init__(
        self,
        *,
        settings: BeamSettings,
        generator: CandidateGenerator,
        scorer: Scorer,
        validators: Sequence[Validator],
        paragraph_rules: Sequence[ParagraphRule],
        context_factory: ContextFactory,
        rejection_reason: RejectionReason,
        adaptation: AuthorAdaptation | None = None,
        affinity_weight: float = 0.0,
    ) -> None:
        self._settings = settings
        self._generator = generator
        self._scorer = scorer
        self._validators = tuple(validators)
        self._rules = tuple(paragraph_rules)
        self._context_factory = context_factory
        self._rejection_reason = rejection_reason
        self._adaptation = adaptation
        self._affinity_weight = affinity_weight

    @property
    def settings(self) -> BeamSettings:
        return self._settings

    # --- candidats locals -------------------------------------------------------------------

    def local_options(self, result: SentenceResult) -> tuple[LocalOption, ...]:
        """Candidats segurs i diversos d'una frase: l'original, el millor i un per signatura.

        Es prefereix la diversitat de signatures a la puntuació: un cop conservat el
        millor candidat, entren els millors de cada signatura estructural (una
        reordenació, una subordinació, una divisió...) i, si queda lloc, els de les
        signatures superficials. Mai més de ``candidates_per_sentence`` alternatives
        a més de l'original.
        """
        accepted = [e for e in result.candidates if e.accepted]
        identity = next((e for e in accepted if e.candidate.is_identity), None)
        if identity is None:
            identity = next((e for e in result.candidates if e.candidate.is_identity), None)
        options: list[LocalOption] = []
        if identity is not None:
            options.append(LocalOption(result.index, identity, "original"))
        others = [e for e in accepted if not e.candidate.is_identity]
        position = {id(e): n for n, e in enumerate(others)}
        ranked = sorted(
            others,
            key=lambda e: (
                -(e.score.total if e.score is not None else 0.0),
                e.candidate.n_transformations,
                position[id(e)],
            ),
        )
        room = self._settings.candidates_per_sentence
        seen: set[str] = set()
        chosen: list[LocalOption] = []
        if ranked and room > 0:
            best = ranked[0]
            chosen.append(LocalOption(result.index, best, "millor local"))
            seen.add(best.candidate.signature)
        for structural in (True, False):
            for evaluated in ranked:
                if len(chosen) >= room:
                    break
                candidate = evaluated.candidate
                if candidate.is_structural is not structural or candidate.signature in seen:
                    continue
                seen.add(candidate.signature)
                chosen.append(LocalOption(result.index, evaluated, f"millor {candidate.signature}"))
        return (*options, *chosen)

    # --- cerca ------------------------------------------------------------------------------

    def search(
        self,
        paragraph: Paragraph,
        sentence_results: Sequence[SentenceResult],
        protected: tuple[ProtectedSpan, ...],
        document: AdaptationContext | None = None,
    ) -> tuple[ParagraphResult, tuple[SentenceResult, ...]]:
        """Explora arquitectures del paràgraf i retorna el resultat i les frases re-marcades."""
        inner = tuple(sentence_results)
        base = paragraph.span.start
        head = paragraph.text[: inner[0].span.start - base] if inner else paragraph.text
        gaps: list[str] = [head]
        for previous, current in zip(inner, inner[1:], strict=False):
            gaps.append(paragraph.text[previous.span.end - base : current.span.start - base])
        tail = paragraph.text[inner[-1].span.end - base :] if inner else ""
        options = tuple(self.local_options(result) for result in inner)

        explored = 0
        pruned: list[PrunedState] = []
        rejected: dict[str, RejectedProposal] = {}
        notes: dict[str, None] = {}
        beam: list[BeamState] = [
            BeamState((), Candidate(paragraph.index, "", "", ()), 0.0, kept_for="inici")
        ]
        for index, group in enumerate(options):
            extended: list[BeamState] = []
            for state in beam:
                for option in group:
                    extended.extend(
                        self._extend(state, option, gaps[index], paragraph, rejected, notes)
                    )
            explored += len(extended)
            beam = self._prune(extended, group, pruned)

        alternatives = self._complete(
            beam, options, gaps, tail, paragraph, protected, document, rejected, notes
        )
        selected = self._select(alternatives)
        winner = alternatives[selected]
        final_notes = self._notes_for(winner.evaluated.candidate.text, notes, rejected)
        search = ParagraphSearch(
            beam_width=self._settings.beam_width,
            candidates_per_sentence=self._settings.candidates_per_sentence,
            options=options,
            alternatives=tuple(alternatives),
            selected=selected,
            explored=explored,
            pruned=tuple(pruned[: self._settings.max_pruned_recorded]),
        )
        evaluated = tuple(
            replace(a.evaluated, selected=(n == selected)) for n, a in enumerate(alternatives)
        )
        result = ParagraphResult(
            index=paragraph.index,
            source_text=paragraph.text,
            intermediate_text=winner.state.paragraph.source_text,
            span=paragraph.span,
            output_text=winner.evaluated.candidate.text,
            candidates=evaluated,
            rejected_proposals=tuple(rejected.values()),
            protected_spans=protected,
            notes=final_notes,
            search=search,
        )
        return result, self._remark(inner, winner)

    def _extend(
        self,
        state: BeamState,
        option: LocalOption,
        gap: str,
        paragraph: Paragraph,
        rejected: dict[str, RejectedProposal],
        notes: dict[str, None],
    ) -> list[BeamState]:
        """Estats que resulten d'afegir un candidat de frase (sense i amb fusió)."""
        candidate = option.candidate
        previous = state.paragraph
        intermediate = previous.source_text + gap + candidate.text
        text = previous.text + gap + candidate.text
        local_total = state.local_total + option.total
        extended = Candidate(paragraph.index, intermediate, text, previous.transformations)
        base_score = self._scorer.score(extended, ScoringContext(None, intermediate, None))
        states = [BeamState((*state.options, option), extended, local_total, base_score, None)]
        if not self._rules or not state.options:
            return states
        ctx = self._context_factory(text)
        boundary = len(previous.text)
        for rule in self._rules:
            for proposal in rule.propose(ctx):
                if proposal.changed_span.end <= boundary:
                    continue  # un parell anterior: ja es va considerar al seu pas
                reason = self._rejection_reason(proposal, text, ctx.protected_conflict)
                if reason is not None:
                    rejected.setdefault(proposal.text_before + "→" + proposal.text_after,
                                        RejectedProposal(proposal, reason))  # fmt: skip
                    continue
                composed = self._generator.compose(extended, proposal)
                if composed is None:
                    continue
                # Validació provisional contra el prefix intermedi (la definitiva, contra
                # el paràgraf original, es fa sobre les arquitectures completes).
                source_ctx = ctx if text == intermediate else self._context_factory(intermediate)
                validation = self._validate(composed, intermediate, source_ctx.protected_spans)
                if not validation.ok:
                    key = proposal.text_before + "→" + proposal.text_after
                    rejected.setdefault(key, RejectedProposal(proposal, validation.summary))
                    continue
                score = self._scorer.score(composed, ScoringContext(validation, intermediate, None))
                if not score.valid:
                    continue
                states.append(
                    BeamState((*state.options, option), composed, local_total, score, validation)
                )
        for note in ctx.notes:
            notes.setdefault(note)
        return states

    def _validate(
        self, candidate: Candidate, source_text: str, protected: tuple[ProtectedSpan, ...]
    ) -> ValidationResult:
        ctx = ValidationContext(source_text, protected)
        return ValidationResult.merge(v.validate(candidate, ctx) for v in self._validators)

    def _prune(
        self,
        states: list[BeamState],
        group: Sequence[LocalOption],
        pruned: list[PrunedState],
    ) -> list[BeamState]:
        """Poda determinista que conserva la diversitat.

        Ordre: el millor estat; el millor estat de cada candidat de la frase que
        s'acaba d'afegir (cap alternativa local no mor sense haver pogut
        combinar-se amb la frase següent); la resta per puntuació parcial.
        """
        unique: dict[str, BeamState] = {}
        for state in states:
            text = state.paragraph.text
            current = unique.get(text)
            if current is None or _rank(state) < _rank(current):
                unique[text] = state
        ranked = sorted(unique.values(), key=_rank)
        width = self._settings.beam_width
        kept: list[BeamState] = []
        reasons: dict[int, str] = {}
        if ranked:
            kept.append(ranked[0])
            reasons[id(ranked[0])] = "millor puntuació parcial"
        for option in group:
            if len(kept) >= width:
                break
            for state in ranked:
                if state.options and state.options[-1] is option:
                    if id(state) not in reasons:
                        kept.append(state)
                        reasons[id(state)] = f"millor estat amb {option.candidate.signature}"
                    break
        for state in ranked:
            if len(kept) >= width:
                break
            if id(state) not in reasons:
                kept.append(state)
                reasons[id(state)] = "puntuació parcial"
        for state in ranked:
            if id(state) not in reasons:
                pruned.append(
                    PrunedState(
                        state.signatures,
                        tuple(t.rule_id for t in state.paragraph.transformations),
                        state.partial_total,
                        f"puntuació parcial {state.partial_total:+.3f} fora del feix "
                        f"(mínim conservat {kept[-1].partial_total:+.3f})",
                        _shorten(state.paragraph.text),
                    )
                )
        kept.sort(key=_rank)
        return [replace(state, kept_for=reasons[id(state)]) for state in kept]

    def _complete(
        self,
        beam: Sequence[BeamState],
        options: Sequence[Sequence[LocalOption]],
        gaps: Sequence[str],
        tail: str,
        paragraph: Paragraph,
        protected: tuple[ProtectedSpan, ...],
        document: AdaptationContext | None,
        rejected: dict[str, RejectedProposal],
        notes: dict[str, None],
    ) -> list[ParagraphAlternative]:
        """Arquitectures completes: els guanyadors locals, l'original i els estats del feix."""
        states: list[tuple[str, BeamState]] = []
        winners = self._path(options, gaps, paragraph, position=1)
        states.append(("guanyadors locals", winners))
        original = self._path(options, gaps, paragraph, position=0)
        states.append(("original", original))
        for state in beam:
            states.append(("feix", state))
        seen: dict[str, None] = {}
        alternatives: list[ParagraphAlternative] = []
        baseline = self._affinity(paragraph.text, paragraph.text, document)
        for origin, state in states:
            final_paragraph = Candidate(
                paragraph.index,
                state.paragraph.source_text + tail,
                state.paragraph.text + tail,
                state.paragraph.transformations,
            )
            if final_paragraph.text in seen:
                continue
            seen[final_paragraph.text] = None
            validation = self._validate(final_paragraph, paragraph.text, protected)
            score = self._scorer.score(
                final_paragraph,
                ScoringContext(validation, final_paragraph.source_text, document),
            )
            local_total = sum(
                o.total - (o.evaluated.score.components.get(AFFINITY_COMPONENT, 0.0)
                           if o.evaluated.score is not None else 0.0)
                for o in state.options
            )  # fmt: skip
            paragraph_total = score.total - score.components.get(AFFINITY_COMPONENT, 0.0)
            affinity_delta: float | None = None
            if baseline is not None:
                affinity = self._affinity(final_paragraph.text, paragraph.text, document)
                if affinity is not None:
                    affinity_delta = round(affinity - baseline, 4)
            global_total = (
                local_total
                + paragraph_total
                + (self._affinity_weight * affinity_delta if affinity_delta is not None else 0.0)
            )
            if not score.valid:
                global_total = score.total
            components = {
                **score.components,
                "frases": round(local_total, 4),
                "paragraf": round(paragraph_total, 4),
            }
            explanation = (
                f"frases {local_total:+.3f}; transformacions de paràgraf {paragraph_total:+.3f}"
            )
            if affinity_delta is not None:
                components["afinitat_paragraf"] = round(self._affinity_weight * affinity_delta, 4)
                explanation += f"; afinitat del paràgraf sencer {affinity_delta:+.3f}"
            explanation += f" → {score.explanation}"
            global_score = replace(
                score,
                total=round(global_total, 4),
                components=components,
                explanation=explanation,
            )
            evaluated = EvaluatedCandidate(final_paragraph, validation, global_score)
            alternatives.append(
                ParagraphAlternative(
                    state=state,
                    evaluated=evaluated,
                    origin=origin,
                    local_total=round(local_total, 4),
                    paragraph_total=round(paragraph_total, 4),
                    affinity_delta=affinity_delta,
                    global_total=round(global_total, 4),
                )
            )
        return alternatives

    def _path(
        self,
        options: Sequence[Sequence[LocalOption]],
        gaps: Sequence[str],
        paragraph: Paragraph,
        *,
        position: int,
    ) -> BeamState:
        """Estat sense transformacions de paràgraf: el candidat ``position`` de cada frase."""
        chosen: list[LocalOption] = []
        text = ""
        local_total = 0.0
        for group, gap in zip(options, gaps, strict=True):
            option = group[min(position, len(group) - 1)]
            chosen.append(option)
            text += gap + option.candidate.text
            local_total += option.total
        return BeamState(tuple(chosen), Candidate(paragraph.index, text, text, ()), local_total)

    def _affinity(
        self, text: str, source_text: str, document: AdaptationContext | None
    ) -> float | None:
        if self._adaptation is None or self._affinity_weight <= 0:
            return None
        affinity = self._adaptation.assess(text, context=document, source_text=source_text)
        return affinity.score if affinity.available else None

    def _select(self, alternatives: Sequence[ParagraphAlternative]) -> int:
        best = -1
        best_key: tuple[float, int, int] | None = None
        for n, alternative in enumerate(alternatives):
            if not alternative.valid:
                continue
            key = (alternative.global_total, -alternative.state.n_transformations, -n)
            if best_key is None or key > best_key:
                best, best_key = n, key
        if best < 0:
            # Cap arquitectura no supera la validació (ni l'original: només amb un
            # validador defectuós): es conserva l'original.
            best = next((n for n, a in enumerate(alternatives) if a.origin == "original"), 0)
        return best

    def _notes_for(
        self, text: str, notes: dict[str, None], rejected: dict[str, RejectedProposal]
    ) -> tuple[str, ...]:
        """Notes del text final (per què no s'hi fusiona res més) i les de la cerca."""
        ctx = self._context_factory(text)
        for rule in self._rules:
            for _proposal in rule.propose(ctx):
                pass
        combined = dict.fromkeys(ctx.notes)
        for note in notes:
            combined.setdefault(note)
        return tuple(combined)

    def _remark(
        self, inner: Sequence[SentenceResult], winner: ParagraphAlternative
    ) -> tuple[SentenceResult, ...]:
        """Frases amb el candidat que el paràgraf ha triat marcat com a seleccionat."""
        updated: list[SentenceResult] = []
        for result, option in zip(inner, winner.state.options, strict=True):
            chosen = option.evaluated
            if chosen.selected:
                updated.append(result)
                continue
            local = result.selected
            candidates = tuple(replace(e, selected=(e is chosen)) for e in result.candidates)
            local_total = local.score.total if local.score is not None else 0.0
            note = (
                f"el paràgraf ha preferit «{_shorten(chosen.candidate.text)}» "
                f"[{chosen.candidate.signature}] ({option.reason}, puntuació local "
                f"{option.total:+.3f}) al millor candidat local «{_shorten(local.candidate.text)}» "
                f"({local_total:+.3f}): dona una arquitectura de paràgraf millor"
            )
            updated.append(
                replace(
                    result,
                    output_text=chosen.candidate.text,
                    candidates=candidates,
                    notes=(*result.notes, note),
                )
            )
        return tuple(updated)


def _rank(state: BeamState) -> tuple[float, int]:
    return (-state.partial_total, state.n_transformations)


__all__ = [
    "BeamSettings",
    "BeamState",
    "LocalOption",
    "ParagraphAlternative",
    "ParagraphBeam",
    "ParagraphSearch",
    "PrunedState",
]
