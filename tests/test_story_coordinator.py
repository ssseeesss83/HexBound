"""Only committed source activity triggers shallow work and safe current views."""
import asyncio
import json
from copy import deepcopy
import pytest
from backend import story_coordinator as coordinator,story_runtime
from backend.dm_scheduler import DMScheduler
from test_generation_jobs import jobs,enqueue
from test_story_generation import Provider
from test_story_requests import waiting
from test_story_challenges import authored
from test_native_story_checks import table,extend_graph


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():await asyncio.sleep(0.01)


def test_refresh_prefetches_only_one_frontier_and_deduplicates_without_room_mutation(jobs):
    service,rid = jobs
    before = deepcopy(service.store.get(rid))
    async def scenario():
        async def publish(room):pytest.fail('No service notification pump was started')
        scheduler = DMScheduler(service,Provider(),clock=lambda:100)
        co = coordinator.StoryCoordinator(service,scheduler,publish)
        first = co.refresh(rid,'p')
        second = co.refresh(rid,'p')
        assert first['id']==second['id'] and first['priority']==2
        assert service.store.get(rid)==before
        assert len(service.ready(now=101))==1
        await scheduler.dispatch()
        task = next(iter(scheduler._running.values()))
        await task
        await asyncio.sleep(0)
        assert co.snapshot()['pending_notifications']==1
        assert co.refresh(rid,'p') is None
        assert service.store.get(rid)['campaign']['runtime_graph']['graph_revision']==1
        with service.store.connect() as db:assert db.execute('SELECT COUNT(*) FROM generation_jobs').fetchone()[0]==1
        await scheduler.close()
        await co.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('visibility',['secret','known'])
def test_prefetch_skips_hidden_routes(visibility):
    book = authored()
    book['edges'][0]['visibility'] = visibility
    assert coordinator.nearby_frontiers(table(book))==[]


@pytest.mark.parametrize('depth',[2,3])
def test_prefetch_horizon_is_two_edges_and_not_full_graph(depth):
    book = authored()
    book['edges'][0]['visibility']='secret'
    frontier = deepcopy(book['nodes'][1])
    frontier['id']='far-end'
    book['nodes'].append(frontier)
    previous='dock'
    for index in range(depth-1):
        sid='step'+str(index)
        book['nodes'].append(dict(id=sid,kind='scene',title='Step',text='A path.'))
        book['edges'].append(dict(id='path'+str(index),**{'from':previous},to=sid))
        previous=sid
    book['edges'].append(dict(id='far-path',**{'from':previous},to='far-end'))
    assert coordinator.nearby_frontiers(table(book))==(['far-end'] if depth==2 else [])


def test_prefetch_respects_current_conditions_and_never_recurses_through_completed_attachment():
    book = authored()
    book['edges'][0]['condition']=dict(op='fact_equals',ref='lens',value=True)
    state = table(book)
    assert coordinator.nearby_frontiers(state)==[]
    state['campaign']['story_state']['facts']['lens'].update(value=True,revision=1)
    assert coordinator.nearby_frontiers(state)==['follow']
    extend_graph(state)
    assert coordinator.nearby_frontiers(state)==[]


def test_required_wait_is_bound_while_offline_without_consuming_attempts(jobs):
    service,rid = jobs
    waiting(jobs)
    async def scenario():
        provider = Provider()
        provider.configured = False
        scheduler = DMScheduler(service,provider,clock=lambda:100)
        async def publish(room):pass
        co = coordinator.StoryCoordinator(service,scheduler,publish)
        job = co.refresh(rid,'p')
        assert job['attempts']==0 and job['priority']==0
        assert co.status(service.store.get(rid),'p')==dict(status='unavailable')
        assert await scheduler.dispatch()==[]
        assert service.get(job['id'])['dispatches']==dict(generation=0,semantic=0)
        await co.close()
        await scheduler.close()
    asyncio.run(scenario())


def test_restart_sweep_binds_existing_wait_and_coalesces_current_snapshot_notices(jobs):
    service,rid = jobs
    before = waiting(jobs)
    async def scenario():
        delivered = []
        provider=Provider();provider.configured=False
        scheduler = DMScheduler(service,provider,clock=lambda:100)
        async def publish(room):
            delivered.append((room,service.store.get(room)['pending_transition']['generation_job_id']))
        co = coordinator.StoryCoordinator(service,scheduler,publish)
        co.start()
        await until(lambda:service.store.get(rid)['pending_transition'].get('generation_job_id'))
        await until(lambda:bool(delivered))
        saved = service.store.get(rid)
        job_id = saved['pending_transition']['generation_job_id']
        assert saved['members']==before['members'] and saved['campaign']['visited']==before['campaign']['visited']
        assert service.get(job_id)['attempts']==0 and co.snapshot()['wait_bindings']==1
        for _ in range(5):co.completed(job_id)
        await until(lambda:len(delivered)>=2)
        assert delivered==[(rid,job_id),(rid,job_id)]
        await scheduler.close()
        await co.close()
    asyncio.run(scenario())


def test_post_commit_binding_fault_is_recovered_without_a_second_player_action(jobs):
    service,rid = jobs
    before = waiting(jobs)
    async def scenario():
        provider=Provider();provider.configured=False
        scheduler = DMScheduler(service,provider,clock=lambda:100)
        async def publish(room):pass
        co = coordinator.StoryCoordinator(service,scheduler,publish)
        with service.store.connect() as db:
            db.execute("CREATE TRIGGER broken_binding BEFORE INSERT ON generation_jobs BEGIN SELECT RAISE(ABORT,'temporary fault'); END")
        assert co.refresh(rid,'p') is None
        assert co.snapshot()['refresh_errors']==1
        assert service.store.get(rid)==before
        with service.store.connect() as db:db.execute('DROP TRIGGER broken_binding')
        co.start()
        await until(lambda:bool(service.store.get(rid)['pending_transition'].get('generation_job_id')))
        assert co.snapshot()['wait_bindings']==1
        await scheduler.close()
        await co.close()
    asyncio.run(scenario())


def test_publication_failure_does_not_rollback_job_or_stop_recovery_pump(jobs):
    service,rid=jobs
    job=enqueue(jobs)
    async def scenario():
        scheduler=DMScheduler(service,Provider(),clock=lambda:100)
        async def broken(room):raise RuntimeError('SECRET_NOTIFY_ERROR')
        co=coordinator.StoryCoordinator(service,scheduler,broken)
        co.completed(job['id'])
        co.start()
        await until(lambda:co.snapshot()['notify_errors']==1)
        assert co.snapshot()['pump_running']
        assert 'SECRET' not in str(co.snapshot())
        assert service.get(job['id'])==job
        await scheduler.close()
        await co.close()
    asyncio.run(scenario())


def test_failed_waits_do_not_starve_later_scenes(jobs,monkeypatch):
    service,rid=jobs
    job=enqueue(jobs)
    with service.store.connect() as db:
        room=json.loads(db.execute('SELECT state FROM rooms WHERE id=?',(rid,)).fetchone()['state'])
        room['scene_instances']={f'scene{i}':dict(local=dict(pending_transition=dict(
            id=f'wait{i}',plan=dict(scope=dict(actor_id='p'))))) for i in range(6)}
        db.execute('UPDATE rooms SET state=? WHERE id=?',(json.dumps(room),rid))
    attempts=[]
    def bind(service,room,actor,transition,**kwargs):
        attempts.append(transition)
        if transition in {'wait0','wait1','wait2','wait3'}:raise ValueError('invalid dependency')
        return dict(job=job,replayed=False)
    monkeypatch.setattr(coordinator.story_requests,'bind',bind)
    async def scenario():
        scheduler=DMScheduler(service,Provider(),clock=lambda:100)
        async def publish(room):pass
        co=coordinator.StoryCoordinator(service,scheduler,publish)
        co.recover_waits()
        assert attempts==['wait0','wait1','wait2','wait3']
        co.recover_waits()
        assert attempts==[f'wait{i}' for i in range(6)]
        assert co.snapshot()['wait_bindings']==2
        await scheduler.close()
        await co.close()
    asyncio.run(scenario())


def test_transient_notification_failure_retries_current_snapshot_with_backoff(jobs):
    service,rid=jobs
    job=enqueue(jobs)
    async def scenario():
        scheduler=DMScheduler(service,Provider(),clock=lambda:100)
        calls=[]
        async def publish(room):
            calls.append(asyncio.get_running_loop().time())
            if len(calls)==1:raise OSError('temporary database fault')
        co=coordinator.StoryCoordinator(service,scheduler,publish)
        co.completed(job['id'])
        co.start()
        await until(lambda:len(calls)==1)
        for _ in range(10):co.completed(job['id'])
        await asyncio.sleep(0.1)
        assert len(calls)==1
        await until(lambda:co.snapshot()['notifications']==1)
        assert calls[1]-calls[0]>=0.5
        assert co.snapshot()['pending_notifications']==0
        assert co._notify_retry=={}
        await scheduler.close()
        await co.close()
    asyncio.run(scenario())
