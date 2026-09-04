"""Reparació determinista de la concordança amb la morfologia local.

Quan una transformació deixa el verb sense concordar amb el subjecte, i el
recurs morfològic local dona **una sola** forma possible, es corregeix la
flexió i la correcció queda registrada com una transformació explícita més
(``concordanca.reparacio``), visible a l'informe i a la interfície.

Límits, deliberats:

- no es repara res que ja estigués al text de l'autor: el motor no esmena
  l'original, només allò que ell mateix ha trencat;
- si la morfologia dona més d'una forma possible, o cap, no es repara: el
  candidat es descarta;
- si el verb cau dins del fragment que una regla ha escrit, tampoc: allà la
  forma correcta és responsabilitat de la regla;
- no hi intervé cap model generatiu ni cap servei extern, i LanguageTool no
  reescriu mai res.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import SemanticRisk, Transformation, TransformationType
from parafrasi_cat.morphology.provider import MorphologyProvider
from parafrasi_cat.syntax.analysis import SyntaxProvider, SyntaxToken
from parafrasi_cat.validation.agreement import Disagreement, find_disagreements, responsible_rule

#: Identificador de la regla amb què es registra la reparació.
REPAIR_RULE_ID = "concordanca.reparacio"

ProtectedConflict = Callable[[Span, str], str | None]


class AgreementRepair:
    """Corregeix la concordança que el motor ha trencat, si la solució és única.

    Necessita el parser i el recurs morfològic locals: sense qualsevol dels
    dos no repara res i els candidats defectuosos queden descartats pel
    validador de concordança.
    """

    rule_id = REPAIR_RULE_ID

    def __init__(self, syntax: SyntaxProvider, morphology: MorphologyProvider) -> None:
        self._syntax = syntax
        self._morphology = morphology
        self._source_cache: dict[str, frozenset[tuple[str, str]]] = {}

    @property
    def available(self) -> bool:
        return self._syntax.available and bool(self._morphology.analyze("és"))

    def repair(
        self, candidate: Candidate, *, protected_conflict: ProtectedConflict | None = None
    ) -> Candidate:
        """Candidat amb la concordança reparada, o el mateix candidat si no es pot."""
        if not self.available or candidate.is_identity:
            return candidate
        found = find_disagreements(self._syntax.parse(candidate.text))
        if len(found) != 1:
            return candidate
        disagreement = found[0]
        if disagreement.key in self._known(candidate.source_text):
            return candidate  # ja hi era a l'original: no es toca
        repaired = self._apply(candidate, disagreement, protected_conflict)
        if repaired is None:
            return candidate
        if find_disagreements(self._syntax.parse(repaired.text)):
            return candidate  # la correcció no ha resolt la discordança
        return repaired

    def _apply(
        self,
        candidate: Candidate,
        disagreement: Disagreement,
        protected_conflict: ProtectedConflict | None,
    ) -> Candidate | None:
        verb = disagreement.verb
        start = candidate.source_offset(verb.start)
        if start is None:
            return None  # el verb és dins del text que ha escrit una regla
        span = Span(start, start + len(verb.text))
        if span.slice(candidate.source_text) != verb.text:  # pragma: no cover - invariant
            return None
        forms = self._forms(verb, disagreement.expected_number)
        if len(forms) != 1:
            return None
        corrected = _matching_case(verb.text, forms[0])
        if corrected == verb.text:
            return None
        if protected_conflict is not None and protected_conflict(span, corrected) is not None:
            return None
        origin = responsible_rule(candidate, disagreement) or "una transformació"
        transformation = Transformation(
            rule_id=REPAIR_RULE_ID,
            text_before=verb.text,
            text_after=corrected,
            changed_span=span,
            transformation_type=TransformationType.MORPHOLOGICAL,
            confidence=1.0,
            semantic_risk=SemanticRisk.NONE,
            explanation=(
                f"Concordança: «{origin}» ha deixat «{verb.text}» sense concordar amb "
                f"«{disagreement.subject.text}» ({disagreement.expected_number}); "
                f"la morfologia local només admet «{corrected}»"
            ),
            metadata={"category": "concordanca", "level": "1", "repair": "1"},
        )
        return Candidate.from_transformations(
            candidate.sentence_index,
            candidate.source_text,
            (*candidate.transformations, transformation),
        )

    def _forms(self, verb: SyntaxToken, number: str) -> tuple[str, ...]:
        """Formes del verb amb el nombre demanat, segons el recurs morfològic."""
        person, mood, tense = _resource_features(verb)
        forms: set[str] = set()
        for entry in self._morphology.analyze(verb.text):
            features = entry.features
            if features.pos != "verb" or not _compatible(features.person, person):
                continue
            if not _compatible(features.mood, mood) or not _compatible(features.tense, tense):
                continue
            forms.update(self._morphology.generate(entry.lemma, replace(features, number=number)))
        return tuple(sorted(forms))

    def _known(self, source_text: str) -> frozenset[tuple[str, str]]:
        cached = self._source_cache.get(source_text)
        if cached is None:
            cached = frozenset(d.key for d in find_disagreements(self._syntax.parse(source_text)))
            self._source_cache[source_text] = cached
        return cached


def _resource_features(verb: SyntaxToken) -> tuple[str | None, str | None, str | None]:
    """Persona, mode i temps del verb en el vocabulari del recurs morfològic.

    Les Universal Dependencies tracten el condicional com un mode; el recurs
    de Softcatalà, com un temps de l'indicatiu. Es tradueix aquí perquè la
    comparació no falli per una diferència de convenció.
    """
    if verb.mood == "cond":
        return verb.person, "ind", "cond"
    return verb.person, verb.mood, verb.tense


def _compatible(entry_value: str | None, wanted: str | None) -> bool:
    """Cert si el tret no contradiu el que diu el parser (desconegut = compatible)."""
    return wanted is None or entry_value is None or entry_value == wanted


def _matching_case(original: str, form: str) -> str:
    """La forma nova amb la caixa de la que substitueix."""
    if original[:1].isupper():
        return form[:1].upper() + form[1:]
    return form


__all__ = ["REPAIR_RULE_ID", "AgreementRepair"]
