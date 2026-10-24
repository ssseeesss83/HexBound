"""Durable leases lose all write authority on cancellation, expiry or restart."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

import pytest

from backend import scene_storage, session_scope
from backend.generation_jobs import GenerationJobs
from backend.store import Store
from test_native_story_checks import table


@pytest.fixture
def jobs(tmp_path):
    state = table()
    state.update(invite_code='JOBFIXTURE',version=1,action_revision=0)
    session_scope.initialize(state)
    path = tmp_path/'jobs.sqlite3'
    store = Store(str(path))
    with store.connect() as db:
        db.execute('INSERT INTO rooms VALUES(?,?,?,?)',
                   (state['id'],state['invite_code'],state['version'],json.dumps(scene_storage.pack(state))))
    store = Store(str(path))
    return GenerationJobs(store),state['id']


def enqueue(jobs,**kwargs):
    service,rid = jobs
    return service.enqueue(rid,'p','follow',now=100,**kwargs)


def test_enqueue_deduplicates_and_promotes_without_room_changes(jobs):
    service,rid = jobs
    before = deepcopy(service.store.get(rid))
    original = enqueue(jobs,priority=3)
    promoted = enqueue(jobs,priority=0,budget=dict(max_attempts=1))
    assert original['id']==promoted['id'] and promoted['priority']==0
    assert promoted['budget']==original['budget'] and promoted['status']=='queued'
    assert service.store.get(rid)==before
    assert service.get(original['id'])==promoted


def test_two_workers_can_only_claim_one_lease(jobs):
    service,_ = jobs
    job = enqueue(jobs)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _:service.claim(job['id'],now=101),range(2)))
    assert sum(result is not None for result in claims)==1
    claimed = next(result for result in claims if result)
    assert claimed['attempts']==1 and claimed['lease_until']==191
    assert service.require_lease(job['id'],claimed['lease_token'],now=102)==claimed
    with pytest.raises(ValueError):service.require_lease(job['id'],'wrong',now=102)


def test_same_scene_members_share_one_task_without_changing_its_authority(jobs):
    service,rid = jobs
    first = enqueue(jobs)
    other = service.enqueue(rid,'ally','follow',priority=0,now=101)
    assert other['id']==first['id'] and other['authorization']==first['authorization']
    assert other['priority']==0


def test_concurrent_enqueue_has_one_persistent_identity(jobs):
    service,_ = jobs
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:enqueue(jobs),range(2)))
    assert results[0]['id']==results[1]['id']
    with service.store.connect() as db:assert db.execute('SELECT COUNT(*) FROM generation_jobs').fetchone()[0]==1


def test_cancellation_revokes_old_callback_and_new_request_has_new_identity(jobs):
    service,_ = jobs
    job = enqueue(jobs)
    running = service.claim(job['id'],now=101)
    cancelled = service.cancel(job['id'])
    assert cancelled['status']=='cancelled' and cancelled['lease_token'] is None
    assert service.cancel(job['id'])==cancelled
    with pytest.raises(ValueError):service.require_lease(job['id'],running['lease_token'],now=102)
    with pytest.raises(ValueError):service.fail(job['id'],running['lease_token'],now=102)
    replacement = enqueue(jobs)
    assert replacement['id']!=job['id'] and replacement['dedup_key']==job['dedup_key']


def test_restart_recovery_revokes_lease_and_uses_bounded_backoff(jobs):
    service,rid = jobs
    before = deepcopy(service.store.get(rid))
    job = enqueue(jobs)
    running = service.claim(job['id'],now=101)
    restarted = GenerationJobs(Store(service.store.path))
    assert restarted.recover(now=191)==[job['id']]
    retry = restarted.get(job['id'])
    assert retry['status']=='retryable_failed' and retry['next_run_at']==193
    assert restarted.claim(job['id'],now=192) is None
    next_worker = restarted.claim(job['id'],now=193)
    assert next_worker['attempts']==2 and next_worker['lease_token']!=running['lease_token']
    with pytest.raises(ValueError):restarted.require_lease(job['id'],running['lease_token'],now=194)
    assert restarted.require_lease(job['id'],next_worker['lease_token'],now=194)
    assert restarted.store.get(rid)==before


def test_failure_budget_terminates_after_three_attempts(jobs):
    service,_ = jobs
    job = enqueue(jobs)
    now = 101
    for attempt in range(1,4):
        worker = service.claim(job['id'],now=now)
        assert worker['attempts']==attempt
        failed = service.fail(job['id'],worker['lease_token'],now=now+1)
        now = failed['next_run_at']
    assert failed['status']=='terminal_failed' and service.claim(job['id'],now=now) is None
    assert not service.recover(now=999)


def test_changed_fact_stales_before_claim_and_never_changes_room(jobs):
    service,rid = jobs
    job = enqueue(jobs)
    state = service.store.get(rid)
    previous = state['version']
    state['campaign']['story_state']['facts']['lens'].update(value=True,revision=1)
    state['version'] += 1
    service.store.save(state,previous)
    before = deepcopy(service.store.get(rid))
    assert service.claim(job['id'],now=101) is None
    assert service.get(job['id'])['status']=='stale'
    assert service.store.get(rid)==before


def test_expired_queued_job_is_replaced_without_reviving_old_grant(jobs):
    service,rid = jobs
    first = enqueue(jobs)
    replacement = service.enqueue(rid,'p','follow',now=701)
    assert replacement['id']!=first['id'] and service.get(first['id'])['status']=='stale'
    assert service.claim(first['id'],now=702) is None
    assert service.claim(replacement['id'],now=702)


@pytest.mark.parametrize('options',[dict(priority=True),dict(priority=4),dict(budget=dict(max_attempts=4)),
                                    dict(budget=dict(timeout_seconds=121)),dict(budget=dict(max_tokens=6001)),dict(budget=dict(hp=99))])
def test_invalid_budgets_or_priority_cannot_enqueue(jobs,options):
    service,_ = jobs
    with pytest.raises(ValueError):enqueue(jobs,**options)
    with service.store.connect() as db:assert db.execute('SELECT COUNT(*) FROM generation_jobs').fetchone()[0]==0


def test_room_queue_bound_rejects_seventeenth_distinct_task(jobs):
    from backend.story_runtime import initialize
    service,rid = jobs
    state = service.store.get(rid)
    previous = state['version']
    book = state['campaign']['package']['scenario']
    for index in range(16):
        frontier = deepcopy(book['nodes'][1])
        frontier['id']='frontier'+str(index)
        book['nodes'].append(frontier)
        book['edges'].append(dict(id='route'+str(index),**{'from':'dock'},to=frontier['id']))
    state['campaign'].update(initialize(book))
    state['version'] += 1
    service.store.save(state,previous)
    enqueue(jobs)
    for index in range(15):service.enqueue(rid,'p','frontier'+str(index),now=100)
    with pytest.raises(ValueError,match='队列已满'):service.enqueue(rid,'p','frontier15',now=100)
    with service.store.connect() as db:assert db.execute('SELECT COUNT(*) FROM generation_jobs').fetchone()[0]==16
    # Old queued tasks become stale after a relevant fact change. A new valid
    # request must not be rejected merely because these were never claimed.
    state = service.store.get(rid)
    previous = state['version']
    state['campaign']['story_state']['facts']['lens'].update(value=True,revision=1)
    state['version'] += 1
    service.store.save(state,previous)
    assert service.enqueue(rid,'p','frontier15',now=102)['status']=='queued'
    with service.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM generation_jobs WHERE status='stale'").fetchone()[0]==16


def test_room_sweep_cleans_expired_queued_and_failed_jobs_without_claim(jobs):
    service,rid = jobs
    job = enqueue(jobs)
    assert service.prune_room(rid,now=701)==[job['id']]
    assert service.get(job['id'])['status']=='stale'
    second = service.enqueue(rid,'p','follow',now=702)
    worker = service.claim(second['id'],now=703)
    service.fail(second['id'],worker['lease_token'],now=704)
    assert service.prune_room(rid,now=1303)==[second['id']]
    assert service.get(second['id'])['status']=='stale'


def test_schema14_upgrade_backs_up_and_adds_jobs_without_changing_room(jobs,tmp_path):
    from backend.maintenance import SCHEMA_VERSION
    service,rid = jobs
    before = deepcopy(service.store.get(rid))
    with service.store.connect() as db:
        db.execute('DROP TABLE generation_jobs')
        db.execute('PRAGMA user_version=14')
    upgraded = GenerationJobs(Store(service.store.path))
    assert list((tmp_path/'backups').glob(f'pre-schema-{SCHEMA_VERSION}-*.zip'))
    assert upgraded.store.get(rid)==before
    assert upgraded.enqueue(rid,'p','follow',now=100)['status']=='queued'


def test_backup_restore_retains_running_lease_and_recovery_rejects_old_worker(jobs,tmp_path,monkeypatch):
    from backend import maintenance
    from backend.maintenance import backup_database,restore_backup
    service,rid = jobs
    job = enqueue(jobs)
    worker = service.claim(job['id'],now=101)
    archive = tmp_path/'jobs.zip'
    backup_database(service.store.path,archive)
    restore_backup(archive,tmp_path/'recovered')
    restored = GenerationJobs(Store(str(tmp_path/'recovered/database.sqlite3')))
    assert restored.get(job['id'])==worker
    assert restored.recover(now=191)==[job['id']]
    with pytest.raises(ValueError):restored.require_lease(job['id'],worker['lease_token'],now=192)
    assert restored.store.get(rid)==service.store.get(rid)
    monkeypatch.setattr(maintenance,'SCHEMA_VERSION',14)
    with pytest.raises(ValueError,match='newer server'):Store(service.store.path)
