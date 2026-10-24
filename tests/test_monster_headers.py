"""Independent header evidence preserves limits and rejects plausible wrong stats."""
from copy import deepcopy
from fractions import Fraction

import pytest

from backend import compendium, monster_headers as headers, rules_packages


def test_complete_header_inventory_and_source_derived_cr_table():
    expected = headers.expected()
    assert len(expected)==334
    table,text = headers.proficiency_table(headers.source())
    assert len(table)==34 and table[Fraction(1,8)]==2 and table[Fraction(30)]==9
    assert table[Fraction(4)]==2 and table[Fraction(5)]==3 and table[Fraction(17)]==6
    assert '0 +2 14 +5' in text
    report = headers.audit(compendium.COLLECTIONS)
    assert len(report['checks'])==3674 and not report['differences']
    for row in expected.values():
        ref = row['official_header_reference']
        assert 'System Reference Document' not in ref['text']
        assert ref['text'].endswith(' XP)') and ref['text'].count('Challenge ')==1
        assert ref['status']=='reference_pending_execution' and ref['runtime_verified'] is False


@pytest.mark.parametrize('rid,key,value',[
    ('adult-brass-dragon','burrow','30 ft.'),('crocodile','swim','30 ft.'),
    ('air-elemental','walk','0 ft.'),('hunter-shark','walk','0 ft.'),
    ('vampire-bat','walk','5 ft.'),('vampire-bat','fly','30 ft.'),('vampire-mist','hover',True),
    ('werebear-hybrid','climb','30 ft.'),('werebear-bear','walk','40 ft.'),
    ('werebear-human','walk','30 ft.'),('wereboar-hybrid','walk','30 ft.'),
    ('wereboar-boar','walk','40 ft.'),('weretiger-tiger','walk','40 ft.'),
    ('werewolf-wolf','walk','40 ft.'),('swarm-of-beetles','burrow','5 ft.'),
    ('swarm-of-wasps','fly','30 ft.')])
def test_source_speeds_and_explicit_variant_selection(rid,key,value):
    assert compendium.MONSTERS[rid]['speed'][key]==value


def test_sense_modality_conditions_and_passive_values_survive():
    monsters = compendium.MONSTERS
    assert monsters['hunter-shark']['senses']=={'blindsight':'30 ft.','passive_perception':12}
    assert monsters['blink-dog']['senses']['passive_perception']==13
    assert monsters['spider']['senses']['passive_perception']==10
    assert monsters['grimlock']['senses']['blindsight']=='30 ft. or 10 ft. while deafened (blind beyond this radius)'
    assert 'darkvision' not in monsters['wererat-human']['senses']
    assert 'darkvision' not in monsters['wererat-hybrid']['senses']
    assert monsters['wererat-rat']['senses']['darkvision']=='60 ft.'
    assert 'swim' not in monsters['giant-wasp']['speed']
    assert 'climb' not in monsters['swarm-of-wasps']['speed']


def test_immunities_preserve_distinct_conditions_and_conditional_damage_phrases():
    monsters = compendium.MONSTERS
    for rid in ['flying-sword','rug-of-smothering','shrieker','violet-fungus','ochre-jelly','shambling-mound']:
        conditions = [r['index'] for r in monsters[rid]['condition_immunities']]
        assert 'deafened' in conditions and len(conditions)==len(set(conditions))
    assert 'cold' in monsters['ice-devil']['damage_immunities']
    assert 'grappled' in [r['index'] for r in monsters['swarm-of-spiders']['condition_immunities']]
    assert monsters['deva']['damage_resistances'][-1]=='bludgeoning, piercing, and slashing from nonmagical attacks'
    assert monsters['werewolf-wolf']['damage_immunities']==['bludgeoning, piercing, and slashing from nonmagical attacks not made with silvered weapons']
    assert monsters['archmage']['damage_resistances']==['damage from spells','nonmagical bludgeoning, piercing, and slashing (from stoneskin)']


def test_proficiency_identity_and_conditional_bonus_are_not_flattened():
    monsters = compendium.MONSTERS
    assert monsters['black-bear']['proficiencies'][0]['value']==3
    assert len(monsters['half-red-dragon-veteran']['proficiencies'])==2
    assert any(r['proficiency']['index']=='skill-sleight-of-hand' and r['value']==4 for r in monsters['spy']['proficiencies'])
    shadow = monsters['shadow']['proficiencies'][0]
    assert shadow['value']==4
    assert shadow['conditional_values']==[dict(value=6,condition='in dim light or darkness',status='reference_pending_execution',runtime_verified=False)]
    assert monsters['manticore']['languages']=='Common'
    assert monsters['giant-eagle']['languages'].endswith("can't speak them")


def test_form_ref_keeps_full_vampire_exceptions_without_granting_effects():
    ref = compendium.MONSTERS['vampire-mist']['official_header_reference']
    text = ref['selected_form_evidence'][0]['text']
    assert "can't take any actions, speak, or manipulate objects" in text
    assert 'immune to all nonmagical damage, except the damage it takes from sunlight' in text
    assert 'speech constraints' in ref['limitation']
    assert compendium.MONSTERS['vampire-mist']['damage_immunities']==[]


@pytest.mark.parametrize('change',['speed','hover_bool','sense','passive','conditional_bonus','proficiency_id',
    'immunity_missing','condition_duplicate','language_scope','challenge_bool','proficiency_bonus','reference_text','fake_execution'])
def test_plausible_wrong_header_cannot_pass(change):
    records = deepcopy(compendium.COLLECTIONS)
    row = records['monsters']['aboleth']
    if change=='speed':row['speed']['swim']='30 ft.'
    elif change=='hover_bool':records['monsters']['vampire-mist']['speed']['hover']=1
    elif change=='sense':row['senses']['blindsight']=row['senses'].pop('darkvision')
    elif change=='passive':row['senses']['passive_perception']=21
    elif change=='conditional_bonus':records['monsters']['shadow']['proficiencies'][0]['conditional_values'][0]['value']=4
    elif change=='proficiency_id':row['proficiencies'][0]['proficiency']['url']='/api/2014/proficiencies/saving-throw-str'
    elif change=='immunity_missing':records['monsters']['ice-devil']['damage_immunities'].remove('cold')
    elif change=='condition_duplicate':records['monsters']['flying-sword']['condition_immunities'][2]=deepcopy(records['monsters']['flying-sword']['condition_immunities'][0])
    elif change=='language_scope':records['monsters']['giant-eagle']['languages']='all'
    elif change=='challenge_bool':row['challenge_rating']=True
    elif change=='proficiency_bonus':row['proficiency_bonus']=3
    elif change=='reference_text':row['official_header_reference']['text']='invented'
    else:row['official_header_reference']['runtime_verified']=True
    assert headers.issues(records)


@pytest.mark.parametrize('value',['30 ft., teleport 60 ft.','30 ft. extra','fly 20 ft. (hover), fly 30 ft.'])
def test_unknown_or_duplicate_movement_is_not_silently_skipped(value):
    with pytest.raises(ValueError):headers.speed(value)


@pytest.mark.parametrize('value',['fire, imaginary','piercing, silver','cold; made up'])
def test_unknown_damage_clause_is_not_silently_skipped(value):
    with pytest.raises(ValueError):headers.defences(value)


@pytest.mark.parametrize('records',[None,[],{'monsters':[]},{'monsters':{'aboleth':None}}])
def test_bad_shapes_produce_differences(records):
    assert headers.issues(records)


def test_candidate_gate_includes_header_semantics():
    records = deepcopy(compendium.COLLECTIONS)
    records['monsters']['giant-wasp']['speed']['swim']='50 ft.'
    assert any('Official monster header differs' in e for e in rules_packages.validate_records(records))
