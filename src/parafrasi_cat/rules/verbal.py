"""Canvis verbals segurs (motor «periphrastic_past»).

Passat perifràstic ↔ passat simple: «va encarregar» ↔ «encarregà»,
«van ser» ↔ «foren». Els dos temps són equivalents en català; el canvi és
només de registre. Les formes irregulars provenen d'una taula de dades i les
regulars es deriven de la conjugació (-ar → -à/-aren, -ir → -í/-iren).

En la direcció simple → perifràstic, que una forma *acabi* com un passat
simple no és cap garantia: «sobirà», «germà» o «sofà» acaben en «-à» i no són
verbs. Per això la regla només transforma amb evidència morfosintàctica
suficient, combinada a :mod:`parafrasi_cat.morphology.verbal`: lectures del
recurs morfològic, taula d'irregulars, terminació, analitzador sintàctic i
pronoms febles. Davant del dubte no transforma, i deixa apuntat per què.
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
from parafrasi_cat.morphology.verbal import PastSimpleEvidence, Verdict, assess_past_simple
from parafrasi_cat.resources import as_mapping_list, as_str, load_mapping
from parafrasi_cat.rules.base import Rule, RuleContext
from parafrasi_cat.rules.definition import RuleDefinition
from parafrasi_cat.rules.patterns import GrammarHints, is_participle
from parafrasi_cat.syntax.analysis import SentenceSyntax

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
# Formes que, davant d'un mot, només poden ser pronoms febles: un pronom feble
# només acompanya un verb. «el», «la», «els», «les» no hi són (poden ser
# articles: «no el germà») i la negació tampoc: «no» precedeix igualment un
# adjectiu o un nom («però ja no sobirà», «però no independent»).
_SURE_PROCLITICS = frozenset(
    {"hi", "ho", "li", "es", "s'", "ens", "us", "em", "et", "n'", "m'", "t'"}
)

#: Factor de confiança quan l'analitzador, tot i ser fiable, no hi veu un verb
#: però la morfologia només hi veu un verb de passat. Es manté la transformació
#: (el diccionari és coneixement lèxic, i l'analitzador s'equivoca sovint amb
#: el passat simple), però amb menys confiança: el mode conservador la descarta.
PARSER_DISAGREEMENT_FACTOR = 0.85

#: Clau de metadades amb què les transformacions verbals es fan reconeixibles
#: als validadors de classe.
VERBAL_CHANGE_KEY = "verbal_change"


def _clitic_before(tokens: tuple[Token, ...], index: int, sure_pronouns: set[int]) -> bool:
    """Hi ha un pronom feble segur just abans del token ``index``?"""
    if index == 0:
        return False
    previous = tokens[index - 1]
    if (index - 1) in sure_pronouns:
        return True
    low = previous.lower.replace("’", "'")
    if low in _SURE_PROCLITICS:
        return True
    return (
        previous.kind is TokenKind.CLITIC
        and previous.subkind is TokenSubkind.PROCLITIC
        and low[:1] not in ("d", "l")
    )


def _worth_noting(evidence: PastSimpleEvidence) -> bool:
    """Cert si val la pena explicar el descart al resultat.

    S'apunta quan hi ha hagut un dubte real: una forma amb lectura verbal que
    el context no resol, o una forma que l'analitzador etiqueta com a verb i
    la morfologia desmenteix («sobirà»). Un mot en «-à» o «-í» que cap font no
    pren per verb («matí», «aquí», «català») no és cap candidat de debò, i
    apuntar-lo seria soroll.
    """
    if evidence.verdict is Verdict.AMBIGUOUS:
        return True
    return evidence.verdict is Verdict.NOT_VERB and evidence.parser_verbal


def _between_names(tokens: tuple[Token, ...], index: int) -> bool:
    """Cert si el token va entre dos mots en majúscula que no obren la frase."""
    before = next((t for t in reversed(tokens[:index]) if t.kind is TokenKind.WORD), None)
    after = next((t for t in tokens[index + 1 :] if t.kind is TokenKind.WORD), None)
    if before is None or after is None:
        return False
    if not (before.text[:1].isupper() and after.text[:1].isupper()):
        return False
    return any(t.kind is TokenKind.WORD for t in tokens[: tokens.index(before)])


def _capitalized_inside(tokens: tuple[Token, ...], index: int) -> bool:
    """Cert si el token va en majúscula i no és el primer mot de la frase."""
    token = tokens[index]
    if not token.text[:1].isupper():
        return False
    return any(t.kind is TokenKind.WORD for t in tokens[:index])


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
            yield self._transformation(
                before,
                after,
                span,
                "passat perifràstic → passat simple",
                extra={VERBAL_CHANGE_KEY: "perifrastic_a_simple"},
            )

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
        # L'anàlisi de la frase, si hi ha parser: la fa servir l'evidència per
        # resoldre les formes ambigües. Sense parser és buida i no hi diu res.
        analysis = ctx.parse() if ctx.analysis is not None or ctx.syntax.available else None
        for index, token in enumerate(tokens):
            if token.kind is not TokenKind.WORD or token.subkind is TokenSubkind.ROMAN_NUMERAL:
                continue
            if index + 1 < len(tokens) and _enclitic_after(token, tokens[index + 1]):
                continue
            evidence = self.evidence(ctx, tokens, index, sure_pronouns, analysis)
            if evidence is None:
                continue
            periphrastic = evidence.periphrastic
            if periphrastic is None:
                if _worth_noting(evidence):
                    ctx.note(
                        f"no s'ha canviat «{token.text}» a passat perifràstic: "
                        + "; ".join(evidence.reasons)
                    )
                continue
            after = match_casing(token.text, periphrastic)
            if ctx.protected_conflict(token.span, after) is not None:
                continue
            confidence = self._definition.confidence
            if evidence.parser_agrees is False:
                confidence = round(confidence * PARSER_DISAGREEMENT_FACTOR, 4)
            yield self._transformation(
                token.text,
                after,
                token.span,
                "passat simple → passat perifràstic",
                confidence=confidence,
                extra={
                    VERBAL_CHANGE_KEY: "simple_a_perifrastic",
                    "evidence": ", ".join(evidence.sources),
                    "evidence_detail": "; ".join(evidence.reasons),
                },
            )

    def evidence(
        self,
        ctx: RuleContext,
        tokens: tuple[Token, ...],
        index: int,
        sure_pronouns: set[int],
        analysis: object = None,
    ) -> PastSimpleEvidence | None:
        """Evidència que el token ``index`` és un passat simple transformable.

        ``None`` si la forma no s'assembla a cap passat simple (cap font no en
        diu res i cap terminació no hi encaixa): aleshores no cal ni apuntar-ho.
        """
        token = tokens[index]
        low = token.lower
        irregular: tuple[str, str] | None = None
        found = self._by_form.get(low)
        if found is not None:
            entry, aux = found
            irregular = (entry.infinitive, aux)
        elif self._hints.is_closed_class(low):
            return None  # «fou» és a la taula i alhora auxiliar: la taula mana
        if _between_names(tokens, index):
            # «Benedetto da Rovezzano»: una partícula entre dos noms propis forma
            # part del nom, encara que el diccionari conegui la forma com a verb.
            return None
        regular: tuple[str, str] | None = None
        plural_ending = False
        for ending, aux, suffix in _REVERSE_ENDINGS:
            if low.endswith(ending) and len(low) >= len(ending) + 3:
                regular = (f"{low[: -len(ending)]}{suffix}", aux)
                plural_ending = True
                break
        if regular is None:
            for ending, suffix in _REVERSE_SINGULAR:
                if low.endswith(ending) and len(low) >= len(ending) + 3:
                    regular = (f"{low[: -len(ending)]}{suffix}", "va")
                    break
        parsed = analysis if isinstance(analysis, SentenceSyntax) else None
        evidence = assess_past_simple(
            token.text,
            morphology=ctx.morphology,
            analysis=parsed,
            offset=token.span.start,
            irregular=irregular,
            regular=regular,
            plural_ending=plural_ending,
            clitic_before=_clitic_before(tokens, index, sure_pronouns),
            capitalized_inside=_capitalized_inside(tokens, index),
        )
        if evidence.verdict is Verdict.UNKNOWN and irregular is None and regular is None:
            return None
        if evidence.verdict is not Verdict.VERB and irregular is None and regular is None:
            # Coneguda pel recurs però sense cap terminació de passat: no és
            # cap candidata i no cal apuntar res.
            return None
        return evidence

    def _transformation(
        self,
        before: str,
        after: str,
        span: Span,
        what: str,
        *,
        confidence: float | None = None,
        extra: Mapping[str, str] | None = None,
    ) -> Transformation:
        metadata = {
            "category": self._definition.category,
            "level": str(self._definition.level),
            "family": "VERBAL",
        }
        if extra:
            metadata.update(extra)
        return Transformation(
            rule_id=self.rule_id,
            text_before=before,
            text_after=after,
            changed_span=span,
            transformation_type=self._definition.transformation_type,
            confidence=self._definition.confidence if confidence is None else confidence,
            semantic_risk=self._definition.semantic_risk,
            explanation=f"{self._definition.description or what}: «{before}» → «{after}»",
            metadata=metadata,
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
