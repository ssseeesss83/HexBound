"""Automatic required generation updates WS readiness without moving players."""
import asyncio
import json
import pytest
from test_capability_proposals_api import table,send
from test_native_story_api import seed
from test_story_generation import Provider


def test_real_commands_bind_generate_and_notify_safe_readiness_without_auto_entry(table):
    app,client,session = seed(table)
    rid=session['room']['id']
    reached,released=asyncio.Event(),asyncio.Event()
    async def block(call):
        if call==1:
            reached.set()
            await released.wait()
    provider=Provider(hook=block)
    app.state.dm_scheduler.provider=provider
    with client.websocket_connect('/api/rooms/'+rid+'/ws') as socket:
        socket.send_json(dict(token=session['token']))
        initial=socket.receive_json()
        assert initial['type']=='snapshot'
        response=send(client,session,'capability_propose',dict(action_id='story-route:follow-courier'))
        assert response.status_code==200,response.text
        proposal=response.json()['room']['director_proposals'][0]
        response=send(client,session,'director_resolve',dict(proposal_id=proposal['id']))
        assert response.status_code==200,response.text
        assert response.json()['room']['route_wait']==dict(status='waiting')
        async def waiting():await asyncio.wait_for(reached.wait(),2)
        client.portal.call(waiting)
        stored=app.state.store.get(rid)
        job_id=stored['pending_transition']['generation_job_id']
        assert app.state.generation_jobs.get(job_id)['status']=='running'
        assert stored['campaign']['node_id']=='dock'
        client.portal.call(released.set)
        ready=None
        for _ in range(20):
            frame=socket.receive_json()
            if frame['type']=='snapshot' and frame['room']['route_wait']==dict(status='ready_for_review'):
                ready=frame['room'];break
        assert ready is not None
        assert ready['scene']['id']=='dock'
        for secret in ['continuation','authorization','runtime_graph','source_metadata','generation_job_id','compiled_digest']:
            assert secret not in json.dumps(ready)
        settled=app.state.store.get(rid)
        assert settled['campaign']['visited']==['dock']
        assert settled['pending_transition']['id']==proposal['id']
        assert app.state.generation_jobs.get(job_id)['status']=='committed'
        with app.state.store.connect() as db:assert db.execute('SELECT COUNT(*) FROM generation_jobs').fetchone()[0]==1
        # Generating a child frontier never recursively dispatches another job.
        assert app.state.dm_scheduler.snapshot()['background_active']==0


def test_failed_post_commit_enqueue_is_recovered_and_command_replay_is_effect_free(table):
    app,client,session=seed(table)
    rid=session['room']['id']
    with app.state.store.connect() as db:
        db.execute("CREATE TRIGGER binding_unavailable BEFORE INSERT ON generation_jobs BEGIN SELECT RAISE(ABORT,'binding unavailable'); END")
    response=send(client,session,'capability_propose',dict(action_id='story-route:follow-courier'))
    proposal=response.json()['room']['director_proposals'][0]
    command='committed-wait-request'
    response=send(client,session,'director_resolve',dict(proposal_id=proposal['id']),command)
    assert response.status_code==200,response.text
    before=app.state.store.get(rid)
    assert before['pending_transition']['id']==proposal['id']
    assert 'generation_job_id' not in before['pending_transition']
    replay=send(client,session,'director_resolve',dict(proposal_id=proposal['id']),command)
    assert replay.status_code==200 and replay.json()['replayed']
    assert app.state.store.get(rid)==before
    with app.state.store.connect() as db:db.execute('DROP TRIGGER binding_unavailable')
    async def recovered():
        async with asyncio.timeout(2):
            while not app.state.store.get(rid)['pending_transition'].get('generation_job_id'):
                await asyncio.sleep(0.01)
    client.portal.call(recovered)
    saved=app.state.store.get(rid)
    assert saved['campaign']['visited']==['dock'] and saved['members']==before['members']
    assert app.state.generation_jobs.get(saved['pending_transition']['generation_job_id'])['attempts']==0
