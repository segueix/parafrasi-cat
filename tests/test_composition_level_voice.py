from dataclasses import replace
import re

import pytest

from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.rules.base import RuleContext
from parafrasi_cat.rules.definition import load_rule_definitions
from parafrasi_cat.rules.voice import VoiceRule
from parafrasi_cat.analyzer.sentences import Sentence
from parafrasi_cat.core.spans import Span
from parafrasi_cat.syntax.analysis import SentenceSyntax, SyntaxToken
from parafrasi_cat.web.service import ComposeRequest, RewriteService


@pytest.mark.parametrize('plural', [False, True])
def test_passive_with_generic_dependencies(plural):
    text = 'Les escultures van ser restaurades per les especialistes.' if plural else 'La pintura va ser restaurada pel taller.'
    labels = [('DET','det',1), ('NOUN','nsubj',4), ('AUX','aux',4), ('AUX','aux',4), ('VERB','ROOT',4)]
    labels += [('ADP','case',7), ('DET','det',7), ('NOUN','obl',4), ('PUNCT','punct',4)] if plural else [('ADP','case',6), ('NOUN','obl',4), ('PUNCT','punct',4)]
    tokens=[]
    for i, (m, (pos,dep,head)) in enumerate(zip(re.finditer(r'\w+|\.',text), labels)):
        word=m.group()
        lemma={'restaurades':'restaurar','restaurada':'restaurar','especialistes':'especialista'}.get(word,word.lower())
        tokens.append(SyntaxToken(i,word,lemma,pos,dep,head,m.start(),m.end(),
                                 number='pl' if plural else 'sg', gender='f' if i==1 else 'm',
                                 verb_form='Part' if i==4 else 'Inf' if i==3 else 'Fin' if i==2 else None))
    tree=SentenceSyntax(text,tuple(tokens),source='generic-UD-fixture')
    ctx=RuleContext(Sentence(0,text,Span(0,len(text)),()),analysis=tree)
    rule=VoiceRule(load_rule_definitions('resources/ca/transformations/veu.yaml')[0])
    proposals=list(rule.propose(ctx))
    assert len(proposals)==1
    assert proposals[0].text_after == ('Les especialistes van restaurar les escultures.' if plural else 'El taller va restaurar la pintura.')
    # An oblique that denotes a cause must not be invented as an agent.
    agent_index=7 if plural else 6
    uncertain=replace(tree,tokens=tuple(replace(t,lemma='pluja') if t.index==agent_index else t for t in tree.tokens))
    blocked=replace(ctx,analysis=uncertain,notes=[])
    assert not list(rule.propose(blocked))
    assert any('agent no resolt' in n for n in blocked.notes)


def test_compose_reports_effective_level_and_nonempty_diagnostics(project_root):
    service=RewriteService(ProjectPaths(project_root))
    text='La coincidència terminològica podria indicar una relació entre els textos, però no demostra que un depengui de l’altre.'
    request=ComposeRequest.from_mapping({'text':text,'level':3,'mode':'profund'})
    result=service.compose(request)
    assert result['requested_level']==result['level']==3
    assert result['level_label']=='3 · sintaxi'
    sentence=result['sentences'][0]
    assert sentence['diagnostics']['messages']
    assert all(isinstance(m,str) and m.strip() for m in sentence['diagnostics']['messages'])
    assert all('divisió' not in o['summary'] for o in sentence['options'])
    assert all('Tanmateix, no demostra' not in o['text'] for o in sentence['options'])
