"""Players submit opaque saved plan IDs, never writable grants or budgets."""
import json
import sqlite3
from pathlib import Path
import pytest
from backend import generation_jobs,maintenance,scene_storage
from test_capability_proposals_api import table,send
from test_native_story_api import seed
from test_story_routes_api import propose


def exhausted_room(table):
    app,client,session=seed(table)
    selected=propose(client,session,'story-route:follow-courier')
    assert send(client,session,'director_resolve',dict(proposal_id=selected['id'])).status_code==200
    rid=session['room']['id']
    job=app.state.generation_jobs.get(app.state.store.get(rid)['pending_transition']['generation_job_id'])
    job.update(status='terminal_failed',attempts=3,dispatches=dict(generation=3,semantic=0))
    with app.state.store.connect() as db:generation_jobs._save(db,job)
    return app,client,session,job


def paths(session):return '/api/rooms/'+session['room']['id']
def headers(session):return dict(Authorization='Bearer '+session['token'])
def prepare(client,session):
    base=paths(session)
    frame=client.get(base,headers=headers(session)).json()
    scope={key:frame[key] for key in ('scene_instance_id','membership_epoch','action_revision')}
    return client.post(base+'/route-retry/prepare',headers=headers(session),json=dict(expected_scope=scope))


def test_http_saved_plan_confirm_replay_and_no_hidden_payload(table):
    app,client,session,old=exhausted_room(table)
    base=paths(session)
    frame=client.get(base,headers=headers(session)).json()
    assert frame['route_retry_available']
    before=app.state.store.get(frame['id'])
    response=prepare(client,session)
    assert response.status_code==200,response.text
    plan=response.json()
    assert set(plan)=={'plan_id','expires_at','additional_attempts','summary'}
    assert app.state.store.get(frame['id'])==before
    for hidden in ('job_id','authorization','route_plan','read_set','generation_retry_receipts'):
        assert hidden not in response.text
    body=dict(plan_id=plan['plan_id'])
    result=client.post(base+'/route-retry/confirm',headers=headers(session),json=body)
    assert result.status_code==200,result.text
    assert result.json()['route_retry']==dict(plan_id=plan['plan_id'],additional_attempts=1,replayed=False)
    assert not result.json()['room']['route_retry_available']
    saved=app.state.store.get(frame['id'])
    assert saved['members']==before['members'] and saved['campaign']==before['campaign']
    new=app.state.generation_jobs.get(saved['pending_transition']['generation_job_id'])
    assert new['budget']['max_attempts']==1 and new['retry_of']==old['id']
    # Even after the review TTL, a lost successful response replays safely.
    app.state.dm_scheduler.clock=lambda:plan['expires_at']+1
    replay=client.post(base+'/route-retry/confirm',headers=headers(session),json=body)
    assert replay.status_code==200,replay.text
    assert replay.json()['route_retry']['replayed']
    assert app.state.store.get(frame['id'])==saved
    for hidden in ('retry_of','dispatches','authorization','generation_retry_receipts','route_plan'):
        assert hidden not in replay.text


def test_http_rejects_client_plan_budget_unknown_id_and_stale_scope(table):
    app,client,session,_=exhausted_room(table)
    base=paths(session)
    plan=prepare(client,session).json()
    for body in (dict(plan_id=plan['plan_id'],budget={'max_attempts':3}),dict(plan_id=plan['plan_id'],plan={})):
        assert client.post(base+'/route-retry/confirm',headers=headers(session),json=body).status_code==422
    assert client.post(base+'/route-retry/confirm',headers=headers(session),json=dict(plan_id='f'*32)).status_code==409
    state=app.state.store.get(session['room']['id']);version=state['version']
    state['member_contexts'][session['member_id']]['epoch']+=1
    state['version']+=1;app.state.store.save(state,version)
    assert client.post(base+'/route-retry/confirm',headers=headers(session),json=dict(plan_id=plan['plan_id'])).status_code==409


def test_saved_reviews_are_bounded_and_expired_unconfirmed_plans_are_pruned(table):
    app,client,session,_=exhausted_room(table)
    for _ in range(4):assert prepare(client,session).status_code==200
    assert prepare(client,session).status_code==409
    with app.state.store.connect() as db:
        db.execute('UPDATE generation_retry_plans SET expires_at=0 WHERE committed=0')
    assert prepare(client,session).status_code==200
    with app.state.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM generation_retry_plans').fetchone()[0]==1


def test_saved_confirmation_marker_failure_rolls_back_entire_confirmation(table):
    app,client,session,_=exhausted_room(table)
    plan=prepare(client,session).json()
    before=app.state.store.get(session['room']['id'])
    with app.state.store.connect() as db:
        db.execute("CREATE TRIGGER broken_review BEFORE UPDATE ON generation_retry_plans WHEN NEW.committed=1 BEGIN SELECT RAISE(ABORT,'temporary failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        client.post(paths(session)+'/route-retry/confirm',headers=headers(session),json=dict(plan_id=plan['plan_id']))
    assert app.state.store.get(session['room']['id'])==before
    with app.state.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM generation_jobs').fetchone()[0]==1
        assert db.execute('SELECT committed FROM generation_retry_plans').fetchone()[0]==0
        db.execute('DROP TRIGGER broken_review')
    result=client.post(paths(session)+'/route-retry/confirm',headers=headers(session),json=dict(plan_id=plan['plan_id']))
    assert result.status_code==200,result.text
    assert not result.json()['route_retry']['replayed']


def test_nonleader_cannot_guess_owners_review_or_open_another_one(table):
    app,client,session,_=exhausted_room(table)
    # Guest seat creation may precede/succeed the adventure; initialize another
    # existing scoped member directly so the test targets authority, not lobby.
    state=app.state.store.get(session['room']['id'])
    original=state['members'][0]
    from copy import deepcopy
    from backend import session_scope
    from backend.store import token_hash
    other=deepcopy(original);other.update(id='other',name='Other')
    state['members'].append(other)
    state['member_contexts']['other']=dict(scene_instance_id='scene-main',epoch=1)
    session_scope.initialize(state)
    with app.state.store.connect() as db:
        db.execute('UPDATE rooms SET state=? WHERE id=?',(json.dumps(scene_storage.pack(state)),state['id']))
        db.execute('INSERT INTO members(id,room_id,token_hash) VALUES(?,?,?)',('other',state['id'],token_hash('other-seat-token-123456789')))
    owner_plan=prepare(client,session)
    assert owner_plan.status_code==200,owner_plan.text
    foreign=dict(session,member_id='other',token='other-seat-token-123456789')
    frame=client.get(paths(session),headers=headers(foreign)).json()
    assert not frame['route_retry_available']
    assert prepare(client,foreign).status_code==409
    response=client.post(paths(session)+'/route-retry/confirm',headers=headers(foreign),json=dict(plan_id=owner_plan.json()['plan_id']))
    assert response.status_code==409
    assert 'job_id' not in response.text and 'route_plan' not in response.text


def test_schema21_saved_plan_restore_and_schema20_refusal(table,tmp_path,monkeypatch):
    from backend.store import Store
    from backend.generation_jobs import GenerationJobs
    from backend import story_requests
    app,client,session,_=exhausted_room(table)
    with app.state.store.connect() as db:db.execute('PRAGMA user_version=20')
    Store(app.state.store.path)
    assert list((Path(app.state.store.path).parent/'backups').glob('pre-schema-21-*.zip'))
    plan=prepare(client,session).json()
    archive=tmp_path/'review.zip'
    maintenance.backup_database(app.state.store.path,archive)
    maintenance.restore_backup(archive,tmp_path/'restored')
    service=GenerationJobs(Store(str(tmp_path/'restored/database.sqlite3')))
    assert not story_requests.confirm_retry_review(service,session['room']['id'],session['member_id'],plan['plan_id'])['replayed']
    monkeypatch.setattr(maintenance,'SCHEMA_VERSION',20)
    with pytest.raises(ValueError,match='newer server'):Store(service.store.path)
