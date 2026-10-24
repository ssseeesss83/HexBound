"""Real command admission yields background authority before player execution."""
import asyncio
from copy import deepcopy
import json
import time

import pytest

from backend.dm import DM
from test_capability_proposals_api import table, send, enter_battle
from test_native_story_api import seed
from test_story_generation import Provider


class BlockedProvider(Provider):
    def __init__(self,stage):
        self.stage = stage
        self.reached,self.released,self.cancelled = asyncio.Event(),asyncio.Event(),asyncio.Event()
        super().__init__(hook=self.block)
    async def block(self,call):
        if call==self.stage:
            self.reached.set()
            try:await self.released.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                await self.released.wait()


def start_background(table,stage):
    app,client,session = table
    provider = BlockedProvider(stage)
    scheduler = app.state.dm_scheduler
    scheduler.provider = provider
    job = app.state.generation_jobs.enqueue(session['room']['id'],session['member_id'],'follow',now=time.time())
    client.portal.call(scheduler.wake)
    async def reached():await asyncio.wait_for(provider.reached.wait(),2)
    client.portal.call(reached)
    task = next(iter(scheduler._running.values()))
    return provider,job,task


def drain(client,provider,task):
    client.portal.call(provider.released.set)
    async def wait():
        result = await asyncio.wait_for(asyncio.gather(task,return_exceptions=True),2)
        await asyncio.sleep(0)
        return result
    return client.portal.call(wait)


@pytest.mark.parametrize('stage',[1,2])
def test_legacy_combat_commands_finish_while_native_background_is_blocked(table,stage):
    app,client,session = seed(table)
    battle = client.post('/api/rooms',json=dict(player_name='战斗者',character_id='wizard',starting_level=1)).json()
    frame = enter_battle(client,battle)
    target = frame['combat']['enemies'][0]['id']
    provider,job,task = start_background((app,client,session),stage)
    try:
        response = send(client,battle,'capability_propose',dict(action_id='attack',target_id=target))
        assert response.status_code==200,response.text
        assert app.state.generation_jobs.get(job['id'])['status']=='running'
        assert not task.done() and not provider.released.is_set()
        selected = response.json()['room']['director_proposals'][0]
        confirmed = send(client,battle,'director_resolve',dict(proposal_id=selected['id']))
        assert confirmed.status_code==200,confirmed.text
        assert confirmed.json()['room']['combat']['action_used']
        assert app.state.dm_scheduler.snapshot()['background_active']==1
        assert app.state.dm_scheduler.snapshot()['late_calls']==0
    finally:
        drain(client,provider,task)
    source = app.state.store.get(session['room']['id'])
    assert source['campaign']['runtime_graph']['graph_revision']==1
    assert len(source['campaign']['runtime_graph']['nodes'])==2


def test_real_realtime_dm_call_uses_reserved_capacity_before_late_background_returns(table,monkeypatch):
    app,client,session = seed(table)
    provider,job,task = start_background((app,client,session),1)
    main_dm = app.state.dm
    main_dm.configured = True
    observed = []
    async def immediate(self,*args,**kwargs):
        observed.append(app.state.dm_scheduler.snapshot())
        assert app.state.generation_jobs.get(job['id'])['lease_token'] is None
        assert not provider.released.is_set() and not task.done()
        return json.dumps(dict(kind='dialogue',label='商量做法',text='请根据眼前线索明确行动目标。'))
    monkeypatch.setattr(DM,'_complete',immediate)
    try:
        response = send(client,session,'director_propose',dict(text='我打算观察周围，有什么可行的办法？'))
        assert response.status_code==200,response.text
        assert observed and observed[0]['realtime_active']==1
        assert observed[0]['background_active']==0 and observed[0]['late_calls']==1
        assert app.state.dm_scheduler.snapshot()['realtime_active']==0
        async def resumed():
            async with asyncio.timeout(2):
                while app.state.generation_jobs.get(job['id'])['status']!='committed':
                    await asyncio.sleep(0.01)
        client.portal.call(resumed)
        settled = app.state.generation_jobs.get(job['id'])
        assert settled['attempts']==2
        assert settled['dispatches']==dict(generation=2,semantic=1)
    finally:
        drain(client,provider,task)
    assert app.state.generation_jobs.get(job['id'])==settled
    assert app.state.store.get(session['room']['id'])['campaign']['runtime_graph']['graph_revision']==1


def test_chat_and_unauthorized_command_do_not_interrupt_valid_background(table):
    app,client,session = seed(table)
    provider,job,task = start_background((app,client,session),1)
    try:
        response = send(client,session,'chat',dict(text='我先和大家商量一下。'))
        assert response.status_code==200,response.text
        bad = client.post('/api/rooms/'+session['room']['id']+'/commands',headers=dict(Authorization='Bearer invalid'),
            json=dict(command_id='unauthorized-command',expected_version=response.json()['room']['version'],
                      type='capability_propose',payload=dict(action_id='story-route:follow-courier')))
        assert bad.status_code==401,bad.text
        assert app.state.generation_jobs.get(job['id'])['status']=='running'
        assert not provider.cancelled.is_set() and not task.done()
    finally:
        drain(client,provider,task)
    saved = app.state.store.get(session['room']['id'])
    assert saved['campaign']['runtime_graph']['graph_revision']==1
    assert any('我先和大家商量一下' in row.get('text','') for row in saved['events'])


def test_app_lifespan_recreates_closed_scheduler_for_a_new_service_loop(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    monkeypatch.delenv('LLM_API_KEY',raising=False)
    monkeypatch.delenv('LLM_MODEL',raising=False)
    app = create_app(str(tmp_path/'restart.sqlite3'))
    with TestClient(app) as client:
        first = app.state.dm_scheduler
        assert first.snapshot()['pump_running']
    assert first.snapshot()['closed']
    with TestClient(app) as client:
        second = app.state.dm_scheduler
        assert first is not second and second.snapshot()['pump_running']
        assert app.state.dm.scheduler is second
        assert client.get('/api/health').status_code==200
    assert second.snapshot()['closed']


def test_successful_receipt_replay_and_invalid_payload_do_not_cancel_later_jobs(table):
    app,client,session = seed(table)
    selected = send(client,session,'capability_propose',dict(action_id='story-check:find-lens'),command_id='review-before-job')
    assert selected.status_code==200,selected.text
    provider,job,task = start_background((app,client,session),1)
    try:
        replay = send(client,session,'capability_propose',dict(action_id='story-check:find-lens'),command_id='review-before-job')
        assert replay.status_code==200 and replay.json()['replayed']
        invalid = send(client,session,'capability_propose',dict(action_id='story-check:find-lens',unexpected='illegal'))
        assert invalid.status_code==422
        assert app.state.generation_jobs.get(job['id'])['status']=='running'
        assert not provider.cancelled.is_set() and not task.done()
    finally:
        drain(client,provider,task)
    assert app.state.store.get(session['room']['id'])['campaign']['runtime_graph']['graph_revision']==1


def test_authenticated_member_without_host_permission_does_not_cancel_background(table):
    app,client,session = table
    guest = client.post('/api/rooms/join',json=dict(invite_code=session['invite_code'],player_name='伙伴',character_id='fighter')).json()
    seed(table)
    provider,job,task = start_background((app,client,session),1)
    try:
        response = send(client,guest,'pause')
        assert response.status_code==403,response.text
        assert app.state.generation_jobs.get(job['id'])['status']=='running'
        assert not provider.cancelled.is_set() and not task.done()
    finally:
        drain(client,provider,task)
    assert app.state.store.get(session['room']['id'])['campaign']['runtime_graph']['graph_revision']==1
