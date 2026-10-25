from copy import deepcopy
import asyncio
import pytest
from backend import tactical as g, action_plans, director, abilities, characters, rules, enemy_dm
from test_scenario_plans import room


def battle(mechanic='none'):
    state=room()
    for m in state['members']:m['character']=characters.create_character('fighter',m['name'])
    state['combat']=dict(active=True,round=1,turn_actor_id='p',action_used=False,dodging=[],
        enemies=[dict(id='foe',name='守卫',hp=30,max_hp=30,ac=12,attack_bonus=2,damage_dice='1d4',attack_range=5)],order=['p','foe'],index=0)
    g.initialize(state,dict(mechanic=mechanic,walls=[dict(x=5,y=4)]))
    return state


def test_grid_preview_cancel_confirm_replay_and_stale_no_mutation(monkeypatch):
    s=battle();before=deepcopy(s)
    monkeypatch.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('movement rolled'))
    result=director.propose_selected(s,'p','grid:move',options=dict(destination=dict(x=4,y=1)))
    assert s==before
    proposal=result['proposal'];assert proposal['plan']['executor']=='tactical'
    director.resolve(s,'p',proposal)
    assert g.board(s)['positions']['p']==dict(x=4,y=1) and s['combat']['movement_spent']==15
    assert g.board(s)['positions']['ally']==g.board(before)['positions']['ally']
    with pytest.raises(ValueError):director.resolve(s,'p',proposal)


@pytest.mark.parametrize('p',[dict(x=19,y=19),dict(x=5,y=4),dict(x=1,y=2),dict(x=10,y=1),dict(x=True,y=2),dict(x=2,y=2,z=0)])
def test_illegal_destination_no_cost(p):
    s=battle();before=deepcopy(s)
    with pytest.raises(ValueError):action_plans.prepare(s,'p','grid:move',options=dict(destination=p))
    assert s==before


def test_wall_corner_difficult_terrain_and_occupancy():
    s=battle();b=g.board(s);b['walls']=[dict(x=2,y=1),dict(x=1,y=2)]
    assert not g.visible(b,dict(x=1,y=1),dict(x=2,y=2))
    assert (2,2) not in g.paths(s,'p',5)
    b['walls']=[];b['difficult']=[dict(x=2,y=1)]
    assert g.paths(s,'p',10)[(2,1)]['cost']==10


def test_range_and_line_of_sight_cannot_be_bypassed():
    s=battle();before=deepcopy(s)
    for fn in [lambda:action_plans.prepare(s,'p','attack','foe'),lambda:abilities.weapon_attack(s,'p','foe')]:
        with pytest.raises(ValueError,match='范围'):fn()
        assert s==before
    g.board(s)['positions']['foe']=dict(x=2,y=1)
    assert action_plans.prepare(s,'p','attack','foe')['target_id']=='foe'
    g.board(s)['walls']=[dict(x=2,y=1)]
    with pytest.raises(ValueError,match='视线'):action_plans.prepare(s,'p','attack','foe')


def test_chat_does_not_expire_movement_but_board_change_does():
    s=battle();plan=action_plans.prepare(s,'p','grid:move',options=dict(destination=dict(x=3,y=1)))
    s['events'].append(dict(kind='chat',text='商量'));s['version']=100
    assert action_plans.revalidate(s,'p',plan)
    g.board(s)['positions']['ally']=dict(x=3,y=1)
    with pytest.raises(ValueError):action_plans.revalidate(s,'p',plan)


def test_dm_moves_only_enemy_and_never_attacks_through_wall(monkeypatch):
    s=battle();s['combat']['turn_actor_id']='foe';before=deepcopy(g.board(s)['positions'])
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:0)
    events=[];enemy_dm.turn(s,s['combat']['enemies'][0],events)
    assert g.board(s)['positions']['p']==before['p'] and g.board(s)['positions']['ally']==before['ally']
    assert s['combat']['movement_spent']<=30
    for event in events:
        if event.get('target_id'):g.target(s,'foe',event['target_id'],5)


def test_boss_warning_is_persisted_and_can_be_avoided(monkeypatch):
    s=battle('storm');e=s['combat']['enemies'][0];e['attack_count']=2
    events=[];enemy_dm.mechanism(s,events);assert g.board(s)['telegraphs']
    once=deepcopy(g.board(s));enemy_dm.mechanism(s,events);assert g.board(s)==once
    g.board(s)['positions']['p']=dict(x=0,y=9);g.board(s)['positions']['ally']=dict(x=1,y=9)
    before=[m['character']['hp'] for m in s['members']];s['combat']['round']=2
    enemy_dm.mechanism(s,events)
    assert before==[m['character']['hp'] for m in s['members']]


def test_free_text_grid_move_uses_same_plan_and_cost():
    s=battle()
    result=asyncio.run(director.propose(None,s,'p','我移动到（4，2）'))
    assert result['proposal']['plan']['options']['destination']==dict(x=3,y=1)
    assert result['proposal']['plan']['executor']=='tactical'


def test_old_combat_does_not_gain_board_on_read():
    s=battle();s['combat'].pop('board');before=deepcopy(s)
    assert g.projection(s,'p') is None and s==before


def test_seal_obeys_corner_visibility_and_cancels_only_scene_warnings():
    s=battle('storm');b=g.board(s);b['positions']['p']=dict(x=3,y=1);b['walls']=[dict(x=4,y=1)]
    with pytest.raises(ValueError):g.prepare(s,'p','grid:seal-a')
    b['walls']=[];b['switches'][1]['active']=False
    b['telegraphs']=[dict(source='scene',cells=[],due=2),dict(source='breath',cells=[],due=2)]
    g.resolve(s,'p','grid:seal-a',{})
    assert [w['source'] for w in b['telegraphs']]==['breath']


def test_self_area_spells_and_forward_lightning_have_spatial_limits():
    s=battle();b=g.board(s);b['walls']=[];b['positions']['p']=dict(x=5,y=3)
    b['positions']['foe']=dict(x=6,y=3);b['positions']['ally']=dict(x=4,y=3)
    g.ability_targets(s,'p','cast:burning-hands',['foe'])
    with pytest.raises(ValueError):g.ability_targets(s,'p','cast:lightning-bolt',['foe','ally'])
    b['positions']['foe']=dict(x=10,y=3)
    with pytest.raises(ValueError):g.ability_targets(s,'p','cast:burning-hands',['foe'])
    with pytest.raises(ValueError):g.ability_targets(s,'p','cast:cure-wounds',['foe'])


def test_grid_moving_away_releases_grapple_permanently():
    s=battle();b=g.board(s);b['walls']=[];b['positions']['p']=dict(x=3,y=1);b['positions']['foe']=dict(x=4,y=1)
    foe=s['combat']['enemies'][0];foe['conditions']=[dict(id='grappled',source='p')]
    assert abilities.has_condition(s,foe,'grappled')
    g.resolve(s,'p','grid:move',dict(destination=dict(x=3,y=6)))
    assert not abilities.has_condition(s,foe,'grappled') and not foe['conditions']
    b['positions']['p']=dict(x=3,y=1)
    assert not abilities.has_condition(s,foe,'grappled')
