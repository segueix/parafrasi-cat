"""Casos comunicats per l'usuari i controls no vistos, sense baixar models."""
import json
from pathlib import Path

import pytest

from parafrasi_cat.pipeline import PipelineConfig, apply_mode
from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.modes import RewriteMode
from parafrasi_cat.rules.blocks import BlockMoveRule
from parafrasi_cat.rules.definition import load_rule_definitions
from parafrasi_cat.syntax.analysis import SentenceSyntax, SyntaxToken
from parafrasi_cat.validation.grammar import assess_grammar
from parafrasi_cat.compose.composer import _diagnostics


@pytest.fixture(scope='module')
def pipeline():
    root = Path(__file__).resolve().parents[1]
    return build_pipeline(apply_mode(PipelineConfig(home=root, rule_set='parafrasi',
                                                    languagetool=False), RewriteMode.DEEP, 5))


def test_six_reported_sentences_have_no_new_duplicate_commas(pipeline):
    texts = json.loads((Path(__file__).parent / 'fixtures/composicio_escacs.json').read_text())
    for text in texts:
        result = pipeline.run(text).sentences[0]
        assert result.rule_proposals
        assert result.to_dict()['rule_proposals'] == result.rule_proposals
        for evaluated in result.candidates:
            if evaluated.accepted:
                assert ', ,' not in evaluated.candidate.text
                assert not evaluated.candidate.text.endswith(' com.')
        diagnostics = _diagnostics(result, pipeline.syntax.available)
        assert diagnostics['search'] == result.generation.to_dict()
        assert diagnostics['messages']
    first = pipeline.run(texts[0]).sentences[0]
    assert any(e.accepted and 'ordre.observacio_inicial_a_final' in e.candidate.rule_ids
               for e in first.candidates)


@pytest.mark.parametrize('text', ['Però la torre és antiga.', 'Però, la torre és antiga.'])
def test_connector_absorbs_optional_comma(pipeline, text):
    matches = [t for t in pipeline.propose(text)
               if t.rule_id == 'cobertura.pero_inicial_a_tanmateix']
    assert matches and all(t.text_after == 'Tanmateix, la torre és antiga' for t in matches)


def test_new_punctuation_errors_block_but_existing_ones_do_not():
    assert assess_grammar('Tanmateix, , plou.', 'Però, plou.').errors
    assert not assess_grammar('Tanmateix, , plou.', 'Però, , plou.').errors


def test_mistagged_com_is_not_an_independent_circumstantial():
    root = Path(__file__).resolve().parents[1]
    definition = next(d for d in load_rule_definitions(root / 'resources/ca/transformations/blocs.yaml')
                      if d.rule_id == 'blocs.circumstancial_curt')
    rule = BlockMoveRule(definition)
    text = 'Com es pot observar, la torre és antiga.'
    token = SyntaxToken(0, 'Com', 'com', 'ADV', 'advmod', 1, 0, 3)
    syntax = SentenceSyntax(text, (token, SyntaxToken(1, 'és', 'ser', 'VERB', 'ROOT', 1, 29, 31)))
    assert rule._circumstantial(syntax, token, text, len(text)-1) is None


def test_reporting_clause_stays_whole_on_unseen_text(pipeline):
    text = 'Com es pot veure, el pont conserva els arcs.'
    matches = [t for t in pipeline.propose(text) if t.rule_id == 'ordre.observacio_inicial_a_final']
    assert matches and matches[0].text_after == 'El pont conserva els arcs, com es pot veure'
    for negative in ('Com es pot veure el pont?', 'Com es podria veure, el pont conserva els arcs.'):
        assert not any(t.rule_id.startswith('ordre.observacio') for t in pipeline.propose(negative))


def test_medial_reporting_clause_requires_verified_subject(pipeline):
    import re
    from types import SimpleNamespace
    from parafrasi_cat.rules.base import RuleContext

    text = 'Com es pot observar, la torre conserva la porta.'
    words = list(re.finditer(r'\w+|[^\w\s]', text))
    tags = [
        ('SCONJ', 'mark', 3), ('PRON', 'expl:pass', 3), ('AUX', 'aux', 3),
        ('VERB', 'advcl', 7), ('PUNCT', 'punct', 3), ('DET', 'det', 6),
        ('NOUN', 'nsubj', 7), ('VERB', 'ROOT', 7), ('DET', 'det', 9),
        ('NOUN', 'obj', 7), ('PUNCT', 'punct', 7),
    ]
    tokens = tuple(SyntaxToken(i, m.group(), m.group().lower(), pos, dep, head,
                              m.start(), m.end(), number='sg',
                              mood='ind' if i in {1, 2, 7} else None)
                   for i, (m, (pos, dep, head)) in enumerate(zip(words, tags, strict=True)))
    syntax = SentenceSyntax(text, tokens)
    rule = next(r for r in pipeline.rule_set.sentence_rules
                if r.rule_id == 'ordre.observacio_inicial_a_medial')
    sentence = pipeline.analyzer.analyze(text).sentences[0]
    ctx = RuleContext(sentence, morphology=pipeline.morphology, lexicon=pipeline.lexicon,
                      syntax=SimpleNamespace(available=True, parse=lambda _: syntax))
    assert any(t.text_after == 'La torre, com es pot observar, conserva la porta'
               for t in rule.propose(ctx))
    assert not list(rule.propose(RuleContext(sentence, morphology=pipeline.morphology,
                                             lexicon=pipeline.lexicon)))
