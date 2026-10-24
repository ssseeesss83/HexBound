"""World hooks reject ownership conflicts before dice and resource changes."""
from copy import deepcopy
import pytest
from backend import campaign, content, director, rules, scene_storage as scenes
from backend import world_environment, world_combat, world_state as world, session_scope
from test_campaign import package, room


def script_room():
    state = {**room(), 'id':'world-script','status':'playing','events':[], 'action_revision':0}
    campaign.start_campaign(state, package())
    session_scope.initialize(state)
    return scenes.for_actor(world_combat.migrate(world_environment.migrate(scenes.pack(state))), 'p0')


def block(state, node):
    pid = world_environment.place_id(state, node)
    if pid not in state['world_places']:
        world.add_place(state, pid)
    state['world_places'][pid].update(active_encounter_id='foreign', encounter_owner_scene_id='side')


def no_dice(monkeypatch):
    monkeypatch.setattr(rules, 'check', lambda *a, **kw: pytest.fail('ownership rejected after rolling'))
    monkeypatch.setattr(rules, 'roll_dice', lambda *a, **kw: pytest.fail('ownership rejected after rolling'))


def test_authored_check_prechecks_both_branches_before_resource_or_roll(monkeypatch):
    state = script_room()
    block(state, 'bad')
    before = deepcopy(state)
    no_dice(monkeypatch)
    with pytest.raises(world.WorldConflict, match='另一队'):
        campaign.apply_action(state, 'p0', 'node:read')
    assert state == before
    with pytest.raises(world.WorldConflict, match='另一队'):
        campaign._enter(state, 'bad', [])
    assert state == before


def test_director_check_prechecks_branches_before_resource_or_roll(monkeypatch):
    state = script_room()
    block(state, 'bad')
    decision = {'kind':'check','label':'Read','text':'Read the stone','skill_id':'investigation','anchor_action_id':'node:read','success_text':'Pass','failure_text':'Fail'}
    proposal = director.validate_proposal(decision, state, 'p0')
    before = deepcopy(state)
    no_dice(monkeypatch)
    with pytest.raises(world.WorldConflict, match='另一队'):
        director.resolve(state, 'p0', proposal)
    assert state == before


def test_direct_start_and_legacy_failure_check_reject_before_roll(monkeypatch):
    state = {**content.initialize_state(), 'id':'legacy-world','status':'playing','events':[],
             'host_id':'p0','members':room()['members']}
    state['scene_index'] = 1
    state['scene'] = content.scene_for(state)
    state['scene_id'] = state['scene']['id']
    session_scope.initialize(state)
    state = scenes.for_actor(world_combat.migrate(world_environment.migrate(scenes.pack(state))), 'p0')
    block(state, state['scene_id'])
    before = deepcopy(state)
    no_dice(monkeypatch)
    with pytest.raises(world.WorldConflict, match='另一队'):
        rules.start_combat(state)
    assert state == before
    with pytest.raises(world.WorldConflict, match='另一队'):
        rules.apply_action(state, 'p0', 'investigate')
    assert state == before


def test_battle_writeback_revisit_and_persisted_entity_refs(monkeypatch):
    state = script_room()
    monkeypatch.setattr(rules.secrets, 'randbelow', lambda n: min(10,n-1))
    campaign.apply_action(state, 'p0', 'node:enter')
    assert state['combat']['active'] and len(state['combat']['enemies']) == 2
    first, second = state['combat']['enemies']
    first['hp'] = 0
    second['hp'] = 3
    state['combat']['active'] = False
    world_environment.prepare_save(state)
    canonical = scenes.pack(state)
    saved = canonical['scene_instances'][scenes.MAIN_SCENE]['local']['combat']
    assert 'enemies' not in saved and len(saved['enemy_refs']) == 2
    state = scenes.for_actor(canonical, 'p0')
    state['combat'] = None
    calls = []
    original_check = rules.check
    def initiative(*args, **kwargs):
        calls.append(args)
        return {**original_check(*args, **kwargs), 'total':len(calls) * 10}
    monkeypatch.setattr(rules, 'check', initiative)
    campaign._start_combat(state, {'monster_ids':['wolf','wolf']}, [])
    assert len(state['combat']['enemies']) == 1
    assert state['combat']['enemies'][0]['hp'] == 3
    assert len(calls) == 2  # one surviving enemy + one player


def test_reading_after_first_member_moves_does_not_write_old_scene(monkeypatch):
    state = script_room()
    monkeypatch.setattr(rules.secrets, 'randbelow', lambda n: min(10,n-1))
    campaign.apply_action(state, 'p0', 'node:enter')
    state['combat']['active'] = False
    world_environment.prepare_save(state)
    canonical = scenes.pack(state)
    side = deepcopy(canonical['scene_instances'][scenes.MAIN_SCENE])
    side.update(id='side', channel_id='side', place_id=world_environment.place_id(canonical,'yard'))
    side['local'].update(scene_id='yard', scene={'id':'yard','objects':[]}, combat=None, environment={})
    canonical['scene_instances']['side'] = side
    world.add_place(canonical, side['place_id'])
    canonical['member_contexts']['p0']['scene_instance_id'] = 'side'
    before = deepcopy(canonical)
    monkeypatch.setattr(world, 'write_entities', lambda *a, **kw: pytest.fail('read must not write entities'))
    result = scenes.for_actor(scenes.unpack(canonical), 'p0')
    assert result['_scene_execution_view'] == 'side'
    assert canonical == before


def test_director_extra_encounter_rejects_before_marking_started(monkeypatch):
    state = script_room()
    block(state, state['scene_id'])
    proposal = director.validate_proposal({'kind':'encounter','label':'Wolves','text':'Wolves arrive','monster_id':'wolf'}, state, 'p0')
    before = deepcopy(state)
    no_dice(monkeypatch)
    with pytest.raises(world.WorldConflict, match='另一队'):
        director.resolve(state, 'p0', proposal)
    assert state == before


def test_object_action_checks_foreign_ownership_and_version_before_dice(monkeypatch):
    from backend import free_actions
    state = script_room()
    state['scene']['objects'] = [{'id':'chest','name':'Chest','hp':20,'tags':['searchable']}]
    world_environment.attach_current(state)
    block(state, state['scene_id'])
    before = deepcopy(state)
    no_dice(monkeypatch)
    decision = {'kind':'free_action','action_id':'search','object_id':'chest'}
    with pytest.raises(world.WorldConflict, match='另一队'):
        free_actions.resolve(state, 'p0', decision)
    assert state == before
    place = state['world_places'][state['scene_instances'][scenes.MAIN_SCENE]['place_id']]
    place.update(active_encounter_id=None, encounter_owner_scene_id=None)
    eid = state['environment'][state['scene_id']]['entity_refs']['chest']
    state['world_entities'][eid]['revision'] += 1
    with pytest.raises(world.WorldConflict, match='物件读取版本'):
        free_actions.resolve(state, 'p0', decision)


def test_first_enemy_turns_keep_new_location_fire_damage_after_save():
    from unittest.mock import patch
    state = script_room()
    node = next(row for row in state['campaign']['package']['scenario']['nodes'] if row['id']=='battle')
    node['objects'] = [{'id':'fire','name':'Fire','hp':20,'tags':['fire']}]
    original = rules.check
    def initiative(bonus, *args, **kwargs):
        if not args and not kwargs:
            return {**original(bonus), 'total':10 if bonus else 20}
        return original(bonus, *args, **kwargs)
    with patch.object(rules, 'check', side_effect=initiative), patch.object(rules.secrets, 'randbelow', return_value=0):
        campaign.apply_action(state, 'p0', 'node:enter')
    obj = state['environment']['battle']['objects']['fire']
    assert obj['hp'] == 16
    world_environment.prepare_save(state)
    restored = scenes.for_actor(scenes.pack(state), 'p0')
    assert restored['environment']['battle']['objects']['fire']['hp'] == 16


from test_core_integration import env, room as api_room, cmd


def test_foreign_encounter_blocks_action_but_keeps_chat_and_reads(env):
    a, _, store, _ = env
    created = api_room(a).json()
    rid = created['room']['id']
    assert cmd(a, rid, 'start')[0].status_code == 200
    state = store.get(rid)
    previous = state['version']
    block(state, state['scene_id'])
    state['version'] += 1
    store.save(state, previous)
    assert a.get(f'/api/rooms/{rid}').status_code == 200
    response, _ = cmd(a, rid, 'action', {'action_id':'investigate'})
    assert response.status_code == 409
    response, _ = cmd(a, rid, 'chat', {'text':'We can still discuss the situation.'})
    assert response.status_code == 200, response.text
    assert 'We can still discuss' in a.get(f'/api/rooms/{rid}/events').text
