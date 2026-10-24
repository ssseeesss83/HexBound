"""Server-registered native story checks, with one evidence and effect boundary.

Not an HTTP surface. Existing publishers and campaign start still reject v2.
"""
from copy import deepcopy
import hashlib
import json
from pydantic import TypeAdapter

from . import abilities, attempts, rules, story_effects, story_graph, story_runtime, world_environment
from .rules_context import bound_rules
from .rules_identity import ENGINE_PROFILE, LEGACY_PACKAGE
from .schemas import Identifier


def _hash(value):
    try:
        encoded = json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    except (TypeError,ValueError) as exc:
        raise ValueError('剧情计划不是有效 JSON') from exc
    return hashlib.sha256(encoded).hexdigest()


def _source(state, challenge_id):
    campaign = state.get('campaign') or {}
    book = campaign.get('package',{}).get('scenario',{})
    if book.get('schema_version') != 2:
        raise ValueError('当前剧本没有原生挑战注册')
    if book['rules_package_version'] != state.get('rules_package_version',LEGACY_PACKAGE):
        raise ValueError('剧本与房间规则包不一致')
    if 'runtime_graph' not in campaign or 'story_state' not in campaign:
        raise ValueError('原生剧情运行状态未初始化')
    view = story_runtime.effective_book(book,campaign['runtime_graph'])
    current = next((node for node in view['book']['nodes'] if node['id']==campaign['node_id']),None)
    if current is None or current['kind'] not in {'scene','key'}:
        raise ValueError('当前不是可行动场景')
    row = next((row for row in current['challenges'] if row['id']==challenge_id),None)
    if row is None:
        raise ValueError('挑战不属于当前场景')
    facts = story_runtime.validate_state(view,campaign['story_state'])
    return view,current,row,facts


def definition(state, challenge_id):
    """Identity is objective/question/place, never method, alias, graph rev or job."""
    view,node,row,facts = _source(state,challenge_id)
    evidence = {'fact:' + sid:facts['facts'][sid]['value'] for sid in row['evidence_fact_ids']}
    if not evidence:
        evidence = {'registered_objective':0}
    return attempts.Challenge(place_id=world_environment.place_id(state,node['id']),
        challenge_id='native:' + row['objective_key'],question=row['question_id'],
        attempt_scope=row['attempt_scope'],repeat_policy=row['repeat_policy'],evidence=evidence,
        definition_ref=_hash(story_graph.challenge_mechanics(row)))


def menu(state, actor):
    """Only currently legal labels/methods; no outcomes, facts or future nodes."""
    campaign = state.get('campaign') or {}
    if campaign.get('package',{}).get('scenario',{}).get('schema_version') != 2:
        return []
    node = story_runtime.node(state,campaign['node_id'])
    result = []
    for row in node.get('challenges',[]):
        try:
            prepare(state,actor,row['id'])
        except ValueError:
            continue
        result.append(dict(id='story-check:'+row['id'],label=row['label'],target='none',
                           kind='story',effect='check',action_cost='none',skill_ids=deepcopy(row['skill_ids'])))
    return result


@bound_rules
def prepare(state, actor, challenge_id, skill_id=None):
    """Pure plan: preflight both results before any dice or effects."""
    from .action_plans import _scope
    if state.get('engine_profile',ENGINE_PROFILE) != ENGINE_PROFILE:
        raise ValueError('此剧情检定尚未适配当前结算配置')
    scope = _scope(state,actor)
    if state.get('status') != 'playing' or state.get('completed'):
        raise ValueError('当前不能提出剧情检定')
    member = abilities.member(state,actor)
    character = member['character']
    if character.get('dead') or character['hp'] <= 0:
        raise ValueError('角色当前无法行动')
    if abilities._combat(state):
        raise ValueError('探索挑战不能绕过战斗动作预算')
    if any(abilities.has_condition(state,character,condition) for condition in ['incapacitated','paralyzed','stunned','unconscious','petrified']):
        raise ValueError('角色失能，不能进行探索检定')
    from .world_combat import validate_read_set
    validate_read_set(state)
    view,node,row,facts = _source(state,challenge_id)
    skill_id = row['skill_ids'][0] if skill_id is None else skill_id
    if skill_id not in row['skill_ids']:
        raise ValueError('这个挑战尚未允许此技能方法')
    condition = story_runtime.evaluate(row['condition'],view,facts)
    if not condition['value']:
        raise ValueError('当前事实尚不满足此挑战前提')
    spec = definition(state,challenge_id)
    if attempts.inspect(state,spec,actor)['status'] != 'eligible':
        raise ValueError('当前证据下的挑战已经结算，不能更换方法重新掷骰')
    reads = deepcopy(condition['read_set'])
    reads.update({'facts:' + sid:deepcopy(facts['facts'][sid]) for sid in row['evidence_fact_ids']})
    for field in ['success_effects','failure_effects']:
        reads.update(story_effects.preflight(view,facts,row[field]))
    return dict(challenge_id=challenge_id,skill_id=skill_id,dc=row['dc'],label=row['label'],
        scope=scope,author_digest=view['author_digest'],
        resources=[dict(type='inspiration_die',dice=character['inspiration_die'],amount=1)] if character.get('inspiration_die') else [],
        actor_digest=_hash(character),definition_ref=spec.definition_ref,
        evidence_digest=attempts.inspect(state,spec,actor)['evidence_digest'],read_set=reads)


@bound_rules
def resolve(state, actor, plan, *, receipt_id):
    """Settle on a copy; caller commits room, consumed proposal and command once."""
    receipt_id = TypeAdapter(Identifier).validate_python(receipt_id,strict=True)
    current = prepare(state,actor,plan['challenge_id'],plan['skill_id'])
    if _hash(current) != _hash(plan):
        raise ValueError('剧情检定的角色、范围或相关事实已变化，请重新裁定')
    work = deepcopy(state)
    view,node,row,facts = _source(work,plan['challenge_id'])
    if receipt_id in facts['effect_receipts']:
        raise ValueError('该剧情结果回执已被处理，请读取原命令回执')
    spec = definition(work,plan['challenge_id'])
    from .characters import SKILL_ABILITIES
    roll = abilities.ability_check(work,abilities.member(work,actor)['character'],
                                   SKILL_ABILITIES[plan['skill_id']],plan['dc'],plan['skill_id'])
    roll['skill'] = plan['skill_id']
    outcome = row['success_effects' if roll['success'] else 'failure_effects']
    result = story_effects.apply(view,facts,outcome,receipt_id=receipt_id,source_ref=row['id'],
                                 success=roll['success'],expected_reads=plan['read_set'])
    work['campaign']['story_state'] = result['state']
    event = rules.event('roll',row['success_text' if roll['success'] else 'failure_text'],
                        actor_id=actor,roll=roll,author_challenge_id=row['id'],rewards_eligible=False)
    attempts.record_roll(work,spec,actor,roll,event)
    state.clear()
    state.update(work)
    return [event]
