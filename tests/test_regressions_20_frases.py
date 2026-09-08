from dataclasses import replace

from parafrasi_cat import PipelineConfig, build_pipeline
from parafrasi_cat.core.transformation import TransformationType
from parafrasi_cat.rules.blocks import BlockMoveRule
from parafrasi_cat.rules.definition import load_rule_definitions
from parafrasi_cat.rules.voice import agent_phrase
from tests.test_nivell3 import analysis


def test_apostrophized_article_and_proper_name():
    assert agent_phrase('L’equip') == 'per l’equip'
    assert agent_phrase("L'equip") == "per l'equip"
    assert agent_phrase("L'Hospitalet", proper=True) == "per L'Hospitalet"


def test_agent_mistagged_as_oblique_is_not_moved():
    tree = analysis(True)
    agent = replace(tree.tokens[6], dep='obl')
    tree = replace(tree, tokens=tuple(agent if t.index == agent.index else t for t in tree.tokens))
    definition = next(d for d in load_rule_definitions('resources/ca/transformations/blocs.yaml') if d.rule_id == 'blocs.circumstancial_curt')
    rule = BlockMoveRule(definition)
    assert rule._circumstantial(tree, agent, tree.text, len(tree.text)-1) is None


def test_clitic_is_not_attached_to_nominalization():
    pipeline = build_pipeline(PipelineConfig(rule_set='parafrasi', level=3, syntax='none'))
    text = 'El document esmenta el castell, però no n’identifica el propietari.'
    proposals = pipeline.propose(text)
    assert not any(t.rule_id == 'nominal.verb_a_nom' for t in proposals)


def test_level3_does_not_split_epistemic_contrast():
    text = 'La coincidència terminològica podria indicar una relació entre els textos, però no demostra que un depengui de l’altre.'
    pipeline = build_pipeline(PipelineConfig(rule_set='parafrasi', level=3, syntax='none'))
    result = pipeline.run(text)
    for evaluation in result.sentences[0].candidates:
        assert all(t.transformation_type != TransformationType.SENTENCE_SPLIT for t in evaluation.candidate.transformations)
        assert len(pipeline.analyzer.analyze(evaluation.candidate.text).sentences) == 1


def test_longer_nominalization_gets_explicit_penalty():
    pipeline = build_pipeline(PipelineConfig(rule_set='parafrasi', level=3, syntax='none'))
    result = pipeline.run('Van analitzar les dades del jaciment.')
    nominal = [e for e in result.sentences[0].candidates if e.accepted and any(t.rule_id == 'nominal.verb_a_nom' for t in e.candidate.transformations)]
    assert nominal
    assert all(e.score.components['nominalitzacio_feixuga'] < 0 for e in nominal)


def test_location_stays_after_verb_with_participial_incise():
    from parafrasi_cat.syntax.analysis import SentenceSyntax
    from tests.test_relative_architecture_1315 import _token, _ctx
    text = 'El retaule, restaurat el 1516, es conserva al museu.'
    specs = [('retaule', 'NOUN', 'nsubj', 3), ('restaurat', 'VERB', 'acl', 0),
             ('1516', 'NUM', 'obl:tmod', 1), ('conserva', 'VERB', 'ROOT', 3),
             ('al', 'ADP', 'case', 5), ('museu', 'NOUN', 'obl', 3)]
    tokens = tuple(_token(text, word, i, pos=pos, dep=dep, head=head,
                         verb_form='Part' if word=='restaurat' else 'Fin' if word=='conserva' else None)
                   for i, (word, pos, dep, head) in enumerate(specs))
    tree = SentenceSyntax(text, tokens, source='manual-regression')
    definitions = load_rule_definitions('resources/ca/transformations/blocs.yaml')
    for definition in definitions:
        if definition.rule_id in ('blocs.circumstancial_curt', 'blocs.complement_del_verb'):
            assert not list(BlockMoveRule(definition).propose(_ctx(text, tree)))
