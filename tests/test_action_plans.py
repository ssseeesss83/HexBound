"""Plans freeze real costs/targets without running the prototype executor."""
from copy import deepcopy

import pytest

from backend import abilities as a, characters, content, rules
from backend.action_plans import prepare, revalidate


def battle(cls='wizard'):
    state = content.initialize_state()
    state.update(id='plan-room', status='playing', host_id='p', events=[],
                 members=[dict(id='p', name='Hero', character=characters.create_character(cls)),
                          dict(id='ally', name='Ally', character=characters.create_character('fighter'))])
    state['combat'] = dict(active=True, round=1, turn_actor_id='p', action_used=False,
                           bonus_action_used=False, dodging=[],
                           enemies=[dict(id='e', name='Enemy', hp=100, max_hp=100, ac=10,
                                         abilities=dict(str=10, dex=10, con=10, wis=10))])
    return state


@pytest.fixture(autouse=True)
def no_execution_during_planning(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Planning cannot roll or execute an action')
    monkeypatch.setattr(rules, 'roll_dice', forbidden)
    monkeypatch.setattr(a, 'apply_action', forbidden)
    monkeypatch.setattr(a, 'weapon_attack', forbidden)


def test_attack_and_spell_normalize_targets_and_freeze_slot_without_mutation():
    state = battle()
    before = deepcopy(state)
    attack = prepare(state, 'p', 'attack', now=10)
    spell = prepare(state, 'p', 'cast:magic-missile', now=10)
    assert attack['target_id'] == spell['target_id'] == 'e'
    assert attack['action_cost'] == 'attack'
    assert attack['budget'] == dict(action=1, attacks=1, attack_allowance_granted=1)
    assert spell['resources'] == [dict(type='spell_slot', source='spell', level=1, amount=1)]
    assert spell['options'] == dict(slot_level=1, slot_source='spell', target_ids=['e'])
    assert revalidate(state, 'p', spell, now=11) == spell  # Original identity/expiry retained.
    assert state == before


@pytest.mark.parametrize('options', [False, 0, '', []])
def test_non_mapping_options_do_not_turn_into_empty_options(options):
    state = battle()
    before = deepcopy(state)
    with pytest.raises(ValueError):
        prepare(state, 'p', 'cast:magic-missile', 'e', options)
    assert state == before


@pytest.mark.parametrize('patch', [
    dict(slot_level=2), dict(target_ids=['ally']), dict(target_ids=['e','e']),
    dict(slot_level=True), dict(resource_amount=5), dict(damage=999),
])
def test_bad_spell_options_fail_without_mutation(patch):
    state = battle()
    before = deepcopy(state)
    with pytest.raises(ValueError):
        prepare(state, 'p', 'cast:magic-missile', 'e', patch)
    assert state == before


def test_cantrip_uses_no_slot_and_pact_slot_source_is_explicit():
    state = battle()
    state['members'][0]['character']['cantrips'].append('fire-bolt')
    assert not prepare(state, 'p', 'cast:fire-bolt', 'e')['resources']
    warlock = battle('warlock')
    c = warlock['members'][0]['character']
    # Fiend expanded-list fixture; this suite tests plans, not build legality.
    c['subclass_id'] = 'fiend'
    c['known_spells'].append('burning-hands')
    plan = prepare(warlock, 'p', 'cast:burning-hands', 'e', dict(slot_source='pact'))
    assert plan['resources'] == [dict(type='spell_slot', source='pact', level=1, amount=1)]
    automatic = prepare(warlock, 'p', 'cast:burning-hands', 'e')
    assert automatic['options'] == plan['options'] and automatic['resources'] == plan['resources']


@pytest.mark.parametrize('cls,fid,resource,cost', [
    ('barbarian','rage','rage',1), ('fighter','second-wind','second-wind',1),
    ('bard','bardic-inspiration','bardic-inspiration',1),
    ('paladin','lay-on-hands','lay-on-hands',3),
    ('monk','patient-defense','ki',1), ('monk','flurry-of-blows','ki',1),
    ('fighter','action-surge','action-surge',1),
    ('wizard','arcane-recovery','arcane-recovery',1),
    ('sorcerer','font-of-magic','sorcery-points',2),
])
def test_feature_resource_costs_are_read_only(cls, fid, resource, cost):
    state = battle(cls)
    c = state['members'][0]['character']
    c['level'] = max(c['level'], 2)
    c['hp'] -= 2
    c['resources'][resource] = dict(current=10, max=10)
    state['members'][1]['character']['hp'] -= 5
    state['combat']['attack_action_taken'] = True
    if fid in {'arcane-recovery', 'font-of-magic'}:
        state['combat']['active'] = False
        c['short_rest_ready'] = True
        c['spell_slots'] = {'1':dict(current=1, max=2)}
    opts = dict(resource_amount=3) if fid == 'lay-on-hands' else {}
    before = deepcopy(state)
    plan = prepare(state, 'p', 'feature:' + fid, 'ally' if fid in {'lay-on-hands','bardic-inspiration'} else None, opts)
    assert plan['resources'] == [dict(type='class_resource', id=resource, amount=cost, unlimited=False)]
    if fid in {'arcane-recovery', 'font-of-magic'}:
        assert plan['restores'] == [dict(type='spell_slot', source='spell', level=1, amount=1)]
    assert state == before


def test_smite_melee_and_slot_validation_and_concentration_end():
    state = battle('paladin')
    c = state['members'][0]['character']
    c['level'] = 2
    c['spell_slots'] = {'1':dict(current=2, max=2)}
    plan = prepare(state, 'p', 'feature:divine-smite', 'e')
    assert plan['resources'][0]['level'] == 1 and plan['action_cost'] == 'attack'
    assert plan['resources'][0]['when'] == 'on_hit'
    state['combat']['enemies'][0]['position'] = 'withdrawn'
    with pytest.raises(ValueError, match='撤远'):
        prepare(state, 'p', 'feature:divine-smite', 'e')
    c['concentration'] = dict(spell_id='bless')
    plan = prepare(state, 'p', 'end-concentration')
    assert plan['target_id'] == 'p' and not plan['resources']
    assert plan['ends_concentration'] == dict(spell_id='bless')
    assert c['concentration']


def test_remaining_attack_cost_does_not_start_a_second_action():
    state = battle('fighter')
    state['combat'].update(action_used=True, attacks_remaining=1)
    plan = prepare(state, 'p', 'attack', 'e')
    assert plan['budget'] == dict(action=0, attacks=1, attack_allowance_granted=0)


@pytest.mark.parametrize('change', ['turn','resources','target','epoch','rules','engine','scope','death'])
def test_confirm_rechecks_frozen_state_and_identity(change):
    state = battle()
    plan = prepare(state, 'p', 'cast:magic-missile', 'e', now=0)
    if change == 'turn': state['combat']['turn_actor_id'] = 'ally'
    elif change == 'resources': state['members'][0]['character']['spell_slots']['1']['current'] = 0
    elif change == 'target': state['combat']['enemies'].clear()
    elif change == 'epoch': state['member_contexts'] = {'p':dict(epoch=2)}
    elif change == 'rules': state['ruleset_id'] = 'other'
    elif change == 'engine': state['engine_profile'] = 'unimplemented-engine'
    elif change == 'scope': state['_scene_execution_view'] = 'other-scene'
    else: state['members'][0]['character']['dead'] = True
    before = deepcopy(state)
    with pytest.raises(ValueError):
        revalidate(state, 'p', plan, now=1)
    assert state == before


def test_chat_keeps_plan_valid_but_expiry_actor_and_unknown_abilities_reject():
    state = battle()
    plan = prepare(state, 'p', 'attack', 'e', now=1)
    state['events'].append(dict(kind='chat', text='still discussing'))
    state['version'] = 100
    assert revalidate(state, 'p', plan, now=2) == plan
    for actor, now in [('ally',2), ('p',121)]:
        with pytest.raises(ValueError): revalidate(state, actor, plan, now=now)
    for action in ['cast:wish', 'feature:invented', 'node:secret', 'end_turn']:
        with pytest.raises(ValueError): prepare(state, 'p', action)
