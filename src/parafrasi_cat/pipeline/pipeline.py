"""La canonada de reredacció."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from parafrasi_cat.analyzer.analysis import Analyzer
from parafrasi_cat.analyzer.sentences import Sentence
from parafrasi_cat.candidates.generator import CandidateGenerator
from parafrasi_cat.core.transformation import SemanticRisk, Transformation
from parafrasi_cat.morphology.provider import MorphologyProvider, NullMorphology
from parafrasi_cat.pipeline.result import (
    EvaluatedCandidate,
    ParaphraseResult,
    RejectedProposal,
    SentenceResult,
)
from parafrasi_cat.protected.protector import Protector
from parafrasi_cat.protected.spans import ProtectedSpan
from parafrasi_cat.rules.base import RuleContext
from parafrasi_cat.rules.ruleset import RuleSet, RuleSetConfig
from parafrasi_cat.scoring.scorer import ScoreBreakdown, Scorer
from parafrasi_cat.scoring.selection import select_best
from parafrasi_cat.style.profile import StyleProfile
from parafrasi_cat.validation.base import ValidationContext, Validator
from parafrasi_cat.validation.result import ValidationResult


class Pipeline:
    """Orquestra tots els components per reredactar un text frase a frase.

    Per a cada frase:

    1. Es calculen els fragments protegits (relatius a la frase).
    2. Cada regla activa proposa transformacions; es descarten les que toquen
       fragments protegits, superen el risc màxim o no arriben a la confiança mínima.
    3. Es generen candidats (sempre inclòs el candidat identitat).
    4. Cada candidat passa tots els validadors; els que fallen queden rebutjats.
    5. Els candidats vàlids es puntuen i se'n tria el millor de manera determinista.

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
    ) -> None:
        self._analyzer = analyzer
        self._protector = protector
        self._rule_set = rule_set or RuleSet(RuleSetConfig.empty(), ())
        self._generator = generator or CandidateGenerator()
        self._validators = tuple(validators)
        self._scorer = scorer
        self._max_risk = max_semantic_risk or self._rule_set.config.max_semantic_risk
        self._min_confidence = (
            min_confidence if min_confidence is not None else self._rule_set.config.min_confidence
        )
        self._style_profile = style_profile
        self._morphology: MorphologyProvider = morphology or NullMorphology()

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

    def run(self, text: str) -> ParaphraseResult:
        analysis = self._analyzer.analyze(text)
        protected = self._protector.protect(text)
        results = tuple(
            self._process_sentence(sentence, protected, text) for sentence in analysis.sentences
        )
        return ParaphraseResult(
            source_text=text,
            output_text=_reassemble(text, results),
            sentences=results,
            protected_spans=protected,
            rule_set_name=self._rule_set.config.name,
            rule_ids=self._rule_set.rule_ids,
            style_profile_name=self._style_profile.name if self._style_profile else "",
        )

    def _process_sentence(
        self,
        sentence: Sentence,
        protected: tuple[ProtectedSpan, ...],
        document_text: str,
    ) -> SentenceResult:
        local_protected = Protector.within(protected, sentence.span)
        ctx = RuleContext(
            sentence=sentence,
            protected_spans=local_protected,
            document_text=document_text,
            style_profile=self._style_profile,
            morphology=self._morphology,
        )
        proposals, rejected = self._collect_proposals(ctx)
        candidates = self._generator.generate(sentence.index, sentence.text, proposals)

        validation_ctx = ValidationContext(sentence.text, local_protected)
        evaluated: list[EvaluatedCandidate] = []
        for candidate in candidates:
            validation = ValidationResult.merge(
                validator.validate(candidate, validation_ctx) for validator in self._validators
            )
            score = self._scorer.score(candidate) if validation.ok else None
            evaluated.append(EvaluatedCandidate(candidate, validation, score))

        accepted = [e for e in evaluated if e.accepted]
        best = select_best(accepted, lambda e: e.candidate, _score_of)
        if best is None:
            # Si cap candidat supera la validació (ni tan sols la identitat, cosa que
            # només passaria amb un validador defectuós), es conserva l'original.
            best = evaluated[0]
        evaluated = [replace(e, selected=e is best) for e in evaluated]

        return SentenceResult(
            index=sentence.index,
            source_text=sentence.text,
            span=sentence.span,
            output_text=best.candidate.text,
            candidates=tuple(evaluated),
            rejected_proposals=tuple(rejected),
            protected_spans=local_protected,
        )

    def _collect_proposals(
        self, ctx: RuleContext
    ) -> tuple[list[Transformation], list[RejectedProposal]]:
        proposals: list[Transformation] = []
        rejected: list[RejectedProposal] = []
        for rule in self._rule_set.rules:
            for transformation in rule.propose(ctx):
                reason = self._rejection_reason(transformation, ctx)
                if reason is None:
                    proposals.append(transformation)
                else:
                    rejected.append(RejectedProposal(transformation, reason))
        return proposals, rejected

    def _rejection_reason(self, transformation: Transformation, ctx: RuleContext) -> str | None:
        if transformation.is_identity:
            return "no canvia res"
        if not transformation.can_apply_to(ctx.text):
            return "el fragment indicat no coincideix amb el text de la frase"
        touched = ctx.overlapping_protected(transformation.changed_span)
        if touched:
            listed = ", ".join(p.describe() for p in touched)
            return f"toca un fragment protegit: {listed}"
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


def _reassemble(text: str, results: Sequence[SentenceResult]) -> str:
    """Reconstrueix el document substituint cada frase i conservant els espais entre frases."""
    pieces: list[str] = []
    cursor = 0
    for result in results:
        pieces.append(text[cursor : result.span.start])
        pieces.append(result.output_text)
        cursor = result.span.end
    pieces.append(text[cursor:])
    return "".join(pieces)
