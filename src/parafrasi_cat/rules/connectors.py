"""Regla de connectors equivalents (motor «connector»).

Les classes d'equivalència es declaren a les dades: connectors de la mateixa
funció discursiva i el mateix lloc sintàctic («slot») són intercanviables.
Cada substitució possible és un candidat.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.text import match_casing, phrase_pattern
from parafrasi_cat.core.transformation import SemanticRisk, Transformation
from parafrasi_cat.resources import as_bool, as_mapping_list, as_str, as_str_list
from parafrasi_cat.rules.base import Rule, RuleContext
from parafrasi_cat.rules.definition import RuleDefinition

SLOTS = ("sentence_initial", "conjunction", "medial")


@dataclass(frozen=True, slots=True)
class ConnectorMember:
    form: str
    register: str = "neutre"


@dataclass(frozen=True, slots=True)
class ConnectorClass:
    """Un grup de connectors intercanviables."""

    class_id: str
    slot: str
    members: tuple[ConnectorMember, ...]
    targets: tuple[ConnectorMember, ...] = ()
    """Si n'hi ha, les substitucions van només de ``members`` cap a ``targets`` (dirigides)."""
    semantic_risk: SemanticRisk | None = None
    function: str = ""

    def __post_init__(self) -> None:
        if self.slot not in SLOTS:
            raise ValueError(f"Slot desconegut a la classe «{self.class_id}»: {self.slot}")

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> ConnectorClass:
        risk = data.get("semantic_risk")
        return cls(
            class_id=as_str(data, "id"),
            slot=as_str(data, "slot", "conjunction"),
            members=tuple(_member(item) for item in as_mapping_list(data, "members")),
            targets=tuple(_member(item) for item in as_mapping_list(data, "targets")),
            semantic_risk=None if risk is None else SemanticRisk.parse(str(risk)),
            function=as_str(data, "function", ""),
        )


def _member(item: Mapping[str, object]) -> ConnectorMember:
    return ConnectorMember(as_str(item, "form").strip(), as_str(item, "register", "neutre"))


class ConnectorEquivalenceRule(Rule):
    """Substitueix un connector per un altre de la mateixa classe i el mateix slot."""

    def __init__(self, definition: RuleDefinition) -> None:
        super().__init__(
            definition.rule_id,
            transformation_type=definition.transformation_type,
            description=definition.description,
            category=definition.category,
            level=definition.level,
        )
        self._definition = definition
        self._classes = tuple(
            ConnectorClass.from_mapping(item)
            for item in as_mapping_list(definition.params, "classes")
        )
        self._registers = frozenset(as_str_list(definition.params, "registers")) or frozenset(
            {"neutre", "formal"}
        )
        self._keep_register = as_bool(definition.params, "keep_register", False)
        self._patterns: list[tuple[ConnectorClass, ConnectorMember, re.Pattern[str]]] = []
        for connector_class in self._classes:
            for member in connector_class.members:
                pattern = phrase_pattern(member.form)
                if connector_class.slot == "sentence_initial":
                    pattern = re.compile(
                        r"^[«“\"(]?\s*" + pattern.pattern + r"(?=\s*,)", re.IGNORECASE
                    )
                self._patterns.append((connector_class, member, pattern))

    @property
    def classes(self) -> tuple[ConnectorClass, ...]:
        return self._classes

    def propose(self, ctx: RuleContext) -> Iterable[Transformation]:
        text = ctx.text
        for connector_class, member, pattern in self._patterns:
            function_name = connector_class.function or connector_class.class_id
            for found in pattern.finditer(text):
                span = Span(found.start(), found.end())
                before = span.slice(text)
                if ctx.is_protected(span):
                    continue
                if not _phrase_starts_at(before, member.form):
                    continue
                if connector_class.slot == "medial" and not _delimited(text, span):
                    continue
                for target in self._targets_for(connector_class, member):
                    after = _rewrite(before, member.form, target.form)
                    if after == before or _repeats_next_word(text, span, target.form):
                        continue
                    yield Transformation(
                        rule_id=self.rule_id,
                        text_before=before,
                        text_after=after,
                        changed_span=span,
                        transformation_type=self._definition.transformation_type,
                        confidence=self._definition.confidence,
                        semantic_risk=connector_class.semantic_risk
                        or self._definition.semantic_risk,
                        explanation=(
                            f"Connector equivalent ({function_name}): "
                            f"«{member.form}» → «{target.form}»"
                        ),
                        metadata={
                            "category": self._definition.category,
                            "level": str(self._definition.level),
                            "class": connector_class.class_id,
                            "register": target.register,
                        },
                    )

    def _targets_for(
        self, connector_class: ConnectorClass, member: ConnectorMember
    ) -> list[ConnectorMember]:
        candidates = connector_class.targets or connector_class.members
        result = []
        for target in candidates:
            if target.form.lower() == member.form.lower():
                continue
            if target.register not in self._registers:
                continue
            if self._keep_register and target.register != member.register:
                continue
            result.append(target)
        return result


def _phrase_starts_at(before: str, form: str) -> bool:
    return before.lower().lstrip('«“"( ').startswith(form.lower().split()[0])


def _rewrite(before: str, source: str, target: str) -> str:
    """Substitueix la locució dins del fragment conservant el prefix (cometes) i les majúscules."""
    match = phrase_pattern(source).search(before)
    if match is None:
        return before
    original = match.group(0)
    return before[: match.start()] + match_casing(original, target) + before[match.end() :]


_BEFORE_DELIMITERS = frozenset(",;:(«—–")
_AFTER_DELIMITERS = frozenset(",.;:)»—–!?")


def _delimited(text: str, span: Span) -> bool:
    """Cert si la locució té puntuació almenys per un costat i no la segueix «que»."""
    before = text[: span.start].rstrip()
    after = text[span.end :].lstrip()
    if after.lower().startswith("que") and (len(after) == 3 or not after[3].isalpha()):
        return False
    before_ok = not before or before[-1] in _BEFORE_DELIMITERS
    after_ok = not after or after[0] in _AFTER_DELIMITERS
    return before_ok or after_ok


def _repeats_next_word(text: str, span: Span, target: str) -> bool:
    """Evita «i també ... també»: cap paraula del connector nou pot ser la següent del text."""
    following = text[span.end :].split(maxsplit=3)[:2]
    target_words = {w.lower() for w in target.split() if len(w) > 1}
    return any(word.lower().strip(",.;") in target_words for word in following)
