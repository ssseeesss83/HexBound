"""Numeric summaries stay source-bound while unprojected branches remain visible."""
from collections import Counter
from copy import deepcopy
import pytest

from backend import compendium, monster_attack_damage as numeric, rules_packages


def action(rid,name,section='actions'):
    return next(a for a in compendium.MONSTERS[rid][section] if a['name']==name)


def test_complete_direct_attack_and_numeric_summary_inventory():
    rows,totals=numeric.expected()
    assert totals==dict(entries=1505,direct_attacks=533,damage_fields=709,damage_literal_mentions=799,unprojected_components=91)
    assert sum(r['attack_bonus'] is not None for r in rows)==533
    report=numeric.audit(compendium.COLLECTIONS)
    assert len(report['checks'])==5933 and not report['differences']
    assert not numeric.issues(compendium.COLLECTIONS)
    for row in rows:
        ref=row['reference']
        assert ref['status']=='reference_pending_execution' and ref['runtime_verified'] is False
        assert ref['conditional_branch_execution_verified'] is False
        assert 'not complete predicates' in ref['limitation']
        assert ref['complete_body_reference'].startswith('official_action_reference.source_text')


def test_twelve_non_attacks_are_not_given_fabricated_zero_attack_rolls():
    fixes=[r for r in compendium.CANONICAL_OVERLAY['corrections'] if r['id'].startswith('official-monster-attack-damage-')]
    assert len(fixes)==1517
    assert Counter(r['path'][-1] for r in fixes)=={'official_attack_damage_reference':1505,'attack_bonus':12}
    zero_fixes=[r for r in fixes if r['path'][-1]=='attack_bonus']
    assert all(r['expected']==0 and r['value'] is None for r in zero_fixes)
    assert action('octopus','Ink Cloud')['attack_bonus'] is None
    for rid in ['vampire-vampire','vampire-bat','vampire-mist']:
        for name in ['Move','Unarmed Strike','Bite (Costs 2 Actions)']:
            entry=action(rid,name,'legendary_actions')
            assert entry['attack_bonus'] is None
            assert entry['official_attack_damage_reference']['attack_bonus_basis']=='no_standalone_attack_sentence'
    # Delegation does not erase the actual base attack's sourced bonus.
    assert action('vampire-vampire','Unarmed Strike')['attack_bonus']==9
    assert action('kraken','Tentacle')['attack_bonus']==17


def test_bugbear_and_duergar_alternative_branches_are_not_silently_lost():
    for rid,dice_values,condition in [('bugbear',['2d6+2','1d6+2'],'at range'),
                                    ('duergar',['1d6+2','2d6+2'],'while enlarged')]:
        entry=action(rid,'Javelin')
        ref=entry['official_attack_damage_reference']
        assert [v['damage_dice'] for v in ref['damage_literals']]==dice_values
        assert condition in ref['damage_literals'][1]['source_context']
        assert entry['damage'][0]['damage_dice']==dice_values[0]
        assert ref['unprojected_literal_components']==[dict(literal_index=1,damage_type='piercing')]
        assert ref['conditional_branch_execution_verified'] is False


def test_djinni_choice_is_one_roll_with_alternative_types():
    ref=action('djinni','Scimitar')['official_attack_damage_reference']
    choice=ref['damage_literals'][1]
    assert choice['damage_dice']=='1d6'
    assert choice['damage_types']==['lightning','thunder']
    assert choice['damage_type_relation']=='or'
    bindings=ref['summary_bindings'][1:]
    assert len(bindings)==2 and {r['literal_index'] for r in bindings}=={1}
    assert {r['damage_type']['index'] for r in bindings}=={'lightning','thunder'}


def test_roll_only_included_bonuses_and_delayed_damage_keep_source_context():
    for rid,roll in [('deva','4d8'),('planetar','5d8'),('solar','6d8')]:
        ref=action(rid,'Angelic Weapons','special_abilities')['official_attack_damage_reference']
        literal=ref['damage_literals'][0]
        assert literal['amount_kind']=='roll_only' and literal['amount'] is None
        assert literal['damage_dice']==roll and 'included in the attack' in literal['source_context']
    ref=action('aboleth','Tentacle')['official_attack_damage_reference']
    acid=next(v for v in ref['damage_literals'] if v['damage_types']==['acid'])
    assert acid['damage_dice']=='1d12' and 'every 10 minutes' in acid['source_context']
    # The legacy list already contains this delayed amount; a correct die is
    # not permission to apply it immediately on the tentacle hit.
    assert any(r['damage_type']['index']=='acid' and r['literal_index']==1 for r in ref['summary_bindings'])
    assert ref['conditional_branch_execution_verified'] is False


def test_negative_dice_modifier_and_fixed_damage_are_not_typography_noise():
    jackal=action('jackal','Bite')['official_attack_damage_reference']['damage_literals'][0]
    assert jackal['amount']==1 and jackal['damage_dice']=='1d4-1'
    literals=numeric.parse_literals('Hit: 1 piercing damage plus 3 (1d6) lightning or thunder damage.')
    assert literals[0]['amount_kind']=='fixed' and literals[0]['damage_dice']=='1'
    assert literals[1]['damage_type_relation']=='or'


def test_offsets_point_to_exact_official_numeric_phrases():
    from backend.monster_action_bodies import expected as bodies
    official,_=bodies()
    for row in numeric.expected()[0]:
        text=next(a['desc'] for a in official[row['record']][row['section']] if a['name']==row['name'])
        for literal in row['reference']['damage_literals']:
            assert text[literal['start']:literal['end']]==literal['source_phrase']


@pytest.mark.parametrize('change',['attack','nonattack_zero','nonattack_bool','die','branch_swap','damage_type',
    'missing_damage','extra_damage','missing_profile','choice_operator','drop_branch','included_bonus',
    'fake_execution','bad_action'])
def test_numeric_drift_missing_fields_and_false_branch_claims_are_rejected(change):
    records=deepcopy(compendium.COLLECTIONS)
    def find(rid,name,section='actions'):
        return next(a for a in records['monsters'][rid][section] if a['name']==name)
    if change=='attack':find('solar','Slaying Longbow')['attack_bonus']=12
    elif change=='nonattack_zero':find('octopus','Ink Cloud')['attack_bonus']=0
    elif change=='nonattack_bool':find('octopus','Ink Cloud')['attack_bonus']=False
    elif change=='die':find('jackal','Bite')['damage'][0]['damage_dice']='1d4+1'
    elif change=='branch_swap':find('bugbear','Javelin')['damage'][0]['damage_dice']='1d6+2'
    elif change=='damage_type':find('solar','Slaying Longbow')['damage'][0]['damage_type']['index']='radiant'
    elif change=='missing_damage':find('solar','Slaying Longbow')['damage'].pop()
    elif change=='extra_damage':find('solar','Slaying Longbow')['damage'].append(deepcopy(find('solar','Slaying Longbow')['damage'][0]))
    elif change=='missing_profile':find('octopus','Ink Cloud').pop('official_attack_damage_reference')
    elif change=='choice_operator':find('djinni','Scimitar')['official_attack_damage_reference']['damage_literals'][1]['damage_type_relation']='and'
    elif change=='drop_branch':find('bugbear','Javelin')['official_attack_damage_reference']['unprojected_literal_components']=[]
    elif change=='included_bonus':find('deva','Angelic Weapons','special_abilities')['official_attack_damage_reference']['damage_literals'][0]['damage_dice']='8d8'
    elif change=='fake_execution':find('bugbear','Javelin')['official_attack_damage_reference']['conditional_branch_execution_verified']=True
    else:records['monsters']['solar']['actions'][0]=None
    assert numeric.issues(records)


@pytest.mark.parametrize('bad',[None,[],{'monsters':[]},{'monsters':{'aboleth':None}}])
def test_bad_collections_return_differences(bad):
    assert numeric.issues(bad)


def test_summary_binding_archive_is_pinned_but_its_values_are_not_the_oracle(monkeypatch):
    templates=numeric.raw_templates()
    modified=deepcopy(templates)
    bite=next(a for a in modified['jackal']['actions'] if a['name']=='Bite')
    bite['attack_bonus']=99
    bite['damage'][0]['damage_dice']='99d99+99'
    monkeypatch.setattr(numeric,'raw_templates',lambda:modified)
    row=next(r for r in numeric.expected()[0] if r['record']=='jackal' and r['name']=='Bite')
    assert row['attack_bonus']==1 and row['bindings'][0]['damage_dice']=='1d4-1'


def test_bad_archive_hash_is_rejected(monkeypatch):
    monkeypatch.setattr(numeric,'RAW_SHA','0'*64)
    with pytest.raises(ValueError,match='archive hash mismatch'):numeric.raw_templates()


def test_candidate_gate_includes_source_numeric_summaries():
    records=deepcopy(compendium.COLLECTIONS)
    records['monsters']['octopus']['actions'][-1]['attack_bonus']=0
    assert any('Official monster attack/damage summary differs' in e for e in rules_packages.validate_records(records))
