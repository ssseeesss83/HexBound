"""Bounded graph-patch review. This module does not commit jobs or enter scenes.

The grant is server-owned input, never a model/client authorization claim.
Structural acceptance is not semantic approval of free narrative text.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import math
import time
from typing import Annotated

from pydantic import Field

from . import session_scope, story_graph as g, story_runtime as runtime
from .action_plans import _scope
from .schemas import Identifier, StrictModel
from .story_challenges import _hash
from .story_effects import snapshot
from .story_transitions import _source

JobID = Annotated[str,Field(pattern=r'^[0-9a-f]{32}$')]


class SourceNote(StrictModel):
    reason: str = Field(min_length=1,max_length=500)


class GraphPatch(StrictModel):
    job_id: JobID
    base_graph_revision: int = Field(ge=0)
    scene_instance_id: str = Field(min_length=1,max_length=100)
    frontier_id: Identifier
    entry_node_id: Identifier
    read_set: dict[str,runtime.ValueState] = Field(max_length=600)
    new_nodes: list[g.StoryNode] = Field(min_length=2,max_length=5)
    new_edges: list[g.StoryEdge] = Field(min_length=1,max_length=8)
    new_fact_definitions: list[g.FactDefinition] = Field(default_factory=list,max_length=10)
    # Typed physical/narrative entity registration is a later boundary. Unknown
    # raw entities are rejected rather than silently ignored or materialized.
    new_entities: list[dict] = Field(default_factory=list,max_length=0)
    continuation: g.Continuation
    source_metadata: SourceNote


@dataclass(frozen=True)
class ReviewedPatch:
    job_id: str
    patch_digest: str
    payload_json: str
    graph_json: str
    state_json: str


def _now(value):
    value = time.time() if value is None else value
    if type(value) not in {float,int} or not math.isfinite(value):
        raise ValueError('剧情任务时间无效')
    return value


def namespace(job_id):
    from pydantic import TypeAdapter
    return 'r'+TypeAdapter(JobID).validate_python(job_id,strict=True)+'_'


def _json(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def grant(state, actor, frontier_id, *, job_id, now=None, ttl=120):
    """Freeze necessary planner facts and authority, without a task/model call."""
    if type(ttl) is not int or not 1<=ttl<=600:
        raise ValueError('剧情任务期限无效')
    prefix = namespace(job_id)
    scope = _scope(state,actor)
    from .abilities import member
    member(state,actor)
    if state.get('status')!='playing' or state.get('completed'):
        raise ValueError('当前不能规划剧情扩展')
    from .world_combat import validate_read_set
    validate_read_set(state)
    view,facts,source = _source(state)
    frontier = next((node for node in view['book']['nodes']
                     if node['id']==frontier_id and node['kind']=='frontier'),None)
    if frontier is None or frontier_id in view['frontier_resolutions']:
        raise ValueError('续写出口不存在或已经完成')
    # Scope grants are only issued for a nearby reachable frontier, not an
    # arbitrary hidden distant branch supplied by a user/model.
    reachable = {source['id']}
    for _ in range(2):
        reachable |= {edge['to'] for edge in view['book']['edges'] if edge['from'] in reachable}
    if frontier_id not in reachable:
        raise ValueError('续写出口不属于当前邻近分支')
    contract = frontier['continuation']
    refs = {'facts:'+sid for sid in contract['confirmed_fact_ids']}
    refs |= {'facts:'+row['id'] for row in view['book']['fact_definitions'] if row['kind']=='premise'}
    refs |= {'milestones:'+sid for sid in contract['candidate_milestone_ids']}
    reads = {key:deepcopy(facts[key.split(':',1)[0]][key.split(':',1)[1]]) for key in sorted(refs)}
    for node in view['book']['nodes']:
        if node['id'] in {source['id'],contract['fallback_scene_id']}:
            for challenge in node['challenges']:
                reads.update(runtime.evaluate(challenge['condition'],view,facts)['read_set'])
                reads.update({'facts:'+sid:deepcopy(facts['facts'][sid]) for sid in challenge['evidence_fact_ids']})
                for field in ['success_effects','failure_effects']:
                    reads.update(snapshot(view,facts,challenge[field]))
    staged = deepcopy(state)
    session_scope.initialize(staged)
    allowed_places = {node['place_id'] for node in view['book']['nodes']
                      if node['id'] in {source['id'],contract['fallback_scene_id']} and node['place_id'] is not None}
    return dict(job_id=job_id,scope=scope,source_node_id=source['id'],frontier_id=frontier_id,
                namespace=prefix,author_digest=view['author_digest'],base_graph_revision=view['graph_revision'],
                package_digest=_hash(state['campaign']['package']),
                audience=session_scope.audience_key(staged),read_set=reads,
                member_epochs={m['id']:state.get('member_contexts',{}).get(m['id'],{}).get('epoch',1) for m in state['members']},
                rejoin_node_ids=[contract['fallback_scene_id']] if contract['fallback_scene_id'] else [],
                allowed_existing_place_ids=sorted(allowed_places),
                place_read_set={pid:state.get('world_places',{}).get(pid,{}).get('revision') for pid in sorted(allowed_places)},
                entity_read_set={eid:state['world_entities'][eid]['revision']
                                 for eid in sorted(set(state.get('_object_read_set',{})) | set(state.get('_creature_read_set',{})))},
                continuation=deepcopy(contract),expires_at=_now(now)+ttl)


def _check_grant(state, authorization, now):
    if _now(now)>=authorization['expires_at']:
        raise ValueError('剧情扩展授权已过期')
    fresh = grant(state,authorization['scope']['actor_id'],authorization['frontier_id'],
                  job_id=authorization['job_id'],now=0,ttl=1)
    for key in fresh:
        if key!='expires_at' and _hash(fresh[key])!=_hash(authorization[key]):
            raise ValueError('剧情扩展的范围、图版本或相关事实已经变化')


def _depth(nodes,edges,entry):
    """New playable nodes form a shallow DAG; existing rejoin loops stay frozen."""
    table = {row['id']:row for row in nodes}
    depths,visiting = {},set()
    def visit(sid,depth):
        if sid not in table or table[sid]['kind']=='frontier':
            return
        if sid in visiting or depth>2:
            raise ValueError('生成分支超过两层或包含新循环')
        if depth<=depths.get(sid,0):
            return
        depths[sid]=depth
        visiting.add(sid)
        for edge in edges:
            if edge['from']==sid:visit(edge['to'],depth+1)
        visiting.remove(sid)
    visit(entry,1)


def review(state, authorization, raw, *, now=None):
    """Validate the complete candidate on copies, returning internal artifacts.

    It still needs semantic review, a valid persistent lease, and a transaction
    that rechecks the original grant before any graph/job write.
    """
    _check_grant(state,authorization,now)
    g._preflight(raw)
    patch = GraphPatch.model_validate(raw).model_dump(mode='json',by_alias=True)
    for key in ['job_id','frontier_id','base_graph_revision','continuation','read_set']:
        if _hash(patch[key])!=_hash(authorization[key]):
            raise ValueError('模型补丁不能替换服务器授权或依赖')
    if patch['scene_instance_id']!=authorization['scope']['scene_instance_id']:
        raise ValueError('模型补丁不属于当前场景')
    prefix = authorization['namespace']
    nodes,edges,new_facts = patch['new_nodes'],patch['new_edges'],patch['new_fact_definitions']
    for rows in [nodes,edges,new_facts]:
        if any(not row['id'].startswith(prefix) for row in rows):
            raise ValueError('新条目必须使用任务专属命名空间')
    new_ids = {row['id'] for row in nodes}
    entry = next((row for row in nodes if row['id']==patch['entry_node_id']),None)
    if entry is None or entry['kind'] not in {'scene','key'}:
        raise ValueError('续写入口必须是新增可玩节点')
    if sum(row['kind'] in {'scene','key'} for row in nodes)>3:
        raise ValueError('单次最多生成三个可玩节点')
    if any(edge['from'] not in new_ids or edge['legacy_action_id'] is not None for edge in edges):
        raise ValueError('补丁不能改已有节点出口或创建旧行动桥')
    if any(edge['to'] not in new_ids and edge['to'] not in authorization['rejoin_node_ids'] for edge in edges):
        raise ValueError('补丁不能猜测未授权的已有汇合点')
    if any(node['kind']=='ending' or node['legacy_actions'] or node['objects'] for node in nodes):
        raise ValueError('首版扩展不创建结局、旧行动或未登记实体')
    allowed_monsters = set(authorization['continuation']['allowed_monster_ids'])
    frozen_monsters = state['campaign']['package'].get('monsters',{})
    view,facts,_ = _source(state)
    registered = {}
    for node in view['book']['nodes']:
        for row in node['challenges']:
            if node['place_id'] is not None:
                key = (node['place_id'],row['objective_key'],row['question_id'])
                registered.setdefault(key,[]).append(dict(mechanics=g.challenge_mechanics(row),condition=row['condition']))
    for node in nodes:
        pid = node['place_id']
        derived_pid = pid or 'place:'+view['book']['id']+':'+node['id']
        if derived_pid in state.get('world_places',{}) and derived_pid not in authorization['allowed_existing_place_ids']:
            raise ValueError('生成地点不能占用未授权的已有物理地点')
        if pid is not None and pid not in authorization['allowed_existing_place_ids']:
            if not pid.startswith(prefix) or pid in state.get('world_places',{}):
                raise ValueError('生成地点必须是任务专属新地点或明确授权的已有地点')
        if set(node['monster_ids'])-allowed_monsters or set(node['monster_ids'])-set(frozen_monsters):
            raise ValueError('生成遭遇只能引用续写契约内的冻结怪兽卡')
        for challenge in node['challenges']:
            key = (node['place_id'],challenge['objective_key'],challenge['question_id'])
            definition = dict(mechanics=g.challenge_mechanics(challenge),condition=challenge['condition'])
            if not challenge['id'].startswith(prefix) or definition not in registered.get(key,[]):
                raise ValueError('新目标须先登记；补丁只能复用同地点已有挑战规则')
        contract = node['continuation']
        if contract:
            parent = authorization['continuation']
            if (any(not set(parent[field])<=set(contract[field]) for field in
                    ['constraints','confirmed_fact_ids','unresolved_threads','npc_goal_ids','candidate_milestone_ids'])
                    or any(set(contract[field])-set(parent[field]) for field in
                           ['allowed_monster_ids','candidate_milestone_ids','npc_goal_ids'])):
                raise ValueError('续写不能放宽冻结约束或扩大既有依赖授权')
            fallback = contract['fallback_scene_id']
            if fallback and fallback not in new_ids and fallback not in authorization['rejoin_node_ids']:
                raise ValueError('续写不能指定未授权的已有 fallback')
    for fact in new_facts:
        neutral = {'boolean':False,'integer':0,'string':''}[fact['value_type']]
        if fact['kind']=='premise' or not fact['mutable'] or type(fact['initial']) is not type(neutral) or fact['initial']!=neutral:
            raise ValueError('生成不能宣称新世界前提或已确认事实')
    _depth(nodes,edges,patch['entry_node_id'])
    graph = deepcopy(state['campaign']['runtime_graph'])
    graph['nodes'] += nodes
    graph['edges'] += edges
    graph['fact_definitions'] += new_facts
    graph['graph_revision'] += 1
    graph['frontier_resolutions'][patch['frontier_id']] = patch['entry_node_id']
    identity = _hash(patch)
    graph['commits'].append(dict(job_id=patch['job_id'],revision=graph['graph_revision'],patch_digest=identity,
                                 frontier_id=patch['frontier_id'],entry_node_id=patch['entry_node_id']))
    result = runtime.effective_book(state['campaign']['package']['scenario'],graph)
    updated_facts = deepcopy(facts)
    for fact in new_facts:updated_facts['facts'][fact['id']]=dict(value=fact['initial'],revision=0)
    runtime.validate_state(result,updated_facts)
    # Existing references must have been frozen in the planner's input. The
    # model cannot add a dependency after seeing the world change.
    old_refs = set()
    def collect(value):
        if isinstance(value,list):
            for row in value:collect(row)
        elif isinstance(value,dict):
            op = value.get('op')
            if op in {'fact_equals','has_item','event_occurred','milestone_state','set_fact'}:
                kind = {'fact_equals':'facts','set_fact':'facts','has_item':'items',
                        'event_occurred':'events','milestone_state':'milestones'}[op]
                if value['ref'] in facts[kind]:old_refs.add(kind+':'+value['ref'])
            for row in value.values():collect(row)
    collect(nodes)
    collect(edges)
    for node in nodes:
        for challenge in node['challenges']:
            old_refs |= {'facts:'+sid for sid in challenge['evidence_fact_ids'] if sid in facts['facts']}
        if node['continuation']:
            old_refs |= {'facts:'+sid for sid in node['continuation']['confirmed_fact_ids'] if sid in facts['facts']}
            old_refs |= {'milestones:'+sid for sid in node['continuation']['candidate_milestone_ids']}
    if old_refs-set(authorization['read_set']):
        raise ValueError('补丁引用了授权输入之外的既有事实')
    return ReviewedPatch(patch['job_id'],identity,_json(patch),_json(graph),_json(updated_facts))
