"""Regla de formes preferides: substitueix les formes a evitar dels diccionaris actius."""

from __future__ import annotations

from collections.abc import Iterable

from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.text import match_casing, phrase_pattern
from parafrasi_cat.core.transformation import SemanticRisk, Transformation, TransformationType
from parafrasi_cat.dictionaries.dictionary import DictionarySet, Substitution
from parafrasi_cat.rules.base import Rule, RuleContext


class DictionaryPreferenceRule(Rule):
    """Proposa la forma preferida d'un diccionari allà on el text fa servir una forma a evitar.

    Funciona com la substitució lèxica: cerca cada forma a evitar com a
    paraula o locució sencera, no toca mai un fragment protegit (ni els
    termes protegits dels mateixos diccionaris), conserva les majúscules i
    explica cada canvi citant el diccionari i les notes de l'entrada.
    """

    DEFAULT_ID = "dictionary.preferred_form"

    def __init__(
        self,
        dictionaries: DictionarySet,
        *,
        rule_id: str = DEFAULT_ID,
        level: int = 1,
        category: str = "diccionari",
    ) -> None:
        super().__init__(
            rule_id,
            transformation_type=TransformationType.LEXICAL,
            description="Forma preferida del diccionari del projecte en lloc d'una forma a evitar",
            category=category,
            level=level,
        )
        self._dictionaries = dictionaries
        self._substitutions = tuple(
            (substitution, phrase_pattern(substitution.source))
            for substitution in dictionaries.substitutions
        )

    @property
    def substitutions(self) -> tuple[Substitution, ...]:
        return tuple(substitution for substitution, _ in self._substitutions)

    def propose(self, ctx: RuleContext) -> Iterable[Transformation]:
        text = ctx.text
        for substitution, pattern in self._substitutions:
            for match in pattern.finditer(text):
                span = Span(match.start(), match.end())
                if ctx.is_protected(span):
                    continue
                before = match.group(0)
                after = match_casing(before, substitution.target)
                if after == before:
                    continue
                entry = substitution.entry
                explanation = (
                    f"S'ha substituït «{before}» per «{after}», la forma preferida del diccionari "
                    f"«{substitution.dictionary}» per al terme «{entry.term}»"
                )
                if entry.notes:
                    explanation += f" ({entry.notes})"
                yield Transformation(
                    rule_id=self.rule_id,
                    text_before=before,
                    text_after=after,
                    changed_span=span,
                    transformation_type=TransformationType.LEXICAL,
                    confidence=substitution.confidence,
                    semantic_risk=SemanticRisk.LOW,
                    explanation=explanation,
                    metadata={
                        "category": self.category,
                        "dictionary": substitution.dictionary,
                        "term": entry.term,
                        "source": substitution.source,
                        "target": substitution.target,
                    },
                )
