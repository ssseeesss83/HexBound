"""Pure route review and durable waiting, never entry or model execution.

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


def prepare(state, actor, edge_id, *, prerequisite_receipt_ids=None):
    """Read current edge/target conditions without moving, revealing or rolling."""
    scope = _guard(state,actor)
    view,facts,source = _source(state)
    edge = next((row for row in view['book']['edges'] if row['id']==edge_id
                 and row['from']==source['id'] and row['visibility']=='public'
                 and row['legacy_action_id'] is None),None)
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
                destination=destination,read_set=reads,prerequisite_receipt_ids=sorted(proofs))


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
