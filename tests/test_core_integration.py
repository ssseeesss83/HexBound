"""Independent API integration checks; trusted fixtures seed progress, never client XP."""
import uuid
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.store import Store


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv('HEXBOUND_ALLOW_GUESTS', raising=False)
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    monkeypatch.delenv('LLM_MODEL', raising=False)
    path = str(tmp_path / 'core.sqlite3')
    app = create_app(path)
    with TestClient(app) as a, TestClient(app) as b:
        for client, name in ((a, 'core_owner'), (b, 'core_other')):
            r = client.post('/api/auth/register', json={'username': name, 'password': 'Independent-Review-123!', 'display_name': name})
            assert r.status_code == 201, r.text
            client.headers['X-CSRF-Token'] = client.get('/api/auth/me').json()['csrf_token']
        yield a, b, Store(path), path


def hero(c):
    r = c.post('/api/my/characters', json={'class_id': 'fighter', 'name': 'Reviewer'})
    assert r.status_code == 201, r.text
    return r.json()


def room(c, hid=None):
    data = {'starting_level': 1, 'player_name': 'Reviewer', 'character_id': 'fighter', 'interaction_mode': 'freeform'}
    if hid:
        data['hero_id'] = hid
    return c.post('/api/rooms', json=data)


def cmd(c, rid, kind, payload=None, body=None):
    body = body or {'command_id': uuid.uuid4().hex, 'expected_version': c.get(f'/api/rooms/{rid}').json()['version'], 'type': kind, 'payload': payload or {}}
    return c.post(f'/api/rooms/{rid}/commands', json=body), body


def settle(c, rid, payload):
    """Exercise selection followed by explicit confirmation; return settlement receipt."""
    selected, _ = cmd(c, rid, 'action', payload)
    assert selected.status_code == 200, selected.text
    proposal = selected.json()['room']['director_proposals'][0]
    return cmd(c, rid, 'director_resolve', {'proposal_id': proposal['id']})


def seed(store, rid, change):
    state = store.get(rid)
    version = state['version']
    change(state)
    state['version'] += 1
    store.save(state, version)
    return state


def test_rules_activation_keeps_old_room_and_joiners_on_original_snapshot(env, tmp_path, monkeypatch):
    import hashlib
    import json
    from backend import rules_packages as packages
    a, b, store, _ = env
    original = room(a).json()
    rid = original['room']['id']
    candidate = packages.build_package()
    candidate['records']['classes']['fighter']['hit_die'] = 12
    candidate.pop('digest')
    candidate['digest'] = hashlib.sha256(packages.encode(candidate).encode()).hexdigest()
    approval = tmp_path / 'test-only-signoff.json'
    approval.write_text(json.dumps({'status': 'approved', 'package_digest': candidate['digest'],
                                   'source_document_sha256': candidate['source_manifest']['original']['sha256']}), encoding='utf-8')
    monkeypatch.setattr(packages, 'SIGNOFF_PATH', approval)
    packages.install_package(store, candidate)
    joined = b.post('/api/rooms/join', json={'invite_code': original['invite_code'], 'player_name': 'Other', 'character_id': 'fighter'})
    assert joined.status_code == 200, joined.text
    old_state = store.get(rid)
    assert old_state['rules_package_version'] == packages.LEGACY_PACKAGE
    assert all(m['character']['rules_package_version'] == packages.LEGACY_PACKAGE for m in old_state['members'])
    assert all(m['character']['hit_dice']['die'] == 10 for m in old_state['members'])
    assert a.get('/api/rooms/' + rid).json()['rules_package_version'] == packages.LEGACY_PACKAGE
    fresh = room(a)
    assert fresh.status_code == 201, fresh.text
    new_state = store.get(fresh.json()['room']['id'])
    assert new_state['rules_package_version'] == packages.PACKAGE_VERSION
    assert new_state['members'][0]['character']['hit_dice']['die'] == 12


def test_event_audiences_match_snapshot_websocket_history_and_model_memory(env):
    from backend import session_scope
    a, b, store, _ = env
    created = room(a).json()
    rid = created['room']['id']
    joined = b.post('/api/rooms/join', json={'invite_code': created['invite_code'], 'player_name': 'Other'}).json()
    other_id = joined['member_id']
    def secret(state):
        item = {'id': len(state['events']) + 1, 'kind': 'dm', 'text': 'PRIVATE-KNOWLEDGE'}
        session_scope.stamp_event(state, item, audience={other_id})
        state['events'].append(item)
    seed(store, rid, secret)
    for path in ('', '/events'):
        assert 'PRIVATE-KNOWLEDGE' not in a.get('/api/rooms/' + rid + path).text
        assert 'PRIVATE-KNOWLEDGE' in b.get('/api/rooms/' + rid + path).text
        assert '_audience' not in b.get('/api/rooms/' + rid + path).text
    host_page = a.get('/api/rooms/' + rid + '/events').json()
    assert b.get('/api/rooms/' + rid + '/events', params={'cursor': host_page['cursor']}).status_code == 409
    with a.websocket_connect('/api/rooms/' + rid + '/ws') as ws:
        ws.send_json({})
        assert 'PRIVATE-KNOWLEDGE' not in str(ws.receive_json())
    state = store.get(rid)
    assert 'PRIVATE-KNOWLEDGE' not in str(session_scope.common_memory(state, {m['id'] for m in state['members']}))


def test_vault_owner_and_server_derived_fields(env):
    a, b, store, _ = env
    h = hero(a)
    assert b.get('/api/my/characters/' + h['id']).status_code == 404
    assert b.patch('/api/my/characters/' + h['id'], json={'operation': 'level_up', 'expected_version': 1, 'choices': {}}).status_code == 404
    assert room(b, h['id']).status_code == 409
    forged = a.post('/api/my/characters', json={'class_id': 'fighter', 'name': 'Forged', 'choices': {'xp': 999999, 'level': 20}})
    assert forged.status_code == 422
    insufficient = a.patch('/api/my/characters/' + h['id'], json={'operation': 'level_up', 'expected_version': 1, 'choices': {}})
    assert insufficient.status_code == 422
    assert a.get('/api/my/characters/' + h['id']).json()['character']['level'] == 1


def test_single_active_room_finished_reuse_and_old_room_write_rejected(env):
    a, _, store, _ = env
    h = hero(a)
    first = room(a, h['id'])
    assert first.status_code == 201, first.text
    rid = first.json()['room']['id']
    assert room(a, h['id']).status_code == 409
    seed(store, rid, lambda s: s.update(status='finished', completed=True))
    second = room(a, h['id'])
    assert second.status_code == 201, second.text
    for kind, payload in [('level_up', {'choices': {}}), ('rest', {'kind': 'short', 'hit_dice': 0}), ('equip_skills', {'skill_ids': []})]:
        response, _ = cmd(a, rid, kind, payload)
        assert response.status_code == 409, response.text
    view = a.get('/api/my/characters/' + h['id']).json()
    assert view['active_room_id'] == second.json()['room']['id']


def test_room_upgrade_receipt_and_vault_sync(env):
    a, _, store, _ = env
    session = room(a).json()
    rid = session['room']['id']
    assert cmd(a, rid, 'start')[0].status_code == 200
    seed(store, rid, lambda s: s['members'][0]['character'].update(xp=300))
    result, body = cmd(a, rid, 'level_up', {'choices': {}})
    assert result.status_code == 200, result.text
    replay, _ = cmd(a, rid, 'level_up', body=body)
    assert replay.status_code == 200 and replay.json()['replayed']
    state = store.get(rid)
    c = state['members'][0]['character']
    assert c['level'] == 2 and len(c['growth_history']) == 1
    hid = state['members'][0]['hero_id']
    assert a.get('/api/my/characters/' + hid).json()['character']['level'] == 2
    assert cmd(a, rid, 'level_up', {'choices': {}})[0].status_code == 422


def test_objective_reward_receipt_and_restart(env):
    a, _, store, path = env
    session = room(a).json()
    rid = session['room']['id']
    assert cmd(a, rid, 'start')[0].status_code == 200
    state = store.get(rid)
    # Trusted fixture makes the existing deterministic scene ready to advance.
    seed(store, rid, lambda s: s['flags'].update(scene_resolved=True))
    response, body = settle(a, rid, {'action_id': 'advance'})
    assert response.status_code == 200, response.text
    after = store.get(rid)
    assert after['members'][0]['character']['xp'] == 100
    replay, _ = cmd(a, rid, 'action', body=body)
    assert replay.status_code == 200 and replay.json()['replayed']
    assert store.get(rid)['reward_ledger'] == after['reward_ledger']
    with TestClient(create_app(path)) as resumed:
        resumed.cookies.update(a.cookies)
        resumed.headers['X-CSRF-Token'] = resumed.get('/api/auth/me').json()['csrf_token']
        again, _ = cmd(resumed, rid, 'action', body=body)
        assert again.status_code == 200 and again.json()['replayed']
    assert store.get(rid)['members'][0]['character']['xp'] == 100


def test_rest_receipt_spends_hit_die_once_and_long_rest_cooldown(env):
    a, _, store, _ = env
    rid = room(a).json()['room']['id']
    seed(store, rid, lambda s: s['members'][0]['character'].update(hp=1))
    response, body = cmd(a, rid, 'rest', {'kind': 'short', 'hit_dice': 1})
    assert response.status_code == 200, response.text
    after = store.get(rid)
    replay, _ = cmd(a, rid, 'rest', body=body)
    assert replay.status_code == 200 and replay.json()['replayed']
    assert store.get(rid)['members'][0]['character'] == after['members'][0]['character']
    assert after['members'][0]['character']['hit_dice']['current'] == 0
    assert cmd(a, rid, 'rest', {'kind': 'short', 'hit_dice': 1})[0].status_code == 422
    assert cmd(a, rid, 'rest', {'kind': 'long'})[0].status_code == 200
    assert cmd(a, rid, 'rest', {'kind': 'long'})[0].status_code == 422


def test_unowned_spell_and_custom_card_do_not_mutate(env):
    a, _, store, _ = env
    rid = room(a).json()['room']['id']
    assert cmd(a, rid, 'start')[0].status_code == 200
    before = store.get(rid)
    for kind, payload in [('equip_skills', {'skill_ids': ['not-in-snapshot']}), ('action', {'action_id': 'cast:magic-missile', 'target_id': 'enemy'}), ('action', {'action_id': 'skill:not-owned', 'target_id': 'enemy'})]:
        result, _ = cmd(a, rid, kind, payload)
        assert result.status_code == 422, result.text
        assert store.get(rid) == before


def test_long_rest_cooldown_survives_adventure_reuse(env):
    a, _, store, _ = env
    h = hero(a)
    rid = room(a, h['id']).json()['room']['id']
    assert cmd(a, rid, 'rest', {'kind': 'long'})[0].status_code == 200
    seed(store, rid, lambda s: s.update(status='finished', completed=True))
    result = room(a, h['id'])
    assert result.status_code == 201, result.text
    next_id = result.json()['room']['id']
    before = store.get(next_id)
    denied, _ = cmd(a, next_id, 'rest', {'kind': 'long'})
    assert denied.status_code == 422, denied.text
    assert store.get(next_id) == before


def test_battle_reward_and_repeated_victory_are_idempotent(env, monkeypatch):
    from backend import rules
    a, _, store, _ = env
    rid = room(a).json()['room']['id']
    assert cmd(a, rid, 'start')[0].status_code == 200
    def prepare(s):
        rules.start_combat(s)
        combat = s['combat']
        combat['turn_actor_id'] = s['members'][0]['id']
        combat['index'] = combat['order'].index(combat['turn_actor_id'])
        combat['enemy']['hp'] = 1
        combat['enemy']['xp'] = 300
        combat['enemy']['ac'] = 1
        combat['enemies'] = [combat['enemy']]
    seed(store, rid, prepare)
    monkeypatch.setattr(rules.secrets, 'randbelow', lambda n: n - 1)
    result, body = settle(a, rid, {'action_id': 'attack', 'target_id': 'enemy'})
    assert result.status_code == 200, result.text
    after = store.get(rid)
    assert not after['combat']['active']
    assert any(key.startswith('battle:') for key in after['reward_ledger'])
    gained = after['members'][0]['character']['xp']
    assert gained >= 300
    replay, _ = cmd(a, rid, 'action', body=body)
    assert replay.status_code == 200 and replay.json()['replayed']
    assert cmd(a, rid, 'action', {'action_id': 'attack', 'target_id': 'enemy'})[0].status_code == 422
    assert store.get(rid)['members'][0]['character']['xp'] == gained
