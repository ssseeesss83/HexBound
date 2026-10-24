"""Read-only plans for existing prototype handlers; never simulate execution.

Complete 2014 spatial/timing
semantics belong to the later engine profile, not to these prototype previews.
"""
from copy import deepcopy
import math
import time
import uuid

from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated, Literal

from . import abilities as a
from .rules_context import bound_rules
from .rules_identity import ENGINE_PROFILE, LEGACY_PACKAGE
from .source_audit import RULESET_ID

PLAN_TTL_SECONDS = 120
PLAN_SCHEMA_VERSION = 2


class Options(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    slot_level: int | None = Field(default=None, ge=1, le=9)
    slot_source: Literal['spell', 'pact'] | None = None
    target_ids: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=12)
    resource_amount: int | None = Field(default=None, ge=1, le=100)
    skill_id: str | None = Field(default=None, max_length=40)


def _clock(now):
    now = time.time() if now is None else now
    if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
        raise ValueError('Invalid plan time')
    return now


def _scope(state, actor):
    if not isinstance(state.get('id'), str) or not state['id']:
        raise ValueError('计划需要房间身份')
    if state.get('ruleset_id', RULESET_ID) != RULESET_ID:
        raise ValueError('规则版本不匹配')
    if state.get('engine_profile', ENGINE_PROFILE) != ENGINE_PROFILE:
        raise ValueError('当前计划器不支持这个结算配置')
    context = state.get('member_contexts', {}).get(actor, {})
    if context.get('scene_instance_id', 'scene-main') != state.get('_scene_execution_view', 'scene-main'):
        raise ValueError('角色不属于当前场景')
    return dict(room_id=state['id'], actor_id=actor,
                scene_instance_id=state.get('_scene_execution_view', 'scene-main'),
                membership_epoch=context.get('epoch', 1),
                ruleset_id=state.get('ruleset_id', RULESET_ID),
                rules_package_version=state.get('rules_package_version', LEGACY_PACKAGE),
                engine_profile=state.get('engine_profile', ENGINE_PROFILE))


def _weapon_target(state, actor, target_id):
    c = a.member(state, actor)['character']
    combat = a._combat(state)
    if not a.modern(c) or not combat or c.get('dead') or c.get('hp', 0) <= 0:
        raise ValueError('当前无法进行武器攻击')
    reason = a._budget_reason(state, actor, 'attack')
    if reason:
        raise ValueError(reason)
    living = [e for e in combat['enemies'] if e['hp'] > 0]
    target = next((e for e in living if e['id'] == target_id), None) if target_id else (living[0] if len(living) == 1 else None)
    if not target:
        raise ValueError('请选择存活的敌方目标')
    if c.get('position') == 'withdrawn' or target.get('position') == 'withdrawn':
        raise ValueError('目标已撤远，请先移动接近（抽象近战规则）')
    return target['id']


@bound_rules
def prepare(state, actor, action_id, target_id=None, options=None, *, now=None):
    """Validate current targets/options and freeze a plan without RNG or writes."""
    from .world_combat import validate_read_set
    from .director import _fingerprint
    scope = _scope(state, actor)
    if state.get('status', 'playing') != 'playing' or state.get('completed'):
        raise ValueError('当前不能提交行动计划')
    if target_id is not None and (not isinstance(target_id, str) or not 1 <= len(target_id) <= 80):
        raise ValueError('目标身份无效')
    now = _clock(now)
    opts = Options.model_validate({} if options is None else options).model_dump()
    if target_id and opts['target_ids'] and target_id not in opts['target_ids']:
        raise ValueError('单目标与目标列表不一致')
    validate_read_set(state)
    c = a.member(state, actor)['character']
    resources, restores = [], []
    executor = 'abilities'
    native_plan = None
    if opts['skill_id'] is not None and not action_id.startswith('story-check:'):
        raise ValueError('只有原生剧情挑战可选择检定方法')
    if action_id.startswith('story-check:'):
        from . import story_challenges
        from .director import SKILL_NAMES
        if target_id is not None or any(value not in (None, []) for key,value in opts.items() if key!='skill_id'):
            raise ValueError('剧情挑战只接受已登记的技能方法')
        native_plan = story_challenges.prepare(state,actor,action_id[12:],opts['skill_id'])
        cap = dict(label=native_plan['label'],action_cost='none',
                   description=f"确认后进行一次{SKILL_NAMES[native_plan['skill_id']]}检定，按已登记的剧情结果结算；同一证据下不能换方法重掷。")
        ids,resources = [],deepcopy(native_plan['resources'])
        normalized = dict(skill_id=native_plan['skill_id'])
        executor = 'story'
    elif not action_id.startswith(('cast:', 'feature:')) and action_id != 'end-concentration' and not (action_id == 'attack' and a.modern(c)):
        from .scenario_plans import prepare as prepare_scenario
        cap, ids, resources = prepare_scenario(state, actor, action_id, target_id, opts)
        target_id = ids[0] if len(ids) == 1 else None
        # A node check uses its authored skill internally, never client targets.
        if action_id.startswith('node:'):
            target_id = None
        normalized = {}
        executor = 'campaign' if state.get('campaign') else 'rules'
    elif action_id == 'attack':
        if opts['slot_level'] or opts['resource_amount'] or opts['target_ids'] or opts['slot_source'] not in (None, 'spell'):
            raise ValueError('普通攻击不接受额外能力参数')
        target_id = _weapon_target(state, actor, target_id)
        ids = [target_id]
        cap = dict(id=action_id, label='武器攻击', action_cost='attack', description='按当前原型武器处理器结算，不保证命中。')
        normalized = {}
    else:
        cap = next((row for row in a.capabilities(state, actor) if row['id'] == action_id), None)
        if not cap or not cap.get('supported') or cap.get('disabled_reason'):
            raise ValueError((cap.get('disabled_reason') if cap else None) or '角色未获得这个可执行能力')
        normalized = {}
        if action_id == 'end-concentration':
            if target_id not in (None, actor) or opts['target_ids'] not in ([], [actor]) or opts['slot_level'] or opts['resource_amount'] or opts['slot_source'] not in (None, 'spell'):
                raise ValueError('结束专注不接受额外目标或消耗')
            ids = [actor]
        elif action_id.startswith('cast:'):
            if opts['resource_amount'] is not None:
                raise ValueError('施法不接受职业资源点数')
            sid = action_id[5:]
            spell, recipe = a._spells()[sid], a._effects()[sid]
            level, source = a._select_slot(c, spell['level'], opts)
            maximum = recipe.get('max_targets', 1) + recipe.get('upcast_targets', 0) * max(0, level - spell['level'])
            _, ids = a._selected_targets(state, actor, cap, target_id, opts, maximum)
            if level:
                normalized.update(slot_level=level, slot_source=source)
                resources.append(dict(type='spell_slot', source=source, level=level, amount=1))
        elif action_id.startswith('feature:'):
            fid = action_id[8:]
            targets, ids = a._selected_targets(state, actor, cap, target_id, opts, 1)
            if opts['resource_amount'] is not None and fid != 'lay-on-hands':
                raise ValueError('这个能力不接受资源点数')
            if (opts['slot_level'] is not None or opts['slot_source'] not in (None, 'spell')) and fid not in {'divine-smite', 'arcane-recovery', 'font-of-magic'}:
                raise ValueError('这个能力不接受法术位选项')
            amount = 1
            if fid == 'divine-smite':
                _weapon_target(state, actor, ids[0])
                level, source = a._select_slot(c, 1, opts)
                normalized.update(slot_level=level, slot_source=source)
                resources.append(dict(type='spell_slot', source=source, level=level, amount=1, when='on_hit'))
            elif fid == 'flurry-of-blows':
                # The prototype executes two unarmed attacks, both on this target.
                combat = a._combat(state)
                if not combat or c.get('position') == 'withdrawn' or targets[0].get('position') == 'withdrawn':
                    raise ValueError('目标不在原型近战距离内')
            elif fid == 'lay-on-hands':
                maximum = min(a._resource(c, 'lay-on-hands'), targets[0]['max_hp'] - targets[0]['hp'])
                amount = opts['resource_amount'] if opts['resource_amount'] is not None else maximum
                if not 1 <= amount <= maximum:
                    raise ValueError('圣疗点数不合法')
                normalized['resource_amount'] = amount
            elif fid == 'arcane-recovery':
                if opts['slot_source'] not in (None, 'spell'):
                    raise ValueError('奥术回想不能恢复契约法术位')
                valid = [int(k) for k, pool in c.get('spell_slots', {}).items() if int(k) <= min(5, (c['level'] + 1) // 2) and pool['current'] < pool['max']]
                level = opts['slot_level'] if opts['slot_level'] is not None else max(valid, default=0)
                if level not in valid:
                    raise ValueError('奥术回想所选法术位不合法')
                normalized['slot_level'] = level
                restores.append(dict(type='spell_slot', source='spell', level=level, amount=1))
            elif fid == 'font-of-magic':
                if opts['slot_source'] not in (None, 'spell'):
                    raise ValueError('灵活施法不能恢复契约法术位')
                level = opts['slot_level'] or 1
                amount = {1:2, 2:3, 3:5, 4:6, 5:7}.get(level)
                pool = c.get('spell_slots', {}).get(str(level))
                if not amount or not pool or pool['current'] >= pool['max'] or a._resource(c, 'sorcery-points') < amount:
                    raise ValueError('当前无法用术法点恢复此环法术位（原型房规）')
                normalized['slot_level'] = level
                restores.append(dict(type='spell_slot', source='spell', level=level, amount=1))
            resource = cap.get('resource')
            if resource:
                unlimited = bool(c.get('resources', {}).get(resource, {}).get('unlimited'))
                resources.append(dict(type='class_resource', id=resource, amount=0 if unlimited else amount, unlimited=unlimited))
        else:
            raise ValueError('这个行动尚未接入能力计划器')
        normalized['target_ids'] = ids
        target_id = ids[0] if len(ids) == 1 else None
    visible = {member['id']: member['name'] for member in state['members']}
    visible.update({enemy['id']:enemy['name'] for enemy in (state.get('combat') or {}).get('enemies', [])})
    cost = cap.get('action_cost', 'none')
    budget = {}
    combat = a._combat(state)
    if combat:
        if cost == 'attack':
            starts_action = not combat.get('action_used')
            budget = dict(action=int(starts_action), attacks=1,
                          attack_allowance_granted=a.attacks_per_action(c) if starts_action else 0)
        elif cost in {'action', 'bonus'}:
            budget = {cost: 1}
    ends_concentration = None
    if c.get('concentration') and (action_id in {'end-concentration', 'feature:rage'}
            or (action_id.startswith('cast:') and a._effects()[action_id[5:]].get('concentration'))):
        ends_concentration = {key: c['concentration'][key] for key in ['spell_id', 'name'] if key in c['concentration']}
    result = dict(id=uuid.uuid4().hex, **scope, action_id=action_id, target_id=target_id,
                executor=executor, party_action=bool(cap.get('party_action')),
                options=deepcopy(normalized), targets=[dict(id=sid, name=visible[sid]) for sid in ids],
                label=cap['label'], action_cost=cost, budget=budget, ends_concentration=ends_concentration,
                resources=resources, restores=restores, summary=[cap.get('description', '')],
                expires_at=now + PLAN_TTL_SECONDS, fingerprint=_fingerprint(state),
                schema_version=PLAN_SCHEMA_VERSION)
    if native_plan is not None:
        result['story_plan'] = native_plan
    return result


@bound_rules
def revalidate(state, actor, plan, *, now=None):
    """Only server-stored plans may reach this function; no execution happens."""
    from .director import _fingerprint
    now = _clock(now)
    if plan.get('schema_version') != PLAN_SCHEMA_VERSION or now >= plan['expires_at']:
        raise ValueError('行动计划已过期，请重新选择')
    if any(plan.get(key) != value for key, value in _scope(state, actor).items()) or plan.get('fingerprint') != _fingerprint(state):
        raise ValueError('场景、角色或规则状态已变化，请重新选择')
    current = prepare(state, actor, plan['action_id'], plan['target_id'], plan['options'], now=now)
    for key in ['executor', 'party_action', 'action_id', 'target_id', 'options', 'targets', 'action_cost', 'budget', 'resources', 'restores', 'ends_concentration']:
        if current[key] != plan[key]:
            raise ValueError('行动的目标或代价已变化，请重新选择')
    if current.get('story_plan') != plan.get('story_plan'):
        raise ValueError('剧情检定的相关事实已变化，请重新裁定')
    return deepcopy(plan)


def describe_cost(plan):
    labels = {'action':'动作', 'bonus':'附赠动作', 'attacks':'攻击额度'}
    parts = [f"{labels[key]} {value}" for key, value in plan['budget'].items() if key in labels and value]
    for resource in plan['resources']:
        if resource['type'] == 'spell_slot':
            text = f"{resource['level']}环{'契约法术位' if resource['source'] == 'pact' else '法术位'} × {resource['amount']}"
        elif resource['type'] == 'inspiration_die':
            text = f"激励骰 {resource['dice']} × {resource['amount']}"
        else:
            text = f"{resource['id']} × {resource['amount']}" if not resource.get('unlimited') else f"{resource['id']} 不限次数"
        if resource.get('when') == 'on_hit':
            text += '（仅命中时消耗）'
        parts.append(text)
    if plan['ends_concentration'] is not None:
        parts.append('结束当前专注')
    return '；'.join(parts) or '不消耗当前已登记的规则资源'


def public_plan(plan):
    keys = ['action_id','target_id','options','targets','label','action_cost','budget',
            'resources','restores','summary','ends_concentration','expires_at']
    return {**{key:deepcopy(plan[key]) for key in keys}, 'cost_label':describe_cost(plan)}


@bound_rules
def menu(state, actor):
    """Same supported subset as prepare(), scoped to this actor's visible view."""
    result = [deepcopy(row) for row in a.capabilities(state, actor)
              if row.get('supported') and not row.get('disabled_reason')]
    targets = []
    for enemy in (state.get('combat') or {}).get('enemies', []):
        try:
            _weapon_target(state, actor, enemy['id'])
            targets.append(dict(id=enemy['id'], name=enemy['name']))
        except ValueError:
            continue
    if targets:
        result.append(dict(id='attack', label='武器攻击', kind='basic', target='enemy',
                           targets=targets, action_cost='attack'))
    from .story_challenges import menu as story_menu
    return result + story_menu(state,actor)
