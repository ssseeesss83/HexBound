"""Legendary source budgets are distinct from form eligibility or execution."""
from collections import Counter
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from backend import compendium, monster_legendary as legendary, rules_packages


def test_all_source_blocks_map_to_cards_and_options_without_invention():
    rows = legendary.expected()
    unique = {r['block']['title']:r['block'] for r in rows.values()}
    assert len(unique)==30 and sum(len(r['options']) for r in unique.values())==93
    assert len(rows)==32 and sum(len(r['block']['options']) for r in rows.values())==99
    assert Counter(r['budget'] for r in unique.values())=={3:30}
    report = legendary.audit(compendium.COLLECTIONS)
    assert len(report['checks'])==334*3+99
    assert not report['differences']
    assert not legendary.issues(compendium.COLLECTIONS)
    assert all(s['text'].strip() for r in unique.values() for s in r['segments'])


def test_general_rules_keep_timing_reset_surprise_and_form_exceptions():
    rows = legendary.expected()
    text = ' '.join(rows['aboleth']['general']['text'].split())
    for sentence in ["doesn’t gain that form’s legendary actions, lair actions, or regional effects",
        'only at the end of another creature’s turn', 'at the start of its turn',
        'incapacitated or otherwise unable to take actions',
        'If surprised, it can’t use them until after its first turn in the combat']:
        assert sentence in text
    assert "A Legendary Creature’s Lair" not in text
    assert 'initiative count 20' not in text
    assert text.endswith('in the combat.')


def test_cross_column_dragon_and_final_vampire_blocks_have_complete_boundaries():
    rows = legendary.expected()
    black = rows['ancient-black-dragon']['block']
    assert {r['page'] for r in black['segments']}=={280,281}
    assert black['options'][-1]['name']=='Wing Attack (Costs 2 Actions)'
    assert 'Adult Black Dragon' not in '\n'.join(r['text'] for r in black['segments'])
    vampire = rows['vampire-vampire']['block']
    assert vampire['options'][-1]['name']=='Bite (Costs 2 Actions)'
    assert 'Vampire Spawn' not in '\n'.join(r['text'] for r in vampire['segments'])


def test_explicit_and_derived_cost_evidence_remains_distinct():
    rows = legendary.expected()
    costs = rows['lich']['block']['options']
    assert [(r['name'],r['cost']) for r in costs]==[
        ('Cantrip',1),('Paralyzing Touch (Costs 2 Actions)',2),
        ('Frightening Gaze (Costs 2 Actions)',2),('Disrupt Life (Costs 3 Actions)',3)]
    assert costs[0]['cost_basis']=='single_action_option_default'
    assert all(r['cost_basis']=='explicit_label' for r in costs[1:])
    assert all(r['cost'] in (1,2,3) for row in rows.values() for r in row['block']['options'])


def test_form_refs_are_not_permission_and_existing_prose_parameters_are_untouched():
    rows = legendary.expected()
    for rid in ['vampire-vampire','vampire-bat','vampire-mist']:
        ref = compendium.MONSTERS[rid]['legendary_rules_reference']
        assert ref['binding']['mapping_type']=='derived_monster_form'
        assert ref['status']=='reference_pending_execution' and ref['runtime_verified'] is False
        assert 'not permission' in ref['limitation']
    corrections = [r for r in compendium.CANONICAL_OVERLAY['corrections'] if r['id'].startswith('official-monster-legendary-')]
    assert len(corrections)==163
    assert all(r['path'] in [['legendary_actions_budget'],['legendary_rules_reference']]
        or r['path'][0]=='legendary_actions' and r['path'][-1]=='legendary_cost' for r in corrections)
    assert all(r['expected'] is None for r in corrections)
    assert compendium.MONSTERS['vampire-mist']['legendary_actions'][0]['attack_bonus']==0


@pytest.mark.parametrize('change',['budget_missing','budget_bool','budget_string','cost_missing','cost_bool','cost_float',
    'cost_zero','name','extra_option','missing_option','no_legendary_list','bad_action','reference_missing',
    'runtime_verified','rule_truncation','form_binding','nonlegendary_budget','nonlegendary_action'])
def test_missing_or_changed_data_cannot_pass(change):
    records = deepcopy(compendium.COLLECTIONS)
    row = records['monsters']['aboleth']
    if change=='budget_missing':row.pop('legendary_actions_budget')
    elif change=='budget_bool':row['legendary_actions_budget']=True
    elif change=='budget_string':row['legendary_actions_budget']='3'
    elif change=='cost_missing':row['legendary_actions'][0].pop('legendary_cost')
    elif change=='cost_bool':row['legendary_actions'][0]['legendary_cost']=True
    elif change=='cost_float':row['legendary_actions'][0]['legendary_cost']=1.0
    elif change=='cost_zero':row['legendary_actions'][0]['legendary_cost']=0
    elif change=='name':row['legendary_actions'][0]['name']='Invented'
    elif change=='extra_option':row['legendary_actions'].append(deepcopy(row['legendary_actions'][0]))
    elif change=='missing_option':row['legendary_actions'].pop()
    elif change=='no_legendary_list':row['legendary_actions']=None
    elif change=='bad_action':row['legendary_actions'][0]=None
    elif change=='reference_missing':row.pop('legendary_rules_reference')
    elif change=='runtime_verified':row['legendary_rules_reference']['runtime_verified']=True
    elif change=='rule_truncation':row['legendary_rules_reference']['general_rules']['text']='Only one option.'
    elif change=='form_binding':row['legendary_rules_reference']['binding']['mapping_type']='official_stat_header_bad'
    elif change=='nonlegendary_budget':records['monsters']['goblin']['legendary_actions_budget']=3
    else:records['monsters']['goblin']['legendary_actions']=[deepcopy(row['legendary_actions'][0])]
    assert legendary.issues(records)


@pytest.mark.parametrize('bad',[None,[],{'monsters':[]},{'monsters':{'aboleth':None}}])
def test_invalid_collection_shapes_return_differences(bad):
    assert legendary.issues(bad)


def test_source_artifact_hash_is_verified(tmp_path,monkeypatch):
    root = Path(legendary.__file__).parent/'data/official'
    raw = (root/'monster-legendary-blocks.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==legendary.BLOCKS_SHA
    (tmp_path/'monster-legendary-blocks.json').write_bytes(raw+b' ')
    monkeypatch.setattr(legendary,'source',lambda _:None)
    with pytest.raises(ValueError,match='hash mismatch'):
        legendary.expected(tmp_path)


def test_candidate_gate_rejects_a_legendary_cost_change():
    records = deepcopy(compendium.COLLECTIONS)
    records['monsters']['lich']['legendary_actions'][-1]['legendary_cost']=1
    assert any('Official legendary data differs' in e for e in rules_packages.validate_records(records))
