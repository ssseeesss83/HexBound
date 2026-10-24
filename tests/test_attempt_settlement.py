"""Both existing exploration routes settle the same global challenge once."""
from copy import deepcopy
import json

import pytest

from backend import attempts, campaign, content, director, free_actions, rules, scene_storage, world_environment
from backend.store import Store
from backend.maintenance import backup_database, restore_backup
from test_scenario_plans import room
from test_campaign import package


def test_failed_search_is_consumed_for_whole_party_despite_unrelated_changes(monkeypatch):
    state = room()
    state['scene']['objects'] = [dict(id='box', name='Box', tags=['searchable'], hp=10)]
    monkeypatch.setattr(rules.secrets, 'randbelow', lambda n: 0)
    decision = dict(kind='free_action', action_id='search', object_id='box')
    events = free_actions.resolve(state, 'p', decision)
    assert not events[0]['success']
    spec = attempts.lookup(state, 'search', object_id='box')
    outcome = attempts.inspect(state, spec, 'ally')['previous']
    assert outcome['effect_receipt'] == events[0]['attempt_receipt']
    assert set(outcome['audience']) == {'p', 'ally'}
    state.update(rest_used=True, version=100)
    state['members'][0]['character']['hp'] -= 1
    state['events'].append({'kind':'chat','text':'I try a different skill'})
    before = deepcopy(state)
    monkeypatch.setattr(rules, 'roll_dice', lambda *a, **k: pytest.fail('Repeated search rolled'))
    with pytest.raises(ValueError):
        free_actions.resolve(state, 'ally', decision)
    assert state == before
    assert not next(row for row in free_actions.context(state, 'ally')['recipes'] if row['id']=='search')['objects']


def test_six_distinct_authored_challenges_have_no_improvisation_counter_limit(monkeypatch):
    state = room()
    definitions = deepcopy(content.SCENES)
    definitions[0]['actions'] = [dict(id=f'observe-{n}', label=f'Read {n}', ability='int', dc=8) for n in range(6)]
    state['scenes'] = definitions
    state['scene'] = content.scene_for(state)
    state['director'] = dict(improv_checks={'dock':{'p':999}})
    monkeypatch.setattr(rules.secrets, 'randbelow', lambda n: n - 1)
    for action in definitions[0]['actions']:
        proposal = director.validate_proposal(dict(kind='check', label='Read', text='Try to read.',
            skill_id='perception', anchor_action_id=action['id'], success_text='Read.', failure_text='Unread.'),state,'p')
        events = director.resolve(state, 'p', proposal)
        assert events[0]['roll']['success']
    assert len(state['attempt_ledger']) == 6
    assert state['director']['improv_checks']['dock']['p'] == 999  # Historical data remains inert.


def test_menu_and_director_cannot_repeat_same_authored_challenge_after_flags_reset(monkeypatch):
    state = room()
    monkeypatch.setattr(rules.secrets, 'randbelow', lambda n: 0)
    proposal = director.propose_selected(state, 'p', 'investigate')['proposal']
    director.resolve(state, 'p', proposal)
    state['flags']['attempted'] = {}  # A new local scene must not reset global eligibility.
    before = deepcopy(state)
    monkeypatch.setattr(rules, 'roll_dice', lambda *a, **k: pytest.fail('Repeated challenge rolled'))
    for actor in ['p', 'ally']:
        with pytest.raises(ValueError):
            rules.apply_action(state, actor, 'investigate')
        with pytest.raises(ValueError):
            director.propose_selected(state, actor, 'investigate')
        assert 'investigate' not in director._anchors(state, actor)
    assert state == before


def test_campaign_failure_stays_consumed_on_revisit_across_entry_methods(monkeypatch):
    state = room(True)
    monkeypatch.setattr(rules.secrets, 'randbelow', lambda n: 0)
    campaign.apply_action(state, 'p', 'node:read')
    assert state['campaign']['node_id'] == 'bad'
    campaign._enter(state, 'gate', [])
    state.update(completed=False, status='playing')
    with pytest.raises(ValueError):
        director.validate_proposal(dict(kind='check', label='Retry', text='Try another skill.',
            skill_id='athletics', anchor_action_id='node:read', success_text='yes', failure_text='no'),state,'ally')
    with pytest.raises(ValueError):
        campaign.apply_action(state, 'ally', 'node:read')
    assert state['campaign']['spent']['p']['read'] == 1


def test_legacy_bool_migration_preserves_unknown_result_without_fake_rolls():
    state = room()
    state['flags']['attempted'] = {'0:investigate': True, '0:parley':False}
    state['director'] = dict(improv_checks={'dock':{'p':3}})
    before = deepcopy(state)
    migrated = attempts.migrate(world_environment.migrate(scene_storage.pack(state)))
    assert state == before and attempts.migrate(migrated) == migrated
    view = scene_storage.unpack(migrated)
    spec = attempts.lookup(view, 'investigate')
    result = attempts.inspect(view, spec, 'ally')
    assert result['status'] == 'legacy_consumed_unknown' and result['previous'] is None
    assert len(view['attempt_ledger']) == 1
    assert view['director'] == before['director']
    assert view['events'] == before['events']


def test_schema11_upgrade_and_verified_backup_preserve_global_consumption(tmp_path, monkeypatch):
    from backend import maintenance
    state = room()
    state['flags']['attempted'] = {'0:investigate':True}
    state['invite_code'] = 'OLD-ATTEMPT'
    path = tmp_path / 'attempt.sqlite3'
    store = Store(str(path))
    with store.connect() as db:
        db.execute('INSERT INTO rooms VALUES(?,?,?,?)',(state['id'],state['invite_code'],0,json.dumps(scene_storage.pack(state))))
        db.execute('PRAGMA user_version=11')
    upgraded = Store(str(path))
    view = upgraded.get(state['id'])
    assert attempts.inspect(view, attempts.lookup(view,'investigate'), 'p')['status'] == 'legacy_consumed_unknown'
    archive = tmp_path / 'attempt.zip'
    backup_database(path, archive)
    restore_backup(archive, tmp_path / 'recovered')
    recovered = Store(str(tmp_path / 'recovered/database.sqlite3'))
    assert recovered.get(state['id']) == view
    monkeypatch.setattr(maintenance, 'SCHEMA_VERSION', 11)
    with pytest.raises(ValueError, match='newer server'):
        Store(str(path))
