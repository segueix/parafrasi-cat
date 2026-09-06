"""Puntuació multidimensional de candidats."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.core.transformation import Transformation, TransformationFamily
from parafrasi_cat.preferences.evaluator import PreferenceEvaluator
from parafrasi_cat.scoring.assertive import AssertiveEvaluator
from parafrasi_cat.scoring.weights import ScoringWeights
from parafrasi_cat.style.adaptation import AdaptationContext, AuthorAdaptation
from parafrasi_cat.style.connector_repetition import ConnectorRepetition, DocumentWindow
from parafrasi_cat.style.degradation import StructuralDegradation
from parafrasi_cat.style.evaluator import StyleEvaluator
from parafrasi_cat.style.fusion_rhythm import FusionRhythm
from parafrasi_cat.validation.grammar import WARNING_PENALTY
from parafrasi_cat.validation.result import ValidationDimension, ValidationResult

DIMENSIONS: tuple[str, ...] = (
    "preservacio_factual",
    "preservacio_epistemologica",
    "compliment_terminologic",
    "gramaticalitat",
    "semblanca_estil",
    "preferencies_autor",
    "afinitat_autor",
    "varietat_connectors",
    "grau_de_canvi",
    "grau_superficial",
    "grau_estructural",
    "qualitat_sintactica",
    "ritme_fusio",
    "assertivitat",
)

INVALID_TOTAL = -1.0

CONNECTOR_COMPONENT = "repeticio_connectors"
"""Component de la penalització per repetició de connectors introduïda."""

STRUCTURAL_PRESSURE_SHARE = 0.65
"""Part de la pressió de reescriptura que és preferència per la reredacció estructural."""
SURFACE_PRESSURE_SHARE = 0.35
"""Part de la pressió de reescriptura que és distància superficial respecte de l'original."""

_DIMENSION_LABELS = {
    "preservacio_factual": "preservació factual",
    "preservacio_epistemologica": "preservació epistemològica",
    "compliment_terminologic": "compliment terminològic",
    "gramaticalitat": "gramaticalitat",
    "semblanca_estil": "semblança amb l'estil",
    "preferencies_autor": "preferències de l'autor",
    "afinitat_autor": "afinitat amb l'estil de l'autor",
    "varietat_connectors": "varietat de connectors",
    "grau_de_canvi": "grau de canvi",
    "grau_superficial": "canvi superficial",
    "grau_estructural": "reredacció estructural",
    "qualitat_sintactica": "qualitat sintàctica",
    "ritme_fusio": "ritme de la fusió",
    "assertivitat": "llenguatge assertiu",
}


@dataclass(frozen=True, slots=True)
class ScoringContext:
    validation: ValidationResult | None = None
    source_text: str = ""
    """Text original de la unitat que es puntua (frase o paràgraf), si es coneix.

    És la referència amb què es compara la repetició de connectors: sense
    original no es pot saber quina repetició és nova i quina ja hi era.
    """
    document: AdaptationContext | None = None
    window: DocumentWindow | None = None
    """Frases veïnes ja decidides (abans) i encara originals (després).

    És el que permet veure una repetició que travessa la frontera entre dues
    unitats consecutives sense obrir la mesura a tot el document.
    """


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    total: float
    components: dict[str, float]
    explanation: str
    dimensions: dict[str, float | None] = field(default_factory=dict)
    valid: bool = True
    invalidating: tuple[str, ...] = ()
    preference_explanation: str = ""
    author_explanation: str = ""
    author_affinity: dict[str, object] = field(default_factory=dict)
    degradation_reasons: tuple[str, ...] = ()
    assertive: dict[str, object] = field(default_factory=dict)
    rhythm: dict[str, object] = field(default_factory=dict)
    connectors: dict[str, object] = field(default_factory=dict)
    """Perfil de connectors i repeticions detectades (buit si no se n'ha mesurat cap)."""

    def dimension(self, name: str) -> float | None:
        return self.dimensions.get(name)

    def describe_dimensions(self) -> str:
        parts: list[str] = []
        for name in DIMENSIONS:
            value = self.dimensions.get(name)
            if value is None:
                continue
            parts.append(f"{_DIMENSION_LABELS[name]} {value:.2f}")
        return " · ".join(parts)

    def to_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "valid": self.valid,
            "components": dict(self.components),
            "dimensions": dict(self.dimensions),
            "invalidating": list(self.invalidating),
            "explanation": self.explanation,
            "preference_explanation": self.preference_explanation,
            "author_explanation": self.author_explanation,
            "author_affinity": dict(self.author_affinity),
            "degradation_reasons": list(self.degradation_reasons),
            "assertive": dict(self.assertive),
            "rhythm": dict(self.rhythm),
            "connectors": dict(self.connectors),
        }


@runtime_checkable
class Scorer(Protocol):
    def score(self, candidate: Candidate, ctx: ScoringContext | None = None) -> ScoreBreakdown: ...


class CompositeScorer:
    """Puntuació composta: seguretat absoluta i preferència entre alternatives segures.

    En mode normal, el comportament és el de sempre. En mode d'esborrany LLM,
    ``rewrite_pressure`` fa que un candidat validat pugui guanyar encara que
    l'original ja sigui molt bo: no se li exigeix una millora estilística absoluta,
    sinó equivalència segura, distància controlada i, si hi ha empremta, més
    afinitat amb l'autor.
    """

    def __init__(
        self,
        weights: ScoringWeights | None = None,
        style_evaluator: StyleEvaluator | None = None,
        preference_evaluator: PreferenceEvaluator | None = None,
        adaptation: AuthorAdaptation | None = None,
        degradation: StructuralDegradation | None = None,
        assertive: AssertiveEvaluator | None = None,
        rhythm: FusionRhythm | None = None,
        connectors: ConnectorRepetition | None = None,
    ) -> None:
        self._weights = weights or ScoringWeights()
        self._style = style_evaluator
        self._preferences = preference_evaluator
        self._adaptation = adaptation
        self._degradation = degradation
        self._assertive = assertive
        self._rhythm = rhythm
        self._connectors = connectors

    @property
    def weights(self) -> ScoringWeights:
        return self._weights

    @property
    def style_evaluator(self) -> StyleEvaluator | None:
        return self._style

    @property
    def preference_evaluator(self) -> PreferenceEvaluator | None:
        return self._preferences

    @property
    def adaptation(self) -> AuthorAdaptation | None:
        return self._adaptation

    @property
    def degradation(self) -> StructuralDegradation | None:
        return self._degradation

    @property
    def assertive(self) -> AssertiveEvaluator | None:
        return self._assertive

    @property
    def rhythm(self) -> FusionRhythm | None:
        return self._rhythm

    @property
    def connectors(self) -> ConnectorRepetition | None:
        """Avaluador de la repetició de connectors (cap si no hi ha inventari)."""
        return self._connectors

    def transformation_gain(self, transformations: Sequence[Transformation]) -> float:
        w = self._weights
        by_family: dict[TransformationFamily, list[float]] = {}
        for t in transformations:
            value = t.confidence * max(0.0, 1.0 - w.semantic_risk * t.semantic_risk.weight)
            by_family.setdefault(t.family, []).append(value)
        total = 0.0
        for values in by_family.values():
            for rank, value in enumerate(sorted(values, reverse=True)):
                total += value * w.family_gain_decay**rank
        return w.transformation_gain * total / w.max_transformations

    def score(self, candidate: Candidate, ctx: ScoringContext | None = None) -> ScoreBreakdown:
        w = self._weights
        gain = self.transformation_gain(candidate.transformations)
        components: dict[str, float] = {"transformacions": round(gain, 4)}
        parts = [f"guany per transformacions {gain:+.3f}"]
        dimensions: dict[str, float | None] = dict.fromkeys(DIMENSIONS)
        invalidating: list[str] = []

        validation = ctx.validation if ctx is not None else None
        if validation is not None:
            dimensions["preservacio_factual"] = _binary(validation, ValidationDimension.FACTUAL)
            dimensions["preservacio_epistemologica"] = _binary(
                validation, ValidationDimension.EPISTEMIC
            )
            dimensions["compliment_terminologic"] = _binary(
                validation, ValidationDimension.TERMINOLOGY
            )
            grammar = _grammar_score(validation)
            dimensions["gramaticalitat"] = grammar
            grammar_penalty = w.grammar * (1.0 - grammar)
            components["gramaticalitat"] = round(-grammar_penalty, 4)
            parts.append(f"gramaticalitat {-grammar_penalty:+.3f}")
            invalidating.extend(i.message for i in validation.errors)
        else:
            grammar_penalty = 0.0
            if not candidate.transformations:
                dimensions["preservacio_factual"] = 1.0
                dimensions["preservacio_epistemologica"] = 1.0
                dimensions["compliment_terminologic"] = 1.0
                dimensions["gramaticalitat"] = 1.0

        style_penalty = 0.0
        if self._style is not None:
            distance = self._style.distance(candidate.text)
            style_penalty = w.style_distance * distance.total
            components["estil"] = round(-style_penalty, 4)
            parts.append(f"distància d'estil {-style_penalty:+.3f}")
            dimensions["semblanca_estil"] = round(max(0.0, 1.0 - distance.total), 4)

        preference_bonus = 0.0
        preference_explanation = ""
        if self._preferences is not None:
            assessment = self._preferences.assess(candidate.source_text, candidate.text)
            if assessment.applies:
                preference_bonus = w.preferences * assessment.score
                preference_explanation = assessment.explanation
                components["preferencies"] = round(preference_bonus, 4)
                parts.append(
                    f"preferències de l'autor {preference_bonus:+.3f} ({preference_explanation})"
                )
                dimensions["preferencies_autor"] = round((assessment.score + 1.0) / 2.0, 4)

        affinity_bonus = 0.0
        author_explanation = ""
        author_affinity: dict[str, object] = {}
        if self._adaptation is not None:
            document = ctx.document if ctx is not None else None
            source = candidate.source_text
            affinity = self._adaptation.assess(candidate.text, context=document, source_text=source)
            baseline = self._adaptation.assess(source, context=document, source_text=source)
            if affinity.available and baseline.available:
                affinity_bonus = w.author_affinity * (affinity.score - baseline.score)
                author_explanation = self._adaptation.explain(affinity, baseline)
                author_affinity = {**affinity.to_dict(), "baseline": baseline.score}
                components["afinitat_autor"] = round(affinity_bonus, 4)
                parts.append(f"afinitat amb l'autor {affinity_bonus:+.3f} ({author_explanation})")
                dimensions["afinitat_autor"] = affinity.score

        connector_repetition_penalty = 0.0
        connector_detail: dict[str, object] = {}
        if self._connectors is not None and w.connector_repetition > 0:
            # Es compara amb l'original de la unitat: només la repetició que el
            # candidat afegeix compta. La que l'autor ja havia escrit es conserva
            # sense càrrec, i canviar-la per una de nova sí que en té.
            reference = (ctx.source_text if ctx is not None else "") or candidate.source_text
            window = ctx.window if ctx is not None else None
            repetition = self._connectors.assess(candidate.text, reference, window)
            connector_detail = repetition.to_dict()
            dimensions["varietat_connectors"] = round(1.0 - repetition.penalty, 4)
            if repetition.penalised:
                connector_repetition_penalty = w.connector_repetition * repetition.penalty
                components[CONNECTOR_COMPONENT] = round(-connector_repetition_penalty, 4)
                parts.append(
                    f"repetició de connectors {-connector_repetition_penalty:+.3f} "
                    f"({repetition.describe()})"
                )

        change = candidate.change_ratio()
        dimensions["grau_de_canvi"] = round(change, 4)
        dimensions["grau_superficial"] = candidate.surface_degree()
        degree = candidate.structural_degree()
        dimensions["grau_estructural"] = degree

        degradation_penalty = 0.0
        degradation_reasons: tuple[str, ...] = ()
        dimensions["qualitat_sintactica"] = 1.0
        if self._degradation is not None and candidate.transformations:
            degradation = self._degradation.assess(candidate.text, candidate.source_text)
            if degradation.degraded:
                degradation_penalty = w.degradation * degradation.score
                degradation_reasons = degradation.reasons
                gain *= 1.0 - degradation.score
                components["transformacions"] = round(gain, 4)
                components["degradacio"] = round(-degradation_penalty, 4)
                parts.append(
                    f"degradació estructural {-degradation_penalty:+.3f} "
                    f"({'; '.join(degradation.reasons)})"
                )
                dimensions["qualitat_sintactica"] = round(1.0 - degradation.score, 4)

        assertive_bonus = 0.0
        assertive_detail: dict[str, object] = {}
        if self._assertive is not None and candidate.transformations:
            assessment_a = self._assertive.assess(candidate.source_text, candidate.text)
            assertive_bonus = w.assertive * assessment_a.delta * 2.0
            assertive_detail = assessment_a.to_dict()
            dimensions["assertivitat"] = assessment_a.score
            if assessment_a.reasons:
                components["assertivitat"] = round(assertive_bonus, 4)
                parts.append(
                    f"llenguatge assertiu {assertive_bonus:+.3f} "
                    f"({'; '.join(assessment_a.reasons)})"
                )

        rhythm_penalty = 0.0
        rhythm_detail: dict[str, object] = {}
        rhythm_scale = 1.0
        if self._rhythm is not None and candidate.transformations:
            assessment_r = self._rhythm.assess(candidate)
            if assessment_r.details:
                dimensions["ritme_fusio"] = round(1.0 - assessment_r.penalty, 4)
            if assessment_r.penalised:
                rhythm_penalty = w.rhythm * assessment_r.penalty
                rhythm_scale = 1.0 - assessment_r.penalty
                rhythm_detail = assessment_r.to_dict()
                components["ritme"] = round(-rhythm_penalty, 4)
                parts.append(
                    f"ritme de la fusió {-rhythm_penalty:+.3f} ({'; '.join(assessment_r.reasons)})"
                )

        # El grau estructural es paga **una sola vegada**. Fins a la 1.3.16 el
        # cobrava el bonus d'estructura i, a més, la pressió de reescriptura
        # (que hi tornava a multiplicar el mateix grau): una sola reordenació
        # arribava a valer sis vegades el desempat estilístic més gran, i cap
        # criteri d'estil no podia decidir mai entre dues arquitectures
        # comparables. Ara la preferència per la reredacció és un únic component
        # —amb el mateix pes total que abans, sumant la part estructural de la
        # pressió— i la pressió només paga el que el grau no mesura: la
        # distància superficial respecte de l'original.
        quality = dimensions["qualitat_sintactica"]
        quality_scale = quality if quality else 0.0
        grammar_score = dimensions.get("gramaticalitat")
        safe_scale = grammar_score if isinstance(grammar_score, float) else 1.0
        structural_weight = w.structure + STRUCTURAL_PRESSURE_SHARE * w.rewrite_pressure

        structure_bonus = 0.0
        if structural_weight > 0 and degree > 0:
            structure_bonus = structural_weight * degree * safe_scale * quality_scale * rhythm_scale
            components["estructura"] = round(structure_bonus, 4)
            parts.append(f"reredacció estructural {structure_bonus:+.3f}")

        rewrite_bonus = 0.0
        if w.rewrite_pressure > 0 and candidate.transformations:
            # Pressió només entre candidats que passen els mateixos filtres de seguretat:
            # amb un esborrany ja ben redactat, no tornar el mateix text.
            rewrite_bonus = (
                w.rewrite_pressure * SURFACE_PRESSURE_SHARE * change * safe_scale * quality_scale
            )
            components["pressio_reescriptura"] = round(rewrite_bonus, 4)
            parts.append(f"pressió de reescriptura {rewrite_bonus:+.3f}")

        valid = not invalidating
        total = (
            gain
            - style_penalty
            - grammar_penalty
            - degradation_penalty
            - rhythm_penalty
            - connector_repetition_penalty
            + preference_bonus
            + affinity_bonus
            + structure_bonus
            + assertive_bonus
            + rewrite_bonus
            if valid
            else INVALID_TOTAL
        )
        if not valid:
            parts.append("candidat invalidat: " + "; ".join(invalidating))
        return ScoreBreakdown(
            total=round(total, 4),
            components=components,
            explanation="; ".join(parts),
            dimensions=dimensions,
            valid=valid,
            invalidating=tuple(invalidating),
            preference_explanation=preference_explanation,
            author_explanation=author_explanation,
            author_affinity=author_affinity,
            degradation_reasons=degradation_reasons,
            assertive=assertive_detail,
            rhythm=rhythm_detail,
            connectors=connector_detail,
        )


def _binary(validation: ValidationResult, dimension: ValidationDimension) -> float:
    return 0.0 if validation.errors_in(dimension) else 1.0


def _grammar_score(validation: ValidationResult) -> float:
    if validation.errors_in(ValidationDimension.GRAMMAR):
        return 0.0
    weight = sum(i.weight for i in validation.warnings_in(ValidationDimension.GRAMMAR))
    return round(max(0.0, 1.0 - WARNING_PENALTY * weight), 4)
