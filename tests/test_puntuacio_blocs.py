"""Regressions de connectors inicials amb anàlisi sintàctica fixada."""

import re

import pytest

from parafrasi_cat.rules import load_rule_definitions
from parafrasi_cat.rules.base import RuleContext
from parafrasi_cat.rules.blocks import BlockMoveRule
from parafrasi_cat.syntax.analysis import SentenceSyntax, SyntaxToken


@pytest.mark.parametrize(
    ("clause", "expected", "mood"),
    [
        ("Encara que plogui", "Sortirem, encara que plogui.", "subj"),
        ("Tot i que plogui", "Sortirem, tot i que plogui.", "subj"),
        ("Si plou", "Sortirem si plou.", "ind"),
        ("Com que plou", "Sortirem, ja que plou.", "ind"),
        ("Perquè plogui", None, "subj"),
    ],
)
def test_initial_connector_keeps_punctuation_and_relation(
    paths, catalan_analyzer, clause, expected, mood
):
    text = f"{clause}, sortirem."
    matches = list(re.finditer(r"\w+|[^\w\s]", text))
    subordinate = len(clause.split()) - 1
    root = subordinate + 2
    tokens = []
    for index, match in enumerate(matches):
        pos, dep, head, token_mood = "SCONJ", "mark", subordinate, None
        if index == subordinate:
            pos, dep, head, token_mood = "VERB", "advcl", root, mood
        elif index == root:
            pos, dep, head, token_mood = "VERB", "ROOT", root, "ind"
        elif match.group() in {",", "."}:
            pos, dep, head = "PUNCT", "punct", root
        tokens.append(SyntaxToken(
            index, match.group(), match.group().lower(), pos, dep, head,
            match.start(), match.end(), mood=token_mood,
        ))
    definition = next(
        d for d in load_rule_definitions(
            paths.language() / "transformations" / "blocs.yaml"
        ) if d.rule_id == "blocs.subordinada_adverbial"
    )
    ctx = RuleContext(
        sentence=catalan_analyzer.analyze(text).sentences[0],
        analysis=SentenceSyntax(text, tuple(tokens)),
    )
    outputs = [t.apply(text) for t in BlockMoveRule(definition).propose(ctx)]
    assert outputs == ([] if expected is None else [expected])
