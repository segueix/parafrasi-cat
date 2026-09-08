"""Munta la pantalla de composició: frases, redaccions i fragments clicables.

El composant no és un motor nou. Fa servir la canonada de sempre per obtenir
els candidats segurs de cada frase —amb els mateixos validadors i el mateix
puntuador— i hi afegeix dues coses que només tenen sentit quan hi ha una
persona davant:

1. de cada frase en tria les redaccions **més diferents entre elles**, en lloc
   de quedar-se amb la millor;
2. de cada redacció en marca els fragments que tenen alternativa, perquè es
   puguin clicar.

L'original hi és sempre, l'últim de la llista: qui escriu ha de poder
quedar-se'l i, tot i així, canviar-hi una paraula. Si el motor no arriba a
tres alternatives validades, es diu clarament; no s'omple la llista.
"""

from __future__ import annotations

from dataclasses import dataclass

from parafrasi_cat.analyzer.analysis import Analysis
from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.compose.options import (
    DEFAULT_WANTED,
    DraftOption,
    SentenceDraft,
    choose_options,
)
from parafrasi_cat.core.transformation import CHAINED_RULES_KEY
from parafrasi_cat.pipeline.pipeline import Pipeline
from parafrasi_cat.pipeline.result import ParaphraseResult, SentenceResult
from parafrasi_cat.synonyms.suggester import SynonymSuggester

MAX_RULES_IN_SUMMARY = 3

#: Nom llegible de cada família de transformació, per a la targeta de la frase.
#: Es fa servir la família i no la regla perquè és el que la signatura declara:
#: una divisió amb reordenació ha de dir les dues coses, encara que les regles
#: hagin arribat encadenades en una sola transformació.
_FAMILY_LABELS: dict[str, str] = {
    "LEXICAL": "lèxic",
    "CONNECTOR": "connector",
    "PUNCTUATION": "puntuació",
    "VERBAL": "forma verbal",
    "NOMINALIZATION": "nominalització",
    "SYNTACTIC": "construcció",
    "REORDER": "ordre de la frase",
    "SUBORDINATION": "subordinació",
    "COPULAR": "verb copulatiu",
    "IMPERSONAL": "construcció impersonal",
    "CLAUSE_SPLIT": "divisió en dues frases",
    "CLAUSE_MERGE": "fusió de frases",
    "COPULAR_MERGE": "fusió copulativa",
    "EPISTEMIC": "llenguatge assertiu",
    "REPAIR": "concordança",
}


@dataclass(frozen=True, slots=True)
class ParagraphDraft:
    """El paràgraf sencer preparat per compondre."""

    source_text: str
    sentences: tuple[SentenceDraft, ...]
    separators: tuple[str, ...]
    """Text entre frases (i abans de la primera), per tornar-les a ajuntar igual."""
    tail: str = ""
    """El que queda després de l'última frase (un espai, un salt de línia…)."""
    suggestions: str = ""
    """Quines fonts d'alternatives hi ha actives, per dir-ho a la interfície."""

    @property
    def n_sentences(self) -> int:
        return len(self.sentences)

    def assemble(self, chosen: dict[int, str] | None = None) -> str:
        """El paràgraf final amb el text triat de cada frase (l'original per defecte)."""
        picked = chosen or {}
        parts: list[str] = []
        for separator, sentence in zip(self.separators, self.sentences, strict=True):
            parts.append(separator)
            parts.append(picked.get(sentence.index, sentence.source_text))
        parts.append(self.tail)
        return "".join(parts)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_text": self.source_text,
            "n_sentences": self.n_sentences,
            "separators": list(self.separators),
            "tail": self.tail,
            "suggestions": self.suggestions,
            "sentences": [sentence.to_dict() for sentence in self.sentences],
        }


class Composer:
    """Prepara un paràgraf per compondre'l frase a frase."""

    def __init__(
        self,
        pipeline: Pipeline,
        suggester: SynonymSuggester,
        *,
        wanted: int = DEFAULT_WANTED,
    ) -> None:
        self._pipeline = pipeline
        self._suggester = suggester
        self._wanted = max(1, wanted)

    @property
    def wanted(self) -> int:
        return self._wanted

    def compose(self, text: str) -> ParagraphDraft:
        """Executa la canonada i en munta les redaccions de cada frase."""
        result = self._pipeline.run(text)
        analysis = self._pipeline.analyzer.analyze(text)
        separators, tail = _separators(text, analysis)
        sentences = tuple(self._sentence(sentence) for sentence in _ordered(result, analysis))
        return ParagraphDraft(
            source_text=text,
            sentences=sentences,
            separators=separators,
            tail=tail,
            suggestions=self._suggester.describe(),
        )

    # -- frase -------------------------------------------------------------------------------

    def _sentence(self, result: SentenceResult) -> SentenceDraft:
        rewrites = choose_options(result.candidates, self._wanted)
        options = [
            self._option(f"s{result.index}-r{n}", evaluated.candidate, original=False)
            for n, evaluated in enumerate(rewrites)
        ]
        options.append(self._option(f"s{result.index}-o", _identity(result), original=True))
        return SentenceDraft(
            index=result.index,
            source_text=result.source_text,
            options=tuple(options),
            diagnostics=_diagnostics(result, self._pipeline.syntax.available),
            note=_note(len(rewrites), self._wanted) + (
                " No s’ha trobat cap alternativa estructural que superi els filtres automàtics; "
                "les alternatives disponibles són canvis locals."
                if rewrites and not any(e.candidate.is_structural for e in rewrites) else ""
            ),
        )

    def _option(self, option_id: str, candidate: Candidate, *, original: bool) -> DraftOption:
        protected = self._pipeline.protector.protect(candidate.text)
        return DraftOption(
            option_id=option_id,
            text=candidate.text,
            original=original,
            signature=candidate.signature,
            structural_degree=candidate.structural_degree(),
            change_ratio=round(candidate.change_ratio(), 4),
            summary="text original, sense cap canvi" if original else _summary(candidate),
            rules=() if original else _rule_ids(candidate),
            tokens=self._suggester.options(candidate.text, protected),
        )


def _diagnostics(result: SentenceResult, parser_available: bool) -> dict[str, object]:
    rejected = [e for e in result.candidates if not e.accepted]
    structural = sum(e.accepted and e.candidate.is_structural
                     for e in result.candidates if not e.candidate.is_identity)
    messages = [
        "Analitzador sintàctic disponible." if parser_available else
        "Sense analitzador sintàctic: les regles que el necessiten no s’apliquen.",
        f"{len(result.rule_proposals)} regles provades sobre el text inicial; "
        f"{sum(n > 0 for n in result.rule_proposals.values())} han generat propostes.",
        result.generation.describe(),
        f"{structural} candidats estructurals han superat els filtres; "
        f"{len(rejected)} candidats han estat rebutjats.",
        *result.notes,
    ]
    if not any(result.rule_proposals.values()):
        messages.append("Cap regla ha generat una proposta: cal revisar l’anàlisi o la cobertura dels patrons.")
    if result.generation.truncated:
        messages.append("La cerca ha arribat al límit configurat; no s’han explorat totes les combinacions.")
    reasons = list(dict.fromkeys(
        [r.reason for r in result.rejected_proposals] + [e.rejection_reason for e in rejected]
    ))
    messages.extend("Motiu de rebuig: " + reason for reason in reasons[:8])
    return {"messages": messages, "initial_rule_proposals": result.rule_proposals,
            "search": result.generation.to_dict(), "rejection_reasons": reasons,
            "accepted_structural": structural, "parser_available": parser_available}


def _identity(result: SentenceResult) -> Candidate:
    """El candidat identitat de la frase (el text tal com el va portar qui escriu)."""
    for evaluated in result.candidates:
        if evaluated.candidate.is_identity:
            return evaluated.candidate
    return Candidate(result.index, result.source_text, result.source_text, ())


def _ordered(result: ParaphraseResult, analysis: Analysis) -> tuple[SentenceResult, ...]:
    """Les frases en ordre de text (les del resultat ja hi són, però no depenguem-ne)."""
    del analysis
    return tuple(sorted(result.sentences, key=lambda s: s.span.start))


def _separators(text: str, analysis: Analysis) -> tuple[tuple[str, ...], str]:
    """El que hi ha entre frases, per poder tornar a ajuntar el paràgraf tal qual."""
    separators: list[str] = []
    position = 0
    for sentence in analysis.sentences:
        separators.append(text[position : sentence.span.start])
        position = sentence.span.end
    return tuple(separators), text[position:]


def _rule_ids(candidate: Candidate) -> tuple[str, ...]:
    """Regles que han intervingut, encadenades incloses.

    Des de la v1.3.16 una composició de regles arriba com una sola
    transformació que conserva la identitat de la primera; les altres queden
    a ``CHAINED_RULES_KEY``. Sense mirar-hi, una divisió amb reordenació es
    presentaria com si només hagués canviat l'ordre.
    """
    found: dict[str, None] = {}
    for transformation in candidate.transformations:
        chained = transformation.metadata.get(CHAINED_RULES_KEY)
        if isinstance(chained, (list, tuple)) and chained:
            for rule_id in chained:
                found.setdefault(str(rule_id), None)
        else:
            found.setdefault(transformation.rule_id, None)
    return tuple(found)


def _summary(candidate: Candidate) -> str:
    """Què s'ha canviat en aquesta redacció, en poques paraules.

    Es llegeix de la signatura (les famílies), no de les regles: des de la
    v1.3.16 una composició arriba com una sola transformació que conserva la
    identitat de la primera, i mirar-ne la regla presentaria una divisió amb
    reordenació com si només hagués canviat l'ordre.
    """
    labels: dict[str, None] = {}
    for family in candidate.families:
        label = _FAMILY_LABELS.get(family.value)
        if label:
            labels.setdefault(label, None)
    listed = list(labels)[:MAX_RULES_IN_SUMMARY]
    return ", ".join(listed) if listed else "sense canvis"


def _note(found: int, wanted: int) -> str:
    """Per què no hi ha tantes redaccions com se'n demanaven."""
    if found >= wanted:
        return ""
    if found == 0:
        return (
            "El motor no ha trobat cap alternativa que superi els filtres automàtics d'aquesta frase. Pots "
            "canviar-hi paraules i connectors clicant-los."
        )
    return (
        f"El motor només ha trobat {found} alternativa que supera els filtres automàtics d'aquesta frase "
        f"de les {wanted} demanades. La resta de canvis els pots fer clicant les paraules."
        if found == 1
        else (
            f"El motor només ha trobat {found} alternatives que superen els filtres automàtics d'aquesta frase "
            f"de les {wanted} demanades. La resta de canvis els pots fer clicant les paraules."
        )
    )


__all__ = ["Composer", "ParagraphDraft"]
