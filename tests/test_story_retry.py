"""Explicit one-attempt budget reviews cannot reset ordinary enqueue budgets."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import asyncio
import json
import sqlite3
import pytest

from backend import generation_jobs,maintenance,scene_storage,story_requests as requests,story_generation
from backend.generation_jobs import GenerationJobs
from backend.store import Store
from test_generation_jobs import jobs,enqueue
from test_story_requests import waiting
from test_story_generation import Provider
from test_native_story_checks import extend_graph


def exhausted(jobs):
    service,rid=jobs
    waiting(jobs)
    job=requests.bind(service,rid,'p','wait1',now=100)['job']
    for now in (101,110,120):
        lease=service.claim(job['id'],now=now)
        service.mark_dispatch(job['id'],lease['lease_token'],'generation',now=now)
        service.fail(job['id'],lease['lease_token'],now=now)
    job=service.get(job['id'])
    assert job['status']=='terminal_failed'
    return job


def save(service,rid,mutate):
    state=service.store.get(rid)
    version=state['version']
    mutate(state)
    state['version']+=1
    service.store.save(state,version)


def test_review_is_pure_and_confirmation_adds_exactly_one_attempt_without_replaying_actions(jobs):
    service,rid=jobs
    old=exhausted(jobs)
    before=service.store.get(rid)
    plan=requests.prepare_retry(service,rid,'p',now=121)
    assert service.store.get(rid)==before and service.get(old['id'])==old
    result=requests.confirm_retry(service,rid,'p',plan,now=122)
    new=result['job']
    assert not result['replayed'] and new['retry_of']==old['id'] and new['retry_receipt_id']==plan['id']
    assert new['budget']['max_attempts']==1 and new['attempts']==0
    assert new['dispatches']==dict(generation=0,semantic=0)
    assert service.get(old['id'])==old
    saved=service.store.get(rid)
    for field in ('action_revision','members','campaign','reward_ledger','progression'):
        assert saved.get(field)==before.get(field)
    assert saved['pending_transition']['generation_job_id']==new['id']
    # Scene-local receipt survives the next ordinary room save.
    save(service,rid,lambda state:None)
    assert requests.confirm_retry(service,rid,'p',plan,now=123)==dict(job=new,replayed=True)
    assert requests.confirm_retry(service,rid,'p',plan,now=242)==dict(job=new,replayed=True)
    assert enqueue(jobs)['id']==new['id']


def test_two_distinct_reviews_concurrently_create_only_one_successor(jobs):
    service,rid=jobs
    old=exhausted(jobs)
    plans=[requests.prepare_retry(service,rid,'p',now=121) for _ in range(2)]
    def confirm(plan):
        try:return requests.confirm_retry(service,rid,'p',plan,now=122)
        except ValueError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(confirm,plans))
    assert sum(item is not None for item in results)==1
    with service.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM generation_jobs WHERE json_extract(payload,'$.retry_of')=?",(old['id'],)).fetchone()[0]==1


@pytest.mark.parametrize('fault',['job','binding'])
def test_any_sql_failure_rolls_back_job_binding_and_receipt(jobs,fault):
    service,rid=jobs
    old=exhausted(jobs)
    plan=requests.prepare_retry(service,rid,'p',now=121)
    before=service.store.get(rid)
    trigger=("BEFORE INSERT ON generation_jobs" if fault=='job' else "AFTER UPDATE ON rooms")
    with service.store.connect() as db:
        db.execute("CREATE TRIGGER broken_retry "+trigger+" BEGIN SELECT RAISE(ABORT,'fault'); END")
    with pytest.raises(sqlite3.IntegrityError):requests.confirm_retry(service,rid,'p',plan,now=122)
    assert service.store.get(rid)==before and service.get(old['id'])==old
    with service.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM generation_jobs').fetchone()[0]==1
        db.execute('DROP TRIGGER broken_retry')
    assert not requests.confirm_retry(service,rid,'p',plan,now=123)['replayed']


@pytest.mark.parametrize('change',['cancel','combat','dead','epoch','ready','source','condition'])
def test_confirmation_rechecks_current_world_and_authority(jobs,change):
    service,rid=jobs
    exhausted(jobs)
    plan=requests.prepare_retry(service,rid,'p',now=121)
    def mutate(state):
        if change=='cancel':state['pending_transition']=None
        elif change=='combat':state['combat']=dict(active=True)
        elif change=='dead':
            for member in state['members']:member['character'].update(hp=0,dead=True)
        elif change=='epoch':state['member_contexts']['p']['epoch']+=1
        elif change=='ready':extend_graph(state)
        elif change=='source':state['campaign']['node_id']='missing'
        elif change=='condition':
            state['campaign']['story_state']['facts']['lens'].update(value=True,revision=1)
    save(service,rid,mutate)
    before=service.store.get(rid)
    with pytest.raises(ValueError):requests.confirm_retry(service,rid,'p',plan,now=122)
    assert service.store.get(rid)==before


def test_expired_or_expanded_plan_and_other_actor_are_rejected(jobs):
    service,rid=jobs
    exhausted(jobs)
    plan=requests.prepare_retry(service,rid,'p',now=121)
    with pytest.raises(ValueError):requests.confirm_retry(service,rid,'p',plan,now=241)
    with pytest.raises(ValueError):requests.confirm_retry(service,rid,'ally',plan,now=122)
    expanded=deepcopy(plan);expanded['budget']['max_attempts']=3
    with pytest.raises(ValueError):requests.confirm_retry(service,rid,'p',expanded,now=122)


def test_revoked_scope_cannot_replay_a_successful_budget_receipt(jobs):
    service,rid=jobs
    exhausted(jobs)
    plan=requests.prepare_retry(service,rid,'p',now=121)
    requests.confirm_retry(service,rid,'p',plan,now=122)
    save(service,rid,lambda state:state['member_contexts']['p'].update(epoch=2))
    before=service.store.get(rid)
    with pytest.raises(ValueError):requests.confirm_retry(service,rid,'p',plan,now=123)
    assert service.store.get(rid)==before


def test_a_wait_revoked_before_review_cannot_be_reauthorized_by_retry(jobs):
    service,rid=jobs
    exhausted(jobs)
    save(service,rid,lambda state:state['member_contexts']['p'].update(epoch=2))
    before=service.store.get(rid)
    with pytest.raises(ValueError):requests.prepare_retry(service,rid,'p',now=121)
    assert service.store.get(rid)==before


def test_historical_unknown_dispatches_are_preserved_in_retry_lineage(jobs):
    service,rid=jobs
    old=exhausted(jobs)
    old['dispatches']=None
    with service.store.connect() as db:generation_jobs._save(db,old)
    plan=requests.prepare_retry(service,rid,'p',now=121)
    new=requests.confirm_retry(service,rid,'p',plan,now=122)['job']
    assert new['retry_of']==old['id'] and service.get(old['id'])['dispatches'] is None


def test_retry_failure_is_exhausted_again_and_ordinary_enqueue_cannot_reset_it(jobs):
    service,rid=jobs
    old=exhausted(jobs)
    plan=requests.prepare_retry(service,rid,'p',now=121)
    new=requests.confirm_retry(service,rid,'p',plan,now=122)['job']
    lease=service.claim(new['id'],now=123)
    service.mark_dispatch(new['id'],lease['lease_token'],'generation',now=123)
    service.fail(new['id'],lease['lease_token'],now=124)
    failed=service.get(new['id'])
    assert failed['status']=='terminal_failed' and failed['attempts']==1
    assert enqueue(jobs)['id']==new['id']
    assert requests.confirm_retry(service,rid,'p',plan,now=125)==dict(job=failed,replayed=True)
    with pytest.raises(ValueError):service.require_lease(new['id'],old['id'],now=125)


def test_retry_success_only_makes_route_reviewable_and_old_task_cannot_commit(jobs):
    service,rid=jobs
    old=exhausted(jobs)
    plan=requests.prepare_retry(service,rid,'p',now=121)
    new=requests.confirm_retry(service,rid,'p',plan,now=122)['job']
    assert asyncio.run(story_generation.run(service,Provider(),new['id'],clock=lambda:123))['status']=='committed'
    assert service.claim(old['id'],now=124) is None
    saved=service.store.get(rid)
    assert saved['campaign']['node_id']=='dock' and saved['campaign']['visited']==['dock']
    assert requests.public_status(service,saved,'p',now=124)==dict(status='ready_for_review')


def test_schema20_restore_keeps_retry_receipt_and_rejects_schema19_server(jobs,tmp_path,monkeypatch):
    service,rid=jobs
    exhausted(jobs)
    with service.store.connect() as db:db.execute('PRAGMA user_version=19')
    service=GenerationJobs(Store(service.store.path))
    assert list((tmp_path/'backups').glob('pre-schema-20-*.zip'))
    plan=requests.prepare_retry(service,rid,'p',now=121)
    result=requests.confirm_retry(service,rid,'p',plan,now=122)
    archive=tmp_path/'retry.zip'
    maintenance.backup_database(service.store.path,archive)
    maintenance.restore_backup(archive,tmp_path/'retry-restored')
    restored=GenerationJobs(Store(str(tmp_path/'retry-restored/database.sqlite3')))
    assert requests.confirm_retry(restored,rid,'p',plan,now=123)==dict(job=result['job'],replayed=True)
    monkeypatch.setattr(maintenance,'SCHEMA_VERSION',19)
    with pytest.raises(ValueError,match='newer server'):Store(service.store.path)
