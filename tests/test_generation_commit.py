"""Independent narrative review, latest-state writes and one atomic receipt."""
import asyncio
from copy import deepcopy
import json
import sqlite3

import pytest

from backend import story_patches, story_semantics, story_transitions
from backend.generation_jobs import GenerationJobs
from backend.store import Store
from test_generation_jobs import jobs, enqueue
from test_story_patches import candidate


class Provider:
    configured = True
    def __init__(self,text=None):
        self.text = text or json.dumps(dict(verdict='accept',reasons=['Preserves the declared courier thread.'],issues=[]))
        self.context = None
    async def _complete(self,system,context,*args,**kwargs):
        self.context = deepcopy(context)
        return self.text


def reviewed(jobs,*,provider=None):
    service,rid = jobs
    job = enqueue(jobs)
    worker = service.claim(job['id'],now=101)
    state = service.store.get(rid)
    _,_,raw = candidate(state,worker['authorization'])
    patch = story_patches.review(state,worker['authorization'],raw,now=102)
    approval = asyncio.run(story_semantics.review(provider or Provider(),state,worker['authorization'],patch))
    return worker,patch,approval


def validate(service,worker,patch,approval):
    return service.validate_output(worker['id'],worker['lease_token'],patch,approval,now=103)


def test_review_then_atomic_commit_and_replay_never_enters_or_moves(jobs):
    service,rid = jobs
    state = service.store.get(rid)
    previous = state['version']
    story_transitions.request(state,'p',story_transitions.prepare(state,'p','follow-courier'),transition_id='wait1')
    state['version'] += 1
    service.store.save(state,previous)
    before = deepcopy(service.store.get(rid))
    provider = Provider()
    worker,patch,approval = reviewed(jobs,provider=provider)
    validated = validate(service,worker,patch,approval)
    assert validated['status']=='validated' and service.store.get(rid)==before
    assert 'events' not in provider.context and 'director' not in provider.context
    result = service.commit(worker['id'],worker['lease_token'],now=104)
    saved = service.store.get(rid)
    assert saved['campaign']['runtime_graph']['graph_revision']==1 and not result['replayed']
    assert saved['campaign']['node_id']==before['campaign']['node_id']=='dock'
    assert saved['campaign']['visited']==before['campaign']['visited']
    assert saved['members']==before['members'] and saved['events']==before['events']
    assert saved['campaign']['story_state']==before['campaign']['story_state']
    assert saved['pending_transition']==before['pending_transition']
    assert story_transitions.status(saved,'p')==dict(status='ready_for_review')
    assert service.get(worker['id'])['status']=='committed'
    assert service.commit(worker['id'],worker['lease_token'],now=999)['replayed']
    assert service.store.get(rid)==saved
    with pytest.raises(ValueError):service.commit(worker['id'],'wrong',now=105)


def test_database_failure_rolls_back_both_graph_and_job_receipt(jobs):
    service,rid = jobs
    worker,patch,approval = reviewed(jobs)
    validate(service,worker,patch,approval)
    before = deepcopy(service.store.get(rid))
    old_job = deepcopy(service.get(worker['id']))
    with service.store.connect() as db:
        db.execute("CREATE TRIGGER fail_graph_commit BEFORE UPDATE ON generation_jobs WHEN NEW.status='committed' BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):service.commit(worker['id'],worker['lease_token'],now=104)
    assert service.store.get(rid)==before and service.get(worker['id'])==old_job
    with service.store.connect() as db:db.execute('DROP TRIGGER fail_graph_commit')
    assert not service.commit(worker['id'],worker['lease_token'],now=105)['replayed']


@pytest.mark.parametrize('change',['cancelled','expired','fact','scope','graph'])
def test_stale_or_revoked_worker_cannot_commit_validated_output(jobs,change):
    service,rid = jobs
    worker,patch,approval = reviewed(jobs)
    validate(service,worker,patch,approval)
    now = 191 if change=='expired' else 104
    if change=='cancelled':service.cancel(worker['id'])
    elif change in {'fact','scope','graph'}:
        state = service.store.get(rid)
        previous = state['version']
        if change=='fact':state['campaign']['story_state']['facts']['lens'].update(value=True,revision=1)
        elif change=='scope':
            state['member_contexts']['p']['epoch'] += 1
            state['text_scope']['members']['p']['epoch'] += 1
        elif change=='graph':
            from test_native_story_checks import extend_graph
            extend_graph(state)
        state['version'] += 1
        service.store.save(state,previous)
    before = deepcopy(service.store.get(rid))
    old_job = deepcopy(service.get(worker['id']))
    with pytest.raises(ValueError):service.commit(worker['id'],worker['lease_token'],now=now)
    assert service.store.get(rid)==before and service.get(worker['id'])==old_job


def test_unrelated_changes_during_review_survive_commit(jobs):
    from backend.story_runtime import initialize
    service,rid = jobs
    state = service.store.get(rid)
    previous = state['version']
    book = state['campaign']['package']['scenario']
    book['fact_definitions'].append(dict(id='other',kind='state',value_type='integer',initial=0,
        mutable=True,visibility='scoped',description='Unrelated activity'))
    state['campaign'].update(initialize(book))
    state['version'] += 1
    service.store.save(state,previous)
    worker,patch,approval = reviewed(jobs)
    validate(service,worker,patch,approval)
    state = service.store.get(rid)
    previous = state['version']
    state['campaign']['story_state']['facts']['other'].update(value=5,revision=1)
    state['version'] += 1
    service.store.save(state,previous)
    service.commit(worker['id'],worker['lease_token'],now=104)
    assert service.store.get(rid)['campaign']['story_state']['facts']['other']==dict(value=5,revision=1)


@pytest.mark.parametrize('text',[
    'not JSON',json.dumps(dict(verdict='reject',reasons=['Contradicts confirmed state'],issues=['Resurrects an NPC'])),
    json.dumps(dict(verdict='accept',reasons=['Uncertain'],issues=['Missing evidence'])),
    json.dumps(dict(verdict='accept',reasons=[],issues=[])),
    json.dumps(dict(verdict='accept',reasons=['Okay'],issues=[],hp=99)),
])
def test_malformed_or_negative_semantic_review_never_approves_or_writes(jobs,text):
    service,rid = jobs
    before = deepcopy(service.store.get(rid))
    with pytest.raises(ValueError):reviewed(jobs,provider=Provider(text))
    assert service.store.get(rid)==before


def test_no_provider_has_no_fallback_approval(jobs):
    provider = Provider()
    provider.configured = False
    with pytest.raises(ValueError,match='尚不可用'):reviewed(jobs,provider=provider)


def test_approval_cannot_be_rebound_to_another_patch(jobs):
    service,rid = jobs
    worker,patch,approval = reviewed(jobs)
    changed = json.loads(patch.payload_json)
    changed['new_nodes'][0]['text']='A different proposed narrative.'
    other = story_patches.review(service.store.get(rid),worker['authorization'],changed,now=102)
    with pytest.raises(ValueError):validate(service,worker,other,approval)
    assert service.get(worker['id'])['status']=='running'


def test_restart_validated_job_rechecks_and_commits_once(jobs):
    service,rid = jobs
    worker,patch,approval = reviewed(jobs)
    validate(service,worker,patch,approval)
    restored = GenerationJobs(Store(service.store.path))
    assert not restored.commit(worker['id'],worker['lease_token'],now=104)['replayed']
    assert restored.commit(worker['id'],worker['lease_token'],now=105)['replayed']


def test_concurrent_commit_has_one_attachment_and_one_replay(jobs):
    from concurrent.futures import ThreadPoolExecutor
    service,rid = jobs
    worker,patch,approval = reviewed(jobs)
    validate(service,worker,patch,approval)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:service.commit(worker['id'],worker['lease_token'],now=104),range(2)))
    assert sorted(result['replayed'] for result in results)==[False,True]
    assert len(service.store.get(rid)['campaign']['runtime_graph']['commits'])==1


def test_schema16_upgrade_and_validated_backup_restore_keep_review_binding(jobs,tmp_path,monkeypatch):
    from backend import maintenance
    from backend.maintenance import backup_database,restore_backup
    service,rid = jobs
    worker,patch,approval = reviewed(jobs)
    with service.store.connect() as db:db.execute('PRAGMA user_version=15')
    service = GenerationJobs(Store(service.store.path))
    assert list((tmp_path/'backups').glob(f'pre-schema-{maintenance.SCHEMA_VERSION}-*.zip'))
    validate(service,worker,patch,approval)
    archive = tmp_path/'reviewed.zip'
    backup_database(service.store.path,archive)
    restore_backup(archive,tmp_path/'reviewed-restore')
    restored = GenerationJobs(Store(str(tmp_path/'reviewed-restore/database.sqlite3')))
    assert restored.get(worker['id'])['output']['approval']==approval.model_dump(mode='json')
    assert not restored.commit(worker['id'],worker['lease_token'],now=104)['replayed']
    assert restored.store.get(rid)['campaign']['runtime_graph']['graph_revision']==1
    monkeypatch.setattr(maintenance,'SCHEMA_VERSION',15)
    with pytest.raises(ValueError,match='newer server'):Store(restored.store.path)
