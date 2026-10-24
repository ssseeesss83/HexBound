"""Real HTTP plans/confirmation, including both entry sources and old receipts."""
from copy import deepcopy
import uuid

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app
from backend import rules


@pytest.fixture
def table(tmp_path, monkeypatch):
    monkeypatch.setenv('HEXBOUND_ALLOW_GUESTS', '1')
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    monkeypatch.delenv('LLM_MODEL', raising=False)
    monkeypatch.setattr(rules.secrets, 'randbelow', lambda n: 0)
    app = create_app(str(tmp_path / 'plans.sqlite3'))
    with TestClient(app) as client:
        session = client.post('/api/rooms', json=dict(player_name='旅人', character_id='wizard', starting_level=1)).json()
        yield app, client, session


def send(client, session, kind, payload=None, command_id=None):
    url = '/api/rooms/' + session['room']['id']
    headers = dict(Authorization='Bearer ' + session['token'])
    frame = client.get(url, headers=headers).json()
    return client.post(url + '/commands', headers=headers, json=dict(
        command_id=command_id or uuid.uuid4().hex, expected_version=frame['version'],
        expected_action_revision=frame['action_revision'], expected_scene_instance_id=frame['scene_instance_id'],
        expected_membership_epoch=frame['membership_epoch'], type=kind, payload=payload or {}))


def enter_battle(client, session):
    for kind, payload in [('start', {}), ('action', {'action_id':'investigate'}),
                          ('action', {'action_id':'advance'}), ('action', {'action_id':'fight'})]:
        response = send(client, session, kind, payload)
        assert response.status_code == 200, response.text
    frame = response.json()['room']
    assert frame['combat']['active'] and frame['combat']['turn_actor_id'] == session['member_id']
    return frame


def test_both_entries_share_attack_plan_and_confirm_once(table, monkeypatch):
    app, client, session = table
    before = enter_battle(client, session)
    target = before['combat']['enemies'][0]['id']
    original_roll = rules.roll_dice
    def forbidden(*args, **kwargs):
        raise AssertionError('Neither entry may roll before confirmation')
    monkeypatch.setattr(rules, 'roll_dice', forbidden)
    requested = send(client, session, 'capability_propose', dict(action_id='attack', target_id=target))
    assert requested.status_code == 200, requested.text
    first = requested.json()['room']['director_proposals'][0]
    described = send(client, session, 'director_propose', dict(text='我攻击眼前的敌人'))
    assert described.status_code == 200, described.text
    frame = described.json()['room']
    second = frame['director_proposals'][0]
    assert first['kind'] == second['kind'] == 'capability'
    assert first['action_intent']['source'] == 'capability'
    assert second['action_intent']['source'] == 'free_text'
    for key in ['action_id','target_id','options','targets','budget','resources']:
        assert first['plan'][key] == second['plan'][key]
    assert frame['party'] == before['party'] and frame['combat'] == before['combat']
    assert not {'fingerprint', 'room_id', 'actor_id', 'membership_epoch'} & second['plan'].keys()
    monkeypatch.setattr(rules, 'roll_dice', original_roll)
    command_id = uuid.uuid4().hex
    confirmed = send(client, session, 'director_resolve', dict(proposal_id=second['id']), command_id)
    assert confirmed.status_code == 200, confirmed.text
    settled = confirmed.json()['room']
    assert settled['combat']['action_used'] and not settled['director_proposals']
    count = sum(bool(event.get('roll')) for event in settled['events'])
    assert count == sum(bool(event.get('roll')) for event in before['events']) + 1
    replay = send(client, session, 'director_resolve', dict(proposal_id=second['id']), command_id)
    assert replay.status_code == 200 and replay.json()['replayed']
    assert sum(bool(event.get('roll')) for event in replay.json()['room']['events']) == count


def test_spell_plan_survives_chat_and_replayed_request_without_spending(table):
    app, client, session = table
    before = enter_battle(client, session)
    target = before['combat']['enemies'][0]['id']
    cid = uuid.uuid4().hex
    payload = dict(action_id='cast:magic-missile', target_id=target)
    response = send(client, session, 'capability_propose', payload, cid)
    assert response.status_code == 200, response.text
    plan = response.json()['room']['director_proposals'][0]
    assert plan['plan']['resources'] == [dict(type='spell_slot', source='spell', level=1, amount=1)]
    assert response.json()['room']['party'] == before['party']
    replay = send(client, session, 'capability_propose', payload, cid)
    assert replay.status_code == 200 and replay.json()['replayed']
    assert replay.json()['room']['director_proposals'][0]['id'] == plan['id']
    chat = send(client, session, 'chat', dict(text='正在商量'))
    assert not chat.json()['room']['director_proposals'][0]['stale']
    resolved = send(client, session, 'director_resolve', dict(proposal_id=plan['id']))
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()['room']['party'][0]['spell_slots']['1']['current'] == before['party'][0]['spell_slots']['1']['current'] - 1


def test_expired_plan_rejects_without_repeating_any_cost(table):
    app, client, session = table
    before = enter_battle(client, session)
    response = send(client, session, 'capability_propose', dict(action_id='attack'))
    proposal = response.json()['room']['director_proposals'][0]
    state = app.state.store.get(before['id'])
    previous = state['version']
    state['director']['proposals'][session['member_id']]['plan']['expires_at'] = 0
    state['version'] += 1
    app.state.store.save(state, previous)
    frozen = deepcopy(app.state.store.get(state['id']))
    rejected = send(client, session, 'director_resolve', dict(proposal_id=proposal['id']))
    assert rejected.status_code == 422
    assert app.state.store.get(state['id']) == frozen


def test_client_cannot_invent_abilities_targets_or_costs(table):
    app, client, session = table
    enter_battle(client, session)
    before = deepcopy(app.state.store.get(session['room']['id']))
    for payload in [dict(action_id='cast:wish'), dict(action_id='attack', target_id='outside'),
                    dict(action_id='attack', damage=999), dict(action_id='attack', resource_amount=True),
                    dict(action_id='cast:magic-missile', slot_level=True)]:
        assert send(client, session, 'capability_propose', payload).status_code == 422
        assert app.state.store.get(before['id']) == before


def test_persisted_plan_backup_and_old_binary_guard(table, tmp_path, monkeypatch):
    from pathlib import Path
    from backend import maintenance
    from backend.store import Store
    app, client, session = table
    before = enter_battle(client, session)
    response = send(client, session, 'capability_propose', dict(action_id='cast:magic-missile'))
    assert response.status_code == 200, response.text
    saved = app.state.store.get(before['id'])
    archive = tmp_path / 'pending-plan.zip'
    maintenance.backup_database(app.state.store.path, archive)
    recovered = tmp_path / 'recovered'
    maintenance.restore_backup(archive, recovered)
    restored = Store(str(recovered / 'database.sqlite3'))
    assert restored.get(saved['id']) == saved
    frozen = Path(restored.path).read_bytes()
    monkeypatch.setattr(maintenance, 'SCHEMA_VERSION', 10)
    with pytest.raises(ValueError, match='newer server'):
        Store(restored.path)
    assert Path(restored.path).read_bytes() == frozen
