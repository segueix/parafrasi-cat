"""Canvis verbals segurs (motor «periphrastic_past»).

Passat perifràstic ↔ passat simple: «va encarregar» ↔ «encarregà»,
«van ser» ↔ «foren». Els dos temps són equivalents en català; el canvi és
només de registre. Les formes irregulars provenen d'una taula de dades i les
regulars es deriven de la conjugació (-ar → -à/-aren, -ir → -í/-iren).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from parafrasi_cat.analyzer.clitics import Certainty
from parafrasi_cat.analyzer.tokens import Token, TokenKind, TokenSubkind
from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.text import match_casing
from parafrasi_cat.core.transformation import Transformation
from parafrasi_cat.resources import as_mapping_list, as_str, load_mapping
from parafrasi_cat.rules.base import Rule, RuleContext
from parafrasi_cat.rules.definition import RuleDefinition
from parafrasi_cat.rules.patterns import GrammarHints, is_participle

_AUX_PERSONS: dict[str, tuple[str, str]] = {
    # auxiliar → (persona, nombre)
    "va": ("3", "sg"),
    "van": ("3", "pl"),
    "vam": ("1", "pl"),
    "vau": ("2", "pl"),
}
_REGULAR_ENDINGS: dict[str, dict[tuple[str, str], str]] = {
    "ar": {("3", "sg"): "à", ("3", "pl"): "aren", ("1", "pl"): "àrem", ("2", "pl"): "àreu"},
    "ir": {("3", "sg"): "í", ("3", "pl"): "iren", ("1", "pl"): "írem", ("2", "pl"): "íreu"},
}
_REVERSE_ENDINGS: tuple[tuple[str, str, str], ...] = (
    # (desinència, auxiliar, sufix d'infinitiu)
    ("aren", "van", "ar"),
    ("iren", "van", "ir"),
    ("àrem", "vam", "ar"),
    ("írem", "vam", "ir"),
    ("àreu", "vau", "ar"),
    ("íreu", "vau", "ir"),
)
_REVERSE_SINGULAR: tuple[tuple[str, str], ...] = (("à", "ar"), ("í", "ir"))
# Formes que, davant d'un verb, només poden ser pronoms febles (o la negació).
_PROCLITIC_EVIDENCE = frozenset(
    {"no", "hi", "ho", "li", "es", "s'", "ens", "us", "em", "et", "n'", "m'", "t'"}
)
# Formes ambigües entre article i pronom: només compten si van precedides de «no»
# o d'un altre pronom («no el pagà», «se'l menjà»).
_AMBIGUOUS_CLITICS = frozenset({"el", "la", "els", "les"})


def _pronoun_evidence(tokens: tuple[Token, ...], index: int, sure_pronouns: set[int]) -> bool:
    """Hi ha un pronom feble (o «no») just abans del token ``index``?"""
    if index == 0:
        return False
    previous = tokens[index - 1]
    low = previous.lower.replace("’", "'")
    if (index - 1) in sure_pronouns or low in _PROCLITIC_EVIDENCE:
        return True
    if low in _AMBIGUOUS_CLITICS and index >= 2:
        before = tokens[index - 2]
        return before.lower == "no" or (index - 2) in sure_pronouns
    return False


@dataclass(frozen=True, slots=True)
class IrregularPast:
    infinitive: str
    singular: str
    plural: str


def load_irregular_pasts(path: str | Path) -> tuple[IrregularPast, ...]:
    data = load_mapping(path)
    return tuple(
        IrregularPast(
            as_str(item, "infinitive").strip(),
            as_str(item, "singular").strip(),
            as_str(item, "plural").strip(),
        )
        for item in as_mapping_list(data, "entries")
    )


class PeriphrasticPastRule(Rule):
    """Passat perifràstic → simple («to_simple») o simple → perifràstic («to_periphrastic»)."""

    def __init__(
        self,
        definition: RuleDefinition,
        irregulars: Iterable[IrregularPast] = (),
        *,
        direction: str | None = None,
        hints: GrammarHints | None = None,
    ) -> None:
        super().__init__(
            definition.rule_id,
            transformation_type=definition.transformation_type,
            description=definition.description,
            category=definition.category,
            level=definition.level,
        )
        self._definition = definition
        self._direction = direction or as_str(definition.params, "direction", "to_simple")
        if self._direction not in ("to_simple", "to_periphrastic"):
            raise ConfigError(f"Direcció desconeguda a «{definition.rule_id}»: {self._direction}")
        self._by_infinitive: dict[str, IrregularPast] = {}
        self._by_form: dict[str, tuple[IrregularPast, str]] = {}
        for entry in irregulars:
            self._by_infinitive.setdefault(entry.infinitive.lower(), entry)
            self._by_form.setdefault(entry.singular.lower(), (entry, "va"))
            self._by_form.setdefault(entry.plural.lower(), (entry, "van"))
        self._hints = hints or GrammarHints()

    @property
    def direction(self) -> str:
        return self._direction

    def propose(self, ctx: RuleContext) -> Iterable[Transformation]:
        tokens = tuple(t for t in ctx.sentence.tokens if t.kind is not TokenKind.SPACE)
        if self._direction == "to_simple":
            yield from self._to_simple(ctx, tokens)
        else:
            yield from self._to_periphrastic(ctx, tokens)

    # --- perifràstic → simple ---------------------------------------------------------

    def _to_simple(self, ctx: RuleContext, tokens: tuple[Token, ...]) -> Iterable[Transformation]:
        for index in range(len(tokens) - 1):
            aux, verb = tokens[index], tokens[index + 1]
            persons = _AUX_PERSONS.get(aux.lower)
            if persons is None or verb.kind is not TokenKind.WORD:
                continue
            if index + 2 < len(tokens) and _enclitic_after(tokens[index + 1], tokens[index + 2]):
                continue  # «va veure'l»: el clític hauria de canviar de posició
            simple = self._simple_form(verb.text, persons)
            if simple is None:
                continue
            span = Span(aux.span.start, verb.span.end)
            before = span.slice(ctx.text)
            after = match_casing(aux.text, simple)
            if ctx.protected_conflict(span, after) is not None:
                continue
            yield self._transformation(before, after, span, "passat perifràstic → passat simple")

    def _simple_form(self, infinitive: str, persons: tuple[str, str]) -> str | None:
        low = infinitive.lower()
        irregular = self._by_infinitive.get(low)
        if irregular is not None:
            return (
                irregular.singular
                if persons[1] == "sg" and persons[0] == "3"
                else (irregular.plural if persons == ("3", "pl") else None)
            )
        if self._hints.is_closed_class(low) or len(low) < 4 or is_participle(low):
            return None
        for suffix, endings in _REGULAR_ENDINGS.items():
            if low.endswith(suffix):
                stem = low[: -len(suffix)]
                if not stem or stem.endswith(("ss", "x")):
                    return None
                return stem + endings[persons]
        return None

    # --- simple → perifràstic ---------------------------------------------------------

    def _to_periphrastic(
        self, ctx: RuleContext, tokens: tuple[Token, ...]
    ) -> Iterable[Transformation]:
        sure_pronouns = {
            p.token_index for p in ctx.sentence.pronouns if p.certainty is Certainty.SURE
        }
        for index, token in enumerate(tokens):
            if token.kind is not TokenKind.WORD or token.subkind is TokenSubkind.ROMAN_NUMERAL:
                continue
            if index + 1 < len(tokens) and _enclitic_after(token, tokens[index + 1]):
                continue
            periphrastic = self._periphrastic_form(token, tokens, index, sure_pronouns)
            if periphrastic is None:
                continue
            after = match_casing(token.text, periphrastic)
            if ctx.protected_conflict(token.span, after) is not None:
                continue
            yield self._transformation(
                token.text, after, token.span, "passat simple → passat perifràstic"
            )

    def _periphrastic_form(
        self,
        token: Token,
        tokens: tuple[Token, ...],
        index: int,
        sure_pronouns: set[int],
    ) -> str | None:
        low = token.lower
        irregular = self._by_form.get(low)
        if irregular is not None:
            entry, aux = irregular
            return f"{aux} {entry.infinitive}"
        if self._hints.is_closed_class(low):
            return None
        for ending, aux, suffix in _REVERSE_ENDINGS:
            if low.endswith(ending) and len(low) >= len(ending) + 3:
                return f"{aux} {low[: -len(ending)]}{suffix}"
        if not _pronoun_evidence(tokens, index, sure_pronouns):
            return None
        for ending, suffix in _REVERSE_SINGULAR:
            if low.endswith(ending) and len(low) >= len(ending) + 3:
                return f"va {low[: -len(ending)]}{suffix}"
        return None

    def _transformation(self, before: str, after: str, span: Span, what: str) -> Transformation:
        return Transformation(
            rule_id=self.rule_id,
            text_before=before,
            text_after=after,
            changed_span=span,
            transformation_type=self._definition.transformation_type,
            confidence=self._definition.confidence,
            semantic_risk=self._definition.semantic_risk,
            explanation=f"{self._definition.description or what}: «{before}» → «{after}»",
            metadata={"category": self._definition.category, "level": str(self._definition.level)},
        )


def _enclitic_after(host: Token, following: Token) -> bool:
    """Cert si ``following`` és un pronom enclític adherit a ``host`` («veure'l», «porta-ho»)."""
    return (
        following.kind is TokenKind.CLITIC
        and following.subkind is TokenSubkind.ENCLITIC
        and following.span.start == host.span.end
    )


def periphrastic_rule_from_params(
    definition: RuleDefinition, params: Mapping[str, object], resolve: Path | None
) -> PeriphrasticPastRule:
    """Fàbrica: llegeix la taula d'irregulars indicada a ``params['irregulars']``."""
    file = as_str(params, "irregulars", "")
    irregulars: tuple[IrregularPast, ...] = ()
    if file:
        path = Path(file)
        if not path.is_absolute() and resolve is not None:
            path = resolve / path
        irregulars = load_irregular_pasts(path)
    return PeriphrasticPastRule(definition, irregulars)
