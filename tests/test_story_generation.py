"""Bounded workers call providers outside locks and reject late callbacks."""
import asyncio
from copy import deepcopy
import json

import pytest

from backend import story_generation
from test_generation_jobs import jobs, enqueue


class Provider:
    configured = True
    def __init__(self,mode='valid',hook=None):
        self.mode,self.hook = mode,hook
        self.calls = []
    async def _complete(self,system,data,*args,**kwargs):
        self.calls.append(deepcopy(data))
        if self.hook:await self.hook(len(self.calls))
        if 'proposed_patch' in data:
            return json.dumps(dict(verdict='reject' if self.mode=='reject' else 'accept',
                reasons=['Checked the frozen outline.'],issues=['Contradiction'] if self.mode=='reject' else []))
        if self.mode=='raise':raise RuntimeError('SECRET_PROVIDER_EXCEPTION')
        if self.mode=='invalid':return json.dumps(dict(hp=99))
        if self.mode=='recursive':return '['*1100+']'*1100
        prefix = data['namespace']
        patch = deepcopy(data['binding'])
        patch.update(scene_instance_id=data['scene_instance_id'],entry_node_id=prefix+'street',
            new_nodes=[dict(id=prefix+'street',kind='scene',title='Street',text='A side street offers another view.'),
                       dict(id=prefix+'next',kind='frontier',title='Continue',continuation=deepcopy(patch['continuation']))],
            new_edges=[dict(id=prefix+'onward',**{'from':prefix+'street'},to=prefix+'next')],
            source_metadata=dict(reason='Continue the courier thread.'))
        return json.dumps(patch)


def test_worker_generates_reviews_and_commits_without_entry_or_repeating(jobs):
    service,rid = jobs
    job = enqueue(jobs)
    before = deepcopy(service.store.get(rid))
    provider = Provider()
    result = asyncio.run(story_generation.run(service,provider,job['id'],clock=lambda:101))
    assert result['status']=='committed' and len(provider.calls)==2
    saved = service.store.get(rid)
    assert saved['campaign']['runtime_graph']['graph_revision']==1
    assert saved['campaign']['node_id']==before['campaign']['node_id'] and saved['members']==before['members']
    assert 'events' not in provider.calls[0] and 'director' not in provider.calls[0]
    assert asyncio.run(story_generation.run(service,provider,job['id'],clock=lambda:102))['status']=='not_claimed'
    assert len(provider.calls)==2


@pytest.mark.parametrize('mode,calls',[('invalid',1),('recursive',1),('raise',1),('reject',2),('offline',0)])
def test_invalid_provider_results_or_unavailability_leave_current_scene_playable(jobs,mode,calls):
    service,rid = jobs
    job = enqueue(jobs)
    before = deepcopy(service.store.get(rid))
    provider = Provider(mode)
    if mode=='offline':provider.configured=False
    result = asyncio.run(story_generation.run(service,provider,job['id'],clock=lambda:101))
    assert result['status']=='retryable_failed' and len(provider.calls)==calls
    assert service.store.get(rid)==before
    assert 'SECRET_PROVIDER_EXCEPTION' not in str(service.get(job['id']))


def test_provider_call_holds_no_database_transaction_and_late_changed_fact_rejects(jobs):
    service,rid = jobs
    job = enqueue(jobs)
    async def mutate(call):
        if call==1:
            state = service.store.get(rid)
            previous = state['version']
            state['campaign']['story_state']['facts']['lens'].update(value=True,revision=1)
            state['version'] += 1
            service.store.save(state,previous)
    provider = Provider(hook=mutate)
    result = asyncio.run(story_generation.run(service,provider,job['id'],clock=lambda:101))
    assert result['status']=='stale' and len(provider.calls)==1
    assert service.store.get(rid)['campaign']['runtime_graph']['graph_revision']==0


def test_dependency_change_during_semantic_call_cannot_commit(jobs):
    service,rid = jobs
    job = enqueue(jobs)
    async def mutate(call):
        if call==2:
            state = service.store.get(rid)
            previous = state['version']
            state['campaign']['story_state']['facts']['lens'].update(value=True,revision=1)
            state['version'] += 1
            service.store.save(state,previous)
    result = asyncio.run(story_generation.run(service,Provider(hook=mutate),job['id'],clock=lambda:101))
    assert result['status']=='stale'
    assert service.store.get(rid)['campaign']['runtime_graph']['graph_revision']==0


def test_worker_cancellation_revokes_its_lease(jobs):
    service,_ = jobs
    job = enqueue(jobs)
    async def scenario():
        entered = asyncio.Event()
        async def block(call):
            entered.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(story_generation.run(service,Provider(hook=block),job['id'],clock=lambda:101))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(scenario())
    assert service.get(job['id'])['status']=='cancelled'


def test_cancelled_old_worker_cannot_cancel_a_recovered_replacement(jobs):
    service,_ = jobs
    job = enqueue(jobs)
    async def scenario():
        entered = asyncio.Event()
        async def block(call):
            entered.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(story_generation.run(service,Provider(hook=block),job['id'],clock=lambda:101))
        await entered.wait()
        service.recover(now=191)
        new_worker = service.claim(job['id'],now=193)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert service.require_lease(job['id'],new_worker['lease_token'],now=194)['status']=='running'
    asyncio.run(scenario())


@pytest.mark.parametrize('stage',[1,2])
@pytest.mark.parametrize('revoke_first',[False,True])
def test_provider_suppressing_cancellation_still_cannot_write_revoked_result(jobs,stage,revoke_first):
    service,rid = jobs
    job = enqueue(jobs)
    before = deepcopy(service.store.get(rid))
    async def scenario():
        entered,release = asyncio.Event(),asyncio.Event()
        async def block(call):
            if call!=stage:return
            entered.set()
            try:await release.wait()
            except asyncio.CancelledError:await release.wait()
        provider = Provider(hook=block)
        task = asyncio.create_task(story_generation.run(service,provider,job['id'],clock=lambda:101))
        await entered.wait()
        if revoke_first:service.cancel(job['id'])
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):await task
        assert len(provider.calls)==stage
    asyncio.run(scenario())
    assert service.store.get(rid)==before
    assert service.get(job['id'])['status']=='cancelled'


def test_timeout_is_bounded_and_does_not_write_a_scene(jobs):
    service,rid = jobs
    job = enqueue(jobs,budget=dict(timeout_seconds=1))
    before = deepcopy(service.store.get(rid))
    async def block(call):await asyncio.Event().wait()
    result = asyncio.run(story_generation.run(service,Provider(hook=block),job['id'],clock=lambda:101))
    assert result['status']=='retryable_failed' and service.store.get(rid)==before
