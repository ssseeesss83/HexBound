"""Interrupted work resumes one identity and budget, never an old lease."""
import asyncio
from copy import deepcopy
import json
import pytest
from backend import scene_storage, story_generation
from backend.generation_jobs import GenerationJobs
from backend.store import Store
from test_generation_jobs import jobs,enqueue
from test_story_generation import Provider


@pytest.mark.parametrize('stage',['claimed','generation','semantic'])
def test_preemption_keeps_identity_authorization_budget_and_dispatch_history(jobs,stage):
    service,_ = jobs
    job = enqueue(jobs)
    worker = service.claim(job['id'],now=101)
    if stage!='claimed':service.mark_dispatch(job['id'],worker['lease_token'],'generation',now=102)
    if stage=='semantic':service.mark_dispatch(job['id'],worker['lease_token'],'semantic',now=103)
    before = service.get(job['id'])
    paused = service.preempt(job['id'],worker['lease_token'],now=104)
    assert paused['status']=='retryable_failed' and paused['error_code']=='preempted'
    assert paused['attempts']==(0 if stage=='claimed' else 1)
    assert paused['dispatches']==before['dispatches']
    assert paused['attempt_stage'] is None and paused['lease_token'] is None
    for key in ['id','authorization','budget','dedup_key','created_at','priority']:
        assert paused[key]==job[key]
    assert enqueue(jobs)['id']==job['id']
    provider = Provider()
    result = asyncio.run(story_generation.run(service,provider,job['id'],clock=lambda:105))
    assert result['status']=='committed' and len(provider.calls)==2
    saved = service.get(job['id'])
    assert saved['attempts']==(1 if stage=='claimed' else 2)
    assert saved['dispatches']==dict(generation=before['dispatches']['generation']+1,semantic=before['dispatches']['semantic']+1)


def test_late_worker_cannot_cancel_fail_dispatch_or_preempt_resumed_lease(jobs):
    service,_ = jobs
    job = enqueue(jobs)
    old = service.claim(job['id'],now=101)
    service.mark_dispatch(job['id'],old['lease_token'],'generation',now=102)
    service.preempt(job['id'],old['lease_token'],now=103)
    fresh = service.claim(job['id'],now=104)
    assert fresh['lease_token']!=old['lease_token']
    before = service.get(job['id'])
    assert service.cancel(job['id'],lease_token=old['lease_token'])==before
    assert service.preempt(job['id'],old['lease_token'],now=105)==before
    with pytest.raises(ValueError):service.fail(job['id'],old['lease_token'],now=105)
    with pytest.raises(ValueError):service.mark_dispatch(job['id'],old['lease_token'],'semantic',now=105)
    assert service.get(job['id'])==before


def test_three_dispatched_attempts_exhaust_same_job_without_automatic_rebirth(jobs):
    service,_ = jobs
    job = enqueue(jobs)
    for index in range(3):
        worker = service.claim(job['id'],now=101+index)
        assert worker is not None
        service.mark_dispatch(job['id'],worker['lease_token'],'generation',now=101+index)
        paused = service.preempt(job['id'],worker['lease_token'],now=101+index)
        assert paused['status']==('terminal_failed' if index==2 else 'retryable_failed')
    assert paused['attempts']==3 and paused['dispatches']==dict(generation=3,semantic=0)
    assert service.claim(job['id'],now=110) is None and service.ready(now=110)==[]
    assert service.get(job['id'])['budget']==job['budget']
    assert enqueue(jobs,priority=0,budget=dict(max_attempts=3))==paused
    with service.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM generation_jobs').fetchone()[0]==1


def test_queued_preemption_does_not_consume_or_replace_an_unstarted_job(jobs):
    service,_ = jobs
    job = enqueue(jobs)
    assert service.preempt(job['id'],None,now=101)==job
    assert service.get(job['id'])==job
    assert service.ready(now=101)[0]['id']==job['id']


@pytest.mark.parametrize('change',['fact','epoch','expiry'])
def test_dependency_changes_become_stale_instead_of_reauthorizing_old_job(jobs,change):
    service,rid = jobs
    job = enqueue(jobs)
    worker = service.claim(job['id'],now=101)
    service.mark_dispatch(job['id'],worker['lease_token'],'generation',now=102)
    if change!='expiry':
        state = service.store.get(rid)
        previous = state['version']
        if change=='fact':state['campaign']['story_state']['facts']['lens'].update(value=True,revision=1)
        else:state['member_contexts']['p']['epoch'] += 1
        state['version'] += 1
        service.store.save(state,previous)
    current = service.preempt(job['id'],worker['lease_token'],now=701 if change=='expiry' else 103)
    assert current['status']=='stale' and current['error_code']=='dependency_changed'
    assert current['attempts']==1 and current['dispatches']==dict(generation=1,semantic=0)
    assert service.claim(job['id'],now=702) is None


def test_dispatch_stages_are_single_ordered_and_lease_checked(jobs):
    service,_ = jobs
    job = enqueue(jobs)
    worker = service.claim(job['id'],now=101)
    before = service.get(job['id'])
    with pytest.raises(ValueError):service.mark_dispatch(job['id'],worker['lease_token'],'semantic',now=102)
    assert service.get(job['id'])==before
    service.mark_dispatch(job['id'],worker['lease_token'],'generation',now=102)
    before = service.get(job['id'])
    with pytest.raises(ValueError):service.mark_dispatch(job['id'],worker['lease_token'],'generation',now=103)
    assert service.get(job['id'])==before
    service.mark_dispatch(job['id'],worker['lease_token'],'semantic',now=103)
    before = service.get(job['id'])
    with pytest.raises(ValueError):service.mark_dispatch(job['id'],worker['lease_token'],'semantic',now=104)
    with pytest.raises(ValueError):service.mark_dispatch(job['id'],worker['lease_token'],'generation',now=192)
    assert service.get(job['id'])==before


def test_unknown_historical_dispatches_remain_unknown_after_schema18_upgrade(jobs,tmp_path,monkeypatch):
    from backend import maintenance
    service,_ = jobs
    job = enqueue(jobs)
    worker = service.claim(job['id'],now=101)
    with service.store.connect() as db:
        old = json.loads(db.execute('SELECT payload FROM generation_jobs WHERE id=?',(job['id'],)).fetchone()[0])
        old.pop('dispatches')
        old.pop('attempt_stage')
        db.execute('UPDATE generation_jobs SET payload=? WHERE id=?',(json.dumps(old),job['id']))
        db.execute('PRAGMA user_version=17')
    upgraded = GenerationJobs(Store(service.store.path))
    historical = upgraded.get(job['id'])
    assert historical['dispatches'] is None and historical['attempt_stage'] is None
    paused = upgraded.preempt(job['id'],worker['lease_token'],now=102)
    assert paused['attempts']==1 and paused['dispatches'] is None
    assert asyncio.run(story_generation.run(upgraded,Provider(),job['id'],clock=lambda:103))['status']=='committed'
    assert upgraded.get(job['id'])['dispatches'] is None
    assert list((tmp_path/'backups').glob(f'pre-schema-{maintenance.SCHEMA_VERSION}-*.zip'))
    monkeypatch.setattr(maintenance,'SCHEMA_VERSION',17)
    with pytest.raises(ValueError,match='newer server'):Store(service.store.path)


def test_preempted_budget_and_call_counts_survive_complete_backup(jobs,tmp_path):
    from backend.maintenance import backup_database,restore_backup
    service,_ = jobs
    job = enqueue(jobs)
    worker = service.claim(job['id'],now=101)
    service.mark_dispatch(job['id'],worker['lease_token'],'generation',now=102)
    service.mark_dispatch(job['id'],worker['lease_token'],'semantic',now=103)
    paused = service.preempt(job['id'],worker['lease_token'],now=104)
    archive = tmp_path/'preempt.zip'
    backup_database(service.store.path,archive)
    restore_backup(archive,tmp_path/'restore')
    restored = GenerationJobs(Store(str(tmp_path/'restore/database.sqlite3')))
    assert restored.get(job['id'])==paused
    resumed = restored.claim(job['id'],now=105)
    assert resumed['attempts']==2 and resumed['dispatches']==dict(generation=1,semantic=1)


def test_old_task_completion_does_not_remove_resumed_worker_from_scheduler(jobs):
    from backend.dm_scheduler import DMScheduler
    service,rid = jobs
    job = enqueue(jobs)
    async def scenario():
        old_enter,new_enter,old_release,new_release = [asyncio.Event() for _ in range(4)]
        async def block(call):
            if call==1:
                old_enter.set()
                try:await old_release.wait()
                except asyncio.CancelledError:await old_release.wait()
            elif call==3:
                new_enter.set()
                await new_release.wait()
        scheduler = DMScheduler(service,Provider(hook=block),clock=lambda:101)
        await scheduler.dispatch()
        await asyncio.wait_for(old_enter.wait(),1)
        old_task = scheduler._running[job['id']]
        async with scheduler.realtime():pass
        await scheduler.dispatch()
        await asyncio.wait_for(new_enter.wait(),1)
        new_task = scheduler._running[job['id']]
        new_token = scheduler._leases[job['id']]
        old_release.set()
        with pytest.raises(asyncio.CancelledError):await old_task
        await asyncio.sleep(0)
        assert scheduler._running[job['id']] is new_task
        assert scheduler._leases[job['id']]==new_token
        assert service.get(job['id'])['lease_token']==new_token
        new_release.set()
        await new_task
        await asyncio.sleep(0)
        assert scheduler.snapshot()['committed']==1 and scheduler.snapshot()['background_active']==0
        assert service.store.get(rid)['campaign']['runtime_graph']['graph_revision']==1
        await scheduler.close()
    asyncio.run(scenario())
