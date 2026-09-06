"""Alternança segura entre relatives passives explicatives i participials.

Aquest motor no intenta «entendre» ni reescriure lliurement una relativa. Només
actua quan l'arbre de dependències és fiable i la correspondència és explícita:

- ``N, que fou/foren PART ...,`` → ``N, PART ...,``;
- ``N, que va/van ser PART ...,`` → ``N, PART ...,``;
- ``N, PART ...,`` → ``N, que fou/foren PART ...,`` quan el participi és un
  modificador nominal explicatiu i porta una àncora d'esdeveniment (data,
  complement temporal o agent amb ``per``).

La coma és deliberada: la regla només tracta relatives/participials
**explicatives**. Les restrictives poden canviar l'extensió del nom i es
conserven. Tampoc es redueixen negacions, modalitzacions, relatives actives ni
construccions en què el parser no identifica de manera inequívoca l'antecedent.

L'objectiu és donar al cercador una arquitectura realment diferent que després
pugui combinar-se amb altres operacions (p. ex. inversió copulativa o moviment
del bloc participial), no introduir sinònims.
"""

from __future__ import annotations

from collections.abc import Iterable

from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import Transformation
from parafrasi_cat.rules.base import Rule, RuleContext
from parafrasi_cat.rules.definition import RuleDefinition
from parafrasi_cat.syntax.analysis import SentenceSyntax, SyntaxToken

_NOMINAL_POS = frozenset({"NOUN", "PROPN", "PRON"})
_PARTICIPIAL_DEPS = frozenset({"acl", "amod"})
_PASSIVE_PREFIXES = frozenset(
    {
        ("que", "fou"),
        ("que", "foren"),
        ("que", "va", "ser"),
        ("que", "van", "ser"),
    }
)
_BOUNDARIES = (",", ".", "!", "?", "…", ";")


class RelativeArchitectureRule(Rule):
    """Genera les dues arquitectures només quan el parser en demostra l'estructura."""

    def __init__(self, definition: RuleDefinition) -> None:
        super().__init__(
            definition.rule_id,
            transformation_type=definition.transformation_type,
            description=definition.description,
            category=definition.category or "subordinada",
            level=definition.level,
        )
        self._definition = definition

    @property
    def definition(self) -> RuleDefinition:
        return self._definition

    def propose(self, ctx: RuleContext) -> Iterable[Transformation]:
        analysis = ctx.parse()
        if not analysis.confident:
            return
        seen: set[tuple[int, int, str]] = set()
        for transformation in self._relative_to_participial(ctx, analysis):
            key = (
                transformation.changed_span.start,
                transformation.changed_span.end,
                transformation.text_after,
            )
            if key not in seen:
                seen.add(key)
                yield transformation
        for transformation in self._participial_to_relative(ctx, analysis):
            key = (
                transformation.changed_span.start,
                transformation.changed_span.end,
                transformation.text_after,
            )
            if key not in seen:
                seen.add(key)
                yield transformation

    # --- relativa passiva → participial -------------------------------------------------

    def _relative_to_participial(
        self, ctx: RuleContext, analysis: SentenceSyntax
    ) -> Iterable[Transformation]:
        by_index = {token.index: token for token in analysis.tokens}
        for clause in analysis.tokens:
            if clause.dep != "acl:relcl" or clause.verb_form != "Part":
                continue
            antecedent = by_index.get(clause.head)
            if antecedent is None or antecedent.pos not in _NOMINAL_POS:
                continue
            if not _agreement_allows(antecedent, clause):
                continue
            members = analysis.subtree(clause)
            relatives = [
                token
                for token in members
                if token.pron_type == "Rel" or token.text.casefold() == "que"
            ]
            if len(relatives) != 1:
                continue
            relative = relatives[0]
            if relative.text.casefold() != "que" or relative.start >= clause.start:
                continue
            if not _explanatory_before(ctx.text, relative.start):
                continue
            _start, end = analysis.subtree_span(clause)
            if not _explanatory_after(ctx.text, end):
                continue
            if any(token.is_negation for token in members):
                continue

            prefix_tokens = tuple(
                token.text.casefold()
                for token in analysis.tokens
                if token.start >= relative.start
                and token.end <= clause.start
                and token.pos != "PUNCT"
            )
            if prefix_tokens not in _PASSIVE_PREFIXES:
                continue
            finite = [token for token in members if token.is_finite_verb]
            if any(token.start >= clause.start for token in finite):
                continue

            span = Span(relative.start, clause.start)
            before = span.slice(ctx.text)
            # La seqüència reconeguda ha d'ocupar exactament el prefix; així no
            # eliminem un adverbi o marcador que el tokenitzador hagués deixat entremig.
            if " ".join(before.split()).casefold().rstrip() != " ".join(prefix_tokens):
                continue
            if ctx.protected_conflict(span, "") is not None:
                continue
            yield self._transformation(
                span,
                before,
                "",
                "relative_to_participial",
                "relativa passiva explicativa reduïda a modificador participial",
            )

    # --- participial → relativa passiva -------------------------------------------------

    def _participial_to_relative(
        self, ctx: RuleContext, analysis: SentenceSyntax
    ) -> Iterable[Transformation]:
        by_index = {token.index: token for token in analysis.tokens}
        for participle in analysis.tokens:
            if participle.verb_form != "Part" or participle.dep not in _PARTICIPIAL_DEPS:
                continue
            antecedent = by_index.get(participle.head)
            if antecedent is None or antecedent.pos not in _NOMINAL_POS:
                continue
            if antecedent.number not in {"sg", "pl"}:
                continue
            if not _agreement_allows(antecedent, participle):
                continue
            start, end = analysis.subtree_span(participle)
            if start != participle.start:
                continue
            if not _explanatory_before(ctx.text, start) or not _explanatory_after(ctx.text, end):
                continue
            members = analysis.subtree(participle)
            if any(token.is_finite_verb or token.is_negation for token in members):
                continue
            if not _event_anchor(ctx.text[start:end], members):
                continue

            auxiliary = "foren" if antecedent.number == "pl" else "fou"
            span = Span(participle.start, participle.end)
            after = f"que {auxiliary} {participle.text}"
            if ctx.protected_conflict(span, after) is not None:
                continue
            yield self._transformation(
                span,
                participle.text,
                after,
                "participial_to_relative",
                "modificador participial explicatiu desplegat com a relativa passiva",
            )

    def _transformation(
        self,
        span: Span,
        before: str,
        after: str,
        architecture: str,
        explanation: str,
    ) -> Transformation:
        definition = self._definition
        return Transformation(
            rule_id=self.rule_id,
            text_before=before,
            text_after=after,
            changed_span=span,
            transformation_type=definition.transformation_type,
            confidence=definition.confidence,
            semantic_risk=definition.semantic_risk,
            explanation=f"{definition.description} — {explanation}",
            metadata={
                "category": definition.category or "subordinada",
                "level": str(definition.level),
                "family": "SUBORDINATION",
                "architecture": architecture,
                "parser_required": "true",
                "structural_weight": "0.85",
            },
        )


def _agreement_allows(antecedent: SyntaxToken, participle: SyntaxToken) -> bool:
    """Rebutja contradiccions explícites; la manca d'un tret no s'inventa."""
    if antecedent.number and participle.number and antecedent.number != participle.number:
        return False
    if antecedent.gender and participle.gender and antecedent.gender != participle.gender:
        return False
    return True


def _explanatory_before(text: str, start: int) -> bool:
    return text[:start].rstrip().endswith(",")


def _explanatory_after(text: str, end: int) -> bool:
    tail = text[end:].lstrip()
    return not tail or tail.startswith(_BOUNDARIES)


def _event_anchor(text: str, members: Iterable[SyntaxToken]) -> bool:
    """Evidència mínima que el participi expressa un esdeveniment, no un adjectiu.

    Una data, un complement temporal anotat o un agent introduït per ``per``
    permeten desplegar el participi amb ``fou/foren`` sense convertir adjectius
    qualificatius en esdeveniments inventats.
    """
    if any(character.isdigit() for character in text):
        return True
    tokens = tuple(members)
    if any(token.adv_type == "Tim" or token.dep == "obl:agent" for token in tokens):
        return True
    return any(token.text.casefold() == "per" for token in tokens)


__all__ = ["RelativeArchitectureRule"]
