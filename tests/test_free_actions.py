from copy import deepcopy
from unittest.mock import patch
import pytest
from backend import free_actions as f, abilities as a, characters, rules


def room():
    return {'scene_id':'s','scene':{'id':'s','objects':[
        {'id':'box','name':'木箱','tags':['movable','cover','flammable','searchable','interactable'],'hp':10},
        {'id':'sand','name':'沙地','tags':['sand'],'hp':10}]},'members':[
        {'id':'p','name':'主角','character':characters.create_character('fighter')},
        {'id':'ally','name':'同伴','character':characters.create_character('rogue')}],
        'combat':{'active':True,'turn_actor_id':'p','round':1,'action_used':False,'dodging':[],
                  'enemies':[{'id':'e','name':'敌人','hp':50,'max_hp':50,'ac':10,'abilities':{'str':10,'dex':10}}]}}


def act(s,recipe,**kw):
    return f.resolve(s,'p',{'kind':'free_action','action_id':recipe,**kw})


def test_context_and_validation_are_readonly_and_forgery_atomic():
    s=room(); original=deepcopy(s)
    assert f.context(s,'p')['recipes']
    f.validate(s,'p',{'action_id':'topple','target_id':'e','object_id':'box'})
    assert s==original
    for decision in [{'action_id':'topple','target_id':'e','object_id':'invented'}, {'action_id':'grapple','target_id':'ally'}, {'action_id':'ignite','object_id':'box','damage':999}]:
        with pytest.raises(ValueError):f.resolve(s,'p',decision)
        assert s==original


@patch('backend.rules.secrets.randbelow',return_value=0)
def test_failed_environment_check_consumes_action_and_blocks_cast(mock):
    s=room(); events=act(s,'topple',target_id='e',object_id='box')
    assert not events[0]['success']
    assert s['combat']['action_used']
    assert s['combat']['enemies'][0]['hp']==50
    with pytest.raises(ValueError):act(s,'interact',object_id='box')


@patch('backend.rules.secrets.randbelow',return_value=19)
def test_topple_damage_prone_and_object_cannot_be_reused(mock):
    s=room(); act(s,'topple',target_id='e',object_id='box')
    assert s['environment']['s']['objects']['box']['toppled']
    assert a.has_condition(s,s['combat']['enemies'][0],'prone')
    assert s['combat']['enemies'][0]['hp']<50
    s['combat']['action_used']=False
    with pytest.raises(ValueError):act(s,'topple',target_id='e',object_id='box')


def test_help_applies_once_to_next_attack():
    s=room(); act(s,'help',target_id='ally')
    s['combat']['turn_actor_id']='ally';s['combat']['action_used']=False
    ally=s['members'][1]['character'];enemy=s['combat']['enemies'][0]
    assert a.attack_advantage(s,ally,enemy)
    with patch('backend.rules.secrets.randbelow',return_value=0):a.weapon_attack(s,'ally','e')
    assert not a.has_condition(s,ally,'helped')


@patch('backend.rules.secrets.randbelow',return_value=0)
def test_sand_blinds_through_targets_turn_then_clears(mock):
    s=room();act(s,'throw-sand',target_id='e',object_id='sand')
    enemy=s['combat']['enemies'][0]
    assert a.attack_disadvantage(s,enemy)
    a.start_turn(s,'e')
    assert a.has_condition(s,enemy,'blinded')
    a.end_turn(s,'e')
    assert not a.has_condition(s,enemy,'blinded')


def test_move_dash_budget_and_melee_restriction():
    s=room();act(s,'withdraw')
    assert s['combat']['movement_spent']==15
    with pytest.raises(ValueError):a.weapon_attack(s,'p','e')
    assert not s['combat']['action_used']
    act(s,'move')
    with pytest.raises(ValueError):act(s,'withdraw')
    act(s,'dash');act(s,'withdraw')
    assert s['combat']['movement_budget']==60
    a.start_turn(s,'p')
    assert s['combat']['movement_budget']==30 and s['combat']['movement_spent']==0


def test_grapple_blocks_movement_but_does_not_block_attacks():
    s=room();s['members'][0]['character']['conditions']=[{'id':'grappled','source':'e'}]
    with pytest.raises(ValueError):act(s,'move')
    with patch('backend.rules.secrets.randbelow',return_value=0):a.weapon_attack(s,'p','e')
    assert s['combat']['action_used']


def test_persistent_fire_outside_combat_and_scene_isolation():
    s=room();s['combat']=None;s['scene']['objects'].append({'id':'torch','name':'火炬','tags':['fire'],'hp':100}); original_scene=deepcopy(s['scene'])
    act(s,'ignite',object_id='box')
    assert s['environment']['s']['objects']['box']['hp']==8
    act(s,'interact',object_id='box')
    assert s['environment']['s']['objects']['box']['hp']==6
    act(s,'extinguish',object_id='box')
    assert s['environment']['s']['objects']['box']['hp']==6
    assert s['environment']['s']['elapsed_seconds']==18
    assert s['scene']==original_scene
    s['scene_id']='other'
    assert f.context(s,'p')['objects'][0]['hp']==10
    s['scene_id']='s'
    assert f.context(s,'p')['objects'][0]['hp']==6


def test_no_objects_no_environment_actions_and_paused_context():
    s=room();s['scene']['objects']=[]
    for r in f.context(s,'p')['recipes']:
        if r['requires_object']:assert r['disabled_reason']
    s['status']='paused'
    assert all(r['disabled_reason'] for r in f.context(s,'p')['recipes'])
    assert f.context(s,'unknown')['recipes']==[]


def test_shove_consumes_one_extra_attack_even_on_failed_contest():
    s=room();s['members'][0]['character']['level']=5
    with patch('backend.rules.secrets.randbelow',return_value=0):
        act(s,'shove-prone',target_id='e')
    assert s['combat']['action_used'] and s['combat']['attacks_remaining']==1
    with patch('backend.rules.secrets.randbelow',return_value=0):a.weapon_attack(s,'p','e')
    assert s['combat']['attacks_remaining']==0
    with pytest.raises(ValueError):act(s,'shove-prone',target_id='e')


def test_free_attack_kill_finishes_combat_and_retains_encounter_identity():
    s=room();s['combat'].update(encounter_id='immutable',director_encounter=True)
    s['combat']['enemies'][0]['hp']=1
    with patch('backend.rules.secrets.randbelow',return_value=19):
        events=act(s,'improvised-attack',target_id='e',object_id='box')
    assert not s['combat']['active']
    assert s['combat']['encounter_id']=='immutable'
    assert not s.get('flags',{}).get('scene_resolved')
    assert any(e['kind']=='combat' for e in events)


def test_ignite_requires_real_fire_and_battle_fire_ticks_only_at_turn_end():
    s=room()
    with pytest.raises(ValueError,match='火源'):act(s,'ignite',object_id='box')
    s['scene']['objects'].append({'id':'torch','name':'火炬','tags':['fire'],'hp':100})
    act(s,'ignite',object_id='box')
    assert s['environment']['s']['objects']['box']['hp']==10
    assert s['environment']['s']['tick']==0
    a.end_turn(s,'p')
    assert s['environment']['s']['objects']['box']['hp']==8
    assert s['environment']['s']['tick']==1


def test_authored_object_dc_is_visible_and_used():
    s=room();s['scene']['objects'][0]['dc']=25
    plan=f.validate(s,'p',{'action_id':'topple','target_id':'e','object_id':'box'})
    assert 'DC25' in plan['check'] and any('DC25' in x for x in plan['summary'])
    with patch('backend.rules.secrets.randbelow',return_value=19):events=act(s,'topple',target_id='e',object_id='box')
    assert events[0]['roll']['dc']==25
    assert not events[0]['success']


def test_close_pushed_enemy_and_stand_up_cost_movement():
    s=room();s['combat']['enemies'][0]['position']='withdrawn'
    with pytest.raises(ValueError):act(s,'grapple',target_id='e')
    act(s,'move')
    assert s['combat']['enemies'][0]['position']=='engaged'
    s['members'][0]['character']['conditions']=[{'id':'prone'}]
    act(s,'stand-up')
    assert not a.has_condition(s,s['members'][0]['character'],'prone')
    assert s['combat']['movement_spent']==30


def test_prone_melee_advantage_but_ranged_spell_disadvantage():
    s=room();attacker=s['members'][0]['character'];target=s['combat']['enemies'][0]
    target['conditions']=[{'id':'prone'}]
    assert a.attack_advantage(s,attacker,target,melee=True)
    assert not a.attack_advantage(s,attacker,target,melee=False)
    assert a.attack_disadvantage(s,attacker,target,melee=False)
    assert not a.attack_disadvantage(s,attacker,target,melee=True)
    caster=characters.create_character('wizard');caster['cantrips']=['fire-bolt'];s['members'][0]['character']=caster
    with patch('backend.rules.attack_roll',return_value={'success':False,'damage':0,'critical':False}) as attack:
        a.apply_action(s,'p','cast:fire-bolt','e')
    assert attack.call_args.kwargs['disadvantage'] and not attack.call_args.kwargs['advantage']


def test_temporary_free_conditions_do_not_leak_between_encounters():
    s=room();s['combat']['encounter_id']='first'
    act(s,'help',target_id='ally')
    ally=s['members'][1]['character']
    assert a.has_condition(s,ally,'helped')
    s['combat']['active']=False
    assert not a.has_condition(s,ally,'helped')
    s['combat'].update(active=True,encounter_id='second')
    assert not a.has_condition(s,ally,'helped')
    a.start_turn(s,'ally')
    assert not any(x['id']=='helped' for x in ally['conditions'])
