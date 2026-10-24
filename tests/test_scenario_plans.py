"""Frozen scenario actions join plans without executing previews."""
from copy import deepcopy

import pytest

from backend import campaign, content, director, rules
from backend.action_plans import prepare, revalidate
from test_campaign import package


def room(custom=False):
    state = content.initialize_state()
    state.update(id='scenario-plan', status='playing', host_id='p', events=[],
                 members=[dict(id='p', name='Hero', character=content.new_character('fighter')),
                          dict(id='ally', name='Ally', character=content.new_character('fighter'))])
    if custom:
        campaign.start_campaign(state, package())
    else:
        state.update(scene=content.scene_for(state), scene_id='dock')
    return state


def test_authored_check_preview_never_rolls_and_confirmation_uses_executor(monkeypatch):
    state = room()
    before = deepcopy(state)
    with monkeypatch.context() as guard:
        guard.setattr(rules, 'roll_dice', lambda *a, **k: pytest.fail('preview rolled'))
        guard.setattr(rules, 'apply_action', lambda *a, **k: pytest.fail('preview executed'))
        proposal = director.propose_selected(state, 'p', 'investigate')['proposal']
        assert proposal['plan']['executor'] == 'rules'
        assert revalidate(state, 'p', proposal['plan']) == proposal['plan']
    assert state == before
    events = director.resolve(state, 'p', proposal)
    assert any(event['kind'] == 'roll' for event in events)
    assert state['flags']['attempted']['0:investigate']


def test_potion_target_and_finite_inventory_are_frozen():
    state = room()
    state['members'][1]['character']['hp'] = 0
    plan = prepare(state, 'p', 'heal', 'ally')
    assert plan['target_id'] == 'ally'
    assert plan['resources'] == [dict(type='item', id='healing-potion', amount=1)]
    state['members'][0]['character']['potions'] = 0
    with pytest.raises(ValueError):
        revalidate(state, 'p', plan)
    for target in ['missing', 'p']:
        with pytest.raises(ValueError):
            prepare(state, 'p', 'heal', target)


def test_custom_node_check_tracks_usage_without_disclosing_future_nodes():
    state = room(True)
    before = deepcopy(state)
    plan = prepare(state, 'p', 'node:read')
    assert plan['executor'] == 'campaign' and not plan['targets']
    assert plan['resources'] == [dict(type='scenario_use', id='read', amount=1, remaining=2)]
    assert state == before
    assert 'good' not in str(plan) and 'bad' not in str(plan)
    state['campaign']['spent']['p'] = {'read': 2}
    with pytest.raises(ValueError):
        prepare(state, 'p', 'node:read')


def test_dead_leader_can_submit_party_move_but_cannot_act_as_character():
    state = room(True)
    state['members'][0]['character'].update(hp=0, dead=True)
    proposal = director.propose_selected(state, 'p', 'node:enter')['proposal']
    assert proposal['plan']['party_action']
    # This route enters a battle; no member can accidentally spend the leader's action.
    director.resolve(state, 'p', proposal)
    assert state['campaign']['node_id'] == 'battle'
    with pytest.raises(ValueError):
        director.propose_selected(state, 'p', 'skill:strike')


@pytest.mark.parametrize('action,target,options', [
    ('end_turn', None, {}), ('investigate', 'ally', {}),
    ('investigate', None, {'slot_level': 1}), ('dodge', 'ally', {}),
])
def test_bad_scenario_inputs_never_mutate(action, target, options):
    state = room()
    before = deepcopy(state)
    with pytest.raises(ValueError):
        prepare(state, 'p', action, target, options)
    assert state == before


def test_previous_plan_schema_requires_replanning():
    state = room()
    proposal = director.propose_selected(state, 'p', 'investigate')['proposal']
    plan = proposal['plan']
    plan['schema_version'] = 1
    assert director.public_proposal(proposal, state)['stale']
    with pytest.raises(ValueError, match='过期'):
        revalidate(state, 'p', plan)


def test_node_preflights_both_outcomes_without_rolling(monkeypatch):
    from backend import world_combat
    state = room(True)
    before = deepcopy(state)
    seen = set()

    def validate(view, destination):
        seen.add(destination)
        if destination == 'bad':
            raise ValueError('occupied future place')

    monkeypatch.setattr(world_combat, 'preflight_place', validate)
    monkeypatch.setattr(rules, 'roll_dice', lambda *a, **k: pytest.fail('preview rolled'))
    with pytest.raises(ValueError, match='occupied'):
        prepare(state, 'p', 'node:read')
    assert 'bad' in seen and state == before


def test_custom_healing_freezes_target_usage_and_no_combat_action_outside_battle():
    state = room(True)
    state['members'][1]['character']['hp'] = 1
    plan = prepare(state, 'p', 'skill:mend', 'ally')
    assert plan['targets'] == [dict(id='ally', name='Ally')]
    assert plan['action_cost'] == 'none' and plan['budget'] == {}
    assert plan['resources'][0]['remaining'] == 2
    proposal = director.propose_selected(state, 'p', 'skill:mend', 'ally')['proposal']
    director.resolve(state, 'p', proposal)
    assert state['campaign']['spent']['p']['mend'] == 1


def test_legacy_combat_attack_and_dodge_consume_whole_action(monkeypatch):
    state = room()
    monkeypatch.setattr(rules.secrets, 'randbelow', lambda n: n - 1)
    state['scene_index'] = 1
    state['scene'] = content.scene_for(state)
    state['scene_id'] = state['scene']['id']
    rules.start_combat(state)
    state['combat']['turn_actor_id'] = 'p'
    for action in ['attack', 'dodge']:
        plan = prepare(state, 'p', action)
        assert plan['action_cost'] == 'action' and plan['budget'] == {'action': 1}
    state['combat']['action_used'] = True
    with pytest.raises(ValueError):
        prepare(state, 'p', 'dodge')
