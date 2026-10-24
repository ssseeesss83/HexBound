"""Limited uses recover by source rules and belong to entity/source ability."""
from collections import Counter
from copy import deepcopy
import pytest

from backend import compendium,monster_usage as usage,rules_packages


def action(rid,name,section='actions'):
    return next(a for a in compendium.MONSTERS[rid][section] if a['name']==name)


def test_source_labels_and_pool_templates_do_not_count_forms_as_fresh_resources():
    rows=usage.expected()
    limited=[r for r in rows if r['usage']]
    assert len(rows)==1505 and len(limited)==122
    assert len({r['reference']['resource_binding']['source_pool_key'] for r in limited})==117
    assert Counter(r['usage']['type'] for r in limited)=={'per day':44,'recharge on roll':66,'recharge after rest':12}


def test_general_recovery_source_preserves_all_three_notations():
    text=usage.general_rules(usage.source())['text']
    assert 'must finish a long rest to regain expended uses' in text
    assert "At the start of each of the monster's turns, roll a d6" in text
    assert 'also recharges when the monster finishes a short or long rest' in text
    assert 'must finish a short or long rest to use it again' in text
    assert 'Grapple Rules' not in text and 'System Reference Document' not in text


def test_daily_means_long_rest_not_calendar_reset():
    old,normalized=usage.parse_label('Enslave (3/Day)')
    assert old=={'type':'per day','times':3}
    assert normalized==dict(maximum_uses=3,rest_recharge=['long'],recharge_roll=None,
        recovery_amount='all_expended_uses',calendar_reset=False)


@pytest.mark.parametrize('label,faces',[('Cold Breath (Recharge 5–6)',[5,6]),('Poison Breath (Recharge 6)',[6]),
    ('Whelm (Recharge 4–6)',[4,5,6])])
def test_exact_recharge_faces_own_turn_and_rest_recovery(label,faces):
    legacy,normalized=usage.parse_label(label)
    assert legacy['dice']=='1d6' and legacy['min_value']==min(faces)
    assert normalized['maximum_uses']==1
    assert normalized['rest_recharge']==['short','long']
    assert normalized['recharge_roll']==dict(dice='1d6',successful_results=faces,timing='start_of_own_turn',
        context='combat',purpose='recover_expended_use')


def test_rest_only_source_has_no_extra_recharge_roll():
    _,normalized=usage.parse_label('Leadership (Recharges after a Short or Long Rest)')
    assert normalized['maximum_uses']==1
    assert normalized['rest_recharge']==['short','long'] and normalized['recharge_roll'] is None


def test_mephit_source_mirror_is_same_cast_not_two_charges():
    rows=usage.expected()
    spells={'dust-mephit':'sleep','ice-mephit':'fog-cloud','magma-mephit':'heat-metal','steam-mephit':'blur'}
    for rid,spell in spells.items():
        ref=next(r['reference'] for r in rows if r['record']==rid and r['name']=='Innate Spellcasting')
        mirror=ref['resource_binding']['mirrored_nested_usage']
        assert mirror['spell_id']==spell and mirror['relationship']=='same_source_use'
        assert mirror['charge_policy']=='one_cast_spends_one_use_not_outer_plus_inner'
        assert mirror['spell_structure_status']=='pending_spellcasting_audit'


def test_vampire_form_pool_is_shared_within_one_entity_only():
    refs=[r['reference'] for r in usage.expected() if r['record'] in {'vampire-vampire','vampire-bat','vampire-mist'}
          and r['name']=='Legendary Resistance']
    assert len(refs)==3
    assert len({r['resource_binding']['source_pool_key'] for r in refs})==1
    for ref in refs:
        binding=ref['resource_binding']
        assert binding['owner_scope']=='authoritative_world_entity_instance'
        assert binding['form_policy']=='same_entity_and_source_ability_share_one_pool'
        assert binding['species_policy']=='different_world_entities_do_not_share_a_pool'


@pytest.mark.parametrize('label',['Breath (Recharge 0)','Breath (Recharge 5–7)','Breath (Recharge 3–5)',
    'Ability (0/Day)','Ability (Recharges tomorrow)'])
def test_unknown_or_unrepresentable_recovery_is_not_silently_defaulted(label):
    with pytest.raises(ValueError):usage.parse_label(label)


def test_candidate_usage_and_source_profiles_are_complete():
    report=usage.audit(compendium.COLLECTIONS)
    assert len(report['checks'])==3010 and not report['differences']
    assert action('iron-golem','Poison Breath')['usage']['min_value']==6
    assert action('ice-devil','Wall of Ice')['usage']==dict(type='recharge on roll',dice='1d6',min_value=6)
    for rid in usage.MEPHITS:
        assert action(rid,'Innate Spellcasting','special_abilities')['usage']==dict(type='per day',times=1)
    corrections=[c for c in compendium.CANONICAL_OVERLAY['corrections'] if c['id'].startswith('official-monster-usage-')]
    assert len(corrections)==128
    assert Counter(c['path'][-1] for c in corrections)=={'official_usage_reference':122,'usage':6}
    assert all(c['expected'] is None for c in corrections if c['path'][-1]=='official_usage_reference')


@pytest.mark.parametrize('change',['wrong_face','missing','day_uses','calendar_reset','roll_timing','rest_recovery',
    'form_pool','mirror_double_cost','runtime','invent_limit'])
def test_wrong_recovery_and_resource_identity_are_rejected(change):
    records=deepcopy(compendium.COLLECTIONS)
    def find(rid,name,section='actions'):
        return next(a for a in records['monsters'][rid][section] if a['name']==name)
    if change=='wrong_face':find('iron-golem','Poison Breath')['usage']['min_value']=5
    elif change=='missing':find('ice-devil','Wall of Ice').pop('usage')
    elif change=='day_uses':find('aboleth','Enslave')['usage']['times']=4
    elif change=='calendar_reset':find('aboleth','Enslave')['official_usage_reference']['normalized_recovery']['calendar_reset']=True
    elif change=='roll_timing':find('iron-golem','Poison Breath')['official_usage_reference']['normalized_recovery']['recharge_roll']['timing']='end_of_any_turn'
    elif change=='rest_recovery':find('iron-golem','Poison Breath')['official_usage_reference']['normalized_recovery']['rest_recharge']=[]
    elif change=='form_pool':find('vampire-bat','Legendary Resistance','special_abilities')['official_usage_reference']['resource_binding']['source_pool_key']='bat-fresh-pool'
    elif change=='mirror_double_cost':find('dust-mephit','Innate Spellcasting','special_abilities')['official_usage_reference']['resource_binding']['mirrored_nested_usage']['charge_policy']='charge_both'
    elif change=='runtime':find('aboleth','Enslave')['official_usage_reference']['runtime_verified']=True
    else:find('aboleth','Tail')['usage']=dict(type='per day',times=1)
    assert usage.issues(records)


@pytest.mark.parametrize('bad',[None,[],{'monsters':[]},{'monsters':{'aboleth':None}}])
def test_bad_collections_return_errors(bad):
    assert usage.issues(bad)


def test_gate_rejects_a_plausible_recharge_bug():
    records=deepcopy(compendium.COLLECTIONS)
    entry=next(a for a in records['monsters']['iron-golem']['actions'] if a['name']=='Poison Breath')
    entry['usage']['min_value']=5
    assert any('Official monster usage differs' in e for e in rules_packages.validate_records(records))
