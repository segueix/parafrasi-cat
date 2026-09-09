"""Presentation grouping must retain safe variants without hiding other structures."""
from dataclasses import replace

from tests.test_structural_option import option
from parafrasi_cat.compose.options import choose_groups, option_group
from parafrasi_cat.compose.composer import _summary


def voice(text, simple=False, nominal=False):
    e = option(text, 'SYNTACTIC', .8)
    t = e.candidate.transformations[0]
    metadata = {'family': 'SYNTACTIC', 'architecture': 'passiva_a_activa'}
    if simple or nominal:
        rule = 'nominal.verb_a_nom' if nominal else 'verbal.perifrastic_a_simple'
        metadata.update(chained_rules=rule,
                        chained_families='NOMINALIZATION' if nominal else 'VERBAL',
                        chained_architectures=rule)
    t = replace(t, rule_id='veu.activa_passiva', metadata=metadata)
    return replace(e, candidate=replace(e.candidate, transformations=(t,)))


def test_voice_variants_share_one_slot_and_direct_form_leads():
    direct = voice('El taller va restaurar la pintura.')
    simple = voice('El taller restaurà la pintura.', simple=True)
    groups = choose_groups([simple, direct], 1)
    assert groups == ((direct, simple),)
    assert _summary(direct.candidate) == 'Passiva → activa'
    assert 'forma verbal' in _summary(simple.candidate)


def test_nominalization_remains_separate_and_secondary():
    direct = voice('El taller va restaurar la pintura.')
    nominal = voice('El taller va dur a terme la restauració de la pintura.', nominal=True)
    assert option_group(direct.candidate) != option_group(nominal.candidate)
    assert choose_groups([nominal, direct], 3) == ((direct,), (nominal,))
    assert 'Verb → nom' in _summary(nominal.candidate)


def test_distinct_movements_and_rejected_candidates_are_not_grouped():
    first = option('Al museu, el taller restaura la pintura.', 'REORDER', .8)
    second = option('El taller, al museu, restaura la pintura.', 'REORDER', .7)
    assert len(choose_groups([first, second], 3)) == 2
    from parafrasi_cat.validation.result import ValidationResult
    rejected = replace(first, validation=ValidationResult.error('test', 'No vàlid'))
    assert choose_groups([rejected, second], 3) == ((second,),)
