"""Validació específica de les transformacions verbals.

LanguageTool va donar per bona «però ja no va sobirar»: una forma que no
existeix, en una posició on no hi havia cap verb. No es pot confiar que un
corrector gramatical detecti un error semanticosintàctic d'aquesta mena. Per
això cada *classe* de transformació té la seva comprovació interna, feta amb
els recursos locals (morfologia i analitzador), i LanguageTool és una capa
addicional, mai l'única garantia.

Per a un canvi de passat simple a perifràstic («encarregà» → «va encarregar»)
es comprova, sobre el candidat sencer i amb independència de la regla que l'ha
proposat:

1. que la forma original tingués una lectura de verb de passat, si el recurs
   morfològic la coneix («sobirà» només és un adjectiu o un nom: es bloqueja);
2. que l'infinitiu produït existeixi, si el recurs té diccionari de verbs
   («sobirar» no existeix: es bloqueja);
3. amb analitzador, que la forma nova quedi en funció verbal (un infinitiu
   amb el seu auxiliar), i que el subjecte que tenia el verb original continuï
   depenent del verb nou o d'un verb coordinat amb ell.

Per al canvi invers («va encarregar» → «encarregà») es comprova que la forma
simple produïda sigui, segons el recurs, un verb de passat.

Qualsevol incompliment és un error: el candidat es descarta.
"""

from __future__ import annotations

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.core.transformation import Transformation
from parafrasi_cat.morphology.provider import MorphologyProvider
from parafrasi_cat.morphology.verbal import (
    NOMINAL_DEPS,
    NOMINAL_POS,
    knows_infinitive,
    lexical_readings,
)
from parafrasi_cat.syntax.analysis import (
    PREDICATE_POS,
    SUBJECT_DEPS,
    SentenceSyntax,
    SyntaxProvider,
    SyntaxToken,
)
from parafrasi_cat.validation.base import ValidationContext
from parafrasi_cat.validation.result import (
    ValidationDimension,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)

VERBAL_CHANGE_KEY = "verbal_change"


class VerbalTransformationValidator:
    """Comprova per classe que un canvi verbal ha partit d'un verb i n'ha produït un."""

    validator_id = "verbal"
    dimension = ValidationDimension.GRAMMAR

    def __init__(
        self, morphology: MorphologyProvider, syntax: SyntaxProvider | None = None
    ) -> None:
        self._morphology = morphology
        self._syntax = syntax if syntax is not None and syntax.available else None

    def validate(self, candidate: Candidate, ctx: ValidationContext) -> ValidationResult:
        verbal = [
            (t, span)
            for t, span in zip(candidate.transformations, candidate.result_spans(), strict=True)
            if t.metadata.get(VERBAL_CHANGE_KEY)
        ]
        if not verbal:
            return ValidationResult.passed()
        issues: list[ValidationIssue] = []
        source_analysis = self._parse(ctx.source_text)
        candidate_analysis = self._parse(candidate.text)
        for transformation, result_span in verbal:
            change = transformation.metadata.get(VERBAL_CHANGE_KEY, "")
            if change == "simple_a_perifrastic":
                issues.extend(
                    self._check_periphrastic(
                        transformation, result_span.start, source_analysis, candidate_analysis
                    )
                )
            elif change == "perifrastic_a_simple":
                issues.extend(self._check_simple(transformation))
        return ValidationResult(tuple(issues))

    # -- passat simple → perifràstic ---------------------------------------------------------

    def _check_periphrastic(
        self,
        transformation: Transformation,
        result_start: int,
        source_analysis: SentenceSyntax | None,
        candidate_analysis: SentenceSyntax | None,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        form = transformation.text_before.strip()
        readings = lexical_readings(self._morphology, form)
        if readings.known and not readings.past_verb:
            issues.append(
                self._error(
                    f"«{form}» no és un verb de passat segons la morfologia "
                    f"({readings.describe_non_verb()}): la regla «{transformation.rule_id}» "
                    "ha partit d'una lectura morfològica errònia"
                )
            )
        parts = transformation.text_after.split()
        infinitive = parts[-1] if parts else ""
        if infinitive and knows_infinitive(self._morphology, infinitive) is False:
            issues.append(
                self._error(
                    f"l'infinitiu «{infinitive}» no existeix segons el recurs morfològic: "
                    f"la regla «{transformation.rule_id}» ha inventat un verb"
                )
            )
        if issues or candidate_analysis is None or not candidate_analysis.confident:
            return issues
        aux_offset = result_start
        inf_offset = result_start + len(transformation.text_after) - len(infinitive)
        aux = candidate_analysis.token_at(aux_offset)
        inf = candidate_analysis.token_at(inf_offset)
        if inf is None or aux is None:
            return issues
        if _nominal_use(inf, candidate_analysis):
            issues.append(
                self._error(
                    f"«{transformation.text_after}» no queda en funció verbal: l'analitzador "
                    f"veu «{inf.text}» com a {inf.pos} ({inf.dep})"
                )
            )
            return issues
        if source_analysis is not None and source_analysis.confident:
            original = source_analysis.token_at(transformation.changed_span.start)
            if original is not None:
                lost = _lost_subjects(original, source_analysis, (aux, inf), candidate_analysis)
                if lost:
                    listed = ", ".join(f"«{s}»" for s in lost)
                    issues.append(
                        self._error(
                            f"el subjecte {listed} ja no depèn del verb transformat "
                            f"«{transformation.text_after}»"
                        )
                    )
        return issues

    # -- perifràstic → passat simple ---------------------------------------------------------

    def _check_simple(self, transformation: Transformation) -> list[ValidationIssue]:
        simple = transformation.text_after.strip()
        readings = lexical_readings(self._morphology, simple)
        if readings.known and not readings.past_verb:
            return [
                self._error(
                    f"«{simple}» no és cap forma de passat simple segons la morfologia: "
                    f"la regla «{transformation.rule_id}» ha produït una forma que no existeix"
                )
            ]
        return []

    # -- utilitats ---------------------------------------------------------------------------

    def _parse(self, text: str) -> SentenceSyntax | None:
        if self._syntax is None:
            return None
        return self._syntax.parse(text)

    def _error(self, message: str) -> ValidationIssue:
        return ValidationIssue(self.validator_id, ValidationSeverity.ERROR, message, self.dimension)


def _nominal_use(token: SyntaxToken, analysis: SentenceSyntax) -> bool:
    """Cert si l'analitzador veu el mot com a nom, adjectiu o coordinat amb un d'ells."""
    if token.pos in NOMINAL_POS or token.dep in NOMINAL_DEPS:
        return True
    if token.dep != "conj":
        return False
    head = next((t for t in analysis.tokens if t.index == token.head), None)
    return head is not None and head.pos not in PREDICATE_POS


def _lost_subjects(
    original: SyntaxToken,
    source_analysis: SentenceSyntax,
    new_verb: tuple[SyntaxToken, ...],
    candidate_analysis: SentenceSyntax,
) -> tuple[str, ...]:
    """Subjectes del verb original que, al candidat, ja no depenen del verb nou."""
    subjects = [
        t.text
        for t in source_analysis.tokens
        if t.head == original.index and t.dep in SUBJECT_DEPS and t.index != original.index
    ]
    if not subjects:
        return ()
    allowed = _verbal_family({t.index for t in new_verb}, candidate_analysis)
    lost: list[str] = []
    for subject in subjects:
        holders = [
            t for t in candidate_analysis.tokens if t.text == subject and t.dep in SUBJECT_DEPS
        ]
        if holders and not any(t.head in allowed for t in holders):
            lost.append(subject)
    return tuple(lost)


def _verbal_family(indices: set[int], analysis: SentenceSyntax) -> set[int]:
    """El verb nou, el seu auxiliar, els seus nuclis verbals i els verbs coordinats."""
    by_index = {t.index: t for t in analysis.tokens}
    family = set(indices)
    for index in list(indices):
        token = by_index.get(index)
        while token is not None and token.head != token.index and token.pos in PREDICATE_POS:
            head = by_index.get(token.head)
            if head is None or head.pos not in PREDICATE_POS:
                break
            family.add(head.index)
            token = head
    for token in analysis.tokens:
        if token.dep == "conj" and token.head in family and token.pos in PREDICATE_POS:
            family.add(token.index)
    return family


__all__ = ["VERBAL_CHANGE_KEY", "VerbalTransformationValidator"]
