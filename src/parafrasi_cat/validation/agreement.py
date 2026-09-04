"""Concordança de subjecte i verb, comprovada amb els recursos locals.

Fa servir el parser sintàctic i el recurs morfològic de l'ordinador: no hi ha
cap model generatiu, cap servei extern i cap heurística d'endevinar. Si algun
dels dos recursos no hi és, el validador no diu res i el motor continua amb
les seves comprovacions de sempre.

Regla de fons: **només compten les discordances que el motor ha introduït**.
Una discordança que ja era al text de l'autor no descarta cap candidat, i
tampoc no es corregeix sola: el motor no esmena el text original.
"""

from __future__ import annotations

from dataclasses import dataclass

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.syntax.analysis import SentenceSyntax, SyntaxProvider, SyntaxToken
from parafrasi_cat.validation.base import ValidationContext
from parafrasi_cat.validation.result import (
    ValidationDimension,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)

#: Relació del complement d'un partitiu o d'un col·lectiu («la majoria **dels
#: autors**»). Amb un nucli d'aquesta mena, el català admet la concordança amb
#: el nucli o amb el complement, i no s'hi toca res.
PARTITIVE_DEPS = frozenset({"nmod"})

#: Nuclis col·lectius i quantitatius que admeten concordança *ad sensum*. És una
#: llista tancada i revisable: no es dedueix de res. Un subjecte que no hi sigui
#: ha de concordar amb el seu verb encara que porti complements.
COLLECTIVE_LEMMAS = frozenset(
    {
        "centenar",
        "colla",
        "conjunt",
        "desena",
        "dotzena",
        "grup",
        "majoria",
        "meitat",
        "miler",
        "milió",
        "minoria",
        "muntanya",
        "nombre",
        "part",
        "percentatge",
        "quantitat",
        "quart",
        "resta",
        "sèrie",
        "terç",
        "totalitat",
        "vintena",
    }
)


@dataclass(frozen=True, slots=True)
class Disagreement:
    """Una discordança de nombre entre el subjecte principal i el seu verb."""

    subject: SyntaxToken
    verb: SyntaxToken

    @property
    def expected_number(self) -> str:
        """Nombre que hauria de tenir el verb, segons el subjecte."""
        return self.subject.number or ""

    @property
    def key(self) -> tuple[str, str]:
        """Identificador per comparar la mateixa discordança en dos textos."""
        return (self.subject.text.lower(), self.verb.text.lower())

    def describe(self) -> str:
        return (
            f"«{self.subject.text}» ({self.subject.number}) no concorda amb "
            f"«{self.verb.text}» ({self.verb.number})"
        )


def find_disagreements(analysis: SentenceSyntax) -> tuple[Disagreement, ...]:
    """Discordances de nombre entre el subjecte principal i el verb principal.

    Només es mira quan el parser confia en l'anàlisi i identifica un únic
    subjecte i un únic verb conjugat. Els subjectes partitius i col·lectius
    queden fora: la concordança *ad sensum* hi és correcta.
    """
    if not analysis.confident:
        return ()
    subject = analysis.main_subject()
    verb = analysis.main_verb()
    if subject is None or verb is None:
        return ()
    if subject.number is None or verb.number is None or subject.number == verb.number:
        return ()
    if _is_partitive(subject, analysis):
        return ()
    return (Disagreement(subject, verb),)


def _is_partitive(subject: SyntaxToken, analysis: SentenceSyntax) -> bool:
    """Cert si el subjecte és un col·lectiu amb complement d'un altre nombre.

    «La majoria dels autors accepten» és correcte; «els sarcòfags de marbre
    presenta», no. Per això no n'hi ha prou amb el complement: el nucli ha de
    ser un dels col·lectius de la llista.
    """
    if subject.lemma.lower() not in COLLECTIVE_LEMMAS:
        return False
    return any(
        token.head == subject.index
        and token.dep in PARTITIVE_DEPS
        and token.number is not None
        and token.number != subject.number
        for token in analysis.tokens
    )


def responsible_rule(candidate: Candidate, disagreement: Disagreement) -> str:
    """Regla que ha tocat el subjecte o el verb de la discordança (buit si cap)."""
    for token in (disagreement.subject, disagreement.verb):
        rule_id = candidate.rule_at(token.start)
        if rule_id:
            return rule_id
    return ""


class AgreementValidator:
    """Descarta els candidats amb una discordança que no era al text original.

    Ho fa amb el parser local; si no n'hi ha cap d'instal·lat, no diu res.
    """

    validator_id = "concordanca"
    dimension = ValidationDimension.GRAMMAR

    def __init__(self, syntax: SyntaxProvider) -> None:
        self._syntax = syntax
        self._source_cache: dict[str, frozenset[tuple[str, str]]] = {}

    @property
    def available(self) -> bool:
        return self._syntax.available

    def validate(self, candidate: Candidate, ctx: ValidationContext) -> ValidationResult:
        if not self._syntax.available or candidate.is_identity:
            return ValidationResult.passed()
        found = find_disagreements(self._syntax.parse(candidate.text))
        if not found:
            return ValidationResult.passed()
        known = self._known(ctx.source_text)
        issues: list[ValidationIssue] = []
        for disagreement in found:
            if disagreement.key in known:
                continue  # la discordança ja era al text de l'autor
            rule_id = responsible_rule(candidate, disagreement)
            origin = f"la regla «{rule_id}» ha introduït" if rule_id else "s'ha introduït"
            issues.append(
                ValidationIssue(
                    self.validator_id,
                    ValidationSeverity.ERROR,
                    f"{origin} una discordança subjecte-verb: {disagreement.describe()}",
                    self.dimension,
                )
            )
        return ValidationResult(tuple(issues))

    def _known(self, source_text: str) -> frozenset[tuple[str, str]]:
        cached = self._source_cache.get(source_text)
        if cached is None:
            cached = frozenset(d.key for d in find_disagreements(self._syntax.parse(source_text)))
            self._source_cache[source_text] = cached
        return cached


__all__ = [
    "AgreementValidator",
    "Disagreement",
    "find_disagreements",
    "responsible_rule",
]
