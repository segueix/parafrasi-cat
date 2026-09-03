"""Comprovació dels exemples declarats a les regles.

Cada regla porta exemples positius (entrada → sortida esperada) i negatius
(entrades que no han de produir cap proposta). Aquesta comprovació és la
garantia que la regla és «identificable i comprovable»: els tests la passen a
totes les definicions carregades.
"""

from __future__ import annotations

from dataclasses import dataclass

from parafrasi_cat.analyzer.analysis import Analyzer
from parafrasi_cat.core.transformation import Transformation
from parafrasi_cat.protected.protector import Protector
from parafrasi_cat.rules.base import AnyRule, ParagraphContext, ParagraphRule, Rule, RuleContext
from parafrasi_cat.rules.definition import RuleDefinition


@dataclass(frozen=True, slots=True)
class ExampleFailure:
    rule_id: str
    input: str
    expected: str | None
    produced: tuple[str, ...]

    def describe(self) -> str:
        if self.expected is None:
            return (
                f"[{self.rule_id}] no hauria de proposar res per «{self.input}», "
                f"però proposa: {list(self.produced)}"
            )
        return (
            f"[{self.rule_id}] per «{self.input}» s'esperava «{self.expected}»; "
            f"proposa: {list(self.produced)}"
        )


def outputs_for(
    rule: AnyRule, text: str, analyzer: Analyzer, protector: Protector
) -> tuple[str, ...]:
    """Textos que resulten d'aplicar cadascuna de les propostes de la regla a ``text``."""
    return tuple(t.apply(text) for t in proposals_for(rule, text, analyzer, protector))


def proposals_for(
    rule: AnyRule, text: str, analyzer: Analyzer, protector: Protector
) -> tuple[Transformation, ...]:
    analysis = analyzer.analyze(text)
    protected = protector.protect(text)
    lexicon = getattr(analyzer, "lexicon", None)
    if isinstance(rule, ParagraphRule):
        paragraph_ctx = ParagraphContext(
            text=text,
            sentences=analysis.sentences,
            protected_spans=protected,
            source_text=text,
            lexicon=lexicon,
        )
        return tuple(rule.propose(paragraph_ctx))
    if not isinstance(rule, Rule) or not analysis.sentences:
        return ()
    proposals: list[Transformation] = []
    for sentence in analysis.sentences:
        ctx = RuleContext(
            sentence=sentence,
            protected_spans=Protector.within(protected, sentence.span),
            document_text=text,
            lexicon=lexicon,
        )
        for transformation in rule.propose(ctx):
            if transformation.changed_span.slice(sentence.text) != transformation.text_before:
                continue
            shifted = Transformation(
                rule_id=transformation.rule_id,
                text_before=transformation.text_before,
                text_after=transformation.text_after,
                changed_span=sentence.absolute(transformation.changed_span),
                transformation_type=transformation.transformation_type,
                confidence=transformation.confidence,
                semantic_risk=transformation.semantic_risk,
                explanation=transformation.explanation,
                metadata=transformation.metadata,
            )
            proposals.append(shifted)
    return tuple(proposals)


def verify_examples(
    rule: AnyRule,
    definition: RuleDefinition,
    analyzer: Analyzer,
    protector: Protector,
) -> tuple[ExampleFailure, ...]:
    """Retorna els exemples de la definició que la regla no compleix."""
    failures: list[ExampleFailure] = []
    for example in definition.examples:
        produced = outputs_for(rule, example.input, analyzer, protector)
        if example.output is None:
            if produced:
                failures.append(ExampleFailure(rule.rule_id, example.input, None, produced))
        elif example.output not in produced:
            failures.append(ExampleFailure(rule.rule_id, example.input, example.output, produced))
    return tuple(failures)
