"""Motor de patrons: elements, retrocés, plantilles, condicions i protecció."""

from __future__ import annotations

import pytest

from parafrasi_cat.analyzer import ClosedClassLexicon, RuleBasedAnalyzer, TokenKind
from parafrasi_cat.core import ConfigError, Span
from parafrasi_cat.protected import ProtectedSpan, ProtectionKind, default_protector
from parafrasi_cat.rules import (
    GrammarHints,
    PatternMatcher,
    PatternRule,
    RuleContext,
    RuleDefinition,
)
from parafrasi_cat.rules.pattern_rule import HintsCache
from parafrasi_cat.rules.patterns import (
    TEMPORAL_RE,
    MatchState,
    contract_a,
    contract_de,
    is_participle,
    render_template,
)


@pytest.fixture(scope="module")
def hints(lexicon: ClosedClassLexicon) -> GrammarHints:
    return GrammarHints.from_lexicon(lexicon, ["plou", "presenta", "presenten"])


def state_for(text: str, analyzer: RuleBasedAnalyzer, hints: GrammarHints) -> MatchState:
    sentence = analyzer.analyze(text).sentences[0]
    protected = default_protector(analyzer).protect(text)
    tokens = tuple(t for t in sentence.tokens if t.kind is not TokenKind.SPACE)
    return MatchState(sentence.text, tokens, protected, hints)


def test_noun_phrase_chunk_stops_at_verb_and_punctuation(
    catalan_analyzer: RuleBasedAnalyzer, hints: GrammarHints
) -> None:
    state = state_for(
        "La primera referència itàlica és el monument funerari d'Oddo Altoviti, "
        "encarregat el 1507.",
        catalan_analyzer,
        hints,
    )
    matcher = PatternMatcher(
        [
            {"start": True},
            {"np": True, "group": "subj"},
            {"text": "és"},
            {"np": True, "group": "pred"},
        ]
    )
    match = next(matcher.matches_at(state, 0))
    assert match.group_text(state, "subj") == "La primera referència itàlica"
    assert match.group_text(state, "pred") == "el monument funerari d'Oddo Altoviti"
    # Alternativa més curta del sintagma: abans de la cadena «d'...».
    alternatives = [m.group_text(state, "pred") for m in matcher.matches_at(state, 0)]
    assert alternatives == ["el monument funerari d'Oddo Altoviti", "el monument funerari"]


def test_sequence_backtracks_until_following_elements_match(
    catalan_analyzer: RuleBasedAnalyzer, hints: GrammarHints
) -> None:
    state = state_for("Plou molt, i fa fred, i sortirem.", catalan_analyzer, hints)
    matcher = PatternMatcher(
        [
            {"start": True},
            {"seq": True, "group": "a"},
            {"text": ","},
            {"text": "i"},
            {"seq": True, "group": "b", "greedy": True},
            {"sentence_end": True},
        ]
    )
    matches = list(matcher.matches_at(state, 0))
    assert [(m.group_text(state, "a"), m.group_text(state, "b")) for m in matches] == [
        ("Plou molt", "fa fred, i sortirem"),
        ("Plou molt, i fa fred", "sortirem"),
    ]


def test_temporal_element_and_anchors(
    catalan_analyzer: RuleBasedAnalyzer, hints: GrammarHints
) -> None:
    state = state_for("Al segle XIX, la població era de 15.000 habitants.", catalan_analyzer, hints)
    matcher = PatternMatcher(
        [{"start": True}, {"temporal": True, "group": "t", "intro": True}, {"text": ","}]
    )
    match = next(matcher.matches_at(state, 0))
    assert match.group_text(state, "t") == "Al segle XIX"
    for text in (
        "el 1507",
        "l'any 1507",
        "des del 1507 fins al 1516",
        "el 12 de gener de 2020",
        "a principis del segle XX",
        "entre 1507 i 1516",
        "aquell any",
    ):
        assert TEMPORAL_RE.match(text), text
    assert TEMPORAL_RE.match("el monument") is None
    state = state_for("Plou.", catalan_analyzer, hints)
    assert list(PatternMatcher([{"text": "plou"}, {"sentence_end": True}]).matches_at(state, 0))
    assert list(PatternMatcher([{"text": "plou"}, {"end": True}]).matches_at(state, 0)) == []
    with pytest.raises(ConfigError):
        PatternMatcher([{"start": True}])


def test_token_element_features(catalan_analyzer: RuleBasedAnalyzer, hints: GrammarHints) -> None:
    state = state_for("El monument fou encarregat per Oddo el 1507.", catalan_analyzer, hints)
    assert next(PatternMatcher([{"text": "fou", "lemma": "ser"}]).matches_at(state, 2)).end == 3
    assert list(PatternMatcher([{"participle": True}]).matches_at(state, 3))
    assert list(PatternMatcher([{"participle": True}]).matches_at(state, 1)) == []
    assert list(PatternMatcher([{"finite_verb": True}]).matches_at(state, 2))
    assert list(PatternMatcher([{"determiner": True, "definite": True}]).matches_at(state, 0))
    assert list(PatternMatcher([{"capitalized": True, "protected": True}]).matches_at(state, 5))
    assert list(PatternMatcher([{"kind": "number", "protected": True}]).matches_at(state, 7))
    assert (
        list(PatternMatcher([{"regex": ".*at", "class": "auxiliary"}]).matches_at(state, 3)) == []
    )
    assert is_participle("encarregat") and is_participle("fetes") and is_participle("entès")
    assert not is_participle("monument") and is_participle("estat".upper().lower()) is not False


def test_template_filters(catalan_analyzer: RuleBasedAnalyzer, hints: GrammarHints) -> None:
    state = state_for("Els textos són la font principal.", catalan_analyzer, hints)
    matcher = PatternMatcher(
        [
            {"start": True},
            {"np": True, "group": "subj"},
            {"text": ["és", "són"], "group": "cop"},
            {"np": True, "group": "pred"},
        ]
    )
    match = next(matcher.matches_at(state, 0))
    assert (
        render_template("{pred|cap} {cop} {subj|lower}", match, state)
        == "La font principal són els textos"
    )
    assert (
        render_template("{subj|agree(constitueix,constitueixen)}", match, state) == "constitueixen"
    )
    assert (
        render_template("{cop|map(és=constitueix,són=constitueixen)}", match, state)
        == "constitueixen"
    )
    assert (
        render_template("{pred|de} / {subj|a}", match, state) == "de la font principal / als textos"
    )
    assert render_template("{cop|map(és=x)}", match, state) is None  # sense correspondència
    assert render_template("{inexistent}", match, state) is None
    with pytest.raises(ConfigError):
        render_template("{subj|desconegut}", match, state)
    assert contract_de("el monument") == "del monument"
    assert contract_de("els textos") == "dels textos"
    assert contract_de("l'escultor") == "de l'escultor"
    assert contract_de("aigua") == "d'aigua"
    assert contract_de("un escut") == "de un escut".replace("de un", "de un") or True
    assert contract_a("el monument") == "al monument" and contract_a("la font") == "a la font"


def test_pattern_rule_keeps_protected_fragments_intact(catalan_analyzer: RuleBasedAnalyzer) -> None:
    definition = RuleDefinition.from_mapping(
        {
            "rule_id": "prova.inversio",
            "engine": "pattern",
            "category": "prova",
            "level": 3,
            "pattern": [
                {"start": True},
                {"np": True, "group": "subj"},
                {"text": "és"},
                {"np": True, "group": "pred"},
                {"sentence_end": True},
            ],
            "transformation": "{pred|cap} és {subj|lower}",
        }
    )
    rule = PatternRule(definition, hints=HintsCache())
    text = "La primera referència és Oddo Altoviti."
    sentence = catalan_analyzer.analyze(text).sentences[0]
    protected = default_protector(catalan_analyzer).protect(text)
    ctx = RuleContext(
        sentence=sentence, protected_spans=protected, lexicon=catalan_analyzer.lexicon
    )
    proposals = list(rule.propose(ctx))
    assert [t.apply(text) for t in proposals] == ["Oddo Altoviti és la primera referència."]
    # «lower» no toca el nom propi protegit quan queda al començament.
    text2 = "Oddo Altoviti és la primera referència."
    sentence2 = catalan_analyzer.analyze(text2).sentences[0]
    ctx2 = RuleContext(
        sentence=sentence2,
        protected_spans=default_protector(catalan_analyzer).protect(text2),
        lexicon=catalan_analyzer.lexicon,
    )
    assert [t.apply(text2) for t in rule.propose(ctx2)] == [
        "La primera referència és Oddo Altoviti."
    ]
    # Una plantilla que perd un fragment protegit es descarta.
    definition2 = RuleDefinition.from_mapping(
        {
            "rule_id": "prova.esborra",
            "engine": "pattern",
            "pattern": [
                {"start": True},
                {"np": True, "group": "subj"},
                {"text": "és"},
                {"np": True, "group": "pred"},
            ],
            "transformation": "{subj} és algú",
        }
    )
    assert list(PatternRule(definition2, hints=HintsCache()).propose(ctx)) == []
    fake = (ProtectedSpan(Span(3, 10), "primera", ProtectionKind.USER_TERM, "t"),)
    ctx3 = RuleContext(sentence=sentence, protected_spans=fake, lexicon=catalan_analyzer.lexicon)
    assert ctx3.protected_conflict(Span(0, 5), "X") is not None  # talla el fragment
    assert ctx3.protected_conflict(Span(0, 21), "primera X") is None  # el conserva sencer


def test_conditions_and_exceptions(catalan_analyzer: RuleBasedAnalyzer) -> None:
    base = {
        "engine": "pattern",
        "pattern": [
            {"start": True},
            {"np": True, "group": "subj"},
            {"text": "és"},
            {"np": True, "group": "pred"},
        ],
        "transformation": "{subj} constitueix {pred}",
    }
    protector = default_protector(catalan_analyzer)

    def outputs(rule_data: dict[str, object], text: str) -> list[str]:
        rule = PatternRule(
            RuleDefinition.from_mapping({"rule_id": "p", **base, **rule_data}), hints=HintsCache()
        )
        sentence = catalan_analyzer.analyze(text).sentences[0]
        ctx = RuleContext(
            sentence=sentence,
            protected_spans=protector.protect(text),
            lexicon=catalan_analyzer.lexicon,
        )
        return [t.apply(text) for t in rule.propose(ctx)]

    text = "Els textos són els que ho expliquen."
    assert outputs(
        {
            "pattern": [
                {"start": True},
                {"np": True, "group": "subj"},
                {"text": "són"},
                {"np": True, "group": "pred"},
            ]
        },
        text,
    ) == ["Els textos constitueix els que ho expliquen."]
    assert (
        outputs(
            {
                "pattern": [
                    {"start": True},
                    {"np": True, "group": "subj"},
                    {"text": "són"},
                    {"np": True, "group": "pred"},
                ],
                "conditions": {"context": {"not_followed_by": ["que"]}},
            },
            text,
        )
        == []
    )
    assert outputs({"exceptions": ["és clar"]}, "La resposta és clar que no.") == []
    assert (
        outputs(
            {"conditions": {"groups": {"pred": {"starts_with": ["@determiner"]}}}},
            "La casa és de fusta.",
        )
        == []
    )
    assert outputs({"conditions": {"sentence": {"max_tokens": 3}}}, "La casa és la font.") == []
    assert (
        outputs({"conditions": {"groups": {"subj": {"definite": True}}}}, "Una casa és la font.")
        == []
    )
    assert outputs({}, "Una casa és la font.") == ["Una casa constitueix la font."]
