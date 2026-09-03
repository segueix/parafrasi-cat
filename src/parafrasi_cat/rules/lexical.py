"""Regla de substitució lèxica basada en diccionari."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.text import match_casing, phrase_pattern
from parafrasi_cat.core.transformation import SemanticRisk, Transformation, TransformationType
from parafrasi_cat.resources import as_float, as_mapping_list, as_str, load_mapping
from parafrasi_cat.rules.base import Rule, RuleContext


@dataclass(frozen=True, slots=True)
class SubstitutionEntry:
    """Una equivalència del diccionari de substitucions."""

    source: str
    target: str
    semantic_risk: SemanticRisk = SemanticRisk.LOW
    confidence: float = 0.8
    transformation_type: TransformationType = TransformationType.LEXICAL
    note: str = ""

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.target.strip():
            raise ValueError("source i target no poden ser buits")
        if self.source.strip().lower() == self.target.strip().lower():
            raise ValueError(f"source i target són iguals: «{self.source}»")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence ha d'estar entre 0 i 1")


class LexicalSubstitutionRule(Rule):
    """Substitueix paraules o locucions per equivalents registrats en un diccionari.

    És la regla més senzilla del motor i serveix de model per a la resta:
    cerca cada entrada com a paraula sencera, respecta els fragments protegits,
    conserva les majúscules del fragment original i explica cada canvi.
    """

    DEFAULT_ID = "lexical.substitution"

    def __init__(
        self,
        entries: Sequence[SubstitutionEntry],
        *,
        rule_id: str = DEFAULT_ID,
        transformation_type: TransformationType = TransformationType.LEXICAL,
        description: str = "Substitució lèxica basada en diccionari",
        source_name: str = "",
        category: str = "lexic",
        level: int = 1,
    ) -> None:
        super().__init__(
            rule_id,
            transformation_type=transformation_type,
            description=description,
            category=category,
            level=level,
        )
        self._entries = tuple(entries)
        self._patterns = tuple((entry, phrase_pattern(entry.source)) for entry in self._entries)
        self._source_name = source_name

    @property
    def entries(self) -> tuple[SubstitutionEntry, ...]:
        return self._entries

    def propose(self, ctx: RuleContext) -> Iterable[Transformation]:
        text = ctx.text
        for entry, pattern in self._patterns:
            for match in pattern.finditer(text):
                span = Span(match.start(), match.end())
                if ctx.is_protected(span):
                    continue
                before = match.group(0)
                after = match_casing(before, entry.target)
                if after == before:
                    continue
                explanation = (
                    f"S'ha substituït «{before}» per «{after}», "
                    "una forma equivalent registrada al diccionari de substitucions"
                )
                if entry.note:
                    explanation += f" ({entry.note})"
                metadata = {"source": entry.source, "target": entry.target}
                if self._source_name:
                    metadata["dictionary"] = self._source_name
                yield Transformation(
                    rule_id=self.rule_id,
                    text_before=before,
                    text_after=after,
                    changed_span=span,
                    transformation_type=entry.transformation_type,
                    confidence=entry.confidence,
                    semantic_risk=entry.semantic_risk,
                    explanation=explanation,
                    metadata=metadata,
                )

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        rule_id: str = DEFAULT_ID,
        category: str = "lexic",
        level: int = 1,
    ) -> LexicalSubstitutionRule:
        """Carrega un diccionari de substitucions en YAML/JSON.

        Format::

            description: ...
            transformation_type: lexical      # opcional (lexical | connector | ...)
            default_semantic_risk: low        # opcional
            default_confidence: 0.8           # opcional
            entries:
              - source: gairebé
                target: quasi
                note: sinònims plens
                semantic_risk: low            # opcional
                confidence: 0.9               # opcional
                transformation_type: lexical  # opcional
        """
        data = load_mapping(path)
        default_type = TransformationType(as_str(data, "transformation_type", "lexical"))
        default_risk = SemanticRisk.parse(as_str(data, "default_semantic_risk", "low"))
        default_confidence = as_float(data, "default_confidence", 0.8)
        entries = [
            SubstitutionEntry(
                source=as_str(item, "source"),
                target=as_str(item, "target"),
                semantic_risk=SemanticRisk.parse(as_str(item, "semantic_risk", default_risk.value)),
                confidence=as_float(item, "confidence", default_confidence),
                transformation_type=TransformationType(
                    as_str(item, "transformation_type", default_type.value)
                ),
                note=as_str(item, "note", ""),
            )
            for item in as_mapping_list(data, "entries")
        ]
        return cls(
            entries,
            rule_id=rule_id,
            transformation_type=default_type,
            description=as_str(data, "description", "Substitució lèxica basada en diccionari"),
            source_name=Path(path).name,
            category=category,
            level=level,
        )
