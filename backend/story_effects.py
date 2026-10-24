"""Pure transactional story effects; never character resources or narration."""
from copy import deepcopy
import hashlib
import json

from pydantic import TypeAdapter

from . import story_graph as g, story_runtime as runtime
from .schemas import Identifier


def _effects(view, effects):
    g._preflight(effects)
    if not isinstance(effects, list) or len(effects) > 20:
        raise ValueError('剧情结果数量超过限制')
    values = [g.StoryEffect.model_validate(row).model_dump(mode='json') for row in effects]
    if len({(row['op'],row['ref']) for row in values}) != len(values):
        raise ValueError('不能重复修改相同剧情目标')
    definitions = {row['id']:row for row in view['book']['fact_definitions']}
    for row in values:
        if row['op'] == 'set_fact':
            definition = definitions.get(row['ref'])
            if not definition or not definition['mutable']:
                raise ValueError('不能改写未登记或不可变事实')
            if type(row['value']) is not {'boolean':bool,'integer':int,'string':str}[definition['value_type']]:
                raise ValueError('剧情结果的事实类型不匹配')
        elif row['op'] == 'milestone_state':
            if row['ref'] not in {item['id'] for item in view['book']['milestones']}:
                raise ValueError('里程碑未登记')
        elif row['ref'] not in view['book']['event_ids']:
            raise ValueError('剧情事件未登记')
    return values


def snapshot(view, story_state, effects):
    """Read target dependencies before a plan, without applying anything."""
    state = runtime.validate_state(view, story_state)
    result = {}
    for effect in _effects(view, effects):
        kind = {'set_fact':'facts','milestone_state':'milestones','event_occurred':'events'}[effect['op']]
        result[kind + ':' + effect['ref']] = deepcopy(state[kind][effect['ref']])
    return result


def preflight(view, story_state, effects):
    """Check an outcome without applying or simulating it, including terminal state."""
    state = runtime.validate_state(view, story_state)
    values = _effects(view, effects)
    for effect in values:
        if effect['op']=='milestone_state' and state['milestones'][effect['ref']]['value'] not in {'pending',effect['state']}:
            raise ValueError('剧情结果与已结算里程碑冲突')
    return snapshot(view,state,values)


def apply(view, story_state, effects, *, receipt_id, source_ref, success, expected_reads):
    """Return one new state atomically; caller saves it with roll/action receipts.

    Input state is unchanged on success, replay or any failure. This internal
    function is only called with the registered outcome selected by the engine.
    It neither creates knowledge grants nor moves players or awards resources.
    """
    receipt_id = TypeAdapter(Identifier).validate_python(receipt_id, strict=True)
    source_ref = TypeAdapter(Identifier).validate_python(source_ref, strict=True)
    state = runtime.validate_state(view, story_state)
    values = _effects(view, effects)
    if type(success) is not bool:
        raise ValueError('剧情结果必须来自已确认检定')
    registered = next((row for node in view['book']['nodes'] for row in node['challenges'] if row['id']==source_ref),None)
    if registered is None:
        raise ValueError('剧情结果来源未登记')
    expected_effects = _effects(view,registered['success_effects' if success else 'failure_effects'])
    if values != expected_effects:
        raise ValueError('请求与登记的剧情结果不一致')
    encoded = json.dumps(dict(source_ref=source_ref,success=success,effects=values), sort_keys=True,
                         ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    prior = state['effect_receipts'].get(receipt_id)
    if prior is not None:
        if prior != digest:
            raise ValueError('同一剧情回执不能执行不同结果')
        return dict(state=state, replayed=True, changes=[])
    if not isinstance(expected_reads, dict):
        raise ValueError('剧情结算需要服务器依赖快照')
    # All written targets must be in the original plan's read set.
    required = snapshot(view,state,values)
    if not set(required) <= set(expected_reads):
        raise ValueError('剧情计划缺少结果目标依赖')
    for key, expected in expected_reads.items():
        if not isinstance(key, str) or not isinstance(expected, dict) or set(expected) != {'value','revision'}:
            raise ValueError('剧情依赖快照形状无效')
        kind, separator, ref = key.partition(':')
        if not separator or kind not in {'facts','milestones','events','items'} or ref not in state[kind]:
            raise ValueError('剧情计划引用未登记事实')
        if type(expected['revision']) is not int or type(expected['value']) is not type(state[kind][ref]['value']) or state[kind][ref] != expected:
            raise ValueError('剧情事实已经变化，请重新裁定')
    changes = []
    for effect in values:
        kind = {'set_fact':'facts','milestone_state':'milestones','event_occurred':'events'}[effect['op']]
        target = state[kind][effect['ref']]
        value = effect['value'] if effect['op']=='set_fact' else effect['state'] if effect['op']=='milestone_state' else True
        if kind=='milestones' and target['value'] not in {'pending',value}:
            raise ValueError('已经结算的里程碑不能改写为另一个结果')
        if type(target['value']) is type(value) and target['value'] == value:
            continue
        before = deepcopy(target)
        target.update(value=value,revision=target['revision']+1)
        changes.append(dict(kind=kind,ref=effect['ref'],before=before,after=deepcopy(target)))
    state['effect_receipts'][receipt_id] = digest
    state['revision'] += 1
    # Validate the complete new state before returning any part of the change.
    state = runtime.validate_state(view,state)
    return dict(state=state,replayed=False,changes=changes)
