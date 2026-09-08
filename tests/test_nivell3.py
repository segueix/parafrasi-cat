from dataclasses import replace

from parafrasi_cat.analyzer.sentences import Sentence
from parafrasi_cat.core.spans import Span
from parafrasi_cat.rules.base import RuleContext
from parafrasi_cat.rules.definition import load_rule_definitions
from parafrasi_cat.rules.voice import VoiceRule
from parafrasi_cat.syntax.analysis import SentenceSyntax, SyntaxToken, empty
from parafrasi_cat.syntax.freeling_parser import parse_columns


def analysis(passive=False):
    text = 'La pintura va ser restaurada pel taller.' if passive else 'El taller va restaurar la pintura.'
    words = text[:-1].split() + ['.']
    heads = [1, 4, 4, 4, 4, 6, 4, 4] if passive else [1, 3, 3, 3, 5, 3, 3]
    deps = ['det', 'nsubj:pass', 'aux', 'aux:pass', 'ROOT', 'case', 'obl:agent', 'punct'] if passive else ['det', 'nsubj', 'aux', 'ROOT', 'det', 'obj', 'punct']
    tokens = []
    cursor = 0
    for i, word in enumerate(words):
        start = text.index(word, cursor); cursor = start + len(word)
        noun = word in ('taller', 'pintura')
        verb = word in ('restaurar', 'restaurada')
        aux = word in ('va', 'ser')
        tokens.append(SyntaxToken(i, word, 'restaurar' if verb else word.lower(),
            'NOUN' if noun else 'VERB' if verb else 'AUX' if aux else 'DET' if deps[i]=='det' else 'PUNCT' if word=='.' else 'ADP',
            deps[i], heads[i], start, cursor, gender='f' if word in ('pintura', 'restaurada') else 'm' if noun else None,
            number='sg' if noun or word=='va' else None, mood='ind' if word=='va' else None,
            verb_form='Part' if word=='restaurada' else 'Inf' if word in ('restaurar', 'ser') else 'Fin' if word=='va' else None))
    return SentenceSyntax(text, tuple(tokens), source='fixture-manual')


def proposals(tree):
    rule = VoiceRule(load_rule_definitions('resources/ca/transformations/veu.yaml')[0])
    return list(rule.propose(RuleContext(Sentence(0, tree.text, Span(0, len(tree.text)), ()), analysis=tree)))


def test_voice_round_trip_and_score():
    active, passive = analysis(), analysis(True)
    for source, target in ((active, passive), (passive, active)):
        result = proposals(source)
        assert len(result) == 1
        assert result[0].text_after == target.text


def test_voice_blocks_missing_parser_modality_negation_and_quantification():
    tree = analysis()
    assert not proposals(empty(tree.text))
    for text in (tree.text.replace('va ', 'no va '), tree.text.replace('va ', 'podria '),
                 tree.text.replace('El ', 'Cada ')):
        assert not proposals(replace(tree, text=text))
    tokens = tuple(replace(t, dep='dep') if t.dep=='obj' else t for t in tree.tokens)
    assert not proposals(replace(tree, tokens=tokens))


def test_freeling_columns_are_not_assumed_to_be_ud():
    text = 'El rei governa.'
    columns = '1 El el DA0MS0 2 spec\n2 rei rei NCMS000 3 subj\n3 governa governar VMIP3S0 0 top\n4 . . Fp 3 punct\n'
    tree = parse_columns(text, columns)
    assert tree.confident
    assert tree.main_subject().text == 'rei'
    assert not parse_columns(text, columns.replace('subj', 'unknown')).confident
    assert not parse_columns(text, columns.replace('2 rei', '7 rei')).confident
    assert not parse_columns(text, columns.replace('rei rei', 'reis rei')).confident
    assert not parse_columns(text, columns.replace('3 subj', '99 subj')).confident


def test_structural_score_is_zero_without_structural_operations():
    from parafrasi_cat import PipelineConfig, build_pipeline
    pipeline = build_pipeline(PipelineConfig(rule_set='parafrasi', level=2, syntax='none'))
    result = pipeline.run('A tall d’exemple, la porta és oberta.')
    for unit in result.sentences:
        for evaluation in unit.candidates:
            c = evaluation.candidate
            assert c.structural_change_score == 0
            assert c.to_dict()['structural_change_score'] == 0


def test_voice_passes_pipeline_and_is_excluded_from_level2(monkeypatch):
    from parafrasi_cat import PipelineConfig, build_pipeline
    class Parser:
        available = True
        def parse(self, text):
            for tree in (analysis(), analysis(True)):
                if tree.text == text:
                    return tree
            return empty(text)
    monkeypatch.setattr('parafrasi_cat.pipeline.builder.build_syntax_provider', lambda *args: Parser())
    for level in (2, 3):
        pipeline = build_pipeline(PipelineConfig(rule_set='parafrasi', level=level))
        result = pipeline.run(analysis().text)
        matches = [e for e in result.sentences[0].candidates if e.accepted and e.candidate.text == analysis(True).text]
        assert bool(matches) == (level == 3)
        if matches:
            assert matches[0].candidate.structural_change_score > 0


def test_nominal_round_trip_is_not_a_structural_change():
    from parafrasi_cat.candidates.candidate import Candidate
    transformation = proposals(analysis())[0]
    candidate = Candidate(0, "Van fer l’anàlisi.", "Van dur a terme l'anàlisi.", (transformation,))
    assert candidate.structural_change_score == 0


def test_ancora_objects_are_closed_and_nonagentive_verbs_are_blocked():
    from pathlib import Path
    fixture = Path('tests/fixtures/nivell3-ancora.conllu').read_text()
    for block in fixture.strip().split('\n\n'):
        text = next(l[9:] for l in block.splitlines() if l.startswith('# text = '))
        rows = [l.split('\t') for l in block.splitlines() if not l.startswith('#')]
        tokens, cursor = [], 0
        for row in rows:
            ident, form, lemma, pos, _, features, parent, dep, *_ = row
            start = text.index(form, cursor); cursor = start + len(form)
            i = int(ident) - 1
            tokens.append(SyntaxToken(i, form, lemma, pos, 'ROOT' if parent=='0' else dep,
                                     i if parent=='0' else int(parent)-1, start, cursor))
        tree = SentenceSyntax(text, tuple(tokens), source='UD-AnCora-gold')
        objects = [t for t in tokens if t.dep == 'obj']
        assert objects
        for obj in objects:
            assert tree.closed_subtree(*tree.subtree_span(obj)) == obj
        assert not proposals(tree)  # costar/durar no són accions passivitzables
