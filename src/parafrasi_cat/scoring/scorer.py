"""Puntuació multidimensional de candidats.

Cada candidat rep una puntuació separada per dimensió:

- ``preservacio_factual``: 1 si cap validador factual ha fallat, 0 altrament;
- ``preservacio_epistemologica``: 1 si la força i la funció epistemològica es
  conserven (o el canvi està autoritzat), 0 altrament;
- ``compliment_terminologic``: 1 si la terminologia protegida es conserva;
- ``gramaticalitat``: 1 menys una penalització per cada avís heurístic, 0 si
  hi ha un error;
- ``semblanca_estil``: 1 − distància respecte del perfil o l'empremta (``None``
  si no hi ha avaluador d'estil);
- ``preferencies_autor``: adequació a les preferències explícites (diccionaris
  del projecte, fitxer de preferències de l'autor, feedback manual): 1 si només
  introdueix formes preferides, 0 si n'introdueix d'evitades, ``None`` si cap
  preferència no hi intervé;
- ``grau_de_canvi``: proporció de caràcters canviats (0 = idèntic).

Una puntuació global (``total``) combina el guany per transformacions amb
les penalitzacions d'estil i gramaticalitat i amb el bonus (o la penalització)
de les preferències explícites, però qualsevol error de
preservació (factual, epistemològica, terminològica) o qualsevol error de
validació **invalida** el candidat: ``valid`` és fals i ``total`` és −1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.preferences.evaluator import PreferenceEvaluator
from parafrasi_cat.scoring.weights import ScoringWeights
from parafrasi_cat.style.evaluator import StyleEvaluator
from parafrasi_cat.validation.grammar import WARNING_PENALTY
from parafrasi_cat.validation.result import ValidationDimension, ValidationResult

DIMENSIONS: tuple[str, ...] = (
    "preservacio_factual",
    "preservacio_epistemologica",
    "compliment_terminologic",
    "gramaticalitat",
    "semblanca_estil",
    "preferencies_autor",
    "grau_de_canvi",
)

INVALID_TOTAL = -1.0

_DIMENSION_LABELS = {
    "preservacio_factual": "preservació factual",
    "preservacio_epistemologica": "preservació epistemològica",
    "compliment_terminologic": "compliment terminològic",
    "gramaticalitat": "gramaticalitat",
    "semblanca_estil": "semblança amb l'estil",
    "preferencies_autor": "preferències de l'autor",
    "grau_de_canvi": "grau de canvi",
}


@dataclass(frozen=True, slots=True)
class ScoringContext:
    """Resultat de la validació i text original, per puntuar per dimensions."""

    validation: ValidationResult | None = None
    source_text: str = ""


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    """Puntuació d'un candidat: global, per components i per dimensions.

    Atributs:
        total: Puntuació global (−1 si el candidat no és vàlid).
        components: Contribucions a la puntuació global (guany, estil, gramaticalitat).
        explanation: Explicació llegible.
        dimensions: Puntuació 0-1 de cada dimensió (``None`` si no s'ha pogut mesurar).
        valid: Fals si alguna dimensió de preservació ha fallat o hi ha errors de validació.
        invalidating: Motius que invaliden el candidat.
        preference_explanation: Per què les preferències explícites afavoreixen o
            penalitzen el candidat (buit si no hi intervenen).
    """

    total: float
    components: dict[str, float]
    explanation: str
    dimensions: dict[str, float | None] = field(default_factory=dict)
    valid: bool = True
    invalidating: tuple[str, ...] = ()
    preference_explanation: str = ""

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
        }


@runtime_checkable
class Scorer(Protocol):
    def score(self, candidate: Candidate, ctx: ScoringContext | None = None) -> ScoreBreakdown: ...


class CompositeScorer:
    """Puntuació composta: guany per transformacions segures menys penalitzacions.

    Un candidat idèntic a l'original té guany 0; un candidat amb canvis segurs
    (confiança alta, risc baix) obté un guany positiu, de manera que el motor
    prefereix reredactar quan pot fer-ho sense risc, i deixar el text intacte
    en cas contrari. Amb un :class:`ScoringContext`, les dimensions de
    preservació es dedueixen de la validació i poden invalidar el candidat.
    Amb un :class:`PreferenceEvaluator`, les preferències explícites de
    l'autor (diccionaris, fitxer de preferències, feedback) afegeixen un bonus
    o una penalització explicats.
    """

    def __init__(
        self,
        weights: ScoringWeights | None = None,
        style_evaluator: StyleEvaluator | None = None,
        preference_evaluator: PreferenceEvaluator | None = None,
    ) -> None:
        self._weights = weights or ScoringWeights()
        self._style = style_evaluator
        self._preferences = preference_evaluator

    @property
    def weights(self) -> ScoringWeights:
        return self._weights

    @property
    def style_evaluator(self) -> StyleEvaluator | None:
        return self._style

    @property
    def preference_evaluator(self) -> PreferenceEvaluator | None:
        return self._preferences

    def score(self, candidate: Candidate, ctx: ScoringContext | None = None) -> ScoreBreakdown:
        w = self._weights
        gain = 0.0
        for t in candidate.transformations:
            gain += t.confidence * max(0.0, 1.0 - w.semantic_risk * t.semantic_risk.weight)
        gain = w.transformation_gain * gain / w.max_transformations

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

        dimensions["grau_de_canvi"] = round(candidate.change_ratio(), 4)

        valid = not invalidating
        total = (
            gain - style_penalty - grammar_penalty + preference_bonus if valid else INVALID_TOTAL
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
        )


def _binary(validation: ValidationResult, dimension: ValidationDimension) -> float:
    return 0.0 if validation.errors_in(dimension) else 1.0


def _grammar_score(validation: ValidationResult) -> float:
    """Gramaticalitat: 0 si hi ha errors, i si no, 1 menys el pes dels avisos.

    Els avisos pesen: un error nou probable (una penalització forta) baixa la
    puntuació molt més que una qüestió d'estil.
    """
    if validation.errors_in(ValidationDimension.GRAMMAR):
        return 0.0
    weight = sum(i.weight for i in validation.warnings_in(ValidationDimension.GRAMMAR))
    return round(max(0.0, 1.0 - WARNING_PENALTY * weight), 4)
