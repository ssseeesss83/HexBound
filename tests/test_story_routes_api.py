"""Real native-route commands, public waits and replay under durable storage."""
from copy import deepcopy
import uuid
import pytest
from backend import rules, story_runtime
from test_capability_proposals_api import table, send
from test_native_story_api import seed
from test_native_story_checks import extend_graph


def propose(client,session,action):
    response = send(client,session,'capability_propose',dict(action_id=action))
    assert response.status_code==200,response.text
    return response.json()['room']['director_proposals'][0]


def test_http_wait_restart_ready_review_entry_and_receipt_replay(table,monkeypatch):
    app,client,session = seed(table)
    rid = session['room']['id']
    headers = dict(Authorization='Bearer '+session['token'])
    monkeypatch.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('Route rolled'))
    selected = propose(client,session,'story-route:follow-courier')
    assert 'route_plan' not in selected['plan']
    command = uuid.uuid4().hex
    response = send(client,session,'director_resolve',dict(proposal_id=selected['id']),command)
    assert response.status_code==200,response.text
    assert response.json()['room']['route_wait']==dict(status='unavailable')
    before = app.state.store.get(rid)
    assert before['campaign']['node_id']=='dock'
    assert app.state.generation_jobs.get(before['pending_transition']['generation_job_id'])['status']=='queued'
    replay = send(client,session,'director_resolve',dict(proposal_id=selected['id']),command)
    assert replay.status_code==200 and replay.json()['replayed']
    assert app.state.store.get(rid)==before
    # Opening another Store simulates a new reader after restart, not a new room.
    from backend.store import Store
    restored = Store(app.state.store.path).get(rid)
    assert restored['pending_transition']==before['pending_transition']
    branch = extend_graph(restored)
    previous = restored['version']
    restored['version'] += 1
    app.state.store.save(restored,previous)
    frame = client.get('/api/rooms/'+rid,headers=headers)
    assert frame.status_code==200,frame.text
    assert frame.json()['route_wait']==dict(status='ready_for_review')
    assert frame.json()['scene']['id']=='dock'
    for secret in ['continuation','read_set','frontier_resolutions','transition_receipts','runtime_graph','route_plan']:
        assert secret not in frame.text
    fresh = propose(client,session,'story-route:follow-courier')
    command = uuid.uuid4().hex
    response = send(client,session,'director_resolve',dict(proposal_id=fresh['id']),command)
    assert response.status_code==200,response.text
    assert response.json()['room']['scene']['id']==branch['id']
    assert response.json()['room']['route_wait'] is None
    settled = app.state.store.get(rid)
    assert settled['campaign']['visited']==['dock',branch['id']]
    assert settled['members']==before['members']
    assert settled['progression']==before['progression']
    assert settled.get('reward_ledger',[])==before.get('reward_ledger',[])
    assert all(row['status']=='entered' for row in settled['campaign']['transition_receipts'].values())
    replay = send(client,session,'director_resolve',dict(proposal_id=fresh['id']),command)
    assert replay.status_code==200 and replay.json()['replayed']
    assert app.state.store.get(rid)==settled


def test_http_wait_cancel_preserves_checks_and_world(table,monkeypatch):
    app,client,session = seed(table)
    rid = session['room']['id']
    monkeypatch.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('Wait/cancel rolled'))
    selected = propose(client,session,'story-route:follow-courier')
    assert send(client,session,'director_resolve',dict(proposal_id=selected['id'])).status_code==200
    before = deepcopy(app.state.store.get(rid))
    check = propose(client,session,'story-check:find-lens')
    assert not check['stale']
    assert send(client,session,'director_cancel',dict(proposal_id=check['id'])).status_code==200
    cancellation = propose(client,session,'story-cancel')
    response = send(client,session,'director_resolve',dict(proposal_id=cancellation['id']))
    assert response.status_code==200,response.text
    assert response.json()['room']['route_wait'] is None
    after = app.state.store.get(rid)
    assert after['campaign']['node_id']=='dock' and after['campaign']['visited']==['dock']
    assert after['campaign']['story_state']==before['campaign']['story_state']
    assert after['world_entities']==before['world_entities']
    assert after['members']==before['members']
    assert after['campaign']['transition_receipts'][selected['id']]['status']=='cancelled'


def test_foreign_encounter_http_cancel_is_allowed_but_checks_still_rejected(table,monkeypatch):
    app,client,session = seed(table)
    rid = session['room']['id']
    selected = propose(client,session,'story-route:follow-courier')
    assert send(client,session,'director_resolve',dict(proposal_id=selected['id'])).status_code==200
    state = app.state.store.get(rid)
    previous = state['version']
    sid = state.get('_scene_execution_view','scene-main')
    state['world_places'][state['scene_instances'][sid]['place_id']].update(
        active_encounter_id='foreign',encounter_owner_scene_id='other')
    state['version'] += 1
    app.state.store.save(state,previous)
    before = deepcopy(app.state.store.get(rid))
    monkeypatch.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('Cancellation rolled'))
    assert send(client,session,'capability_propose',dict(action_id='story-check:find-lens')).status_code==409
    cancellation = propose(client,session,'story-cancel')
    response = send(client,session,'director_resolve',dict(proposal_id=cancellation['id']))
    assert response.status_code==200,response.text
    after = app.state.store.get(rid)
    assert not after['pending_transition']
    assert after['world_places']==before['world_places']
    assert after['world_entities']==before['world_entities']
    assert after['members']==before['members']
