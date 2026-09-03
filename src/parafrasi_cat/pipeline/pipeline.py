"""La canonada de reredacció."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from parafrasi_cat.analyzer.analysis import Analyzer, RuleBasedAnalyzer
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon
from parafrasi_cat.analyzer.paragraphs import Paragraph
from parafrasi_cat.analyzer.sentences import Sentence
from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.candidates.generator import CandidateGenerator
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import SemanticRisk, Transformation
from parafrasi_cat.morphology.provider import MorphologyProvider, NullMorphology
from parafrasi_cat.pipeline.result import (
    EvaluatedCandidate,
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
from parafrasi_cat.style.profile import StyleProfile
from parafrasi_cat.validation.base import ValidationContext, Validator
from parafrasi_cat.validation.result import ValidationResult

ProtectedConflict = Callable[[Span, str], str | None]


class Pipeline:
    """Orquestra tots els components per reredactar un text.

    Fase de frase (per a cada frase):

    1. Es calculen els fragments protegits (relatius a la frase).
    2. Cada regla de frase proposa transformacions; es descarten les que alteren
       un fragment protegit, superen el risc màxim o no arriben a la confiança mínima.
    3. Es generen candidats (identitat, transformacions soltes, combinacions i,
       si escau, reaplicació de regles sobre els millors candidats).
    4. Cada candidat passa tots els validadors (preservació factual, terminologia,
       epistemologia, gramaticalitat, longitud); els que fallen queden rebutjats.
    5. Tots els candidats es puntuen per dimensions; només els vàlids competeixen
       i se'n tria el millor de manera determinista. Si cap candidat amb canvis
       és segur, es conserva l'original.

    Fase de paràgraf (només si hi ha regles de paràgraf): sobre el text de cada
    paràgraf resultant, les regles entre frases (fusió) proposen transformacions
    que se seleccionen amb el mateix procediment i es validen contra el paràgraf
    original.

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
        lexicon: ClosedClassLexicon | None = None,
        max_level: int | None = None,
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
        if lexicon is None and isinstance(analyzer, RuleBasedAnalyzer):
            lexicon = analyzer.lexicon
        self._lexicon = lexicon

    @property
    def analyzer(self) -> Analyzer:
        return self._analyzer

    @property
    def protector(self) -> Protector:
        return self._protector

    @property
    def rule_set(self) -> RuleSet:
        return self._rule_set

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
    def lexicon(self) -> ClosedClassLexicon | None:
        return self._lexicon

    @property
    def max_level(self) -> int | None:
        return self._max_level

    # --- execució ------------------------------------------------------------------------

    def run(self, text: str) -> ParaphraseResult:
        analysis = self._analyzer.analyze(text)
        protected = self._protector.protect(text)
        sentence_results = tuple(
            self._process_sentence(sentence, protected, text) for sentence in analysis.sentences
        )
        paragraph_results: tuple[ParagraphResult, ...] = ()
        if self._rule_set.paragraph_rules and analysis.paragraphs:
            paragraph_results = tuple(
                self._process_paragraph(paragraph, sentence_results, protected, text)
                for paragraph in analysis.paragraphs
            )
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
        )

    def propose(self, text: str) -> tuple[Transformation, ...]:
        """Transformacions que les regles de frase proposen per a ``text`` (una sola frase).

        Útil per inspeccionar les regles; també és el pas d'expansió del
        generador de candidats.
        """
        analysis = self._analyzer.analyze(text)
        if len(analysis.sentences) != 1 or analysis.sentences[0].text != text:
            return ()
        sentence = analysis.sentences[0]
        ctx = self._sentence_context(sentence, self._protector.protect(text), text)
        proposals, _rejected = self._collect_proposals(ctx)
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
        )

    def _process_sentence(
        self,
        sentence: Sentence,
        protected: tuple[ProtectedSpan, ...],
        document_text: str,
    ) -> SentenceResult:
        ctx = self._sentence_context(sentence, protected, document_text)
        proposals, rejected = self._collect_proposals(ctx)
        candidates = self._generator.generate(
            sentence.index, sentence.text, proposals, expand=self.propose
        )
        validation_ctx = ValidationContext(sentence.text, ctx.protected_spans)
        evaluated, best = self._evaluate(candidates, validation_ctx)
        return SentenceResult(
            index=sentence.index,
            source_text=sentence.text,
            span=sentence.span,
            output_text=best.candidate.text,
            candidates=evaluated,
            rejected_proposals=tuple(rejected),
            protected_spans=ctx.protected_spans,
        )

    def _collect_proposals(
        self, ctx: RuleContext
    ) -> tuple[list[Transformation], list[RejectedProposal]]:
        proposals: list[Transformation] = []
        rejected: list[RejectedProposal] = []
        for rule in self._rule_set.sentence_rules:
            for transformation in rule.propose(ctx):
                reason = self._rejection_reason(transformation, ctx.text, ctx.protected_conflict)
                if reason is None:
                    proposals.append(transformation)
                else:
                    rejected.append(RejectedProposal(transformation, reason))
        return proposals, rejected

    # --- paràgrafs -----------------------------------------------------------------------

    def _process_paragraph(
        self,
        paragraph: Paragraph,
        sentence_results: tuple[SentenceResult, ...],
        protected: tuple[ProtectedSpan, ...],
        document_text: str,
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
        evaluated, best = self._evaluate(candidates, validation_ctx)
        return ParagraphResult(
            index=paragraph.index,
            source_text=paragraph.text,
            intermediate_text=intermediate,
            span=paragraph.span,
            output_text=best.candidate.text,
            candidates=evaluated,
            rejected_proposals=tuple(rejected),
            protected_spans=original_protected,
        )

    # --- comú -------------------------------------------------------------------------------

    def _evaluate(
        self, candidates: tuple[Candidate, ...], validation_ctx: ValidationContext
    ) -> tuple[tuple[EvaluatedCandidate, ...], EvaluatedCandidate]:
        evaluated: list[EvaluatedCandidate] = []
        for candidate in candidates:
            validation = ValidationResult.merge(
                validator.validate(candidate, validation_ctx) for validator in self._validators
            )
            score = self._scorer.score(
                candidate, ScoringContext(validation, validation_ctx.source_text)
            )
            evaluated.append(EvaluatedCandidate(candidate, validation, score))
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
