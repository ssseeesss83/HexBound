"""Wait identity, durable enqueue and binding commit or roll back together."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import sqlite3
import pytest
from backend import scene_storage,story_generation,story_requests as requests,story_transitions as routes
from backend.generation_jobs import GenerationJobs
from backend.store import Store
from test_generation_jobs import jobs,enqueue
from test_story_generation import Provider


def waiting(jobs,transition='wait1',actor='p'):
    service,rid = jobs
    state = scene_storage.for_actor(scene_storage.pack(service.store.get(rid)),actor)
    previous = state['version']
    routes.request(state,actor,routes.prepare(state,actor,'follow-courier'),transition_id=transition)
    state['version'] += 1
    service.store.save(state,previous)
    return service.store.get(rid)


def test_new_binding_only_updates_private_wait_and_storage_version(jobs):
    service,rid = jobs
    before = waiting(jobs)
    result = requests.bind(service,rid,'p','wait1',now=100)
    assert not result['replayed']
    job = result['job']
    assert job['priority']==0 and job['attempts']==0
    saved = service.store.get(rid)
    expected = scene_storage.pack(before)
    expected['version'] += 1
    expected['scene_instances']['scene-main']['local']['pending_transition']['generation_job_id'] = job['id']
    assert scene_storage.pack(saved)==expected
    assert saved['action_revision']==before['action_revision']
    assert requests.public_status(service,saved,'p',now=101)==dict(status='waiting')
    assert requests.public_status(service,saved,'ally',now=101)==dict(status='waiting')
    assert requests.bind(service,rid,'p','wait1',now=101)==dict(job=job,replayed=True)
    assert service.store.get(rid)==saved


def test_wait_promotes_prefetch_without_new_grant_budget_or_worker(jobs):
    service,rid = jobs
    prefetched = enqueue(jobs,priority=3,budget=dict(max_attempts=2))
    worker = service.claim(prefetched['id'],now=101)
    service.mark_dispatch(prefetched['id'],worker['lease_token'],'generation',now=102)
    waiting(jobs)
    bound = requests.bind(service,rid,'p','wait1',now=103)['job']
    assert bound['id']==prefetched['id'] and bound['priority']==0
    assert bound['authorization']==prefetched['authorization'] and bound['budget']==prefetched['budget']
    assert bound['lease_token']==worker['lease_token'] and bound['attempts']==1
    assert bound['dispatches']==dict(generation=1,semantic=0)
    with service.store.connect() as db:assert db.execute('SELECT COUNT(*) FROM generation_jobs').fetchone()[0]==1


def test_concurrent_bind_is_one_job_one_association_one_storage_revision(jobs):
    service,rid = jobs
    before = waiting(jobs)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:requests.bind(service,rid,'p','wait1',now=100),range(2)))
    assert sum(not row['replayed'] for row in results)==1
    assert len({row['job']['id'] for row in results})==1
    saved = service.store.get(rid)
    assert saved['version']==before['version']+1
    with service.store.connect() as db:assert db.execute('SELECT COUNT(*) FROM generation_jobs').fetchone()[0]==1


@pytest.mark.parametrize('failed_table',['rooms','generation_jobs'])
def test_failure_of_either_write_rolls_back_enqueue_and_binding(jobs,failed_table):
    service,rid = jobs
    before = waiting(jobs)
    with service.store.connect() as db:
        operation = 'UPDATE' if failed_table=='rooms' else 'INSERT'
        db.execute(f"CREATE TRIGGER binding_fault BEFORE {operation} ON {failed_table} BEGIN SELECT RAISE(ABORT,'injected binding fault'); END")
    with pytest.raises(sqlite3.IntegrityError):requests.bind(service,rid,'p','wait1',now=100)
    assert service.store.get(rid)==before
    with service.store.connect() as db:assert db.execute('SELECT COUNT(*) FROM generation_jobs').fetchone()[0]==0


@pytest.mark.parametrize('change',['transition','actor','epoch','leader','source','fact'])
def test_invalid_wait_or_authority_does_not_create_a_job(change,jobs):
    service,rid = jobs
    waiting(jobs)
    transition,actor = 'wait1','p'
    if change=='transition':transition='old-wait'
    elif change=='actor':actor='ally'
    else:
        state = service.store.get(rid)
        previous = state['version']
        if change=='epoch':state['member_contexts']['p']['epoch'] += 1
        elif change=='leader':state['scene_instances']['scene-main']['leader_id']='ally'
        elif change=='source':state['campaign']['node_id']='follow'
        else:
            # This edge's qualification changes after the review.
            book = state['campaign']['package']['scenario']
            book['edges'][0]['condition']=dict(op='fact_equals',ref='lens',value=True)
            from backend.story_runtime import initialize
            state['campaign'].update(initialize(book))
        state['version'] += 1
        service.store.save(state,previous)
    before = deepcopy(service.store.get(rid))
    with pytest.raises(ValueError):requests.bind(service,rid,actor,transition,now=100)
    assert service.store.get(rid)==before
    with service.store.connect() as db:assert db.execute('SELECT COUNT(*) FROM generation_jobs').fetchone()[0]==0


def test_preemption_retry_and_exhaustion_keep_bound_identity_and_safe_public_codes(jobs):
    service,rid = jobs
    waiting(jobs)
    job = requests.bind(service,rid,'p','wait1',now=100)['job']
    for attempt in range(3):
        worker = service.claim(job['id'],now=101+attempt)
        service.mark_dispatch(job['id'],worker['lease_token'],'generation',now=101+attempt)
        service.preempt(job['id'],worker['lease_token'],now=101+attempt)
        current = service.get(job['id'])
        assert requests.bind(service,rid,'p','wait1',now=101+attempt)['job']==current
        assert requests.public_status(service,service.store.get(rid),'p',now=101+attempt)==dict(status='failed' if attempt==2 else 'retrying')
    assert service.get(job['id'])['attempts']==3
    assert requests.bind(service,rid,'p','wait1',now=110)['job']['id']==job['id']
    with service.store.connect() as db:assert db.execute('SELECT COUNT(*) FROM generation_jobs').fetchone()[0]==1


def test_source_change_marks_review_without_automatically_reauthorizing_bound_job(jobs):
    service,rid = jobs
    waiting(jobs)
    job = requests.bind(service,rid,'p','wait1',now=100)['job']
    state = service.store.get(rid)
    previous = state['version']
    state['campaign']['story_state']['facts']['lens'].update(value=True,revision=1)
    state['version'] += 1
    service.store.save(state,previous)
    before = deepcopy(service.store.get(rid))
    assert requests.public_status(service,before,'p',now=101)==dict(status='review_required')
    rebound = requests.bind(service,rid,'p','wait1',now=101)['job']
    assert rebound['id']==job['id'] and rebound['status']=='stale'
    assert service.store.get(rid)==before
    assert requests.bind(service,rid,'p','wait1',now=102)['job']['id']==job['id']


def test_success_only_makes_wait_ready_and_cancellation_never_resurrects_it(jobs):
    service,rid = jobs
    before = waiting(jobs)
    job = requests.bind(service,rid,'p','wait1',now=100)['job']
    assert asyncio.run(story_generation.run(service,Provider(),job['id'],clock=lambda:101))['status']=='committed'
    saved = service.store.get(rid)
    assert requests.public_status(service,saved,'p',now=102)==dict(status='ready_for_review')
    assert saved['campaign']['node_id']=='dock' and saved['campaign']['visited']==['dock']
    assert saved['members']==before['members'] and saved['campaign']['story_state']==before['campaign']['story_state']
    previous = saved['version']
    routes.cancel(saved,'p','wait1')
    saved['version'] += 1
    service.store.save(saved,previous)
    assert requests.public_status(service,service.store.get(rid),'p',now=102) is None
    with pytest.raises(ValueError):requests.bind(service,rid,'p','wait1',now=102)


def test_cancelled_wait_remains_absent_when_a_valid_background_job_finishes(jobs):
    service,rid = jobs
    waiting(jobs)
    job = requests.bind(service,rid,'p','wait1',now=100)['job']
    state = service.store.get(rid)
    previous = state['version']
    routes.cancel(state,'p','wait1')
    state['version'] += 1
    service.store.save(state,previous)
    assert asyncio.run(story_generation.run(service,Provider(),job['id'],clock=lambda:101))['status']=='committed'
    saved = service.store.get(rid)
    assert not saved['pending_transition'] and requests.public_status(service,saved,'p',now=102) is None
    assert saved['campaign']['transition_receipts']['wait1']['status']=='cancelled'


def test_two_scenes_bind_different_private_jobs_and_cannot_guess_other_wait(jobs):
    from backend.scene_groups import prepare_split,commit_split
    service,rid = jobs
    canonical = scene_storage.pack(service.store.get(rid))
    plan = prepare_split(canonical,'scene-main','scene-side','side-channel',['ally'])
    commit_split(canonical,plan)
    with service.store.connect() as db:
        db.execute('UPDATE rooms SET state=? WHERE id=?',(json.dumps(canonical),rid))
    waiting(jobs,'main-wait')
    waiting(jobs,'side-wait','ally')
    main = requests.bind(service,rid,'p','main-wait',now=100)['job']
    side = requests.bind(service,rid,'ally','side-wait',now=100)['job']
    assert main['id']!=side['id']
    with pytest.raises(ValueError):requests.bind(service,rid,'ally','main-wait',now=101)
    with pytest.raises(ValueError):requests.bind(service,rid,'p','side-wait',now=101)
    service.cancel(main['id'])
    canonical = scene_storage.pack(service.store.get(rid))
    assert requests.public_status(service,scene_storage.for_actor(canonical,'p'),'p',now=101)==dict(status='failed')
    assert requests.public_status(service,scene_storage.for_actor(canonical,'ally'),'ally',now=101)==dict(status='waiting')


def test_binding_and_same_budget_survive_schema19_backup_recovery(jobs,tmp_path,monkeypatch):
    from backend import maintenance
    from backend.maintenance import backup_database,restore_backup
    service,rid = jobs
    waiting(jobs)
    with service.store.connect() as db:db.execute('PRAGMA user_version=18')
    service = GenerationJobs(Store(service.store.path))
    assert list((tmp_path/'backups').glob(f'pre-schema-{maintenance.SCHEMA_VERSION}-*.zip'))
    job = requests.bind(service,rid,'p','wait1',now=100)['job']
    archive=tmp_path/'bound.zip'
    backup_database(service.store.path,archive)
    restore_backup(archive,tmp_path/'restored')
    restored = GenerationJobs(Store(str(tmp_path/'restored/database.sqlite3')))
    assert requests.bind(restored,rid,'p','wait1',now=101)==dict(job=job,replayed=True)
    assert restored.store.get(rid)['pending_transition']['generation_job_id']==job['id']
    monkeypatch.setattr(maintenance,'SCHEMA_VERSION',18)
    with pytest.raises(ValueError,match='newer server'):Store(service.store.path)
