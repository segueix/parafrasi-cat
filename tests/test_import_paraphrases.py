"""Les etiquetes del corpus no es converteixen en garanties del motor."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('import_pairs', Path(__file__).resolve().parents[1] / 'scripts/import_paraphrases.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def import_data(tmp_path, data, split='train', reviews=None):
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(data, ensure_ascii=False))
    return list(module.import_pairs(path, {'dataset': 'test', 'split': split}, reviews))


def test_source_equivalence_does_not_mean_reviewed(tmp_path):
    row = import_data(tmp_path, [{'original':'El pont és antic.', 'new':'És antic, el pont.', 'label':1}])[0]
    assert row['source_label'] == 'equivalent'
    assert row['review_status'] == 'pending'
    assert not row['rule_evidence_eligible']


@pytest.mark.parametrize(('first','second','flag'), [
    ('Hi ha 23 capítols.', 'Hi ha 24 capítols.', 'xifres_diferents'),
    ('És del segle XVII.', 'És del segle XVIII.', 'romans_diferents'),
    ('Va contractar diverses agències.', 'Va contractar set agències.', 'quantificadors_a_revisar'),
    ('El rei no governa.', 'El rei governa.', 'negacio_a_revisar'),
])
def test_conflicting_data_is_flagged_not_silently_relabelled(tmp_path, first, second, flag):
    row = import_data(tmp_path, [{'sentence1':first,'sentence2':second,'label':1}])[0]
    assert row['source_label'] == 'equivalent' and flag in row['risk_flags']


def test_unknown_and_contradictory_labels_are_preserved(tmp_path):
    data = [{'original':'La torre és alta.', 'new':'És alta, la torre.', 'label':label} for label in (1,0)]
    result = import_data(tmp_path, data)
    assert len(result) == 1
    assert result[0]['source_label'] == 'conflict'
    assert result[0]['source_labels_raw'] == [1,0]
    assert 'etiquetes_contradictories' in result[0]['risk_flags']
    data[0]['label'] = 'perhaps'
    assert import_data(tmp_path,data[:1])[0]['source_label'] == 'unknown'


def test_explicit_review_is_tied_to_text_and_split(tmp_path):
    data=[{'original':'El pont és antic.', 'new':'És antic, el pont.', 'label':1}]
    row=import_data(tmp_path,data)[0]
    reviews={row['id']:{'id':row['id'],'reviewer':'Dani','verdict':'equivalent','note':'Revisat'}}
    assert import_data(tmp_path,data,reviews=reviews)[0]['rule_evidence_eligible']
    assert not import_data(tmp_path,data,split='test',reviews=reviews)[0]['rule_evidence_eligible']
    data[0]['new']='El pont és modern.'
    assert import_data(tmp_path,data,reviews=reviews)[0]['review_status']=='pending'


def test_conllu_exports_syntax_not_paraphrases(tmp_path):
    path=tmp_path/'tiny.conllu'
    path.write_text('# sent_id = ex1\n# text = La torre.\n1\tLa\tel\tDET\t_\tGender=Fem\t2\tdet\t_\t_\n2\ttorre\ttorre\tNOUN\t_\tGender=Fem\t0\troot\t_\t_\n')
    result=module.conllu_patterns(path)
    assert result[0]['pattern']=='NOUN -> det -> DET'
    assert result[0]['status']=='observed_not_validated_rule'


def test_nominal_concession_rules_generalize_without_corpus_lookup():
    from parafrasi_cat.pipeline import PipelineConfig, apply_mode
    from parafrasi_cat.pipeline.builder import build_pipeline
    from parafrasi_cat.pipeline.modes import RewriteMode
    root=Path(__file__).resolve().parents[1]
    pipeline=build_pipeline(apply_mode(PipelineConfig(home=root,rule_set='parafrasi',languagetool=False),RewriteMode.DEEP,5))
    for first, second in [('Tot i la pluja, la porta és oberta.', 'La porta és oberta, tot i la pluja.'),
                          ('Malgrat el fred, la porta és oberta.', 'La porta és oberta, malgrat el fred.')]:
        for source, target in [(first,second),(second,first)]:
            result=pipeline.run(source).sentences[0]
            assert any(e.accepted and e.candidate.text==target for e in result.candidates)
    for source in ['Tot i que plou, la porta és oberta.', 'La porta és oberta tot i la pluja.',
                   'Tot i la pluja, si neva, la gent marxarà.']:
        assert not any(t.rule_id.startswith('ordre.concessio_nominal') for t in pipeline.propose(source))
