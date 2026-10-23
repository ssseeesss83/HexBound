"""Starting-level choices are authoritative, atomic and account-bound."""
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend import characters


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv('HEXBOUND_ALLOW_GUESTS', raising=False)
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    monkeypatch.delenv('LLM_MODEL', raising=False)
    return create_app(str(tmp_path / 'setup.sqlite3'))


def account(app, name='setup_player'):
    client = TestClient(app)
    response = client.post('/api/auth/register', json={'username': name, 'password': 'Reviewed-Choices-123!', 'display_name': name})
    assert response.status_code == 201, response.text
    client.headers['X-CSRF-Token'] = client.get('/api/auth/me').json()['csrf_token']
    return client


def build(level=3):
    return {'class_id': 'fighter', 'name': '银发旅人',
            'abilities': {'str': 17, 'dex': 12, 'con': 16, 'int': 9, 'wis': 11, 'cha': 10},
            'profile': {'appearance': '银发、绿眼', 'background': '守桥人', 'talents': ['善于雕刻']},
            'choices': {'skills': ['athletics', 'perception']},
            'levels': ([{'choices': {}}, {'choices': {'subclass_id': 'champion'}}] if level == 3 else [])}


def room(client, **extra):
    response = client.post('/api/rooms', json={'player_name': '旅人', 'interaction_mode': 'freeform', **extra})
    assert response.status_code == 201, response.text
    return response.json()


def command(client, rid, kind, payload=None, command_id=None, version=None):
    current = client.get(f'/api/rooms/{rid}').json()
    return client.post(f'/api/rooms/{rid}/commands', json={
        'command_id': command_id or uuid.uuid4().hex,
        'expected_version': current['version'] if version is None else version,
        'type': kind, 'payload': payload or {}})


def test_default_three_requires_review_and_persists_custom_build(app):
    with account(app) as client:
        session = room(client)
        rid = session['room']['id']
        assert session['room']['starting_level'] == 3
        assert session['room']['party'][0]['build_ready'] is False
        assert command(client, rid, 'start').status_code == 409
        response = command(client, rid, 'configure_character', {'build': build()})
        assert response.status_code == 200, response.text
        party = response.json()['room']['party'][0]
        assert party['build_ready'] and party['level'] == 3 and party['abilities']['str'] == 17
        hero = client.get('/api/my/characters').json()['items'][0]
        assert hero['character']['profile']['appearance'] == '银发、绿眼'
        assert hero['character']['level'] == 3
        assert command(client, rid, 'start').status_code == 200
        assert command(client, rid, 'configure_character', {'build': build()}).status_code == 409


def test_incomplete_and_forged_builds_do_not_mutate_room_or_hero(app):
    with account(app) as client:
        session = room(client)
        rid = session['room']['id']
        before = app.state.store.get(rid)
        hero_before = client.get('/api/my/characters').json()
        for malformed in (build(1), {**build(), 'xp': 999999}, {**build(), 'levels': [{'choices': {}}, {'choices': {}}]}):
            response = command(client, rid, 'configure_character', {'build': malformed})
            assert response.status_code == 422, response.text
            assert app.state.store.get(rid) == before
            assert client.get('/api/my/characters').json() == hero_before


def test_existing_hero_prepares_one_level_at_a_time_without_respec(app):
    with account(app) as client:
        hero = client.post('/api/my/characters', json={'class_id': 'fighter', 'name': 'Veteran'}).json()
        session = room(client, hero_id=hero['id'])
        rid = session['room']['id']
        assert not session['room']['party'][0]['can_rebuild']
        assert command(client, rid, 'configure_character', {'build': build()}).status_code == 409
        response = command(client, rid, 'prepare_level_up', {'choices': {}})
        assert response.status_code == 200, response.text
        assert response.json()['room']['party'][0]['level'] == 2
        assert not response.json()['room']['party'][0]['build_ready']
        assert command(client, rid, 'prepare_level_up', {'choices': {}}).status_code == 422
        response = command(client, rid, 'prepare_level_up', {'choices': {'subclass_id': 'champion'}})
        assert response.status_code == 200, response.text
        assert response.json()['room']['party'][0]['build_ready']
        assert command(client, rid, 'prepare_level_up', {'choices': {}}).status_code == 409
        persisted = client.get(f"/api/my/characters/{hero['id']}").json()['character']
        assert persisted['level'] == 3 and persisted['xp'] == characters.XP_THRESHOLDS[2]
        assert persisted['abilities'] == hero['character']['abilities']


def test_higher_level_hero_rejected_without_binding_or_creating_room(app):
    with account(app) as client:
        response = client.post('/api/my/characters', json={'build': build(), 'starting_level': 3})
        assert response.status_code == 201, response.text
        hero = response.json()
        rejected = client.post('/api/rooms', json={'player_name': 'Veteran', 'hero_id': hero['id'], 'starting_level': 1})
        assert rejected.status_code == 409, rejected.text
        assert client.get(f"/api/my/characters/{hero['id']}").json() == hero
        assert not client.get('/api/my/rooms').json()['items']


def test_every_member_must_finish_and_cannot_edit_another_seat(app):
    with account(app, 'setup_host') as host, account(app, 'setup_guest') as guest:
        session = room(host)
        rid = session['room']['id']
        joined = guest.post('/api/rooms/join', json={'invite_code': session['invite_code'], 'player_name': 'Guest'}).json()
        assert joined['room']['starting_level'] == 3
        assert command(host, rid, 'configure_character', {'build': build()}).status_code == 200
        assert command(host, rid, 'start').status_code == 409
        assert command(guest, rid, 'configure_character', {'build': build(), 'member_id': session['member_id']}).status_code == 422
        assert command(guest, rid, 'configure_character', {'build': build()}).status_code == 200
        assert command(host, rid, 'start').status_code == 200


def test_preview_ai_require_auth_and_do_not_create_or_change_characters(app):
    draft = {'build': {'class_id': 'fighter', 'name': 'Draft'}, 'target_level': 3}
    with TestClient(app) as anonymous:
        assert anonymous.post('/api/character-builds/preview', json=draft).status_code == 401
        assert anonymous.post('/api/character-builds/ai', json=draft).status_code == 401
    with account(app) as client:
        before = client.get('/api/my/characters').json()
        preview = client.post('/api/character-builds/preview', json=draft)
        assert preview.status_code == 200 and not preview.json()['ready']
        response = client.post('/api/character-builds/ai', json={**draft, 'prompt': '完善外貌和背景'})
        assert response.status_code == 200, response.text
        assert response.json()['source'] == 'local'
        assert response.json()['build'].get('levels', []) == []
        assert client.get('/api/my/characters').json() == before
        csrf = client.headers.pop('X-CSRF-Token')
        assert client.post('/api/character-builds/ai', json=draft).status_code == 403
        client.headers['X-CSRF-Token'] = csrf


def test_configure_retry_is_idempotent_and_stale_edit_rejected(app):
    with account(app) as client:
        session = room(client)
        rid = session['room']['id']
        cid = uuid.uuid4().hex
        first = command(client, rid, 'configure_character', {'build': build()}, command_id=cid, version=0)
        assert first.status_code == 200, first.text
        repeated = command(client, rid, 'configure_character', {'build': build()}, command_id=cid, version=0)
        assert repeated.status_code == 200 and repeated.json()['replayed']
        assert command(client, rid, 'configure_character', {'build': build()}, version=0).status_code == 409
        assert len([event for event in app.state.store.get(rid)['events'] if event['kind'] == 'character']) == 1


def test_tenth_level_start_replays_all_nine_upgrade_steps(app):
    from backend.character_builds import build_character
    payload = build(1)
    for target in range(2, 11):
        character = build_character(payload, target - 1)
        choices = {}
        if target == 3:
            choices['subclass_id'] = 'champion'
        if target in (4, 6, 8):
            remaining = 2
            choices['asi'] = {}
            for ability in characters.ABILITIES:
                points = min(remaining, 20 - character['abilities'][ability])
                if points:
                    choices['asi'][ability] = points
                    remaining -= points
                if not remaining:
                    break
        payload['levels'].append({'choices': choices})
    with account(app) as client:
        session = room(client, starting_level=10)
        rid = session['room']['id']
        assert command(client, rid, 'configure_character', {'build': build()}).status_code == 422
        response = command(client, rid, 'configure_character', {'build': payload})
        assert response.status_code == 200, response.text
        member = app.state.store.get(rid)['members'][0]
        assert member['character']['level'] == 10
        assert len(member['character']['growth_history']) == 9
        assert member['build_ready']
        assert command(client, rid, 'start').status_code == 200
