"""Graph patch review rejects authority claims and never commits world changes."""
from copy import deepcopy
import json

import pytest

from backend import rules, story_patches as patches, story_runtime
from test_native_story_checks import table

JOB = 'a'*32


def candidate(state=None):
    state = table() if state is None else state
    auth = patches.grant(state,'p','follow',job_id=JOB,now=10)
    prefix = auth['namespace']
    patch = dict(job_id=JOB,base_graph_revision=auth['base_graph_revision'],scene_instance_id='scene-main',
        frontier_id='follow',entry_node_id=prefix+'street',read_set=deepcopy(auth['read_set']),
        new_nodes=[dict(id=prefix+'street',kind='scene',title='Street',text='The courier turns into a street.'),
                   dict(id=prefix+'next',kind='frontier',title='Continue',continuation=deepcopy(auth['continuation']))],
        new_edges=[dict(id=prefix+'onward',**{'from':prefix+'street'},to=prefix+'next')],
        continuation=deepcopy(auth['continuation']),source_metadata=dict(reason='A small local branch.'))
    return state,auth,patch


def test_review_is_pure_and_produces_valid_bounded_attachment_without_entry(monkeypatch):
    state,auth,patch = candidate()
    before = deepcopy(state)
    monkeypatch.setattr(rules,'roll_dice',lambda *a,**k:pytest.fail('Patch review rolled'))
    result = patches.review(state,auth,patch,now=11)
    assert state == before and result.job_id==JOB
    graph = json.loads(result.graph_json)
    view = story_runtime.effective_book(state['campaign']['package']['scenario'],graph)
    assert story_runtime.destination(view,'follow')['node_id']==patch['entry_node_id']
    assert state['campaign']['node_id']=='dock' and graph['graph_revision']==1
    assert graph['commits'][0]['patch_digest']==result.patch_digest
    assert 'new_entities' in json.loads(result.payload_json)


@pytest.mark.parametrize('change',[
    'extra_hp','job','scene','revision','continuation','reads','overwrite_node','frozen_edge_source',
    'bad_monster','new_object','new_entity','legacy','ending','bad_reference','unreachable','dead_leaf',
    'initial_true','premise','new_challenge','ungranted_fact','four_playable','deep','cycle',
])
def test_invalid_patch_is_wholly_rejected_without_mutation(change):
    state,auth,patch = candidate()
    prefix = auth['namespace']
    if change=='extra_hp':patch['hp']=99
    elif change=='job':patch['job_id']='b'*32
    elif change=='scene':patch['scene_instance_id']='other'
    elif change=='revision':patch['base_graph_revision']=1
    elif change=='continuation':patch['continuation']['summary']='Changed frozen intent'
    elif change=='reads':patch['read_set']['facts:lens']['value']=True
    elif change=='overwrite_node':patch['new_nodes'][0]['id']='dock'
    elif change=='frozen_edge_source':patch['new_edges'][0]['from']='dock'
    elif change=='bad_monster':patch['new_nodes'][0]['monster_ids']=['invented']
    elif change=='new_object':patch['new_nodes'][0]['objects']=[dict(id='loot',name='Loot')]
    elif change=='new_entity':patch['new_entities']=[dict(id=prefix+'npc',kind='npc',name='An NPC')]
    elif change=='legacy':patch['new_nodes'][0]['legacy_actions']=[dict(id='go',label='Go',next_node_id='dock')]
    elif change=='ending':patch['new_nodes'][0].update(kind='ending',ending_condition=None)
    elif change=='bad_reference':patch['new_edges'][0]['condition']=dict(op='fact_equals',ref='invented',value=True)
    elif change=='unreachable':patch['new_nodes'].append(dict(id=prefix+'unreachable',kind='scene',title='Missing',text='Lost'))
    elif change=='dead_leaf':patch['new_edges']=[]
    elif change in {'initial_true','premise'}:
        patch['new_fact_definitions']=[dict(id=prefix+'fact',kind='premise' if change=='premise' else 'state',
            value_type='boolean',mutable=change!='premise',initial=change=='initial_true',visibility='public',description='New state')]
    elif change=='new_challenge':
        challenge = deepcopy(state['campaign']['package']['scenario']['nodes'][0]['challenges'][0])
        challenge.update(id=prefix+'challenge',objective_key='invented-new-goal')
        patch['new_nodes'][0].update(place_id='harbor',challenges=[challenge])
    elif change=='ungranted_fact':patch['new_edges'][0]['condition']=dict(op='has_item',ref='lens-item')
    elif change in {'four_playable','deep','cycle'}:
        count = 3 if change=='four_playable' else 2
        for i in range(count):patch['new_nodes'].append(dict(id=prefix+str(i),kind='scene',title='Scene',text='Text'))
        patch['new_edges']=[dict(id=prefix+'first',**{'from':prefix+'street'},to=prefix+'0')]
        for i in range(count):patch['new_edges'].append(dict(id=prefix+'edge'+str(i),
            **{'from':prefix+str(i)},to=prefix+str(i+1) if i+1<count else prefix+'next'))
        if change=='cycle':patch['new_edges'].append(dict(id=prefix+'cycle',**{'from':prefix+'0'},to=prefix+'street'))
    before = deepcopy(state)
    with pytest.raises(ValueError):patches.review(state,auth,patch,now=11)
    assert state == before


@pytest.mark.parametrize('change',['expired','paused','epoch','scope','source','fact','fact_revision','graph','audience','package'])
def test_stale_grant_cannot_validate_a_returned_result(change):
    state,auth,patch = candidate()
    now = 131 if change=='expired' else 11
    if change=='paused':state['status']='paused'
    elif change=='epoch':state['member_contexts']={'p':dict(scene_instance_id='scene-main',epoch=2)}
    elif change=='scope':state['member_contexts']={'p':dict(scene_instance_id='other',epoch=2)}
    elif change=='source':state['campaign']['node_id']='follow'
    elif change in {'fact','fact_revision'}:
        state['campaign']['story_state']['facts']['lens'].update(value=change=='fact',revision=1)
    elif change=='graph':
        from test_native_story_checks import extend_graph
        extend_graph(state)
    elif change=='audience':state['members'].pop()
    elif change=='package':state['campaign']['package']['monsters']['invented']={'hp':99}
    before = deepcopy(state)
    with pytest.raises(ValueError):patches.review(state,auth,patch,now=now)
    assert state == before


def test_chat_and_unrelated_fact_do_not_expire_valid_grant():
    from test_story_challenges import authored
    book = authored()
    book['fact_definitions'].append(dict(id='unrelated',kind='state',value_type='integer',initial=0,
                                        mutable=True,visibility='scoped',description='Other activity'))
    state,auth,patch = candidate(table(book))
    state['version']=999
    state['events'].append(dict(kind='chat',text='A discussion'))
    state['campaign']['story_state']['facts']['unrelated'].update(value=1,revision=1)
    assert patches.review(state,auth,patch,now=11)


def test_neutral_new_fact_is_registered_on_candidate_copy_without_confirming_it():
    state,auth,patch = candidate()
    fid = auth['namespace']+'observed'
    patch['new_fact_definitions']=[dict(id=fid,kind='knowledge',value_type='boolean',mutable=True,
                                      initial=False,visibility='scoped',description='A future observation')]
    result = patches.review(state,auth,patch,now=11)
    assert json.loads(result.state_json)['facts'][fid]==dict(value=False,revision=0)
    assert fid not in state['campaign']['story_state']['facts']


def test_guessing_existing_ending_id_cannot_create_unauthorized_rejoin():
    from test_story_challenges import authored
    book = authored()
    book['nodes'].append(dict(id='end',kind='ending',title='End',text='Frozen ending',
                             ending_condition=dict(op='fact_equals',ref='lens',value=True)))
    book['edges'].append(dict(id='old-end',**{'from':'dock'},to='end'))
    state,auth,patch = candidate(table(book))
    patch['new_edges'].append(dict(id=auth['namespace']+'rejoin',**{'from':patch['entry_node_id']},to='end'))
    with pytest.raises(ValueError,match='未授权'):patches.review(state,auth,patch,now=11)


def test_authorized_fallback_rejoin_is_allowed_without_rewriting_existing_exit():
    state,auth,patch = candidate()
    patch['new_edges'].append(dict(id=auth['namespace']+'rejoin',**{'from':patch['entry_node_id']},to='dock'))
    assert patches.review(state,auth,patch,now=11)


def test_alias_cannot_remove_or_change_registered_preconditions():
    from test_story_challenges import authored
    book = authored()
    book['nodes'][0]['challenges'][0]['condition']=dict(op='fact_equals',ref='lens',value=True)
    book['nodes'][1]['continuation']['confirmed_fact_ids'].append('weather')
    state,auth,patch = candidate(table(book))
    alias = deepcopy(story_runtime.node(state,'dock')['challenges'][0])
    alias['id']=auth['namespace']+'alias'
    patch['new_nodes'][0].update(place_id='harbor',challenges=[alias])
    assert patches.review(state,auth,patch,now=11)
    alias['condition']=None
    with pytest.raises(ValueError,match='已有挑战规则'):patches.review(state,auth,patch,now=11)


@pytest.mark.parametrize('place',['hidden-vault','unknown-place'])
def test_guessing_unauthorized_place_id_is_rejected(place):
    state,auth,patch = candidate()
    patch['new_nodes'][0]['place_id']=place
    with pytest.raises(ValueError,match='生成地点'):patches.review(state,auth,patch,now=11)


def test_explicit_new_place_requires_job_namespace_and_cannot_collide_with_existing_world():
    state,auth,patch = candidate()
    pid = auth['namespace']+'new-place'
    patch['new_nodes'][0]['place_id']=pid
    assert patches.review(state,auth,patch,now=11)
    state['world_places']={pid:dict(revision=0)}
    with pytest.raises(ValueError,match='生成地点'):patches.review(state,auth,patch,now=11)


def test_authorized_existing_place_revision_change_invalidates_grant():
    state = table()
    state['world_places']={'harbor':dict(revision=0)}
    state,auth,patch = candidate(state)
    state['world_places']['harbor']['revision']=1
    with pytest.raises(ValueError,match='已经变化'):patches.review(state,auth,patch,now=11)


def test_implicit_generated_place_cannot_collide_with_existing_physical_world():
    state,auth,patch = candidate()
    pid = 'place:sparse:'+patch['entry_node_id']
    state['world_places']={pid:dict(revision=0)}
    with pytest.raises(ValueError,match='物理地点'):patches.review(state,auth,patch,now=11)


@pytest.mark.parametrize('change',['constraints','monster_scope','milestone_scope','npc_scope','fallback','forget_fact','forget_thread','forget_goal','forget_milestone'])
def test_child_continuation_cannot_drop_constraints_or_expand_frozen_scope(change):
    state,auth,patch = candidate()
    child = patch['new_nodes'][1]['continuation']
    if change=='constraints':child['constraints']=['A different constraint']
    elif change=='monster_scope':child['allowed_monster_ids'].append('invented-monster')
    elif change=='milestone_scope':child['candidate_milestone_ids'].append('invented-milestone')
    elif change=='npc_scope':child['npc_goal_ids'].append('invented-goal')
    elif change=='fallback':child['fallback_scene_id']='invented-place'
    elif change=='forget_fact':child['confirmed_fact_ids']=[]
    elif change=='forget_thread':child['unresolved_threads']=['An unrelated thread']
    elif change=='forget_goal':child['npc_goal_ids']=[]
    elif change=='forget_milestone':child['candidate_milestone_ids']=[]
    with pytest.raises(ValueError):patches.review(state,auth,patch,now=11)
