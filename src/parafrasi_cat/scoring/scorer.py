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
- ``afinitat_autor``: afinitat amb l'empremta de l'autor, només quan el text és
  un esborrany generat amb LLM (``None`` altrament);
- ``grau_de_canvi``: proporció de caràcters canviats (0 = idèntic);
- ``grau_superficial``: grau de canvi superficial (0-1): mots, connectors,
  puntuació i flexió verbal, que no toquen l'arquitectura de la frase;
- ``grau_estructural``: grau de reredacció estructural (0-1): només les
  famílies que reorganitzen la frase o el paràgraf (reordenació, subordinació,
  canvi de construcció, divisió, fusió). No mesura distància de caràcters ni
  nombre de canvis: mesura què s'ha reestructurat;
- ``qualitat_sintactica``: 1 menys la degradació estructural local que el
  candidat introdueix respecte de l'original (relatives consecutives,
  acumulació de «que», repetició d'estructura).

El guany per transformacions és conscient de la família: dins d'una mateixa
família les aportacions tenen rendiments decreixents (``family_gain_decay``),
de manera que tres retocs verbals no valen tres vegades un i mai no simulen
una reordenació. Una puntuació global (``total``) combina aquest guany amb
les penalitzacions d'estil, de gramaticalitat i de degradació, amb el bonus
(o la penalització) de les preferències explícites, en mode d'esborrany amb
l'afinitat autoral relativa a l'original i, amb el pes ``structure`` (el mode
profund), amb el grau estructural multiplicat per la gramaticalitat; un
candidat que degrada l'estructura perd, proporcionalment, el guany i el bonus
estructural. Qualsevol error de preservació (factual, epistemològica,
terminològica) o qualsevol error de validació **invalida** el candidat:
``valid`` és fals i ``total`` és −1, i cap estil ni cap grau de canvi no ho
compensa.
"""

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
    "grau_de_canvi",
    "grau_superficial",
    "grau_estructural",
    "qualitat_sintactica",
    "ritme_fusio",
    "assertivitat",
)

INVALID_TOTAL = -1.0

_DIMENSION_LABELS = {
    "preservacio_factual": "preservació factual",
    "preservacio_epistemologica": "preservació epistemològica",
    "compliment_terminologic": "compliment terminològic",
    "gramaticalitat": "gramaticalitat",
    "semblanca_estil": "semblança amb l'estil",
    "preferencies_autor": "preferències de l'autor",
    "afinitat_autor": "afinitat amb l'estil de l'autor",
    "grau_de_canvi": "grau de canvi",
    "grau_superficial": "canvi superficial",
    "grau_estructural": "reredacció estructural",
    "qualitat_sintactica": "qualitat sintàctica",
    "ritme_fusio": "ritme de la fusió",
    "assertivitat": "llenguatge assertiu",
}


@dataclass(frozen=True, slots=True)
class ScoringContext:
    """Resultat de la validació i text original, per puntuar per dimensions.

    ``document`` és la resta del document, en ordre (abans i després de la
    unitat que es puntua), perquè l'afinitat autoral mesuri el ritme i les
    densitats sobre tot el text i no sobre una frase sola.
    """

    validation: ValidationResult | None = None
    source_text: str = ""
    document: AdaptationContext | None = None


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
        author_explanation: Per què el candidat s'assembla més (o menys) a l'autor
            que l'original (buit fora del mode d'esborrany).
        author_affinity: Afinitat amb l'empremta, per components (buit fora del
            mode d'esborrany).
        degradation_reasons: Per què el candidat degrada l'estructura local
            (buit si no la degrada).
        assertive: Valoració del llenguatge assertiu (buit si l'opció no és activa).
        rhythm: Valoració del ritme de les fusions (buit si no n'hi ha cap).
    """

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
    o una penalització explicats. Amb una :class:`AuthorAdaptation` (només en
    mode d'esborrany generat amb LLM), l'afinitat amb l'empremta de l'autor,
    relativa a l'original, també hi suma o hi resta.
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
    ) -> None:
        self._weights = weights or ScoringWeights()
        self._style = style_evaluator
        self._preferences = preference_evaluator
        self._adaptation = adaptation
        self._degradation = degradation
        self._assertive = assertive
        self._rhythm = rhythm

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
        """Adaptació autoral activa (només en mode d'esborrany generat amb LLM)."""
        return self._adaptation

    @property
    def degradation(self) -> StructuralDegradation | None:
        """Mesura de degradació estructural local (opcional)."""
        return self._degradation

    @property
    def assertive(self) -> AssertiveEvaluator | None:
        """Avaluador del llenguatge assertiu (només amb l'opció activa)."""
        return self._assertive

    @property
    def rhythm(self) -> FusionRhythm | None:
        """Avaluador del ritme de les fusions (opcional)."""
        return self._rhythm

    def transformation_gain(self, transformations: Sequence[Transformation]) -> float:
        """Guany per transformacions, conscient de la família.

        Cada transformació aporta ``confiança × (1 − pes_del_risc × risc)``;
        dins d'una mateixa família, les aportacions s'ordenen de més a menys i
        la k-èsima es multiplica per ``family_gain_decay^(k−1)``: repetir la
        mateixa mena de retoc aporta cada cop menys.
        """
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
                # Bonus o penalització relatius a l'original: l'identitat val zero, i
                # un candidat només hi guanya si s'acosta més a l'autor que el text
                # que substitueix.
                affinity_bonus = w.author_affinity * (affinity.score - baseline.score)
                author_explanation = self._adaptation.explain(affinity, baseline)
                author_affinity = {**affinity.to_dict(), "baseline": baseline.score}
                components["afinitat_autor"] = round(affinity_bonus, 4)
                parts.append(f"afinitat amb l'autor {affinity_bonus:+.3f} ({author_explanation})")
                dimensions["afinitat_autor"] = affinity.score

        dimensions["grau_de_canvi"] = round(candidate.change_ratio(), 4)
        dimensions["grau_superficial"] = candidate.surface_degree()
        degree = candidate.structural_degree()
        dimensions["grau_estructural"] = degree

        degradation_penalty = 0.0
        degradation_reasons: tuple[str, ...] = ()
        dimensions["qualitat_sintactica"] = 1.0
        if self._degradation is not None and candidate.transformations:
            degradation = self._degradation.assess(candidate.text, candidate.source_text)
            if degradation.degraded:
                # Un canvi que degrada l'estructura local (relatives encadenades,
                # «que» acumulats) perd el premi que tindria com a reredacció i, a
                # més, rep una penalització; mai no s'invalida.
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
            # Llenguatge assertiu: més directe, mai més cert. Un bonus petit entre
            # candidats ja validats; la matriu de transicions ha fet la feina abans.
            assessment_a = self._assertive.assess(candidate.source_text, candidate.text)
            assertive_bonus = w.assertive * assessment_a.delta * 2.0
            assertive_detail = assessment_a.to_dict()
            dimensions["assertivitat"] = assessment_a.score
            if assessment_a.reasons:
                components["assertivitat"] = round(assertive_bonus, 4)
                reasons_a = "; ".join(assessment_a.reasons)
                parts.append(f"llenguatge assertiu {assertive_bonus:+.3f} ({reasons_a})")

        rhythm_penalty = 0.0
        rhythm_detail: dict[str, object] = {}
        rhythm_scale = 1.0
        if self._rhythm is not None and candidate.transformations:
            # Una fusió que deixa una frase massa llarga o carregada per al ritme de
            # l'autor paga una penalització i perd part del bonus estructural.
            assessment_r = self._rhythm.assess(candidate)
            if assessment_r.details:
                # Hi ha una fusió: la dimensió es reporta sempre (1,0 = cap càrrega).
                dimensions["ritme_fusio"] = round(1.0 - assessment_r.penalty, 4)
            if assessment_r.penalised:
                rhythm_penalty = w.rhythm * assessment_r.penalty
                rhythm_scale = 1.0 - assessment_r.penalty
                rhythm_detail = assessment_r.to_dict()
                components["ritme"] = round(-rhythm_penalty, 4)
                parts.append(
                    f"ritme de la fusió {-rhythm_penalty:+.3f} ({'; '.join(assessment_r.reasons)})"
                )

        structure_bonus = 0.0
        if w.structure > 0 and degree > 0:
            # Entre candidats igualment segurs, la reredacció estructural real té
            # avantatge; escalat per la gramaticalitat, perquè un avís gramatical
            # no quedi mai compensat pel grau de canvi, i per la qualitat sintàctica
            # i el ritme.
            grammar_score = dimensions.get("gramaticalitat")
            scale = grammar_score if isinstance(grammar_score, float) else 1.0
            quality = dimensions["qualitat_sintactica"]
            structure_bonus = (
                w.structure * degree * scale * (quality if quality else 0.0) * rhythm_scale
            )
            components["estructura"] = round(structure_bonus, 4)
            parts.append(f"reredacció estructural {structure_bonus:+.3f}")

        valid = not invalidating
        total = (
            gain
            - style_penalty
            - grammar_penalty
            - degradation_penalty
            - rhythm_penalty
            + preference_bonus
            + affinity_bonus
            + structure_bonus
            + assertive_bonus
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
