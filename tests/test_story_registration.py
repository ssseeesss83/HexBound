"""New clues compile to one stable target with server-owned mechanics."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
import re

import pytest

from backend import rules,story_challenges,story_patches,story_registration as registry,story_semantics
from test_story_patches import candidate
from test_generation_commit import Provider
from test_generation_jobs import jobs,enqueue


def clue_patch():
    state,auth,patch = candidate()
    prefix = auth['namespace']
    patch['new_nodes'][0]['place_id']=prefix+'site'
    patch['new_fact_definitions']=[dict(id=prefix+'resolved',kind='state',value_type='boolean',initial=False,
        mutable=True,visibility='scoped',description='This clue has been resolved, not whether its contents are true.')]
    patch['new_entities']=[dict(kind='clue',id=prefix+'clue',node_id=patch['entry_node_id'],
        resolution_fact_id=prefix+'resolved',name='Courier marks',internal_description='SECRET_CLUE_INTERNAL')]
    patch['new_challenges']=[dict(node_id=patch['entry_node_id'],target_clue_id=prefix+'clue',method_recipe='observe',
        difficulty='easy',label='Study the marks',success_text='The marks reveal a route.',failure_text='The marks remain unclear.')]
    return state,auth,patch


def apply_candidate(state,result,node_id):
    state['campaign']['runtime_graph']=json.loads(result.graph_json)
    state['campaign']['story_state']=json.loads(result.state_json)
    state['campaign']['node_id']=state['scene_id']=node_id
    state['scene']=next(deepcopy(row) for row in state['campaign']['runtime_graph']['nodes'] if row['id']==node_id)


def test_registration_is_deterministic_pure_and_does_not_resolve_or_reveal_clue():
    state,auth,patch = clue_patch()
    before = deepcopy(state)
    result = story_patches.review(state,auth,patch,now=11)
    assert result==story_patches.review(state,auth,patch,now=11) and state==before
    graph = json.loads(result.graph_json)
    clue = graph['narrative_entities'][0]
    challenge = graph['nodes'][0]['challenges'][0]
    assert challenge['id']==clue['challenge_id'] and challenge['dc']==10
    assert challenge['skill_ids']==['investigation','perception'] and challenge['question_id']=='resolve-clue'
    assert challenge['evidence_fact_ids']==[] and challenge['failure_effects']==[]
    assert clue['resolution_fact_id'] in graph['nodes'][1]['continuation']['confirmed_fact_ids']
    assert clue['lineage']==['follow'] and graph['commits'][0]['compiled_digest']==result.compiled_digest
    assert graph['fact_definitions'][0]['visibility']=='dm_secret'
    assert 'does not assert clue truth' in graph['fact_definitions'][0]['description']
    assert json.loads(result.state_json)['facts'][clue['resolution_fact_id']]==dict(value=False,revision=0)


@pytest.mark.parametrize('change',['recipe','difficulty','dc','effects','id','existing_fact','frontier_node','cross_node',
    'duplicate_target','duplicate_fact','missing_request','existing_place','initial_true','truth_premise','duplicate_name'])
def test_invalid_target_or_client_mechanics_never_register(change):
    state,auth,patch = clue_patch()
    clue,request = patch['new_entities'][0],patch['new_challenges'][0]
    if change=='recipe':request['method_recipe']='invented'
    elif change=='difficulty':request['difficulty']='automatic'
    elif change=='dc':request['dc']=1
    elif change=='effects':request['success_effects']=[dict(op='grant_item',ref='lens-item')]
    elif change=='id':request['id']='new-retry'
    elif change=='existing_fact':clue['resolution_fact_id']='lens'
    elif change=='frontier_node':clue['node_id']=patch['new_nodes'][1]['id']
    elif change=='cross_node':request['node_id']=patch['new_nodes'][1]['id']
    elif change=='duplicate_target':patch['new_challenges'].append(deepcopy(request))
    elif change in {'duplicate_fact','duplicate_name'}:
        other = deepcopy(clue)
        other['id']=auth['namespace']+'other-clue'
        if change=='duplicate_name':
            other['name']='  COURIER   MARKS '
            fact = deepcopy(patch['new_fact_definitions'][0]);fact['id']=auth['namespace']+'other-resolved'
            patch['new_fact_definitions'].append(fact);other['resolution_fact_id']=fact['id']
        patch['new_entities'].append(other)
        other_request=deepcopy(request);other_request['target_clue_id']=other['id']
        patch['new_challenges'].append(other_request)
    elif change=='missing_request':patch['new_challenges']=[]
    elif change=='existing_place':patch['new_nodes'][0]['place_id']='harbor'
    elif change=='initial_true':patch['new_fact_definitions'][0]['initial']=True
    elif change=='truth_premise':patch['new_fact_definitions'][0]['kind']='knowledge'
    before = deepcopy(state)
    with pytest.raises(ValueError):story_patches.review(state,auth,patch,now=11)
    assert state==before


def test_failed_clue_cannot_retry_with_method_member_or_generated_same_place_alias(monkeypatch):
    state,auth,patch = clue_patch()
    result = story_patches.review(state,auth,patch,now=11)
    apply_candidate(state,result,patch['entry_node_id'])
    challenge = state['scene']['challenges'][0]
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:0)
    story_challenges.resolve(state,'p',story_challenges.prepare(state,'p',challenge['id']),receipt_id='failed-clue')
    with pytest.raises(ValueError):story_challenges.prepare(state,'ally',challenge['id'],'perception')
    frontier = patch['new_nodes'][1]['id']
    next_auth = story_patches.grant(state,'p',frontier,job_id='b'*32,now=20)
    _,_,next_patch = candidate(state,next_auth)
    alias = deepcopy(challenge)
    alias['id']=next_auth['namespace']+'alias'
    next_patch['new_nodes'][0].update(place_id=patch['new_nodes'][0]['place_id'],challenges=[alias])
    followup = story_patches.review(state,next_auth,next_patch,now=21)
    apply_candidate(state,followup,next_patch['entry_node_id'])
    with pytest.raises(ValueError):story_challenges.prepare(state,'ally',alias['id'],'perception')


def test_success_only_resolves_own_marker_without_item_reward_or_internal_description(monkeypatch):
    state,auth,patch = clue_patch()
    result = story_patches.review(state,auth,patch,now=11)
    apply_candidate(state,result,patch['entry_node_id'])
    cid = state['scene']['challenges'][0]['id']
    monkeypatch.setattr(rules.secrets,'randbelow',lambda n:n-1)
    events = story_challenges.resolve(state,'p',story_challenges.prepare(state,'p',cid),receipt_id='clue-success')
    assert events[0]['roll']['success']
    assert state['campaign']['story_state']['facts'][patch['new_entities'][0]['resolution_fact_id']]['value'] is True
    assert not state.get('reward_ledger') and state['campaign']['story_state']['items']['lens-item']['value'] is False
    assert 'SECRET_CLUE_INTERNAL' not in str(events) and all('knowledge' not in m for m in state['members'])


def test_semantic_approval_binds_compiled_mechanics_and_recipe_changes_stale_grant(monkeypatch):
    state,auth,patch = clue_patch()
    result = story_patches.review(state,auth,patch,now=11)
    provider = Provider()
    approval = asyncio.run(story_semantics.review(provider,state,auth,result))
    assert provider.context['compiled_nodes'][0]['challenges'][0]['dc']==10
    with pytest.raises(ValueError):approval.verify(auth,replace(result,compiled_digest='0'*64))
    monkeypatch.setitem(registry.DIFFICULTIES,'easy',11)
    with pytest.raises(ValueError):story_patches.review(state,auth,patch,now=11)


def test_typical_difficulty_table_is_source_based_but_method_groups_are_product_recipes():
    from backend import compendium
    pages=json.loads((compendium.DATA_DIR/'official/pages.json').read_text(encoding='utf-8'))
    text=re.sub(r'\s+',' ',pages[76]['text'])
    for phrase in ['Very easy 5','Easy 10','Medium 15','Hard 20','Very hard 25','Nearly impossible 30']:
        assert phrase in text
    assert sorted(registry.DIFFICULTIES.values())==[5,10,15,20,25,30]


def test_semantic_review_cannot_inspect_forged_compiled_nodes_under_real_digest():
    state,auth,patch = clue_patch()
    result=story_patches.review(state,auth,patch,now=11)
    graph=json.loads(result.graph_json)
    graph['nodes'][0]['challenges'][0]['dc']=5
    provider=Provider()
    with pytest.raises(ValueError):
        asyncio.run(story_semantics.review(provider,state,auth,replace(result,graph_json=json.dumps(graph))))
    assert provider.context is None


def test_worker_commits_one_registration_and_backup_preserves_bound_mechanics(jobs,tmp_path,monkeypatch):
    from backend import maintenance,story_generation
    from backend.generation_jobs import GenerationJobs
    from backend.maintenance import backup_database,restore_backup
    from backend.store import Store
    from test_story_generation import Provider as GenerationProvider
    service,rid=jobs
    before=deepcopy(service.store.get(rid))
    with service.store.connect() as db:db.execute('PRAGMA user_version=16')
    service=GenerationJobs(Store(service.store.path))
    assert list((tmp_path/'backups').glob(f'pre-schema-{maintenance.SCHEMA_VERSION}-*.zip'))
    job=service.enqueue(rid,'p','follow',now=100)
    class ClueProvider(GenerationProvider):
        async def _complete(self,system,data,*args,**kwargs):
            text=await super()._complete(system,data,*args,**kwargs)
            if 'proposed_patch' in data:return text
            patch=json.loads(text);prefix=data['namespace']
            patch['new_fact_definitions']=[dict(id=prefix+'resolved',kind='state',value_type='boolean',initial=False,
                mutable=True,visibility='scoped',description='Clue is resolved')]
            patch['new_entities']=[dict(kind='clue',id=prefix+'clue',node_id=patch['entry_node_id'],
                resolution_fact_id=prefix+'resolved',name='Courier marks',internal_description='INTERNAL_REGISTRATION')]
            patch['new_challenges']=[dict(node_id=patch['entry_node_id'],target_clue_id=prefix+'clue',
                method_recipe='observe',difficulty='easy',label='Study marks',success_text='A route emerges.',failure_text='Unclear.')]
            return json.dumps(patch)
    result=asyncio.run(story_generation.run(service,ClueProvider(),job['id'],clock=lambda:101))
    assert result['status']=='committed'
    saved=service.store.get(rid)
    assert len(saved['campaign']['runtime_graph']['narrative_entities'])==1
    clue=saved['campaign']['runtime_graph']['narrative_entities'][0]
    assert saved['campaign']['story_state']['facts'][clue['resolution_fact_id']]['value'] is False
    assert saved['campaign']['node_id']==before['campaign']['node_id'] and saved['members']==before['members']
    persisted=service.get(job['id'])
    assert persisted['output']['approval']['compiled_digest']==persisted['commit_receipt']['compiled_digest']
    assert asyncio.run(story_generation.run(service,ClueProvider(),job['id'],clock=lambda:102))['status']=='not_claimed'
    archive=tmp_path/'registered.zip'
    backup_database(service.store.path,archive)
    restore_backup(archive,tmp_path/'registered-restore')
    restored=Store(str(tmp_path/'registered-restore/database.sqlite3'))
    assert restored.get(rid)['campaign']['runtime_graph']==saved['campaign']['runtime_graph']
    monkeypatch.setattr(maintenance,'SCHEMA_VERSION',16)
    with pytest.raises(ValueError,match='newer server'):Store(restored.path)
