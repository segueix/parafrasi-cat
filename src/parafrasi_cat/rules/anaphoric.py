"""Reparació determinista de fragments nominals anafòrics.

Patró objectiu: «Un fet que obligava...» quan la frase queda com un sintagma
nominal amb una relativa, sense oració principal. Amb parser local, si el nom
és realment l'arrel del fragment i la relativa en depèn, es pot reformular com
«Aquest fet obligava...». No es genera text lliurement: només es substitueix
l'inici declarat per una forma demostrativa equivalent.
"""

from __future__ import annotations

from collections.abc import Iterable

from parafrasi_cat.analyzer.tokens import TokenKind
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import Transformation
from parafrasi_cat.rules.base import Rule, RuleContext
from parafrasi_cat.rules.definition import RuleDefinition
from parafrasi_cat.syntax.analysis import COPULA_DEPS


#: Inicis que indiquen un fragment anafòric reprenent la frase anterior.
#: Es manté deliberadament una llista curta: davant del dubte, no es transforma.
ANAPHORIC_HEADS: dict[tuple[str, str], str] = {
    ("un", "fet"): "Aquest fet",
    ("una", "circumstància"): "Aquesta circumstància",
    ("un", "aspecte"): "Aquest aspecte",
    ("una", "situació"): "Aquesta situació",
    ("un", "element"): "Aquest element",
}

_RELATIVE_DEPS = frozenset({"acl", "acl:relcl"})
_NOMINAL_POS = frozenset({"NOUN", "PROPN", "PRON"})


class AnaphoricFragmentRepairRule(Rule):
    """«Un fet que V...» → «Aquest fet V...» només si el parser confirma fragment."""

    def __init__(self, definition: RuleDefinition) -> None:
        super().__init__(
            definition.rule_id,
            transformation_type=definition.transformation_type,
            description=definition.description,
            category=definition.category,
            level=definition.level,
        )
        self._definition = definition

    def propose(self, ctx: RuleContext) -> Iterable[Transformation]:
        if not ctx.syntax.available:
            return

        tokens = tuple(t for t in ctx.sentence.tokens if t.kind is not TokenKind.SPACE)
        if len(tokens) < 5:
            return

        determiner, noun, relative = tokens[0], tokens[1], tokens[2]
        key = (determiner.lower.replace("’", "'"), noun.lower.replace("’", "'"))
        replacement = ANAPHORIC_HEADS.get(key)
        if replacement is None or relative.lower != "que":
            return
        if determiner.kind is not TokenKind.WORD or noun.kind is not TokenKind.WORD:
            return

        analysis = ctx.parse()
        root = analysis.root
        noun_syntax = analysis.token_at(noun.span.start)
        relative_syntax = analysis.token_at(relative.span.start)
        if root is None or noun_syntax is None or relative_syntax is None:
            return

        # La regla només actua sobre un fragment nominal: el nom inicial ha de
        # ser l'arrel. Si hi ha una oració principal («Un fet que X és Y»),
        # l'arrel serà el predicat principal i no es toca.
        if root.index != noun_syntax.index or root.pos not in _NOMINAL_POS:
            return
        if any(t.head == root.index and t.dep in COPULA_DEPS for t in analysis.tokens):
            return

        relatives = tuple(
            t for t in analysis.tokens if t.head == root.index and t.dep in _RELATIVE_DEPS
        )
        if not relatives:
            return

        # «que» ha de formar part de la relativa que depèn del nom. Acceptem que
        # pengi directament del verb de la relativa o d'un node intern del seu
        # subarbre, però mai d'una altra construcció.
        relative_members = {
            member.index
            for clause in relatives
            for member in analysis.subtree(clause)
        }
        if relative_syntax.index not in relative_members:
            return

        span = Span(determiner.span.start, relative.span.end)
        before = span.slice(ctx.text)
        if ctx.protected_conflict(span, replacement) is not None:
            return

        yield Transformation(
            rule_id=self.rule_id,
            text_before=before,
            text_after=replacement,
            changed_span=span,
            transformation_type=self._definition.transformation_type,
            confidence=self._definition.confidence,
            semantic_risk=self._definition.semantic_risk,
            explanation=(
                f"{self._definition.description}: «{before}» → «{replacement}»"
            ),
            metadata={
                "category": self._definition.category,
                "level": str(self._definition.level),
                "family": "REPAIR",
                "strategy": "demostratiu_anaforic",
            },
        )
