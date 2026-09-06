"""Alternança segura entre relatives passives explicatives i participials.

Aquest motor no intenta «entendre» ni reescriure lliurement una relativa. Només
actua quan l'arbre de dependències és fiable i la correspondència és explícita:

- ``N, que fou/foren PART ...,`` → ``N, PART ...,``;
- ``N, que va/van ser PART ...,`` → ``N, PART ...,``;
- quan ``N`` és inequívocament el subjecte principal, la mateixa relativa pot
  donar també ``PART ..., N ...`` (reducció + avantposició del bloc sencer);
- ``N, PART ...,`` → ``N, que fou/foren PART ...,`` quan el participi és un
  modificador nominal explicatiu i porta una àncora d'esdeveniment (data,
  complement temporal o agent amb ``per``).

La coma és deliberada: la regla només tracta relatives/participials
**explicatives**. Les restrictives poden canviar l'extensió del nom i es
conserven. Tampoc es redueixen negacions, modalitzacions, relatives actives ni
construccions en què el parser no identifica de manera inequívoca l'antecedent.

L'objectiu és donar al cercador arquitectures realment diferents que després
puguin competir amb altres operacions, no introduir sinònims.
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
_LOWERABLE_OPENERS = frozenset(
    {
        "el",
        "la",
        "els",
        "les",
        "l'",
        "l’",
        "un",
        "una",
        "uns",
        "unes",
        "aquest",
        "aquesta",
        "aquests",
        "aquestes",
        "aquell",
        "aquella",
        "aquells",
        "aquelles",
    }
)


class RelativeArchitectureRule(Rule):
    """Genera arquitectures relatives/participials només amb estructura demostrada."""

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

            fronted = self._fronted_relative(
                ctx, analysis, antecedent, relative, clause, end, members
            )
            if fronted is not None:
                yield fronted

    def _fronted_relative(
        self,
        ctx: RuleContext,
        analysis: SentenceSyntax,
        antecedent: SyntaxToken,
        relative: SyntaxToken,
        clause: SyntaxToken,
        clause_end: int,
        members: tuple[SyntaxToken, ...],
    ) -> Transformation | None:
        """Redueix i avantposa el participial si modifica el subjecte principal.

        És una arquitectura composta explícita, però continua sent una sola regla
        verificable. Només s'ofereix quan el subjecte ocupa l'inici de l'oració i
        la relativa va immediatament després: si hi ha un altre incís o una
        estructura topicalitzada, s'absté.
        """
        subject = analysis.main_subject()
        if subject is None or subject.index != antecedent.index:
            return None
        if any(
            token is not relative
            and token.pos in {"PRON", "DET"}
            and token.pron_type in {"Prs", "Dem"}
            for token in members
        ):
            return None

        before_relative = ctx.text[: relative.start].rstrip()
        if not before_relative.endswith(","):
            return None
        subject_text = before_relative[:-1].strip()
        if not subject_text or "," in subject_text or antecedent.text not in subject_text:
            return None

        tail = ctx.text[clause_end:].lstrip()
        if not tail.startswith(","):
            return None
        remainder = tail[1:].lstrip()
        if not remainder:
            return None
        participial = ctx.text[clause.start : clause_end].strip()
        if not participial:
            return None

        rebuilt = (
            f"{_capitalize_first(participial)}, "
            f"{_lower_subject_opener(subject_text)} {remainder}"
        )
        span = Span(0, len(ctx.text))
        if ctx.protected_conflict(span, rebuilt) is not None:
            return None
        return self._transformation(
            span,
            ctx.text,
            rebuilt,
            "relative_to_fronted_participial",
            "relativa reduïda i participial explicatiu avantposat davant del seu subjecte",
            family="REORDER",
            structural_weight="0.9",
            confidence=max(0.0, self._definition.confidence - 0.04),
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
        *,
        family: str = "SUBORDINATION",
        structural_weight: str = "0.85",
        confidence: float | None = None,
    ) -> Transformation:
        definition = self._definition
        return Transformation(
            rule_id=self.rule_id,
            text_before=before,
            text_after=after,
            changed_span=span,
            transformation_type=definition.transformation_type,
            confidence=definition.confidence if confidence is None else confidence,
            semantic_risk=definition.semantic_risk,
            explanation=f"{definition.description} — {explanation}",
            metadata={
                "category": definition.category or "subordinada",
                "level": str(definition.level),
                "family": family,
                "architecture": architecture,
                "parser_required": "true",
                "structural_weight": structural_weight,
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


def _capitalize_first(text: str) -> str:
    if not text:
        return text
    return text[0].upper() + text[1:]


def _lower_subject_opener(text: str) -> str:
    """Baixa només un determinant inicial conegut; mai un nom propi."""
    if not text:
        return text
    first, separator, rest = text.partition(" ")
    if first.casefold() not in _LOWERABLE_OPENERS:
        return text
    lowered = first[0].lower() + first[1:]
    return lowered + (separator + rest if separator else "")


__all__ = ["RelativeArchitectureRule"]
