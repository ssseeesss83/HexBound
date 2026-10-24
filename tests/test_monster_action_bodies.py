"""Source prose keeps form limits, nested choices, variants and exact numbers."""
from collections import Counter
from copy import deepcopy
import pytest

from backend import compendium, monster_action_bodies as bodies, rules_packages


def action(rid,name,section='actions'):
    return next(a for a in compendium.MONSTERS[rid][section] if a['name']==name)


def test_all_source_primary_entries_expand_to_the_complete_candidate_inventory():
    rows,counts=bodies.expected()
    assert len(rows)==334
    assert counts=={'special_abilities':550,'actions':844,'reactions':12,'legendary_actions':99}
    report=bodies.audit(compendium.COLLECTIONS)
    assert len(report['checks'])==4346 and not report['differences']
    assert not bodies.issues(compendium.COLLECTIONS)
    for groups in rows.values():
        for entries in groups.values():
            for entry in entries:
                ref=entry['official_action_reference']
                assert ref['status']=='reference_pending_execution' and ref['runtime_verified'] is False


def test_all_43_nested_options_remain_in_their_parent_prose():
    rows,_=bodies.expected()
    nested=[]
    for rid,groups in rows.items():
        for entry in groups['actions']:
            ref=entry['official_action_reference']
            if ref['nested_labels']:
                nested.append((rid,entry['name'],ref['nested_labels']))
                for label in ref['nested_labels']:assert label+'.' in entry['desc']
    assert len(nested)==21 and sum(len(r[2]) for r in nested)==43
    assert Counter(name for _,name,_ in nested)=={'Breath Weapons':20,'Roar':1}
    roar=action('androsphinx','Roar')['desc']
    assert all(label in roar for label in ['First Roar.','Second Roar.','Third Roar.'])
    assert action('androsphinx','Roar')['official_action_reference']['source_label']=='Roar (3/Day)'
    assert 'long rest' in roar


def test_explicit_catalog_aliases_keep_exact_official_labels():
    cases=[('hezrou','Claws','Claw','actions'),('quasit','Claw (Bite in Beast Form)','Claws (Bite in Beast Form)','actions'),
        ('ghast','Turn Defiance','Turning Defiance','special_abilities'),
        ('assassin','Sneak Attack (1/Turn)','Sneak Attack','special_abilities'),
        ('weretiger-tiger','Pounce','Pounce (Tiger or Hybrid Form Only)','special_abilities')]
    for rid,name,label,section in cases:
        assert action(rid,name,section)['official_action_reference']['source_label']==label


def test_usage_and_form_conditions_remain_in_source_labels():
    ref=action('aboleth','Enslave')['official_action_reference']
    assert ref['source_label']=='Enslave (3/Day)'
    ref=action('clay-golem','Haste')['official_action_reference']
    assert ref['source_label']=='Haste (Recharge 5–6)'
    ref=action('werebear-hybrid','Greataxe')['official_action_reference']
    assert ref['source_label']=='Greataxe (Humanoid or Hybrid Form Only)'
    rows,_=bodies.expected()
    assert {a['name'] for a in rows['werebear-human']['actions']}=={'Multiattack','Greataxe'}
    assert {a['name'] for a in rows['werebear-bear']['actions']}=={'Multiattack','Bite','Claw'}
    assert not any(a['name']=='Pounce' for a in rows['weretiger-human']['special_abilities'])
    assert not any(a['name'].startswith('Charge') for a in rows['wereboar-human']['special_abilities'])
    assert not rows['vampire-mist']['actions']
    assert len(rows['vampire-mist']['legendary_actions'])==3
    assert 'not permission' in bodies.audit(compendium.COLLECTIONS)['limitations'][-1]


def test_source_numeric_wording_and_delayed_disease_are_restored():
    bow=action('solar','Slaying Longbow')['desc']
    assert '100 hit points or fewer' in bow and '190 hit points' not in bow
    bite=action('giant-rat-diseased','Bite')['desc']
    assert 'Hit: 4 (1d4 + 2)' in bite
    assert 'every 24 hours' in bite and 'except by magical means' in bite
    basilisk=action('basilisk','Petrifying Gaze','special_abilities')['desc']
    assert 'its reflection' in basilisk and 'bright light' in basilisk
    tail=action('aboleth','Tentacle')['desc']
    assert 'After 1 minute' in tail and 'every 10 minutes' in tail


def test_centipede_and_spider_variants_keep_exact_source_owner_and_conditions():
    centipede=action('swarm-of-centipedes','Bites')
    assert 'reduced to 0 hit points' in centipede['desc']
    assert 'stable but poisoned for 1 hour' in centipede['desc']
    assert 'paralyzed while poisoned' in centipede['desc']
    assert 391 in centipede['official_action_reference']['printed_pages']
    for name in ['Spider Climb','Web Sense','Web Walker']:
        ref=action('swarm-of-spiders',name,'special_abilities')['official_action_reference']
        assert ref['source_variant']['owner']=='Swarm of Insects'
        assert ref['selected_binding']['record_id']=='swarm-of-spiders'
    ordinary=action('spider','Web Sense','special_abilities')['official_action_reference']
    assert ordinary['heading']=='Spider' and ordinary['source_variant'] is None
    assert sum(a['name']=='Web Sense' for a in compendium.MONSTERS['spider']['special_abilities'])==1


def test_rule_bearing_supporting_prose_is_not_injected_into_last_action():
    parry=action('bandit-captain','Parry','reactions')['desc']
    assert 'strong personality' not in parry
    shark=action('reef-shark','Bite')['desc']
    assert 'shallow waters' not in shark
    frog=compendium.MONSTERS['frog']
    assert not frog.get('actions')
    assert 'no effective attacks' in frog['official_stat_block_reference']['supporting_prose'][0]['text']


def test_only_prose_and_source_refs_change_and_original_guards_remain():
    fixes=[r for r in compendium.CANONICAL_OVERLAY['corrections'] if r['id'].startswith('official-monster-action-prose-')]
    assert len(fixes)==1661
    assert Counter(r['path'][-1] for r in fixes)=={'desc':156,'official_action_reference':1505}
    assert all(r['path'][0] in bodies.SECTIONS and len(r['path'])==3 for r in fixes)
    assert all(r['expected'] is None for r in fixes if r['path'][-1]=='official_action_reference')
    # Creature-level anchors remain on the stat heading, despite cross-page actions.
    dragon=compendium.MONSTERS['ancient-black-dragon']
    assert dragon['source_refs']['canonical_page']==280
    assert action('ancient-black-dragon','Wing Attack (Costs 2 Actions)','legendary_actions')['legendary_cost']==2


@pytest.mark.parametrize('change',['body_threshold','wrong_damage','missing_nested','missing_condition','wrong_label',
    'wrong_owner','wrong_binding','runtime','missing_ref','wrong_name','duplicate_name','extra_action','form_action','bad_array','bad_action'])
def test_missing_or_changed_prose_and_identity_are_rejected(change):
    records=deepcopy(compendium.COLLECTIONS)
    def find(rid,name,section='actions'):
        return next(a for a in records['monsters'][rid][section] if a['name']==name)
    if change=='body_threshold':
        row=find('solar','Slaying Longbow');row['desc']=row['desc'].replace('100 hit points','190 hit points')
    elif change=='wrong_damage':
        row=find('giant-rat-diseased','Bite');row['desc']=row['desc'].replace('Hit: 4','Hit: 3')
    elif change=='missing_nested':
        row=find('androsphinx','Roar');row['desc']=row['desc'].split('Second Roar.',1)[0]
    elif change=='missing_condition':
        row=find('swarm-of-centipedes','Bites');row['desc']=row['desc'].replace('reduced to 0 hit points','hit')
    elif change=='wrong_label':find('aboleth','Enslave')['official_action_reference']['source_label']='Enslave (At Will)'
    elif change=='wrong_owner':find('swarm-of-spiders','Web Sense','special_abilities')['official_action_reference']['source_variant']['owner']='Spider'
    elif change=='wrong_binding':find('aboleth','Tail')['official_action_reference']['selected_binding']['record_id']='solar'
    elif change=='runtime':find('aboleth','Tail')['official_action_reference']['runtime_verified']=True
    elif change=='missing_ref':find('aboleth','Tail').pop('official_action_reference')
    elif change=='wrong_name':find('hezrou','Claws')['name']='Claw'
    elif change=='duplicate_name':records['monsters']['aboleth']['actions'].append(deepcopy(find('aboleth','Tail')))
    elif change=='extra_action':records['monsters']['aboleth']['actions'].append(dict(name='Invented',desc='automatic success'))
    elif change=='form_action':records['monsters']['vampire-mist']['actions']=[deepcopy(find('vampire-vampire','Unarmed Strike'))]
    elif change=='bad_array':records['monsters']['aboleth']['actions']=None
    else:records['monsters']['aboleth']['actions'][0]=None
    assert bodies.issues(records)


def test_action_array_order_is_not_a_rule_or_source_identity():
    records=deepcopy(compendium.COLLECTIONS)
    records['monsters']['vampire-spawn']['actions'].reverse()
    assert not bodies.issues(records)


@pytest.mark.parametrize('bad',[None,[],{'monsters':[]},{'monsters':{'aboleth':None}}])
def test_bad_collection_shape_returns_differences(bad):
    assert bodies.issues(bad)


def test_canonical_gate_rejects_a_plausible_restored_bug():
    records=deepcopy(compendium.COLLECTIONS)
    bow=next(a for a in records['monsters']['solar']['actions'] if a['name']=='Slaying Longbow')
    bow['desc']=bow['desc'].replace('100 hit points','190 hit points')
    assert any('Official monster action prose differs' in e for e in rules_packages.validate_records(records))
