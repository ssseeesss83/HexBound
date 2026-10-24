"""Seeded v2 fixtures exercise real commands while publishing remains locked."""
from copy import deepcopy
import uuid

import pytest

from backend import rules, story_runtime, world_combat
from test_capability_proposals_api import table, send
from test_story_challenges import authored


def seed(table):
    app,client,session = table
    assert send(client,session,'start').status_code==200
    state = app.state.store.get(session['room']['id'])
    previous = state['version']
    book = authored()
    state['campaign'] = dict(package=dict(scenario=book,skills={},monsters={}),node_id='dock',
                             visited=['dock'],spent={},cleared=[],**story_runtime.initialize(book))
    world_combat.enter_place(state,'dock')
    state.update(scene=deepcopy(book['nodes'][0]),scene_id='dock',director={},combat=None)
    state['version'] += 1
    app.state.store.save(state,previous)
    return app,client,session


def test_native_commands_preview_cancel_confirm_replay_and_private_projection(table,monkeypatch):
    app,client,session = seed(table)
    rid = session['room']['id']
    before = deepcopy(app.state.store.get(rid)['campaign']['story_state'])
    original = rules.roll_dice
    with monkeypatch.context() as guard:
        guard.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('Preview rolled'))
        response = send(client,session,'capability_propose',dict(action_id='story-check:find-lens',skill_id='perception'))
        assert response.status_code==200,response.text
        proposal = response.json()['room']['director_proposals'][0]
        assert not {'story_plan','fingerprint','read_set'} & proposal['plan'].keys()
        assert app.state.store.get(rid)['campaign']['story_state']==before
        assert send(client,session,'director_cancel',dict(proposal_id=proposal['id'])).status_code==200
    response = send(client,session,'director_propose',dict(text='我尝试辨认路线',skill_id='perception'))
    assert response.status_code==200,response.text
    proposal = response.json()['room']['director_proposals'][0]
    assert proposal['kind']=='capability' and proposal['plan']['options']=={'skill_id':'perception'}
    rolls = []
    def counted(*args,**kwargs):
        rolls.append(args[0])
        return original(*args,**kwargs)
    monkeypatch.setattr(rules,'roll_dice',counted)
    command = uuid.uuid4().hex
    response = send(client,session,'director_resolve',dict(proposal_id=proposal['id']),command)
    assert response.status_code==200,response.text
    assert rolls==['1d20']
    saved = app.state.store.get(rid)
    assert len(saved['attempt_ledger'])==1
    assert proposal['id'] in saved['campaign']['story_state']['effect_receipts']
    assert not response.json()['room']['director_proposals']
    replay = send(client,session,'director_resolve',dict(proposal_id=proposal['id']),command)
    assert replay.status_code==200 and replay.json()['replayed'] and rolls==['1d20']
    assert send(client,session,'capability_propose',dict(action_id='story-check:find-lens')).status_code==422
    assert app.state.store.get(rid)['campaign']['story_state']==saved['campaign']['story_state']
    public = client.get('/api/rooms/'+rid,headers=dict(Authorization='Bearer '+session['token'])).text
    assert 'story_state' not in public and 'effect_receipts' not in public and 'attempt_ledger' not in public


def test_changed_facts_disable_http_plan_without_cost_or_roll(table,monkeypatch):
    app,client,session = seed(table)
    response = send(client,session,'capability_propose',dict(action_id='story-check:find-lens'))
    assert response.status_code==200,response.text
    proposal = response.json()['room']['director_proposals'][0]
    state = app.state.store.get(session['room']['id'])
    previous = state['version']
    state['campaign']['story_state']['facts']['weather'].update(value=1,revision=1)
    state['version'] += 1
    app.state.store.save(state,previous)
    before = deepcopy(app.state.store.get(state['id']))
    monkeypatch.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('Stale confirmation rolled'))
    response = send(client,session,'director_resolve',dict(proposal_id=proposal['id']))
    assert response.status_code==422,response.text
    assert app.state.store.get(state['id'])==before
