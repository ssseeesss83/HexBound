"""Reviewed native routes and durable waiting; no model execution.

Only explicit public edge conditions govern routes. main_path is navigation;
key.advancement_condition describes conflict completion, not every exit's gate.
"""
from copy import deepcopy

from pydantic import TypeAdapter

from . import abilities, campaign, story_runtime, world_combat
from .action_plans import _scope
from .schemas import Identifier
from .story_challenges import _hash
from .rules_identity import LEGACY_PACKAGE


def _guard(state, actor, *, route=True):
    scope = _scope(state,actor)
    abilities.member(state,actor)
    if state.get('status')!='playing' or state.get('completed'):
        raise ValueError('当前不能审核路线')
    leader = state.get('_scene_leader_id',state.get('host_id',state.get('host_member_id')))
    leader_character = next((m['character'] for m in state['members'] if m['id']==leader),None)
    if leader_character and leader_character.get('dead'):
        survivors = campaign._conscious(state)
        if survivors: leader = survivors[0]['id']
    if actor != leader:
        raise ValueError('只有当前场景领队可以管理路线等待')
    if not route:
        return scope
    if abilities._combat(state) or not campaign._conscious(state):
        raise ValueError('请先完成战斗或恢复队伍行动能力')
    if not any(not any(abilities.has_condition(state,m['character'],cid) for cid in
                      ['incapacitated','paralyzed','stunned','unconscious','petrified'])
               for m in campaign._conscious(state)):
        raise ValueError('队伍当前失能，无法前往其他地点')
    world_combat.validate_read_set(state)
    return scope


def _source(state):
    current = state.get('campaign') or {}
    author = current.get('package',{}).get('scenario',{})
    if author.get('schema_version')!=2 or author['rules_package_version']!=state.get('rules_package_version',LEGACY_PACKAGE):
        raise ValueError('当前没有匹配规则包的原生剧情路线')
    if 'runtime_graph' not in current or 'story_state' not in current:
        raise ValueError('剧情运行状态未初始化')
    view = story_runtime.effective_book(author,current['runtime_graph'])
    facts = story_runtime.validate_state(view,current['story_state'])
    source = next((row for row in view['book']['nodes'] if row['id']==current['node_id']),None)
    if source is None or source['kind'] not in {'scene','key'}:
        raise ValueError('当前没有可审核路线')
    return view,facts,source


def available_edges(state, view, source):
    """Public routes and server retreat to a committed branch's visited fallback."""
    edges = [row for row in view['book']['edges'] if row['from']==source['id']
             and row['visibility']=='public' and row['legacy_action_id'] is None]
    commits = state['campaign']['runtime_graph']['commits']
    commit = next((row for row in commits
                   if source['id'].startswith('r'+row['job_id']+'_')),None)
    origin_job = commit['job_id'] if commit else None
    seen = set()
    while commit and commit['job_id'] not in seen:
        seen.add(commit['job_id'])
        frontier = next((n for n in view['book']['nodes'] if n['id']==commit['frontier_id']),None)
        fallback = (frontier.get('continuation') or {}).get('fallback_scene_id') if frontier else None
        target = next((n for n in view['book']['nodes'] if n['id']==fallback),None)
        if target and target['kind'] in {'scene','key'} and fallback!=source['id'] and fallback in state['campaign']['visited']:
            edge_id = 'back-'+origin_job
            # An author cannot suppress this exit by claiming the ID. Keep a
            # deterministic alternate ID if a frozen edge already uses it.
            while any(row['id']==edge_id for row in view['book']['edges']):
                edge_id = 'back-'+_hash(edge_id)[:32]
            edges.append(dict(id=edge_id, **{'from':source['id']}, to=fallback,
                label='返回此前的主线场景（保留已结算结果）',condition=None,
                visibility='public',priority=100,legacy_action_id=None))
            break
        # A child frontier may omit fallback or name an unvisited new scene.
        # Walk only its verified commit lineage to a visited ancestor fallback.
        commit = next((row for row in commits if frontier and
                       frontier['id'].startswith('r'+row['job_id']+'_')),None)
    return edges


def route_edge(state, view, source, edge_id):
    return next((row for row in available_edges(state,view,source) if row['id']==edge_id),None)


def prepare(state, actor, edge_id, *, prerequisite_receipt_ids=None):
    """Read current edge/target conditions without moving, revealing or rolling."""
    scope = _guard(state,actor)
    view,facts,source = _source(state)
    edge = route_edge(state,view,source,edge_id)
    if edge is None:
        raise ValueError('当前路线不可用')
    result = story_runtime.evaluate(edge['condition'],view,facts)
    if not result['value']:
        raise ValueError('当前路线不可用')
    destination = story_runtime.destination(view,edge['to'])
    reads = deepcopy(result['read_set'])
    if destination['status']=='ready':
        target = next(row for row in view['book']['nodes'] if row['id']==destination['node_id'])
        if target['kind']=='ending':
            ending = story_runtime.evaluate(target['ending_condition'],view,facts)
            if not ending['value']:
                raise ValueError('当前路线不可用')
            reads.update(ending['read_set'])
        staged = deepcopy(state)
        staged.pop('pending_transition',None)
        sid = scope['scene_instance_id']
        if sid in staged.get('scene_instances',{}):
            staged['scene_instances'][sid]['local'].pop('pending_transition',None)
        world_combat.preflight_place(staged,target['id'])
    proofs = [] if prerequisite_receipt_ids is None else prerequisite_receipt_ids
    if not isinstance(proofs,list) or len(proofs)>20 or not all(isinstance(row,str) for row in proofs) or len(set(proofs))!=len(proofs):
        raise ValueError('前置结算回执无效')
    for receipt in proofs:
        TypeAdapter(Identifier).validate_python(receipt,strict=True)
        if receipt not in facts['effect_receipts']:
            raise ValueError('前置结算回执不存在')
    return dict(scope=scope,source_node_id=source['id'],edge_id=edge['id'],
                author_digest=view['author_digest'],edge_digest=_hash(edge),
                destination=destination,read_set=reads,prerequisite_receipt_ids=sorted(proofs),
                pending_transition_id=(state.get('pending_transition') or {}).get('id'))


def _receipts(state):
    receipts = state['campaign'].get('transition_receipts',{})
    if not isinstance(receipts,dict) or len(receipts)>10000:
        raise ValueError('路线回执存储无效')
    return receipts


def request(state, actor, plan, *, transition_id):
    """Persist one wait on a copy. Replaying a cancelled wait cannot revive it."""
    transition_id = TypeAdapter(Identifier).validate_python(transition_id,strict=True)
    scope = _guard(state,actor)
    if scope != plan['scope']:
        raise ValueError('路线审核范围已经变化')
    receipts = _receipts(state)
    prior = receipts.get(transition_id)
    fingerprint = _hash(plan)
    if prior is not None:
        if prior['digest']!=fingerprint or prior['scope']!=scope:
            raise ValueError('同一路线回执不能用于不同请求')
        return dict(status=prior['status'],replayed=True)
    current = prepare(state,actor,plan['edge_id'],prerequisite_receipt_ids=plan['prerequisite_receipt_ids'])
    if _hash(current)!=fingerprint:
        raise ValueError('路线事实或出口已经变化，请重新审核')
    if plan['destination']['status']!='pending':
        raise ValueError('该路线已经可供审核，不需要等待')
    if state.get('pending_transition'):
        raise ValueError('已有路线等待，请先明确取消')
    if len(receipts)>=10000:
        raise ValueError('路线等待回执已达到上限')
    work = deepcopy(state)
    work['pending_transition'] = dict(id=transition_id,plan=deepcopy(plan))
    work['campaign'].setdefault('transition_receipts',{})[transition_id] = dict(
        digest=fingerprint,scope=deepcopy(scope),status='waiting')
    state.clear()
    state.update(work)
    return dict(status='waiting',replayed=False)


def cancel(state, actor, transition_id):
    """Explicit current-leader cancellation; generation/other scenes untouched."""
    _guard(state,actor,route=False)
    TypeAdapter(Identifier).validate_python(transition_id,strict=True)
    pending = state.get('pending_transition')
    receipts = _receipts(state)
    prior = receipts.get(transition_id)
    scene_id = _scope(state,actor)['scene_instance_id']
    if prior is None or prior['scope']['scene_instance_id']!=scene_id:
        raise ValueError('当前没有这个路线等待')
    if prior['status']=='cancelled':
        return dict(status='cancelled',replayed=True)
    if not pending or pending['id']!=transition_id:
        raise ValueError('路线等待已经变化')
    work = deepcopy(state)
    work['pending_transition'] = None
    work['campaign']['transition_receipts'][transition_id]['status'] = 'cancelled'
    state.clear()
    state.update(work)
    return dict(status='cancelled',replayed=False)


def status(state, actor):
    """Safe scene-local status; never return a contract, dependency or target."""
    pending = state.get('pending_transition')
    if not pending:
        return None
    try:
        plan = pending['plan']
        abilities.member(state,actor)
        if _scope(state,actor)['scene_instance_id']!=plan['scope']['scene_instance_id']:
            return dict(status='review_required')
        current = prepare(state,plan['scope']['actor_id'],plan['edge_id'],prerequisite_receipt_ids=plan['prerequisite_receipt_ids'])
        # A resolution changes destination and may add target dependencies. It
        # still requires a fresh review, and never triggers scene entry here.
        if current['scope']!=plan['scope'] or current['source_node_id']!=plan['source_node_id']:
            return dict(status='review_required')
        if any(current[key]!=plan[key] for key in ['author_digest','edge_digest']):
            return dict(status='review_required')
        if any(current['read_set'].get(key)!=value for key,value in plan['read_set'].items()):
            return dict(status='review_required')
        return dict(status='ready_for_review' if current['destination']['status']=='ready' else 'waiting')
    except (ValueError,KeyError):
        return dict(status='review_required')


def prepare_cancel(state, actor):
    scope = _guard(state,actor,route=False)
    pending = state.get('pending_transition')
    if not pending:
        raise ValueError('当前没有路线等待')
    receipt = _receipts(state).get(pending['id'])
    if not receipt or receipt['status']!='waiting' or receipt['scope']['scene_instance_id']!=scope['scene_instance_id']:
        raise ValueError('路线等待已经变化')
    return dict(scope=scope,transition_id=pending['id'])


def resolve(state, actor, plan, *, receipt_id):
    """Confirm a fresh server plan once, on a copy; no frontier is playable."""
    TypeAdapter(Identifier).validate_python(receipt_id,strict=True)
    scope = _guard(state,actor)
    receipts = _receipts(state)
    fingerprint = _hash(plan)
    prior = receipts.get(receipt_id)
    if prior is not None:
        if prior['digest']!=fingerprint or prior['scope']!=scope:
            raise ValueError('同一路线回执不能用于不同请求')
        return []
    current = prepare(state,actor,plan['edge_id'],prerequisite_receipt_ids=plan['prerequisite_receipt_ids'])
    if current!=plan:
        raise ValueError('路线或等待已经变化，请重新审核')
    pending = state.get('pending_transition')
    if pending and pending['plan']['edge_id']!=plan['edge_id']:
        raise ValueError('请先明确取消已有路线等待')
    if plan['destination']['status']=='pending':
        request(state,actor,plan,transition_id=receipt_id)
        return [campaign.rules.event('system','路线正在准备中。仍可在当前场景行动，也可取消等待。',actor_id=actor)]
    if len(receipts)>=10000:
        raise ValueError('路线回执已达到上限')
    work = deepcopy(state)
    work['pending_transition'] = None
    sid = scope['scene_instance_id']
    if sid in work.get('scene_instances',{}):
        work['scene_instances'][sid]['local'].pop('pending_transition',None)
    if pending:
        old = work['campaign'].get('transition_receipts',{}).get(pending['id'])
        if not old or old['status']!='waiting' or old['scope']['scene_instance_id']!=sid:
            raise ValueError('路线等待已经变化')
        old['status'] = 'entered'
    events = []
    campaign._enter(work,plan['destination']['node_id'],events)
    work['campaign'].setdefault('transition_receipts',{})[receipt_id] = dict(
        digest=fingerprint,scope=deepcopy(scope),status='entered')
    state.clear()
    state.update(work)
    return events


def resolve_cancel(state, actor, plan):
    if prepare_cancel(state,actor)!=plan:
        raise ValueError('路线等待已经变化，请重新审核')
    cancel(state,actor,plan['transition_id'])
    return [campaign.rules.event('system','已取消路线等待。',actor_id=actor)]


def menu(state, actor):
    """Only legal public choices; no target IDs, contracts or future prose."""
    result = []
    try:
        prepare_cancel(state,actor)
        result.append(dict(id='story-cancel',label='取消路线等待',kind='story_route',target='none',action_cost='none'))
    except (ValueError,KeyError):
        pass
    try:
        _guard(state,actor)
        view,_,source = _source(state)
    except (ValueError,KeyError):
        return result
    pending = state.get('pending_transition')
    for edge in sorted(available_edges(state,view,source),key=lambda row:(-row['priority'],row['id'])):
        if pending and pending['plan']['edge_id']!=edge['id']:
            continue
        try:
            plan = prepare(state,actor,edge['id'])
            if pending and plan['destination']['status']=='pending':
                continue
            result.append(dict(id='story-route:'+edge['id'],label=edge['label'],kind='story_route',target='none',action_cost='none'))
        except ValueError:
            continue
    return result
