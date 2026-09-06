"""La canonada de reredacció."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from functools import partial

from parafrasi_cat.analyzer.analysis import Analyzer, RuleBasedAnalyzer
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon
from parafrasi_cat.analyzer.paragraphs import Paragraph
from parafrasi_cat.analyzer.sentences import Sentence
from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.candidates.generator import (
    CHAINED_RULES_KEY,
    CandidateAssessment,
    CandidateGenerator,
)
from parafrasi_cat.candidates.repair import AgreementRepair
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import SemanticRisk, Transformation
from parafrasi_cat.morphology.provider import MorphologyProvider, NullMorphology
from parafrasi_cat.pipeline.paragraph_search import BeamSettings, ParagraphBeam
from parafrasi_cat.pipeline.result import (
    EvaluatedCandidate,
    OpportunityStats,
    ParagraphOpportunities,
    ParagraphResult,
    ParaphraseResult,
    RejectedProposal,
    SentenceResult,
)
from parafrasi_cat.protected.protector import Protector
from parafrasi_cat.protected.spans import ProtectedSpan
from parafrasi_cat.rules.base import ParagraphContext, RuleContext
from parafrasi_cat.rules.ruleset import RuleSet, RuleSetConfig
from parafrasi_cat.scoring.scorer import ScoreBreakdown, Scorer, ScoringContext
from parafrasi_cat.scoring.selection import select_best
from parafrasi_cat.style.adaptation import AdaptationContext, AuthorAdaptation, UnitStats
from parafrasi_cat.style.profile import StyleProfile
from parafrasi_cat.syntax.analysis import CachedSyntax, NullSyntax, SyntaxProvider
from parafrasi_cat.validation.base import ValidationContext, Validator
from parafrasi_cat.validation.result import ValidationResult

ProtectedConflict = Callable[[Span, str], str | None]

#: Nivell màxim de transformació d'una frase que el parser no sap analitzar bé.
#: Un fragment només admet canvis lèxics i de connectors: res estructural.
FRAGMENT_MAX_LEVEL = 2


class Pipeline:
    """Orquestra tots els components per reredactar un text.

    Fase de frase (per a cada frase):

    1. Es calculen els fragments protegits (relatius a la frase).
    2. Si hi ha parser, s'analitza la frase i es mira si l'anàlisi és fiable.
       Quan no ho és, el nivell efectiu baixa a :data:`FRAGMENT_MAX_LEVEL` i
       s'apunta per què: sobre un fragment no s'hi fa res estructural.
    3. Cada regla de frase proposa transformacions; es descarten les que alteren
       un fragment protegit, superen el risc màxim o no arriben a la confiança mínima.
    4. Es generen candidats (identitat, transformacions soltes, combinacions i,
       si escau, reaplicació de regles sobre els millors candidats).
    5. Si una transformació ha trencat la concordança i la morfologia local dona
       una sola forma correcta, es repara i queda registrat com un canvi més.
    6. Cada candidat passa tots els validadors (preservació factual, terminologia,
       epistemologia, gramaticalitat, concordança, longitud); els que fallen
       queden rebutjats.
    7. Tots els candidats es puntuen per dimensions; només els vàlids competeixen
       i se'n tria el millor de manera determinista. Si cap candidat amb canvis
       és segur, es conserva l'original.

    Fase de paràgraf (només si hi ha regles de paràgraf): sobre el text de cada
    paràgraf resultant, les regles entre frases (fusió) proposen transformacions
    que se seleccionen amb el mateix procediment i es validen contra el paràgraf
    original. La fusió respecta la longitud de frase de l'autor.

    Amb ``paragraph_beam_width`` > 1 i nivell 5 (el mode profund), la fase de
    paràgraf no parteix d'un sol text intermedi: conserva uns quants candidats
    segurs i diversos de cada frase i compara arquitectures alternatives de
    paràgraf senceres amb una cerca en feix determinista
    (:mod:`parafrasi_cat.pipeline.paragraph_search`). El candidat que guanya
    localment pot perdre davant d'un que, combinat amb la frase següent, dona
    un paràgraf millor; les frases s'hi remarquen d'acord amb la tria final.

    Sense regles actives, el resultat és exactament el text d'entrada.
    """

    def __init__(
        self,
        *,
        analyzer: Analyzer,
        protector: Protector,
        rule_set: RuleSet | None = None,
        generator: CandidateGenerator | None = None,
        validators: Sequence[Validator] = (),
        scorer: Scorer,
        max_semantic_risk: SemanticRisk | None = None,
        min_confidence: float | None = None,
        style_profile: StyleProfile | None = None,
        morphology: MorphologyProvider | None = None,
        syntax: SyntaxProvider | None = None,
        lexicon: ClosedClassLexicon | None = None,
        max_level: int | None = None,
        dictionary_names: Sequence[str] = (),
        preferences_name: str = "",
        preferred_sentence_length: int | None = None,
        max_sentence_length: int | None = None,
        adaptation: AuthorAdaptation | None = None,
        source_mode: str = "own",
        paragraph_beam_width: int = 1,
        sentence_candidates_for_paragraph: int = 3,
        assertive_language: bool = False,
    ) -> None:
        self._analyzer = analyzer
        self._protector = protector
        self._rule_set = (rule_set or RuleSet(RuleSetConfig.empty(), ())).up_to_level(max_level)
        self._max_level = max_level
        self._generator = generator or CandidateGenerator()
        self._validators = tuple(validators)
        self._scorer = scorer
        self._max_risk = max_semantic_risk or self._rule_set.config.max_semantic_risk
        self._min_confidence = (
            min_confidence if min_confidence is not None else self._rule_set.config.min_confidence
        )
        self._style_profile = style_profile
        self._morphology: MorphologyProvider = morphology or NullMorphology()
        provider: SyntaxProvider = NullSyntax() if syntax is None else syntax
        if provider.available and not isinstance(provider, CachedSyntax):
            provider = CachedSyntax(provider)
        self._syntax = provider
        self._repair = AgreementRepair(self._syntax, self._morphology)
        self._preferred_sentence_length = preferred_sentence_length
        self._max_sentence_length = max_sentence_length
        self._adaptation = adaptation
        self._source_mode = source_mode
        if lexicon is None and isinstance(analyzer, RuleBasedAnalyzer):
            lexicon = analyzer.lexicon
        self._lexicon = lexicon
        self._dictionary_names = tuple(dictionary_names)
        self._preferences_name = preferences_name
        self._beam_settings = BeamSettings(
            beam_width=max(1, paragraph_beam_width),
            candidates_per_sentence=max(1, sentence_candidates_for_paragraph),
        )
        self._assertive_language = assertive_language

    @property
    def analyzer(self) -> Analyzer:
        return self._analyzer

    @property
    def beam_settings(self) -> BeamSettings:
        return self._beam_settings

    @property
    def assertive_language(self) -> bool:
        """Cert si l'opció «Llenguatge assertiu» és activa en aquesta canonada."""
        return self._assertive_language

    @property
    def searches_paragraphs(self) -> bool:
        """Cert si la fase de paràgraf compara arquitectures amb la cerca en feix."""
        if self._beam_settings.beam_width <= 1:
            return False
        if self._max_level is not None and self._max_level < 5:
            return False
        return bool(self._rule_set.paragraph_rules) or self._adaptation is not None

    @property
    def protector(self) -> Protector:
        return self._protector

    @property
    def rule_set(self) -> RuleSet:
        return self._rule_set

    @property
    def scorer(self) -> Scorer:
        return self._scorer

    @property
    def generator(self) -> CandidateGenerator:
        return self._generator

    @property
    def validators(self) -> tuple[Validator, ...]:
        return self._validators

    @property
    def style_profile(self) -> StyleProfile | None:
        return self._style_profile

    @property
    def max_semantic_risk(self) -> SemanticRisk:
        return self._max_risk

    @property
    def min_confidence(self) -> float:
        return self._min_confidence

    @property
    def syntax(self) -> SyntaxProvider:
        return self._syntax

    @property
    def lexicon(self) -> ClosedClassLexicon | None:
        return self._lexicon

    @property
    def max_level(self) -> int | None:
        return self._max_level

    @property
    def repair(self) -> AgreementRepair:
        """Reparador de concordança (inactiu sense parser o sense morfologia)."""
        return self._repair

    @property
    def adaptation(self) -> AuthorAdaptation | None:
        """Adaptació autoral (només en mode d'esborrany generat amb LLM)."""
        return self._adaptation

    @property
    def source_mode(self) -> str:
        return self._source_mode

    @property
    def dictionary_names(self) -> tuple[str, ...]:
        return self._dictionary_names

    @property
    def preferences_name(self) -> str:
        return self._preferences_name

    # --- execució ------------------------------------------------------------------------

    def run(self, text: str) -> ParaphraseResult:
        analysis = self._analyzer.analyze(text)
        protected = self._protector.protect(text)
        stats = self._unit_stats(analysis.sentences)
        sentence_results = tuple(
            self._process_sentence(sentence, protected, text, _context(stats, {sentence.index}))
            for sentence in analysis.sentences
        )
        paragraph_results: tuple[ParagraphResult, ...] = ()
        searching = self.searches_paragraphs
        if analysis.paragraphs and (self._rule_set.paragraph_rules or searching):
            beam = self._paragraph_beam() if searching else None
            updated = list(sentence_results)
            collected: list[ParagraphResult] = []
            for paragraph in analysis.paragraphs:
                positions = [
                    n for n, s in enumerate(sentence_results) if paragraph.span.contains(s.span)
                ]
                document = _context(stats, {sentence_results[n].index for n in positions})
                if beam is not None and positions:
                    result, remarked = beam.search(
                        paragraph,
                        [sentence_results[n] for n in positions],
                        Protector.within(protected, paragraph.span),
                        document,
                    )
                    for n, sentence_result in zip(positions, remarked, strict=True):
                        updated[n] = sentence_result
                else:
                    result = self._process_paragraph(
                        paragraph, sentence_results, protected, text, document
                    )
                collected.append(result)
            sentence_results = tuple(updated)
            paragraph_results = tuple(collected)
            output = _reassemble(text, tuple((p.span, p.output_text) for p in paragraph_results))
        else:
            output = _reassemble(text, tuple((s.span, s.output_text) for s in sentence_results))
        return ParaphraseResult(
            source_text=text,
            output_text=output,
            sentences=sentence_results,
            protected_spans=protected,
            rule_set_name=self._rule_set.config.name,
            rule_ids=self._rule_set.rule_ids,
            style_profile_name=self._style_profile.name if self._style_profile else "",
            paragraphs=paragraph_results,
            dictionary_names=self._dictionary_names,
            preferences_name=self._preferences_name,
            source_mode=self._source_mode,
            assertive_language=self._assertive_language,
        )

    def _unit_stats(self, sentences: Sequence[Sentence]) -> dict[int, UnitStats]:
        """Recomptes de cada frase original, per donar context a l'afinitat autoral."""
        if self._adaptation is None:
            return {}
        return {s.index: self._adaptation.stats_of(s.text) for s in sentences}

    def propose(self, text: str, *, max_level: int | None = None) -> tuple[Transformation, ...]:
        """Transformacions que les regles de frase proposen per a ``text`` (una sola frase).

        Útil per inspeccionar les regles; també és el pas d'expansió del
        generador de candidats, que hi arrossega el nivell màxim decidit per a
        la frase original.
        """
        analysis = self._analyzer.analyze(text)
        if len(analysis.sentences) != 1 or analysis.sentences[0].text != text:
            return ()
        sentence = analysis.sentences[0]
        ctx = self._sentence_context(sentence, self._protector.protect(text), text)
        proposals, _rejected = self._collect_proposals(ctx, max_level)
        return tuple(proposals)

    # --- frases --------------------------------------------------------------------------

    def _sentence_context(
        self, sentence: Sentence, protected: tuple[ProtectedSpan, ...], document_text: str
    ) -> RuleContext:
        return RuleContext(
            sentence=sentence,
            protected_spans=Protector.within(protected, sentence.span),
            document_text=document_text,
            style_profile=self._style_profile,
            morphology=self._morphology,
            lexicon=self._lexicon,
            syntax=self._syntax,
            analysis=self._syntax.parse(sentence.text) if self._syntax.available else None,
        )

    def _level_for(self, ctx: RuleContext) -> int | None:
        """Nivell màxim per a aquesta frase segons la confiança del parser.

        Si el parser hi és i no es refia de l'anàlisi (frase fragmentària,
        estructura incompleta, contradiccions), no s'hi autoritza res
        estructural: es baixa el nivell efectiu i s'apunta per què.
        """
        analysis = ctx.analysis
        if analysis is None or analysis.confident:
            return self._max_level
        ctx.note(
            f"{analysis.confidence.describe()}; només s'han provat transformacions "
            f"fins al nivell {FRAGMENT_MAX_LEVEL}"
        )
        if self._max_level is None:
            return FRAGMENT_MAX_LEVEL
        return min(self._max_level, FRAGMENT_MAX_LEVEL)

    def _process_sentence(
        self,
        sentence: Sentence,
        protected: tuple[ProtectedSpan, ...],
        document_text: str,
        document: AdaptationContext | None = None,
    ) -> SentenceResult:
        ctx = self._sentence_context(sentence, protected, document_text)
        max_level = self._level_for(ctx)
        proposals, rejected = self._collect_proposals(ctx, max_level)
        validation_ctx = ValidationContext(sentence.text, ctx.protected_spans)
        # La reparació, la validació i la puntuació es fan **abans** de repartir les
        # places: un candidat que no supera la validació no n'ha d'ocupar cap que
        # podria aprofitar una alternativa vàlida. La memòria cau fa que després no
        # es torni a validar ni a puntuar res.
        assess, cache = self._admission(validation_ctx, ctx.protected_conflict, document)
        search = self._generator.search(
            sentence.index,
            sentence.text,
            proposals,
            expand=partial(self.propose, max_level=max_level),
            admissible=assess,
        )
        evaluated, best = self._evaluate(
            (*search.candidates, *search.rejected), validation_ctx, document, cache
        )
        return SentenceResult(
            index=sentence.index,
            source_text=sentence.text,
            span=sentence.span,
            output_text=best.candidate.text,
            candidates=evaluated,
            rejected_proposals=tuple(rejected),
            protected_spans=ctx.protected_spans,
            notes=tuple(ctx.notes),
            opportunities=_opportunities(len(proposals), len(rejected), evaluated, best),
            generation=search.trace,
        )

    def _admission(
        self,
        validation_ctx: ValidationContext,
        protected_conflict: ProtectedConflict,
        document: AdaptationContext | None,
    ) -> tuple[Callable[[Candidate], CandidateAssessment], dict[str, EvaluatedCandidate]]:
        """Funció que repara, valida i puntua un candidat, amb la seva memòria cau.

        Es consulta mentre es reparteixen les places i, després, la mateixa cau
        serveix el resultat: cada candidat es valida i es puntua una sola vegada.
        """
        cache: dict[str, EvaluatedCandidate] = {}

        def assess(candidate: Candidate) -> CandidateAssessment:
            repaired = candidate
            if self._repair.available:
                repaired = self._repair.repair(candidate, protected_conflict=protected_conflict)
            evaluated = cache.get(repaired.text)
            if evaluated is None:
                evaluated = self._evaluated(repaired, validation_ctx, document)
                cache[repaired.text] = evaluated
            score = evaluated.score
            return CandidateAssessment(
                candidate=evaluated.candidate,
                valid=evaluated.accepted,
                total=score.total if score is not None else 0.0,
                reason=evaluated.rejection_reason,
            )

        return assess, cache

    def _evaluated(
        self,
        candidate: Candidate,
        validation_ctx: ValidationContext,
        document: AdaptationContext | None,
    ) -> EvaluatedCandidate:
        validation = ValidationResult.merge(
            validator.validate(candidate, validation_ctx) for validator in self._validators
        )
        score = self._scorer.score(
            candidate, ScoringContext(validation, validation_ctx.source_text, document)
        )
        return EvaluatedCandidate(candidate, validation, score)

    def _collect_proposals(
        self, ctx: RuleContext, max_level: int | None = None
    ) -> tuple[list[Transformation], list[RejectedProposal]]:
        proposals: list[Transformation] = []
        rejected: list[RejectedProposal] = []
        for rule in self._rule_set.sentence_rules:
            if max_level is not None and rule.level > max_level:
                continue
            for transformation in rule.propose(ctx):
                reason = self._rejection_reason(transformation, ctx.text, ctx.protected_conflict)
                if reason is None:
                    proposals.append(transformation)
                else:
                    rejected.append(RejectedProposal(transformation, reason))
        return proposals, rejected

    # --- paràgrafs -----------------------------------------------------------------------

    def _paragraph_context(self, text: str) -> ParagraphContext:
        """Context de regles de paràgraf per a un text de paràgraf qualsevol."""
        analysis = self._analyzer.analyze(text)
        return ParagraphContext(
            text=text,
            sentences=analysis.sentences,
            protected_spans=self._protector.protect(text),
            source_text=text,
            lexicon=self._lexicon,
            syntax=self._syntax,
            style_profile=self._style_profile,
            preferred_sentence_length=self._preferred_sentence_length,
            max_sentence_length=self._max_sentence_length,
        )

    def _paragraph_beam(self) -> ParagraphBeam:
        weights = getattr(self._scorer, "weights", None)
        affinity_weight = float(getattr(weights, "author_affinity", 0.0)) if weights else 0.0
        balance_weight = float(getattr(weights, "coverage_balance", 0.0)) if weights else 0.0
        return ParagraphBeam(
            settings=replace(self._beam_settings, coverage_balance=balance_weight),
            generator=self._generator,
            scorer=self._scorer,
            validators=self._validators,
            paragraph_rules=self._rule_set.paragraph_rules,
            context_factory=self._paragraph_context,
            rejection_reason=self._rejection_reason,
            adaptation=self._adaptation,
            affinity_weight=affinity_weight,
            connectors=getattr(self._scorer, "connectors", None),
        )

    def _process_paragraph(
        self,
        paragraph: Paragraph,
        sentence_results: tuple[SentenceResult, ...],
        protected: tuple[ProtectedSpan, ...],
        document_text: str,
        document: AdaptationContext | None = None,
    ) -> ParagraphResult:
        inner = tuple(r for r in sentence_results if paragraph.span.contains(r.span))
        intermediate = _reassemble(
            paragraph.text,
            tuple((r.span.shift(-paragraph.span.start), r.output_text) for r in inner),
        )
        original_protected = Protector.within(protected, paragraph.span)
        analysis = self._analyzer.analyze(intermediate)
        ctx = ParagraphContext(
            text=intermediate,
            sentences=analysis.sentences,
            protected_spans=self._protector.protect(intermediate),
            source_text=paragraph.text,
            lexicon=self._lexicon,
            syntax=self._syntax,
            style_profile=self._style_profile,
            preferred_sentence_length=self._preferred_sentence_length,
            max_sentence_length=self._max_sentence_length,
        )
        proposals: list[Transformation] = []
        rejected: list[RejectedProposal] = []
        for rule in self._rule_set.paragraph_rules:
            for transformation in rule.propose(ctx):
                reason = self._rejection_reason(transformation, ctx.text, ctx.protected_conflict)
                if reason is None:
                    proposals.append(transformation)
                else:
                    rejected.append(RejectedProposal(transformation, reason))
        candidates = self._generator.generate(paragraph.index, intermediate, proposals)
        validation_ctx = ValidationContext(paragraph.text, original_protected)
        evaluated, best = self._evaluate(candidates, validation_ctx, document)
        fusions = sum(
            1
            for e in evaluated
            if e.accepted and e.candidate.n_transformations == 1 and e.candidate.is_structural
        )
        return ParagraphResult(
            index=paragraph.index,
            source_text=paragraph.text,
            intermediate_text=intermediate,
            span=paragraph.span,
            output_text=best.candidate.text,
            candidates=evaluated,
            rejected_proposals=tuple(rejected),
            protected_spans=original_protected,
            notes=tuple(ctx.notes),
            opportunities=ParagraphOpportunities(
                safe=sum(r.opportunities.safe for r in inner) + fusions,
                structural=sum(1 for r in inner if r.opportunities.structural) + fusions,
                fusion=fusions,
                split=sum(
                    1
                    for r in inner
                    for e in r.candidates
                    if e.accepted
                    and e.candidate.n_transformations == 1
                    and any(t.family.cross_sentence for t in e.candidate.transformations)
                ),
                beam_candidates=len(evaluated),
                distribution_of_change=tuple(
                    r.selected.candidate.structural_degree() for r in inner
                ),
            ),
        )

    # --- comú -------------------------------------------------------------------------------

    def _evaluate(
        self,
        candidates: tuple[Candidate, ...],
        validation_ctx: ValidationContext,
        document: AdaptationContext | None = None,
        cache: dict[str, EvaluatedCandidate] | None = None,
    ) -> tuple[tuple[EvaluatedCandidate, ...], EvaluatedCandidate]:
        evaluated: list[EvaluatedCandidate] = []
        for candidate in candidates:
            known = cache.get(candidate.text) if cache is not None else None
            if known is not None:
                evaluated.append(known)
                continue
            evaluated.append(self._evaluated(candidate, validation_ctx, document))
        accepted = [e for e in evaluated if e.accepted]
        best = select_best(accepted, lambda e: e.candidate, _score_of)
        if best is None:
            # Si cap candidat supera la validació (ni tan sols la identitat, cosa que
            # només passaria amb un validador defectuós), es conserva l'original.
            best = evaluated[0]
        marked = tuple(replace(e, selected=e is best) for e in evaluated)
        return marked, next(e for e in marked if e.selected)

    def _rejection_reason(
        self,
        transformation: Transformation,
        text: str,
        protected_conflict: ProtectedConflict,
    ) -> str | None:
        if transformation.is_identity:
            return "no canvia res"
        if not transformation.can_apply_to(text):
            return "el fragment indicat no coincideix amb el text"
        conflict = protected_conflict(transformation.changed_span, transformation.text_after)
        if conflict is not None:
            return conflict
        if transformation.semantic_risk.exceeds(self._max_risk):
            return (
                f"risc semàntic «{transformation.semantic_risk.value}» superior al màxim permès "
                f"«{self._max_risk.value}»"
            )
        if transformation.confidence < self._min_confidence:
            return (
                f"confiança {transformation.confidence:.2f} inferior al mínim "
                f"{self._min_confidence:.2f}"
            )
        return None


def _context(stats: Mapping[int, UnitStats], own: set[int]) -> AdaptationContext | None:
    """La resta del document, en ordre: abans i després de la unitat que es puntua."""
    if not stats or not own:
        return None
    first, last = min(own), max(own)
    return AdaptationContext(
        before=UnitStats.total(value for index, value in sorted(stats.items()) if index < first),
        after=UnitStats.total(value for index, value in sorted(stats.items()) if index > last),
    )


def _opportunities(
    n_proposals: int,
    n_rejected: int,
    evaluated: Sequence[EvaluatedCandidate],
    best: EvaluatedCandidate,
) -> OpportunityStats:
    """Recompte d'oportunitats d'una frase a partir dels candidats d'una sola transformació.

    Una transformació encadenada (una regla reaplicada sobre el resultat d'una
    altra) no és cap oportunitat nova de l'original: no hi compta.
    """
    singles = [
        e
        for e in evaluated
        if e.candidate.n_transformations == 1
        and not e.candidate.transformations[0].metadata.get(CHAINED_RULES_KEY)
    ]
    safe = [e for e in singles if e.accepted]
    structural = sum(1 for e in safe if e.candidate.is_structural)
    return OpportunityStats(
        detected=n_proposals + n_rejected,
        rejected_proposals=n_rejected,
        safe=len(safe),
        structural=structural,
        surface=len(safe) - structural,
        unsafe=len(singles) - len(safe),
        selected_family=best.candidate.signature,
        selected_is_original=best.candidate.is_identity,
    )


def _score_of(evaluated: EvaluatedCandidate) -> ScoreBreakdown:
    if evaluated.score is None:  # pragma: no cover - només s'invoca amb candidats acceptats
        raise ValueError("El candidat no té puntuació")
    return evaluated.score


def _reassemble(text: str, pieces: Sequence[tuple[Span, str]]) -> str:
    """Substitueix cada interval pel text nou, conservant tot el que hi ha entremig."""
    parts: list[str] = []
    cursor = 0
    for span, replacement in sorted(pieces, key=lambda item: item[0].start):
        parts.append(text[cursor : span.start])
        parts.append(replacement)
        cursor = span.end
    parts.append(text[cursor:])
    return "".join(parts)
