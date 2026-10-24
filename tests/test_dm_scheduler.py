"""A25: durable preemption frees logical capacity before a late provider exits."""
import asyncio
from copy import deepcopy
import json

import pytest

from backend.dm_scheduler import DMScheduler
from test_generation_jobs import jobs, enqueue
from test_story_generation import Provider


@pytest.mark.parametrize('stage',[1,2])
def test_blocked_provider_loses_authority_before_realtime_and_rule_admission(jobs,stage):
    service,rid = jobs
    job = enqueue(jobs)
    before = deepcopy(service.store.get(rid))
    async def scenario():
        reached,released,cancelled = asyncio.Event(),asyncio.Event(),asyncio.Event()
        async def block(call):
            if call==stage:
                reached.set()
                try:await released.wait()
                except asyncio.CancelledError:
                    # Adversarial remote adapter swallows cancellation.
                    cancelled.set()
                    await released.wait()
        provider = Provider(hook=block)
        scheduler = DMScheduler(service,provider,clock=lambda:101,realtime_capacity=1)
        assert await scheduler.dispatch()==[job['id']]
        await asyncio.wait_for(reached.wait(),1)
        worker = next(iter(scheduler._running.values()))
        with scheduler.player_activity():
            assert service.get(job['id'])['status']=='retryable_failed'
            assert scheduler.snapshot()['background_active']==0
            assert scheduler.snapshot()['late_calls']==1
            # Rule-only work never waits for foreground or background LLM slots.
            assert await scheduler.dispatch()==[]
        async with scheduler.realtime():
            assert service.get(job['id'])['lease_token'] is None
            assert not released.is_set() and not worker.done()
            assert scheduler.snapshot()['realtime_active']==1
            assert await scheduler.dispatch()==[]
        await asyncio.wait_for(cancelled.wait(),1)
        assert not worker.done() and scheduler.snapshot()['realtime_active']==0
        released.set()
        with pytest.raises(asyncio.CancelledError):await worker
        await asyncio.sleep(0)
        assert scheduler.snapshot()['late_calls']==0
        assert scheduler.snapshot()['preemptions']==1
        assert scheduler.snapshot()['committed']==0
        await scheduler.close()
    asyncio.run(scenario())
    assert service.store.get(rid)==before
    assert service.get(job['id'])['status']=='retryable_failed'


def test_rule_commands_do_not_wait_for_busy_realtime_permits(jobs):
    service,_ = jobs
    async def scenario():
        scheduler = DMScheduler(service,Provider(),realtime_capacity=1,clock=lambda:101)
        inside,released = asyncio.Event(),asyncio.Event()
        async def realtime():
            async with scheduler.realtime():
                inside.set()
                await released.wait()
        first = asyncio.create_task(realtime())
        await inside.wait()
        with scheduler.player_activity():
            assert scheduler.snapshot()['realtime_active']==1
            assert await scheduler.dispatch()==[]
        # Queued model calls count as foreground activity; cancelling one must
        # release its waiter/player markers without consuming a permit.
        second = asyncio.create_task(realtime())
        await asyncio.sleep(0)
        assert scheduler.snapshot()['realtime_waiting']==1
        second.cancel()
        with pytest.raises(asyncio.CancelledError):await second
        assert scheduler.snapshot()['realtime_waiting']==0
        released.set()
        await first
        assert scheduler.snapshot()['players']==0
        async with scheduler.realtime():pass
        assert scheduler.snapshot()['realtime_active']==0
        await scheduler.close()
    asyncio.run(scenario())


def test_ready_queue_prioritizes_promotions_and_ignores_backoff_and_leased_work(jobs):
    service,rid = jobs
    low = enqueue(jobs,priority=3)
    room = service.store.get(rid)
    room.update(id='other-room',invite_code='OTHER-JOB')
    from backend import scene_storage
    with service.store.connect() as db:
        db.execute('INSERT INTO rooms VALUES(?,?,?,?)',(room['id'],room['invite_code'],room['version'],json.dumps(scene_storage.pack(room))))
    high = service.enqueue(room['id'],'p','follow',priority=0,now=100)
    assert [job['id'] for job in service.ready(now=101)]==[high['id'],low['id']]
    claimed = service.claim(high['id'],now=101)
    assert [job['id'] for job in service.ready(now=101)]==[low['id']]
    service.fail(high['id'],claimed['lease_token'],now=101)
    assert [job['id'] for job in service.ready(now=102)]==[low['id']]
    assert service.ready(now=104)[0]['id']==high['id']
    promoted = enqueue(jobs,priority=0)
    assert promoted['id']==low['id']
    assert all(job['priority']==0 for job in service.ready(now=104))
    for bad in [True,0,101]:
        with pytest.raises(ValueError):service.ready(limit=bad,now=101)


def test_dispatch_commits_one_shallow_job_and_consumes_worker_result(jobs):
    service,rid = jobs
    job = enqueue(jobs)
    async def scenario():
        scheduler = DMScheduler(service,Provider(),clock=lambda:101)
        assert await scheduler.dispatch()==[job['id']]
        assert await scheduler.dispatch()==[]
        task = next(iter(scheduler._running.values()))
        await task
        await asyncio.sleep(0)
        assert scheduler.snapshot()['committed']==1
        assert scheduler.snapshot()['background_active']==0
        assert await scheduler.dispatch()==[]
        assert len(service.store.get(rid)['campaign']['runtime_graph']['nodes'])==2
        await scheduler.close()
    asyncio.run(scenario())


def test_orphan_bound_limits_background_amplification_without_blocking_realtime(jobs):
    service,_ = jobs
    async def scenario():
        reached,released,cancelled = asyncio.Event(),asyncio.Event(),asyncio.Event()
        async def block(call):
            if call==1:
                reached.set()
                try:await released.wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    await released.wait()
        scheduler = DMScheduler(service,Provider(hook=block),orphan_limit=1,clock=lambda:101)
        job = enqueue(jobs)
        await scheduler.dispatch()
        task = next(iter(scheduler._running.values()))
        await reached.wait()
        with scheduler.player_activity():pass
        await cancelled.wait()
        replacement = enqueue(jobs)
        assert replacement['id']==job['id']
        assert await scheduler.dispatch()==[]
        async with scheduler.realtime():
            assert scheduler.snapshot()['late_calls']==1
        released.set()
        with pytest.raises(asyncio.CancelledError):await task
        await asyncio.sleep(0)
        assert await scheduler.dispatch()==[replacement['id']]
        await next(iter(scheduler._running.values()))
        await asyncio.sleep(0)
        await scheduler.close()
    asyncio.run(scenario())


def test_background_pump_shutdown_revokes_without_waiting_for_supplier(jobs):
    service,rid = jobs
    job = enqueue(jobs)
    async def scenario():
        reached,released,cancelled = asyncio.Event(),asyncio.Event(),asyncio.Event()
        async def block(call):
            if call==1:
                reached.set()
                try:await released.wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    await released.wait()
        scheduler = DMScheduler(service,Provider(hook=block),clock=lambda:101)
        scheduler.start()
        scheduler.start()
        await asyncio.wait_for(reached.wait(),1)
        task = next(iter(scheduler._running.values()))
        await asyncio.wait_for(scheduler.close(),1)
        await cancelled.wait()
        assert scheduler.snapshot()['closed'] and scheduler.snapshot()['late_calls']==1
        assert service.get(job['id'])['status']=='retryable_failed'
        assert not task.done()
        await scheduler.close()
        with pytest.raises(RuntimeError):await scheduler.dispatch()
        released.set()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(scenario())
    assert service.store.get(rid)['campaign']['runtime_graph']['graph_revision']==0


def test_revocation_failure_does_not_release_background_authority_silently(jobs,monkeypatch):
    service,_ = jobs
    enqueue(jobs)
    async def scenario():
        scheduler = DMScheduler(service,Provider(),clock=lambda:101)
        await scheduler.dispatch()
        task = next(iter(scheduler._running.values()))
        def failed(*args,**kwargs):raise OSError('durable store unavailable')
        with monkeypatch.context() as guard:
            guard.setattr(service,'preempt',failed)
            with pytest.raises(OSError):
                with scheduler.player_activity():pytest.fail('Admitted without revocation')
        assert scheduler.snapshot()['players']==0
        assert scheduler.snapshot()['background_active']==1 and not task.cancelling()
        await scheduler.close()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(scenario())


def test_stale_queue_rejected_by_worker_and_realtime_exception_releases_capacity(jobs):
    service,rid = jobs
    job = enqueue(jobs)
    state = service.store.get(rid)
    previous = state['version']
    state['campaign']['story_state']['facts']['lens'].update(value=True,revision=1)
    state['version'] += 1
    service.store.save(state,previous)
    provider = Provider()
    async def scenario():
        scheduler = DMScheduler(service,provider,clock=lambda:101)
        await scheduler.dispatch()
        await next(iter(scheduler._running.values()))
        await asyncio.sleep(0)
        assert provider.calls==[] and service.get(job['id'])['status']=='stale'
        with pytest.raises(ValueError):
            async with scheduler.realtime():raise ValueError('foreground failure')
        assert scheduler.snapshot()['players']==0 and scheduler.snapshot()['realtime_active']==0
        async with scheduler.realtime():pass
        await scheduler.close()
    asyncio.run(scenario())


def test_offline_does_not_consume_jobs_and_scheduler_rejects_foreign_loop(jobs):
    service,_ = jobs
    job = enqueue(jobs)
    provider = Provider()
    provider.configured = False
    scheduler = DMScheduler(service,provider,clock=lambda:101)
    assert asyncio.run(scheduler.dispatch())==[]
    assert service.get(job['id'])['status']=='queued'
    with pytest.raises(RuntimeError,match='事件循环'):asyncio.run(scheduler.dispatch())


def test_pump_recovers_from_transient_database_failure_without_blocking_players(jobs,monkeypatch):
    service,_ = jobs
    enqueue(jobs)
    async def scenario():
        scheduler = DMScheduler(service,Provider(),clock=lambda:101)
        original = service.recover
        failed = asyncio.Event()
        count = 0
        def intermittent(**kwargs):
            nonlocal count
            count += 1
            if count==1:
                failed.set()
                raise OSError('SECRET_DATABASE_EXCEPTION')
            return original(**kwargs)
        monkeypatch.setattr(service,'recover',intermittent)
        scheduler.start()
        await failed.wait()
        async with scheduler.realtime():
            assert scheduler.snapshot()['dispatch_errors']==1
            assert scheduler.snapshot()['pump_running']
        async def completed():
            while scheduler.snapshot()['committed']!=1:await asyncio.sleep(0.01)
        await asyncio.wait_for(completed(),2)
        assert count>=2 and 'SECRET' not in str(scheduler.snapshot())
        await scheduler.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('restart',[False,True])
def test_finished_pump_failure_can_be_restarted_or_closed(jobs,monkeypatch,restart):
    service,_ = jobs
    async def scenario():
        scheduler = DMScheduler(service,Provider(),clock=lambda:101)
        original = scheduler.dispatch
        async def fatal():raise RuntimeError('SECRET_UNEXPECTED_EXCEPTION')
        monkeypatch.setattr(scheduler,'dispatch',fatal)
        scheduler.start()
        # Await a completed failing task without relying on exception logs.
        await asyncio.wait({scheduler._pump})
        assert scheduler._pump.done() and not scheduler.snapshot()['pump_running']
        if restart:
            monkeypatch.setattr(scheduler,'dispatch',original)
            scheduler.start()
            assert scheduler.snapshot()['pump_running']
            assert scheduler.snapshot()['pump_failures']==1
        await scheduler.close()
        assert scheduler.snapshot()['pump_failures']==1
        assert 'SECRET' not in str(scheduler.snapshot())
    asyncio.run(scenario())
