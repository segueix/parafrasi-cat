"""Verb ↔ construcció nominal amb verb lleuger (motor «nominalization»).

«van analitzar les dades» ↔ «van fer l'anàlisi de les dades». Només s'aplica
als parells verb–nom registrats a les dades, amb les formes de present
explícites per no haver de conjugar.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from parafrasi_cat.analyzer.tokens import Token, TokenKind
from parafrasi_cat.core.errors import ConfigError
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.text import match_casing
from parafrasi_cat.core.transformation import Transformation
from parafrasi_cat.resources import as_mapping_list, as_str, as_str_list, load_mapping
from parafrasi_cat.rules.base import Rule, RuleContext
from parafrasi_cat.rules.definition import RuleDefinition
from parafrasi_cat.rules.patterns import (
    GrammarHints,
    MatchState,
    NounPhraseElement,
    contract_de,
)

_AUX = frozenset({"va", "van", "vam", "vau", "vaig", "vas", "ha", "han", "havia", "havien"})
_VOWEL_RE = re.compile(r"^[haeiouàèéíòóúïü]", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class NominalizationPair:
    verb: str
    noun: str
    gender: str
    present_sg: str
    present_pl: str
    participle: str = ""

    @property
    def article(self) -> str:
        if _VOWEL_RE.match(self.noun):
            return "l'"
        return "el " if self.gender == "m" else "la "


@dataclass(frozen=True, slots=True)
class LightVerb:
    infinitive: str
    present_sg: str
    present_pl: str
    participle: str


DEFAULT_LIGHT_VERBS: tuple[LightVerb, ...] = (
    LightVerb("fer", "fa", "fan", "fet"),
    LightVerb("realitzar", "realitza", "realitzen", "realitzat"),
    LightVerb("dur a terme", "duu a terme", "duen a terme", "dut a terme"),
)


def load_nominalization_pairs(path: str | Path) -> tuple[NominalizationPair, ...]:
    data = load_mapping(path)
    return tuple(
        NominalizationPair(
            verb=as_str(item, "verb").strip().lower(),
            noun=as_str(item, "noun").strip().lower(),
            gender=as_str(item, "gender", "f"),
            present_sg=as_str(item, "present_sg").strip().lower(),
            present_pl=as_str(item, "present_pl").strip().lower(),
            participle=as_str(item, "participle", "").strip().lower(),
        )
        for item in as_mapping_list(data, "entries")
    )


class NominalizationRule(Rule):
    """Verb → nom («to_noun») o nom → verb («to_verb»)."""

    def __init__(
        self,
        definition: RuleDefinition,
        pairs: Iterable[NominalizationPair],
        *,
        direction: str | None = None,
        light_verbs: Iterable[LightVerb] = DEFAULT_LIGHT_VERBS,
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
        self._direction = direction or as_str(definition.params, "direction", "to_noun")
        if self._direction not in ("to_noun", "to_verb"):
            raise ConfigError(f"Direcció desconeguda a «{definition.rule_id}»: {self._direction}")
        self._pairs = tuple(pairs)
        self._by_verb_form: dict[str, tuple[NominalizationPair, str]] = {}
        self._by_noun: dict[str, NominalizationPair] = {}
        for pair in self._pairs:
            self._by_verb_form[pair.verb] = (pair, "inf")
            self._by_verb_form[pair.present_sg] = (pair, "sg")
            self._by_verb_form[pair.present_pl] = (pair, "pl")
            self._by_noun[pair.noun] = pair
        self._light_verbs = tuple(light_verbs)
        self._light_forms: dict[str, tuple[LightVerb, str]] = {}
        for light in self._light_verbs:
            self._light_forms[light.infinitive] = (light, "inf")
            self._light_forms[light.present_sg] = (light, "sg")
            self._light_forms[light.present_pl] = (light, "pl")
        self._hints = hints or GrammarHints()
        self._np = NounPhraseElement(bare=True, max_tokens=14)

    @property
    def direction(self) -> str:
        return self._direction

    def propose(self, ctx: RuleContext) -> Iterable[Transformation]:
        tokens = tuple(t for t in ctx.sentence.tokens if t.kind is not TokenKind.SPACE)
        state = MatchState(ctx.text, tokens, ctx.protected_spans, self._hints, ctx.morphology)
        if self._direction == "to_noun":
            yield from self._to_noun(ctx, state)
        else:
            yield from self._to_verb(ctx, state)

    def _object_end(self, state: MatchState, index: int) -> int | None:
        ends = self._np.ends(state, index)
        return ends[0] if ends else None

    def _to_noun(self, ctx: RuleContext, state: MatchState) -> Iterable[Transformation]:
        tokens = state.tokens
        for index, token in enumerate(tokens):
            found = self._by_verb_form.get(token.lower)
            if found is None or token.kind is not TokenKind.WORD:
                continue
            pair, form = found
            if form == "inf" and (index == 0 or tokens[index - 1].lower not in _AUX):
                continue
            if index + 1 >= len(tokens) or tokens[index + 1].kind is TokenKind.CLITIC:
                continue
            end = self._object_end(state, index + 1)
            if end is None:
                continue
            obj_span = Span(tokens[index + 1].span.start, tokens[end - 1].span.end)
            obj = obj_span.slice(ctx.text)
            span = Span(token.span.start, obj_span.end)
            before = span.slice(ctx.text)
            for light in self._light_verbs:
                verb_form = {
                    "inf": light.infinitive,
                    "sg": light.present_sg,
                    "pl": light.present_pl,
                }[form]
                verb_text = match_casing(token.text, verb_form)
                after = f"{verb_text} {pair.article}{pair.noun} {contract_de(obj)}"
                if ctx.protected_conflict(span, after) is not None:
                    continue
                yield self._transformation(before, after, span, pair)

    def _to_verb(self, ctx: RuleContext, state: MatchState) -> Iterable[Transformation]:
        tokens = state.tokens
        for index, token in enumerate(tokens):
            light_found = self._light_match(tokens, index)
            if light_found is None:
                continue
            light, form, light_end = light_found
            if form == "inf" and (index == 0 or tokens[index - 1].lower not in _AUX):
                continue
            # article + nom
            article_index = light_end
            if article_index >= len(tokens):
                continue
            article = tokens[article_index]
            noun_index = article_index + 1
            if article.lower.replace("’", "'") in ("l'",):
                noun_index = article_index + 1
            elif article.lower not in ("el", "la", "un", "una"):
                continue
            if noun_index >= len(tokens):
                continue
            pair = self._by_noun.get(tokens[noun_index].lower)
            if pair is None:
                continue
            prep_index = noun_index + 1
            if prep_index >= len(tokens):
                continue
            prep = tokens[prep_index].lower.replace("’", "'")
            if prep not in ("de", "d'", "del", "dels"):
                continue
            obj_start = prep_index + 1
            if obj_start >= len(tokens):
                continue
            end = self._object_end(state, obj_start)
            if end is None:
                continue
            obj_text = Span(tokens[obj_start].span.start, tokens[end - 1].span.end).slice(ctx.text)
            restored = _restore_object(prep, obj_text)
            span = Span(token.span.start, tokens[end - 1].span.end)
            before = span.slice(ctx.text)
            verb_form = {"inf": pair.verb, "sg": pair.present_sg, "pl": pair.present_pl}[form]
            after = f"{match_casing(token.text, verb_form)} {restored}"
            if ctx.protected_conflict(span, after) is not None:
                continue
            yield self._transformation(before, after, span, pair)

    def _light_match(
        self, tokens: tuple[Token, ...], index: int
    ) -> tuple[LightVerb, str, int] | None:
        """Reconeix un verb lleuger (d'una o més paraules) a partir de ``index``."""
        for light in self._light_verbs:
            for form_name, form in (
                ("inf", light.infinitive),
                ("sg", light.present_sg),
                ("pl", light.present_pl),
            ):
                words = form.split()
                if index + len(words) > len(tokens):
                    continue
                if all(tokens[index + k].lower == w for k, w in enumerate(words)):
                    return light, form_name, index + len(words)
        return None

    def _transformation(
        self, before: str, after: str, span: Span, pair: NominalizationPair
    ) -> Transformation:
        return Transformation(
            rule_id=self.rule_id,
            text_before=before,
            text_after=after,
            changed_span=span,
            transformation_type=self._definition.transformation_type,
            confidence=self._definition.confidence,
            semantic_risk=self._definition.semantic_risk,
            explanation=(
                f"{self._definition.description} ({pair.verb} ↔ {pair.noun}): "
                f"«{before}» → «{after}»"
            ),
            metadata={
                "category": self._definition.category,
                "level": str(self._definition.level),
                "pair": f"{pair.verb}/{pair.noun}",
            },
        )


def _restore_object(prep: str, obj_text: str) -> str:
    """Desfà la contracció «de + article»: del → el, dels → els, d'X → X."""
    if prep == "del":
        return "el " + obj_text
    if prep == "dels":
        return "els " + obj_text
    return obj_text


def nominalization_rule_from_params(
    definition: RuleDefinition, params: Mapping[str, object], resolve: Path | None
) -> NominalizationRule:
    file = as_str(params, "pairs", "")
    if not file:
        raise ConfigError(f"La regla «{definition.rule_id}» necessita el paràmetre «pairs»")
    path = Path(file)
    if not path.is_absolute() and resolve is not None:
        path = resolve / path
    light_names = as_str_list(params, "light_verbs")
    light_verbs = (
        tuple(lv for lv in DEFAULT_LIGHT_VERBS if lv.infinitive in light_names)
        if light_names
        else DEFAULT_LIGHT_VERBS
    )
    return NominalizationRule(definition, load_nominalization_pairs(path), light_verbs=light_verbs)
