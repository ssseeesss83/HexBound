"""Finite, server-owned free-action recipes; narrative never supplies rules.

Movement is an explicit theatre-of-the-mind house rule: one move (15 ft)
changes engaged/withdrawn posture; there are no coordinates or opportunity attacks.
"""
from copy import deepcopy
from . import abilities as a, rules

RECIPES = {
    'shove-prone': ('推倒', 'attack', 'enemy', None, '运动对抗目标运动/体操；成功倒地。'),
    'shove-push': ('推离', 'attack', 'enemy', None, '运动对抗；成功推离5尺，目标需要移动重新接近。'),
    'grapple': ('擒抱', 'attack', 'enemy', None, '运动对抗；成功限制移动，攻击不被禁止。'),
    'escape': ('挣脱', 'action', 'self', None, '运动或体操对抗擒抱者；成功解除擒抱。'),
    'help': ('协助攻击', 'action', 'ally', None, '友方下一次攻击获得优势；不叠加。'),
    'improvised-attack': ('临时武器攻击', 'action', 'enemy', 'movable', '力量攻击，无武器熟练；命中1d4+力量钝击。'),
    'throw-sand': ('扬沙', 'action', 'enemy', 'sand', '目标敏捷豁免DC12；失败失明至其下回合结束（房规）。'),
    'topple': ('推倒障碍物', 'action', 'enemy', 'movable', '力量运动DC12；成功造成1d6钝击并倒地，对象变为倒塌。'),
    'barricade': ('搭建掩体', 'action', 'self', 'cover', '力量运动DC12；成功获得半身掩护AC+2，移动后失效。'),
    'ignite': ('点燃', 'action', 'object', 'flammable', '使用场景已有火源点燃可燃对象；每次回合结束持续2点（战斗外每次自由行动推进6秒），直到熄灭或烧毁。'),
    'extinguish': ('灭火', 'action', 'object', None, '熄灭已燃烧对象，停止持续损坏。'),
    'interact': ('操作物件', 'action', 'object', 'interactable', '切换作者标记的可操作物件状态；不自动解锁主线。'),
    'move': ('接近', 'movement', 'self', None, '消耗15尺移动，使双方恢复接战距离（抽象距离房规）。'),
    'withdraw': ('撤远', 'movement', 'self', None, '消耗15尺移动，撤离近战距离；不触发未实现的机会攻击。'),
    'stand-up': ('起身', 'movement', 'self', None, '消耗15尺移动，解除倒地（固定30尺速度房规）。'),
    'dash': ('疾走', 'action', 'self', None, '本回合额外获得30尺移动额度。'),
    'hide': ('隐蔽', 'action', 'self', 'cover', '敏捷隐匿DC12；成功后下一次攻击具有优势，移动或攻击后显形（房规）。'),
    'search': ('搜索物件', 'action', 'object', 'searchable', '智力调查DC12；成功标记物件已搜索，不捏造隐藏物品或主线奖励。'),
}


def _scene_id(state):
    return str(state.get('scene_id') or state.get('scene', {}).get('id') or 'scene')


def _objects(state):
    sid = _scene_id(state)
    saved = state.get('environment', {}).get(sid, {}).get('objects', {})
    result = {}
    for obj in state.get('scene', {}).get('objects', []):
        item = deepcopy(obj)
        item.update(deepcopy(saved.get(obj['id'], {})))
        item.setdefault('hp', obj.get('hp', 10))
        item.setdefault('burning', 'fire' in obj.get('tags', []))
        result[obj['id']] = item
    return result


def _actor(state, actor):
    for m in state['members']:
        if m['id'] == actor:
            return m['character']
    return next((e for e in (state.get('combat') or {}).get('enemies', []) if e['id'] == actor), None)


def _grapple(state, c):
    return next((x for x in a.active_conditions(state, c) if x['id'] == 'grappled' and (_actor(state, x.get('source')) or {}).get('hp', 0) > 0), None)


def _reason(state, actor, recipe):
    c = a.member(state, actor)['character']
    combat = a._combat(state)
    if state.get('status') is not None and state.get('status') != 'playing':
        return '冒险尚未开始、已暂停或已结束'
    if c.get('dead') or c['hp'] <= 0 or state.get('completed'):
        return '角色无法行动或冒险已经结束'
    if any(a.has_condition(state, c, x) for x in ('incapacitated', 'paralyzed', 'stunned', 'unconscious')):
        return '失能状态下不能行动'
    name, cost, side, tag, summary = RECIPES[recipe]
    reason = a._budget_reason(state, actor, cost)
    if reason:
        return reason
    if recipe == 'move' and combat and c.get('position','engaged')=='engaged' and not any(e.get('position')=='withdrawn' for e in combat['enemies'] if e['hp']>0):
        return '已经处于接战距离'
    if recipe == 'withdraw' and c.get('position')=='withdrawn':
        return '已经撤远'
    if recipe == 'stand-up' and not a.has_condition(state,c,'prone'):
        return '当前没有倒地'
    if recipe in {'shove-prone','shove-push','grapple','escape','help','improvised-attack','throw-sand','topple','move','withdraw','stand-up','dash','hide'} and not combat:
        return '此行动需要战斗遭遇'
    if recipe == 'ignite' and not any(o.get('burning') and o.get('hp',0)>0 for o in _objects(state).values()):
        return '场景没有可用火源；尚未实现点火工具背包'
    if recipe == 'escape' and not _grapple(state, c):
        return '当前没有有效的擒抱'
    if recipe in {'move','withdraw','stand-up', 'dash'} and _grapple(state, c):
        return '擒抱使速度为零，请先挣脱'
    if recipe in {'move','withdraw','stand-up'} and combat.get('movement_spent', 0) + 15 > combat.get('movement_budget', 30):
        return '本回合剩余移动不足15尺'
    if recipe in {'shove-prone','shove-push','grapple','improvised-attack','topple','throw-sand'} and c.get('position', 'engaged') == 'withdrawn':
        return '请先移动接近目标'
    return None


def context(state, actor):
    """Read-only planning context. Objects are projected, never initialized here."""
    if not any(m['id']==actor for m in state.get('members',[])):
        return {'recipes':[],'objects':[],'environment_tick':0}
    objects = _objects(state)
    recipes = []
    for rid, (label, cost, side, tag, summary) in RECIPES.items():
        candidates = [o for o in objects.values() if o.get('hp', 0) > 0 and (not tag or tag in o.get('tags', []))]
        if rid == 'extinguish':
            candidates = [o for o in candidates if o.get('burning')]
        if rid == 'ignite':
            candidates = [o for o in candidates if not o.get('burning')]
        if rid == 'topple':
            candidates = [o for o in candidates if not o.get('toppled')]
        if rid == 'search':
            candidates = [o for o in candidates if not o.get('searched')]
        targets = a._targets(state, actor, side) if side in {'enemy','ally','self'} else []
        if rid == 'help':
            targets = [t for t in targets if t['id'] != actor and _actor(state,t['id'])['hp'] > 0]
        reason = _reason(state, actor, rid)
        needs_object = tag is not None or rid in {'extinguish', 'interact', 'search'}
        if not reason and needs_object and not candidates:
            reason = '场景中没有符合条件的作者定义物件'
        if not reason and side in {'enemy','ally'} and not targets:
            reason = '没有合法目标'
        recipes.append({'id': rid, 'label': label, 'cost': cost, 'cost_label': {'action':'一个动作','attack':'攻击动作中的一次攻击','movement':'15尺移动'}[cost], 'target': side, 'targets': targets, 'objects': [{'id': o['id'], 'name':o['name']} for o in candidates] if needs_object else [], 'requires_object':needs_object, 'disabled_reason':reason, 'summary':[summary.replace('DC12','物件作者DC') if tag in {'movable','cover','searchable'} and rid!='improvised-attack' else summary,'成功或失败均消耗所列预算；规则结算不会自动推进主线。']})
    return {'recipes':recipes,'objects':list(objects.values()),'movement_model':'接近/撤远/起身各15尺；默认30尺移动，无战术网格与机会攻击', 'environment_tick':state.get('environment',{}).get(_scene_id(state),{}).get('tick',0)}


def validate(state, actor, decision):
    if decision.get('kind') not in (None, 'free_action'):
        raise ValueError('不是自由行动提案')
    if set(decision) - {'kind','action_id','target_id','object_id','label','text','success_text','failure_text'}:
        raise ValueError('自由行动不能指定规则数值或额外参数')
    rid = decision.get('action_id')
    cap = next((r for r in context(state,actor)['recipes'] if r['id'] == rid),None)
    if not cap or cap['disabled_reason']:
        raise ValueError(cap['disabled_reason'] if cap else '未注册的自由行动')
    target = decision.get('target_id')
    if cap['target'] == 'self':
        if target not in (None, actor):
            raise ValueError('只能作用于自己')
        target = actor
    elif cap['target'] in {'enemy','ally'} and target not in {x['id'] for x in cap['targets']}:
        raise ValueError('请选择合法目标')
    elif cap['target'] == 'object' and target is not None:
        raise ValueError('物件行动不接受角色目标')
    if rid in {'shove-prone','shove-push','grapple','improvised-attack','topple','throw-sand'} and (_actor(state,target) or {}).get('position')=='withdrawn':
        raise ValueError('请先移动接近已撤远的目标')
    obj = decision.get('object_id')
    if cap['requires_object'] and obj not in {x['id'] for x in cap['objects']}:
        raise ValueError('请选择合法的场景物件')
    if not cap['requires_object'] and obj is not None:
        raise ValueError('此行动不接受场景物件')
    cap = deepcopy(cap)
    if obj and rid in {'topple','barricade','hide','search'}:
        cap['summary'] = [x.replace('物件作者DC',f"DC{_objects(state)[obj].get('dc',12)}") for x in cap['summary']]
    return {**cap, 'action_id':rid,'actor_id':actor,'target_id':target,'object_id':obj,'check':{'shove-prone':'运动对抗','shove-push':'运动对抗','grapple':'运动对抗','escape':'运动/体操对抗','topple':f"力量运动 DC{_objects(state).get(obj,{}).get('dc',12)}",'barricade':f"力量运动 DC{_objects(state).get(obj,{}).get('dc',12)}",'hide':f"敏捷隐匿 DC{_objects(state).get(obj,{}).get('dc',12)}",'search':f"智力调查 DC{_objects(state).get(obj,{}).get('dc',12)}",'throw-sand':'目标敏捷豁免 DC12','improvised-attack':'力量攻击，对目标AC'}.get(rid,'自动成功，仍需满足对象与目标条件')}


def _check(state,c,ability,skill,dc=12):
    c.setdefault('abilities', {}).setdefault(ability,10)
    return a.ability_check(state,c,ability,dc,skill)


def _skill_bonus(c,ability,skill):
    from .characters import skill_bonus
    return skill_bonus(c,skill) if a.modern(c) else rules.modifier(c.get('abilities',{}).get(ability,10))


def _contest(state, attacker, defender, escape=False):
    ability,skill = ('str','athletics')
    if escape and _skill_bonus(attacker,'dex','acrobatics') > _skill_bonus(attacker,'str','athletics'):
        ability,skill = 'dex','acrobatics'
    offense = _check(state,attacker,ability,skill,0)
    da,ds = ('dex','acrobatics') if _skill_bonus(defender,'dex','acrobatics')>_skill_bonus(defender,'str','athletics') else ('str','athletics')
    defense = _check(state,defender,da,ds,0)
    offense.update(kind='contested_check',success=offense['total']>defense['total'],opposed_roll=defense)
    return offense


def _condition(state, c, name, **extra):
    if name in {'helped','blinded','grappled','prone','hidden'}:
        extra.update(encounter_scoped=True,encounter_id=(state.get('combat') or {}).get('encounter_id'))
    c.setdefault('conditions',[])
    c['conditions'] = [x for x in c['conditions'] if x.get('id') != name]
    c['conditions'].append({'id':name, **extra})


def resolve(state, actor, decision):
    from .world_combat import validate_read_set
    validate_read_set(state)
    plan = validate(state,actor,decision)
    work = deepcopy(state)
    c = a.member(work,actor)['character']
    combat = a._combat(work)
    sid = _scene_id(work)
    env = work.setdefault('environment',{}).setdefault(sid,{'objects':{},'tick':0})
    env['objects'] = _objects(work)
    rid,target_id = plan['action_id'],plan['target_id']
    target = _actor(work,target_id) if target_id else None
    obj = env['objects'].get(plan['object_id'])
    if combat and plan['cost'] == 'attack':
        if not combat.get('action_used'):
            combat.update(action_used=True,attacks_remaining=a.attacks_per_action(c),attack_action_taken=True)
        combat['attacks_remaining'] -= 1
    elif plan['cost'] == 'action':
        a._spend_budget(work,'action')
    success,roll = True,None
    if rid in {'shove-prone','shove-push','grapple'}:
        roll = _contest(work,c,target)
        success = roll['success']
        if success and rid == 'shove-prone':
            _condition(work,target,'prone')
        elif success and rid == 'shove-push':
            target['position']='withdrawn'
            target['pushed_ft']=5
            target['conditions']=[x for x in target.get('conditions',[]) if x['id']!='grappled']
        elif success:
            _condition(work,target,'grappled',source=actor)
    elif rid == 'escape':
        grapple = _grapple(work,c)
        roll = _contest(work,c,_actor(work,grapple['source']),escape=True)
        success = roll['success']
        if success:
            c['conditions']=[x for x in c.get('conditions',[]) if x['id']!='grappled']
    elif rid == 'help':
        _condition(work,target,'helped',expires_on_turn_start=actor)
    elif rid == 'improvised-attack':
        bonus=rules.modifier(c['abilities']['str'])
        roll=rules.attack_roll(bonus,a.armor_class(work,target),'1d4',bonus,advantage=a.attack_advantage(work,c,target),disadvantage=a.attack_disadvantage(work,c))
        a.consume_attack_conditions(c,target)
        success=roll['success']
        roll['damage']=a._damage_enemy(target,roll['damage'],'bludgeoning')
    elif rid == 'throw-sand':
        roll=a.saving_throw(work,target,'dex',12)
        success=not roll['success']
        if success:
            _condition(work,target,'blinded',expires_on_turn_end=target_id)
    elif rid in {'topple','barricade','hide','search'}:
        ability,skill = ('dex','stealth') if rid=='hide' else ('int','investigation') if rid=='search' else ('str','athletics')
        roll=_check(work,c,ability,skill,obj.get('dc',12))
        success=roll['success']
        if success and rid=='topple':
            damage=rules.roll_dice('1d6')
            roll.update(damage_dice=damage['dice'],damage=a._damage_enemy(target,damage['total'],'bludgeoning'))
            obj['toppled']=True
            _condition(work,target,'prone')
        elif success and rid=='barricade':
            _condition(work,c,'half-cover',object_id=obj['id'],scene_id=sid)
        elif success and rid=='hide':
            _condition(work,c,'hidden',object_id=obj['id'],scene_id=sid)
        elif success:
            obj['searched']=True
    elif rid=='ignite':
        obj['burning']=True
    elif rid=='extinguish':
        obj['burning']=False
    elif rid=='interact':
        obj['activated']=not obj.get('activated',False)
    elif rid in {'move','withdraw','stand-up'}:
        combat['movement_spent']=combat.get('movement_spent',0)+15
        if rid=='stand-up':
            c['conditions']=[x for x in c.get('conditions',[]) if x['id']!='prone']
        else:
            c['position']='withdrawn' if rid=='withdraw' else 'engaged'
            if rid=='move':
                for enemy in combat['enemies']:
                    enemy['position']='engaged'
            c['conditions']=[x for x in c.get('conditions',[]) if x['id'] not in {'half-cover','hidden'}]
            if rid=='withdraw':
                for enemy in combat['enemies']:
                    enemy['conditions']=[x for x in enemy.get('conditions',[]) if x.get('source')!=actor or x['id']!='grappled']
    elif rid=='dash':
        combat['movement_budget']=combat.get('movement_budget',30)+30
    if not combat:
        advance_environment(work)
    events=[rules.event('roll' if roll else 'free_action',f"{plan['label']}：{'成功' if success else '失败'}。",actor_id=actor,target_id=target_id,object_id=plan['object_id'],action_id=rid,success=success,roll=roll,rule_plan=plan)]
    a.finish_combat(work,events)
    state.clear()
    state.update(work)
    return events


def advance_environment(state):
    """One six-second beat: called once per combat turn end, or out-of-combat action."""
    sid = _scene_id(state)
    if not _objects(state):
        return
    env = state.setdefault('environment',{}).setdefault(sid,{'objects':{},'tick':0})
    env['objects'] = _objects(state)
    env['tick'] = env.get('tick',0) + 1
    env['elapsed_seconds'] = env.get('elapsed_seconds',0)+6
    from .world_environment import environment_tick
    if not environment_tick(state, env['elapsed_seconds']):
        return
    for item in env['objects'].values():
        if item.get('burning') and item['hp']>0:
            item['hp']=max(0,item['hp']-2)
            if item['hp']==0:
                item.update(burning=False,destroyed=True)
