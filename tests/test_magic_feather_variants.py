"""Every feather effect retains the common single-use condition and full tail."""
from copy import deepcopy
import pytest

from backend import compendium, magic_feather_variants as variants, rules_packages


def test_six_complete_effects_match_and_all_are_single_use():
    rows=variants.expected()
    assert len(rows)==6
    report=variants.audit(compendium.COLLECTIONS)
    assert len(report['checks'])==48 and not report['differences']
    covered=[]
    for row in rows.values():
        ref=row['official_variant_reference']
        assert ref['selection']['single_use'] is True and ref['runtime_verified'] is False
        assert 'single-use effect' in ' '.join(row['desc'])
        low,high=ref['selection']['d100_range']; covered.extend(range(low,high+1))
    assert sorted(covered)==list(range(1,101))


def test_all_six_effects_keep_specific_limits_and_endings():
    rows=variants.expected()
    cases={
        'anchor':['For the next 24 hours',"can't be moved by any means",'Touching the token to the vessel again','token disappears'],
        'bird':['statistics of a roc',"can't attack",'500 pounds','1,000 pounds','one-hour rest for every 3 hours','dismiss the bird as an action'],
        'fan':['If you are on a boat or ship','5 miles per hour for 8 hours','dismiss the fan as an action'],
        'swan-boat':['at least 60 feet in diameter','6 miles per hour','up to 90 degrees','thirty-two','counts as four','counts as nine','remains for 24 hours'],
        'tree':['must be outdoors','an unoccupied space','nonmagical oak tree','60 feet tall','20-foot radius'],
        'whip':['use a bonus action','melee spell attack','attack bonus of +9','1d6 + 5 force','fly up to 20 feet','after 1 hour','incapacitated or die'],
    }
    for key,phrases in cases.items():
        text=' '.join(rows['feather-token-'+key]['desc'])
        for phrase in phrases:assert phrase in text


@pytest.mark.parametrize('change',['single_use_text','single_use_value','single_use_integer','range','bird_attack',
    'bird_capacity','bird_rest','fan_duration','boat_size','boat_capacity','tree_outdoors','whip_tail','whip_bonus',
    'whip_damage','whip_action','whip_death','parent_source','verified','zero','bad_desc','missing_record'])
def test_effect_omissions_and_source_selection_drift_are_rejected(change):
    records=deepcopy(compendium.COLLECTIONS)
    row=records['magic-items']['feather-token-anchor']
    if change=='single_use_text':row['desc']=[s.replace('single-use','reusable') for s in row['desc']]
    elif change=='single_use_value':row['official_variant_reference']['selection']['single_use']=False
    elif change=='single_use_integer':row['official_variant_reference']['selection']['single_use']=1
    elif change=='range':row['official_variant_reference']['selection']['d100_range']=[1,100]
    elif change in {'bird_attack','bird_capacity','bird_rest'}:
        row=records['magic-items']['feather-token-bird']
        old,new={'bird_attack':("can't attack",'can attack'),'bird_capacity':('500 pounds','5,000 pounds'),
                 'bird_rest':('one-hour rest for every 3 hours','no rest for 24 hours')}[change]
        row['desc']=[s.replace(old,new) for s in row['desc']]
    elif change=='fan_duration':
        row=records['magic-items']['feather-token-fan']; row['desc']=[s.replace('8 hours','80 hours') for s in row['desc']]
    elif change in {'boat_size','boat_capacity'}:
        row=records['magic-items']['feather-token-swan-boat']
        old,new=('60 feet in diameter','6 feet in diameter') if change=='boat_size' else ('counts as nine','counts as one')
        row['desc']=[s.replace(old,new) for s in row['desc']]
    elif change=='tree_outdoors':
        row=records['magic-items']['feather-token-tree']; row['desc']=[s.replace('must be outdoors','can be anywhere') for s in row['desc']]
    elif change.startswith('whip_'):
        row=records['magic-items']['feather-token-whip']
        if change=='whip_tail':row['desc']=[s.split('As a bonus action on your turn')[0] for s in row['desc']]
        else:
            old,new={'whip_bonus':('+9','+99'),'whip_damage':('1d6 + 5','9d6 + 5'),
                     'whip_action':('bonus action','free action'),'whip_death':('or die','or rest')}[change]
            row['desc']=[s.replace(old,new) for s in row['desc']]
    elif change=='parent_source':row['official_variant_reference']['complete_parent_text']='Wondrous item, rare'
    elif change=='verified':row['official_variant_reference']['runtime_verified']=True
    elif change=='zero':row['official_variant_reference']['runtime_verified']=0
    elif change=='bad_desc':row['desc']=[None]
    else:records['magic-items'].pop('feather-token-anchor')
    assert variants.issues(records)


def test_candidate_gate_cannot_lose_shared_single_use_rule():
    records=deepcopy(compendium.COLLECTIONS)
    row=records['magic-items']['feather-token-tree']
    row['desc']=[s.replace('single-use effect','effect') for s in row['desc']]
    assert any('Official magic feather variant differs' in issue for issue in rules_packages.validate_records(records))
