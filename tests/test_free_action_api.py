"""Free-action API acceptance with stubbed model JSON, no external LLM calls."""
import json
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from backend.dm import DM
from backend import rules
from test_core_integration import env, cmd, room, seed, settle


@pytest.fixture
def play(env, monkeypatch):
    a, b, store, path = env
    session = room(a).json()
    rid = session['room']['id']
    joined = b.post('/api/rooms/join', json={'invite_code': session['invite_code'], 'player_name': 'Other', 'character_id': 'fighter'})
    assert joined.status_code == 200, joined.text
    assert cmd(a, rid, 'start')[0].status_code == 200
    def setup(s):
        s['scene']['objects'] = [{'id': 'crate', 'name': '木箱', 'tags': ['flammable', 'movable', 'interactable', 'searchable'], 'hp': 20}, {'id': 'torch', 'name': '燃烧的火把', 'tags': ['fire'], 'hp': 100}]
    seed(store, rid, setup)
    monkeypatch.setattr(DM, '__getattribute__', lambda self, key: True if key == 'configured' else object.__getattribute__(self, key))
    return a, b, store, path, rid


def model(monkeypatch, action='interact', **extra):
    data = {'kind': 'free_action', 'label': '尝试操作', 'text': '准备尝试操作场景中的对象。', 'action_id': action, **extra}
    async def complete(self, *args, **kwargs):
        return json.dumps(data)
    monkeypatch.setattr(DM, '_complete', complete)


def propose(a, rid):
    response, _ = cmd(a, rid, 'director_propose', {'text': '我尝试指定行动'})
    assert response.status_code == 200, response.text
    proposals = response.json()['room']['director_proposals']
    assert len(proposals) == 1
    return proposals[0]


def combat(store, rid):
    def setup(s):
        rules.start_combat(s)
        c = s['combat']
        c['turn_actor_id'] = s['members'][0]['id']
        c['index'] = c['order'].index(c['turn_actor_id'])
        c['enemy']['hp'] = c['enemy']['max_hp'] = 1000
        c['enemies'] = [c['enemy']]
    seed(store, rid, setup)


def test_model_proposal_confirm_and_receipt_share_combat_budget(play, monkeypatch):
    a, b, store, path, rid = play
    combat(store, rid)
    model(monkeypatch, object_id='crate')
    before = store.get(rid)
    proposal = propose(a, rid)
    assert proposal['kind'] == 'free_action' and proposal['source'] == 'llm'
    assert store.get(rid)['combat']['action_used'] == before['combat']['action_used']
    response, body = cmd(a, rid, 'director_resolve', {'proposal_id': proposal['id']})
    assert response.status_code == 200, response.text
    after = store.get(rid)
    assert after['combat']['action_used']
    assert after['environment'][after['scene_id']]['objects']['crate']['activated']
    assert cmd(a, rid, 'director_resolve', body=body)[0].json()['replayed']
    assert store.get(rid) == after
    denied, _ = cmd(a, rid, 'action', {'action_id': 'attack', 'target_id': 'enemy'})
    assert denied.status_code == 422
    assert store.get(rid) == after


def test_other_player_cannot_resolve_or_cancel_and_owner_cancel_costs_nothing(play, monkeypatch):
    a, b, store, path, rid = play
    model(monkeypatch, object_id='crate')
    proposal = propose(a, rid)
    before = store.get(rid)
    for action in ('director_resolve', 'director_cancel'):
        assert cmd(b, rid, action, {'proposal_id': proposal['id']})[0].status_code == 409
    assert store.get(rid) == before
    response, _ = cmd(a, rid, 'director_cancel', {'proposal_id': proposal['id']})
    assert response.status_code == 200
    after = store.get(rid)
    assert after.get('environment') == before.get('environment')
    assert after['members'] == before['members']
    assert cmd(a, rid, 'director_resolve', {'proposal_id': proposal['id']})[0].status_code == 409


def test_stale_proposal_after_skill_budget_spent_is_rejected(play, monkeypatch):
    a, b, store, path, rid = play
    combat(store, rid)
    model(monkeypatch, object_id='crate')
    proposal = propose(a, rid)
    # A trusted concurrent state change must invalidate this stored proposal.
    # Selecting another own action now replaces it instead of executing directly.
    seed(store, rid, lambda state: state['combat'].update(action_used=True))
    before = store.get(rid)
    response, _ = cmd(a, rid, 'director_resolve', {'proposal_id': proposal['id']})
    assert response.status_code == 422
    assert store.get(rid) == before
    assert a.get(f'/api/rooms/{rid}').json()['director_proposals'][0]['stale']


def test_environment_persists_after_restart_without_reapplying_effect(play, monkeypatch):
    from backend.app import create_app
    a, b, store, path, rid = play
    model(monkeypatch, action='ignite', object_id='crate')
    proposal = propose(a, rid)
    response, body = cmd(a, rid, 'director_resolve', {'proposal_id': proposal['id']})
    assert response.status_code == 200, response.text
    after = store.get(rid)
    obj = after['environment'][after['scene_id']]['objects']['crate']
    assert obj['burning'] and obj['hp'] < 20
    with TestClient(create_app(path)) as reopened:
        reopened.cookies.update(a.cookies)
        reopened.headers['X-CSRF-Token'] = reopened.get('/api/auth/me').json()['csrf_token']
        snapshot = reopened.get(f'/api/rooms/{rid}').json()
        assert next(x for x in snapshot['free_actions']['objects'] if x['id'] == 'crate')['hp'] == obj['hp']
        assert cmd(reopened, rid, 'director_resolve', body=body)[0].json()['replayed']
    assert store.get(rid)['environment'] == after['environment']


@pytest.mark.parametrize('extra', [{'dc': 1}, {'damage': 999}, {'xp': 999}, {'cost': 'free'}])
def test_model_numeric_injection_never_enters_executable_proposal(play, monkeypatch, extra):
    a, b, store, path, rid = play
    model(monkeypatch, object_id='crate', **extra)
    before = deepcopy(store.get(rid))
    proposal = propose(a, rid)
    assert proposal['source'] == 'fallback'
    assert proposal['kind'] != 'free_action'  # Unrecognized neutral intent safely degrades.
    after = store.get(rid)
    assert after['members'] == before['members'] and after.get('environment') == before.get('environment')


def test_client_cannot_edit_confirmed_effect_or_request_after_budget_exhaustion(play, monkeypatch):
    a, b, store, path, rid = play
    combat(store, rid)
    model(monkeypatch, object_id='crate')
    proposal = propose(a, rid)
    before = store.get(rid)
    response, _ = cmd(a, rid, 'director_resolve', {'proposal_id': proposal['id'], 'damage': 999})
    assert response.status_code == 422 and store.get(rid) == before
    assert settle(a, rid, {'action_id': 'dodge'})[0].status_code == 200
    fallback = propose(a, rid)
    assert fallback['source'] == 'fallback' and fallback['kind'] != 'free_action'
    assert store.get(rid)['combat']['action_used']


def test_out_of_turn_illegal_free_action_falls_back_to_dialogue_without_effect(play, monkeypatch):
    a, b, store, path, rid = play
    combat(store, rid)
    model(monkeypatch, object_id='crate')
    before = store.get(rid)
    proposal = propose(b, rid)
    assert proposal['kind'] == 'dialogue' and proposal['source'] == 'fallback'
    response, _ = cmd(b, rid, 'director_resolve', {'proposal_id': proposal['id']})
    assert response.status_code == 200, response.text
    after = store.get(rid)
    assert after['combat'] == before['combat'] and after['members'] == before['members']
    assert after.get('environment') == before.get('environment')
