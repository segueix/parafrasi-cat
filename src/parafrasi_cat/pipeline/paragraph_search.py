"""Cerca en feix d'arquitectures alternatives de paràgraf (nivell 5, mode profund).

Frase per frase, la canonada tria un candidat i el paràgraf es reconstrueix amb
aquests guanyadors locals: un òptim local que fa desaparèixer massa aviat les
alternatives. Un candidat que queda segon en una frase pot ser el que permet
una fusió segura amb la frase següent o el que dona al paràgraf sencer el
ritme de l'autor, i el nivell 5 no arribava a veure-ho.

Aquí, en lloc d'un sol text intermedi, es conserven uns quants candidats
**segurs i diversos** de cada frase (l'original, el millor local, el millor de
cada signatura estructural i, quan hi ha marge, més d'una variant segura de
connector) i es construeixen arquitectures de paràgraf amb una cerca en feix
determinista i acotada:

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

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from parafrasi_cat.analyzer.paragraphs import Paragraph
from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.candidates.generator import CandidateGenerator
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import Transformation, TransformationFamily
from parafrasi_cat.pipeline.result import (
    EvaluatedCandidate,
    ParagraphOpportunities,
    ParagraphResult,
    RejectedProposal,
    SentenceResult,
)
from parafrasi_cat.protected.spans import ProtectedSpan
from parafrasi_cat.rules.base import ParagraphContext, ParagraphRule
from parafrasi_cat.scoring.scorer import (
    CONNECTOR_COMPONENT,
    ScoreBreakdown,
    Scorer,
    ScoringContext,
)
from parafrasi_cat.style.adaptation import AdaptationContext, AuthorAdaptation
from parafrasi_cat.style.connector_repetition import ConnectorRepetition
from parafrasi_cat.validation.base import ValidationContext, Validator
from parafrasi_cat.validation.result import ValidationResult

ProtectedConflict = Callable[[Span, str], str | None]
RejectionReason = Callable[[Transformation, str, ProtectedConflict], str | None]
ContextFactory = Callable[[str], ParagraphContext]

AFFINITY_COMPONENT = "afinitat_autor"
CONNECTOR_SIGNATURE = "CONNECTOR"
CONNECTOR_VARIANTS_PER_SENTENCE = 2
"""Màxim de candidats transformats de connector que el feix conserva per frase."""
CONNECTOR_PROFILE_TAIL = 2
"""Connectors recents que identifiquen el perfil d'un estat dins de la poda."""
WITHDRAWN_COMPONENT = "guany_repeticio_connectors"
"""Guany retirat a les frases que recreen una repetició de connector."""
_SHORT = 60


def _shorten(text: str, limit: int = _SHORT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass(frozen=True, slots=True)
class LocalOption:
    """Un candidat de frase conservat per al feix, i per què."""

    sentence_index: int
    evaluated: EvaluatedCandidate
    reason: str
    connectors: tuple[str, ...] = ()
    """Connectors de l'inventari que conté aquest candidat, en ordre."""

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
        # El prefix ja té una puntuació d'estil: no hi sumem de nou les
        # distàncies de cada frase (que afavoreixen repetir la forma més habitual).
        local_style = (
            sum(
                o.evaluated.score.components.get("estil", 0.0)
                for o in self.options
                if o.evaluated.score is not None
            )
            if self.paragraph_score is not None
            else 0.0
        )
        return round(self.local_total - local_style + paragraph, 4)

    @property
    def n_transformations(self) -> int:
        return sum(o.candidate.n_transformations for o in self.options) + len(
            self.paragraph.transformations
        )

    @property
    def signatures(self) -> tuple[str, ...]:
        return tuple(o.candidate.signature for o in self.options)

    @property
    def connector_profile(self) -> tuple[str, ...]:
        """Connectors triats fins ara, en ordre: dues arquitectures amb la mateixa
        signatura estructural poden diferir només en això."""
        return tuple(form for option in self.options for form in option.connectors)

    @property
    def connector_key(self) -> tuple[str, ...]:
        """Clau compacta del perfil: els darrers connectors, que són els que decideixen
        si la frase següent repetirà una forma o no."""
        return self.connector_profile[-CONNECTOR_PROFILE_TAIL:]

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
    distribution: tuple[float, ...] = ()
    """Grau estructural del candidat triat a cada frase (0 = original)."""
    coverage_balance: float | None = None
    """Repartiment de la reredacció entre les frases amb alternatives segures (0-1)."""

    @property
    def connectors(self) -> dict[str, object]:
        """Perfil de connectors, repeticions detectades i quines són noves."""
        score = self.evaluated.score
        return dict(score.connectors) if score is not None else {}

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
            "distribution_of_change": list(self.distribution),
            "coverage_balance": self.coverage_balance,
            "connectors": self.connectors,
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
    fusions: int = 0
    """Fusions de paràgraf que han superat la validació provisional dins del feix."""

    @property
    def structural_opportunities(self) -> tuple[int, ...]:
        """Índexs (dins del paràgraf) de les frases amb alguna alternativa estructural segura."""
        return tuple(
            n
            for n, group in enumerate(self.options)
            if any(o.candidate.is_structural for o in group)
        )

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
            "fusions": self.fusions,
            "structural_opportunities": list(self.structural_opportunities),
        }


@dataclass(frozen=True, slots=True)
class BeamSettings:
    beam_width: int = 6
    candidates_per_sentence: int = 3
    max_pruned_recorded: int = 24
    coverage_balance: float = 0.0
    """Pes del balanç de cobertura a la puntuació global (0 = cap)."""


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
        connectors: ConnectorRepetition | None = None,
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
        self._connectors = connectors

    @property
    def settings(self) -> BeamSettings:
        return self._settings

    # --- candidats locals -------------------------------------------------------------------

    def local_options(self, result: SentenceResult) -> tuple[LocalOption, ...]:
        """Candidats segurs i diversos d'una frase, sense perdre variants de connector.

        L'original sempre es conserva. Entre els candidats transformats entren el
        millor local, les signatures estructurals diferents i, si hi ha marge, fins
        a dues redaccions de connector diferents encara que comparteixin la mateixa
        signatura ``CONNECTOR``. Això evita que, per exemple, «ja que» desaparegui
        abans que el paràgraf pugui comparar-lo amb «atès que» i penalitzar-ne la
        repetició. Després s'omplen els llocs restants amb altres signatures
        superficials. Mai més de ``candidates_per_sentence`` alternatives a més de
        l'original.
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
        seen_signatures: set[str] = set()
        connector_variants: set[str] = set()
        chosen: list[LocalOption] = []

        def remember_connector(candidate: Candidate) -> None:
            if candidate.signature == CONNECTOR_SIGNATURE:
                connector_variants.add(candidate.normalized_text())

        if ranked and room > 0:
            best = ranked[0]
            chosen.append(LocalOption(result.index, best, "millor local"))
            seen_signatures.add(best.candidate.signature)
            remember_connector(best.candidate)

        # La diversitat estructural continua tenint prioritat: no sacrifiquem una
        # reordenació o una divisió segura només per conservar un sinònim de connector.
        for evaluated in ranked:
            if len(chosen) >= room:
                break
            candidate = evaluated.candidate
            if not candidate.is_structural or candidate.signature in seen_signatures:
                continue
            seen_signatures.add(candidate.signature)
            chosen.append(LocalOption(result.index, evaluated, f"millor {candidate.signature}"))

        # Excepció deliberada a «un candidat per signatura»: dos connectors
        # equivalents poden necessitar arribar al paràgraf complet perquè la
        # no-repetició i l'empremta decideixin quin combina millor amb els veïns.
        connector_count = sum(
            1 for option in chosen if option.candidate.signature == CONNECTOR_SIGNATURE
        )
        for evaluated in ranked:
            if len(chosen) >= room or connector_count >= CONNECTOR_VARIANTS_PER_SENTENCE:
                break
            candidate = evaluated.candidate
            if candidate.signature != CONNECTOR_SIGNATURE:
                continue
            variant = candidate.normalized_text()
            if variant in connector_variants:
                continue
            connector_variants.add(variant)
            seen_signatures.add(candidate.signature)
            connector_count += 1
            chosen.append(LocalOption(result.index, evaluated, "variant segura de connector"))

        # Finalment, una alternativa per cada altra signatura superficial.
        for evaluated in ranked:
            if len(chosen) >= room:
                break
            candidate = evaluated.candidate
            if candidate.is_structural or candidate.signature in seen_signatures:
                continue
            seen_signatures.add(candidate.signature)
            chosen.append(LocalOption(result.index, evaluated, f"millor {candidate.signature}"))
        return tuple(self._with_profile(option) for option in (*options, *chosen))

    def _with_profile(self, option: LocalOption) -> LocalOption:
        """Anota quins connectors de l'inventari conté el candidat."""
        if self._connectors is None:
            return option
        return replace(option, connectors=self._connectors.profile(option.candidate.text))

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
        # Prefix del paràgraf **original** després de cada frase: és la referència amb
        # què es compara la repetició de connectors mentre el feix creix.
        originals: list[str] = []
        prefix = ""
        for gap, sentence in zip(gaps, inner, strict=True):
            prefix += gap + sentence.source_text
            originals.append(prefix)

        explored = 0
        pruned: list[PrunedState] = []
        rejected: dict[str, RejectedProposal] = {}
        notes: dict[str, None] = {}
        fusions = 0
        beam: list[BeamState] = [
            BeamState((), Candidate(paragraph.index, "", "", ()), 0.0, kept_for="inici")
        ]
        for index, group in enumerate(options):
            extended: list[BeamState] = []
            for state in beam:
                for option in group:
                    grown = self._extend(
                        state, option, gaps[index], originals[index], paragraph, rejected, notes
                    )
                    already = len(state.paragraph.transformations)
                    fusions += sum(1 for g in grown if len(g.paragraph.transformations) > already)
                    extended.extend(grown)
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
            fusions=fusions,
        )
        opportunities = ParagraphOpportunities(
            safe=sum(r.opportunities.safe for r in inner) + fusions,
            structural=len(search.structural_opportunities) + fusions,
            fusion=fusions,
            split=sum(
                1
                for group in options
                if any(
                    any(t.family.cross_sentence for t in o.candidate.transformations) for o in group
                )
            ),
            beam_candidates=len(alternatives),
            distribution_of_change=winner.distribution,
            coverage_balance=winner.coverage_balance,
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
            opportunities=opportunities,
        )
        return result, self._remark(inner, winner)

    def _extend(
        self,
        state: BeamState,
        option: LocalOption,
        gap: str,
        original: str,
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
        # El prefix es puntua contra el prefix original: així la repetició de
        # connectors que el candidat introdueix ja compta mentre el feix creix, i no
        # només al final.
        base_score = self._scorer.score(extended, ScoringContext(None, original, None))
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
                score = self._scorer.score(composed, ScoringContext(validation, original, None))
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
        combinar-se amb la frase següent); el millor estat de cada perfil de
        connectors recent; la resta per puntuació parcial.

        Les dues primeres capes miren la frase que s'acaba d'afegir; la tercera
        mira l'historial, perquè dues arquitectures poden tenir les mateixes
        signatures i el mateix candidat final i diferir només en un connector
        triat unes quantes frases enrere («atès que… atès que» contra «atès
        que… ja que»). Sense aquesta capa, la que puntua una mil·lèsima menys
        mor abans que el paràgraf sencer pugui comparar-les. Tot continua acotat
        per l'amplada del feix: cap capa no n'afegeix ni un estat de més.
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
        seen_profiles = {state.connector_key for state in kept}
        for state in ranked:
            if len(kept) >= width:
                break
            key = state.connector_key
            if id(state) in reasons or key in seen_profiles:
                continue
            seen_profiles.add(key)
            kept.append(state)
            reasons[id(state)] = "millor estat amb connectors " + (
                ", ".join(f"«{form}»" for form in key) if key else "sense connectors"
            )
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
        # Frases amb alguna alternativa estructural segura: només aquestes compten
        # per al balanç de cobertura (una frase sense alternativa no hi resta res).
        structural_sentences = [
            n for n, group in enumerate(options) if any(o.candidate.is_structural for o in group)
        ]
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
                ScoringContext(validation, paragraph.text, document),
            )
            # L'estil, l'afinitat i la repetició són propietats del paràgraf
            # sencer: es descompten de les puntuacions de frase (on només se'n podia
            # veure una aproximació) i es tornen a comptar una sola vegada sobre
            # l'arquitectura completa, mesurades contra el paràgraf original.
            local_total = sum(o.total - _paragraph_scale_components(o) for o in state.options)
            paragraph_total = score.total - score.components.get(AFFINITY_COMPONENT, 0.0)
            affinity_delta: float | None = None
            if baseline is not None:
                affinity = self._affinity(final_paragraph.text, paragraph.text, document)
                if affinity is not None:
                    affinity_delta = round(affinity - baseline, 4)
            distribution = tuple(o.candidate.structural_degree() for o in state.options)
            balance = _coverage_balance(distribution, structural_sentences)
            balance_bonus = (
                self._settings.coverage_balance * balance if balance is not None else 0.0
            )
            # Un canvi de connector que recrea una repetició no és cap millora: se li
            # retira, en proporció a la severitat, el guany que cobrava per haver-lo
            # fet. Sense això, afegir un segon canvi idèntic sempre compensaria la
            # penalització, per petita que sigui la repetició resultant.
            withdrawn = self._withdrawn_gain(state, score)
            global_total = (
                local_total
                + paragraph_total
                + (self._affinity_weight * affinity_delta if affinity_delta is not None else 0.0)
                + balance_bonus
                - withdrawn
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
            if balance is not None and self._settings.coverage_balance > 0:
                components["balanc_cobertura"] = round(balance_bonus, 4)
                explanation += f"; balanç de cobertura {balance:.2f}"
            if withdrawn:
                components[WITHDRAWN_COMPONENT] = round(-withdrawn, 4)
                explanation += f"; guany retirat per repetició de connectors {-withdrawn:+.3f}"
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
                    distribution=distribution,
                    coverage_balance=balance,
                )
            )
        return alternatives

    def _withdrawn_gain(self, state: BeamState, score: ScoreBreakdown) -> float:
        """Guany que perden les frases que porten la forma repetida de nou.

        Si el paràgraf introdueix una repetició de connector, les frases que
        contenen la forma repetida deixen de cobrar (en proporció a la severitat)
        el premi que els donava aquell canvi. No hi ha cap constant nova: es
        retira exactament el guany que el mateix puntuador havia concedit.
        """
        detail = score.connectors
        penalty = detail.get("penalty") if detail else None
        severity = float(penalty) if isinstance(penalty, (int, float)) else 0.0
        if severity <= 0.0:
            return 0.0
        introduced = detail.get("introduced")
        forms = (
            {str(item["form"]) for item in introduced if isinstance(item, dict)}
            if isinstance(introduced, list)
            else set()
        )
        gain_of = getattr(self._scorer, "transformation_gain", None)
        if not forms or gain_of is None:
            return 0.0
        total = 0.0
        for option in state.options:
            if not forms.intersection(option.connectors):
                continue
            connectors = [
                t
                for t in option.candidate.transformations
                if t.family is TransformationFamily.CONNECTOR
            ]
            if connectors:
                total += gain_of(connectors)
        return round(severity * total, 4)

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


def _coverage_balance(distribution: Sequence[float], sentences: Sequence[int]) -> float | None:
    """Repartiment de la reredacció entre les frases amb alternatives segures (0-1).

    Mitjana de l'arrel del grau estructural de cada frase amb oportunitats,
    elevada al quadrat: amb el mateix canvi total, repartir-lo entre més frases
    puntua més que concentrar-lo en una. Sense cap frase amb oportunitats no
    hi ha res a repartir (``None``), i una frase sense alternativa segura no
    hi entra mai.
    """
    if not sentences:
        return None
    total = sum(math.sqrt(max(0.0, min(1.0, distribution[n]))) for n in sentences)
    return round((total / len(sentences)) ** 2, 4)


def _paragraph_scale_components(option: LocalOption) -> float:
    """Part de la puntuació de frase que es tornarà a mesurar sobre el paràgraf.

    L'estil, l'afinitat amb l'autor i la repetició de connectors depenen del text del
    voltant: mesurades frase a frase només en són una aproximació, i sumar-les
    aquí i tornar-les a comptar sobre l'arquitectura completa seria comptar dues
    vegades el mateix fenomen.
    """
    score = option.evaluated.score
    if score is None:
        return 0.0
    return sum(
        score.components.get(name, 0.0)
        for name in ("estil", AFFINITY_COMPONENT, CONNECTOR_COMPONENT)
    )


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
