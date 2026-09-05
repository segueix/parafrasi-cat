"""Reparació determinista de fragments nominals anafòrics.

Patró objectiu: «... . Un fet que obligava...» quan la segona frase queda com
un sintagma nominal amb una relativa, sense oració principal. Amb parser local,
si hi ha una frase anterior, el nom és realment l'arrel del fragment i la
relativa en depèn, es pot reformular com «... . Aquest fet obligava...».

No es genera text lliurement: només es substitueix l'inici declarat per una
forma demostrativa equivalent. La regla treballa a escala de paràgraf perquè
«aquest/a» només és segur quan hi ha una frase anterior que fa d'antecedent.
"""

from __future__ import annotations

from collections.abc import Iterable

from parafrasi_cat.analyzer.sentences import Sentence
from parafrasi_cat.analyzer.tokens import TokenKind
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import Transformation
from parafrasi_cat.rules.base import ParagraphContext, ParagraphRule
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


class AnaphoricFragmentRepairRule(ParagraphRule):
    """«X. Un fet que V...» → «X. Aquest fet V...» amb antecedent i parse segurs."""

    def __init__(self, definition: RuleDefinition) -> None:
        super().__init__(
            definition.rule_id,
            transformation_type=definition.transformation_type,
            description=definition.description,
            category=definition.category,
            level=definition.level,
        )
        self._definition = definition

    def propose(self, ctx: ParagraphContext) -> Iterable[Transformation]:
        if not ctx.syntax.available:
            return

        for first, second in zip(ctx.sentences, ctx.sentences[1:], strict=False):
            if not _same_paragraph_gap(first, second, ctx.text):
                continue

            matched = _fragment_head(second)
            if matched is None:
                continue
            determiner, noun, relative, replacement = matched

            analysis = ctx.parse_sentence(second)
            root = analysis.root
            noun_syntax = analysis.token_at(noun.span.start)
            relative_syntax = analysis.token_at(relative.span.start)
            if root is None or noun_syntax is None or relative_syntax is None:
                continue

            # La regla només actua sobre un fragment nominal: el nom inicial ha
            # de ser l'arrel. En una oració completa («Un fet que X és Y»),
            # l'arrel és el predicat principal i no es toca.
            if root.index != noun_syntax.index or root.pos not in _NOMINAL_POS:
                continue
            if any(t.head == root.index and t.dep in COPULA_DEPS for t in analysis.tokens):
                continue

            relatives = tuple(
                t for t in analysis.tokens if t.head == root.index and t.dep in _RELATIVE_DEPS
            )
            if not relatives:
                continue

            # «que» ha de formar part de la relativa que depèn del nom. Acceptem
            # que pengi del verb de la relativa o d'un node intern del seu subarbre.
            relative_members = {
                member.index
                for clause in relatives
                for member in analysis.subtree(clause)
            }
            if relative_syntax.index not in relative_members:
                continue

            start = second.span.start + determiner.span.start
            end = second.span.start + relative.span.end
            span = Span(start, end)
            before = span.slice(ctx.text)
            if ctx.protected_conflict(span, replacement) is not None:
                continue

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


def _fragment_head(sentence: Sentence):  # type: ignore[no-untyped-def]
    """Retorna l'inici reconegut del fragment, o ``None`` si no és dels declarats."""
    tokens = tuple(t for t in sentence.tokens if t.kind is not TokenKind.SPACE)
    if len(tokens) < 5:
        return None
    determiner, noun, relative = tokens[0], tokens[1], tokens[2]
    if determiner.kind is not TokenKind.WORD or noun.kind is not TokenKind.WORD:
        return None
    if relative.lower != "que":
        return None
    key = (determiner.lower.replace("’", "'"), noun.lower.replace("’", "'"))
    replacement = ANAPHORIC_HEADS.get(key)
    if replacement is None:
        return None
    return determiner, noun, relative, replacement


def _same_paragraph_gap(first: Sentence, second: Sentence, text: str) -> bool:
    """Exigeix dues frases consecutives del mateix paràgraf, sense salt de línia."""
    gap = text[first.span.end : second.span.start]
    return bool(gap) and gap.isspace() and "\n" not in gap and "\r" not in gap
