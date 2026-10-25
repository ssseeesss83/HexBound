"""Script-owned character actions for the SRD 5.1 encounter adapter.

The complete compendium is reference data. Only the explicit handlers below
are executable. Area targets use an openly declared abstract encounter model;
this module does not pretend that the application has a tactical grid.
"""
from __future__ import annotations

from copy import deepcopy
import re
import uuid
from . import rules
from .rules_context import bound_rules, current_view

# Explicit effect recipes: never execute descriptions or client-provided dice.
SPELL_EFFECTS = {
    'produce-flame': {'kind': 'attack', 'dice': '1d8', 'type': 'fire', 'scale': True},
    'fire-bolt': {'kind': 'attack', 'dice': '1d10', 'type': 'fire', 'scale': True},
    'ray-of-frost': {'kind': 'attack', 'dice': '1d8', 'type': 'cold', 'scale': True},
    'chill-touch': {'kind': 'attack', 'dice': '1d8', 'type': 'necrotic', 'scale': True, 'condition': 'healing-blocked'},
    'shocking-grasp': {'kind': 'attack', 'dice': '1d8', 'type': 'lightning', 'scale': True, 'condition': 'no-reactions'},
    'eldritch-blast': {'kind': 'attack', 'dice': '1d10', 'type': 'force', 'beams': True},
    'sacred-flame': {'kind': 'save', 'dice': '1d8', 'save': 'dex', 'type': 'radiant', 'scale': True},
    'poison-spray': {'kind': 'save', 'dice': '1d12', 'save': 'con', 'type': 'poison', 'scale': True},
    'vicious-mockery': {'kind': 'save', 'dice': '1d4', 'save': 'wis', 'type': 'psychic', 'scale': True, 'condition': 'attack-disadvantage'},
    'acid-splash': {'kind': 'save', 'dice': '1d6', 'save': 'dex', 'type': 'acid', 'scale': True, 'max_targets': 2},
    'magic-missile': {'kind': 'missile', 'dice': '1d4', 'type': 'force', 'upcast': 1},
    'guiding-bolt': {'kind': 'attack', 'dice': '4d6', 'type': 'radiant', 'upcast': 1, 'condition': 'next-hit-advantage'},
    'inflict-wounds': {'kind': 'attack', 'dice': '3d10', 'type': 'necrotic', 'upcast': 1},
    'scorching-ray': {'kind': 'attack', 'dice': '2d6', 'type': 'fire', 'rays': 3, 'upcast_rays': 1},
    'burning-hands': {'kind': 'save', 'dice': '3d6', 'save': 'dex', 'type': 'fire', 'half': True, 'upcast': 1, 'max_targets': 6},
    'thunderwave': {'kind': 'save', 'dice': '2d8', 'save': 'con', 'type': 'thunder', 'half': True, 'upcast': 1, 'max_targets': 6},
    'fireball': {'kind': 'save', 'dice': '8d6', 'save': 'dex', 'type': 'fire', 'half': True, 'upcast': 1, 'max_targets': 6},
    'lightning-bolt': {'kind': 'save', 'dice': '8d6', 'save': 'dex', 'type': 'lightning', 'half': True, 'upcast': 1, 'max_targets': 6},
    'cone-of-cold': {'kind': 'save', 'dice': '8d8', 'save': 'con', 'type': 'cold', 'half': True, 'upcast': 1, 'max_targets': 6},
    'disintegrate': {'kind': 'save', 'dice': '10d6', 'save': 'dex', 'type': 'force', 'flat': 40, 'upcast': 3},
    'cure-wounds': {'kind': 'heal', 'dice': '1d8', 'upcast': 1, 'modifier': True},
    'healing-word': {'kind': 'heal', 'dice': '1d4', 'upcast': 1, 'modifier': True, 'cost': 'bonus'},
    'mass-healing-word': {'kind': 'heal', 'dice': '1d4', 'upcast': 1, 'modifier': True, 'cost': 'bonus', 'max_targets': 6},
    'mass-cure-wounds': {'kind': 'heal', 'dice': '3d8', 'upcast': 1, 'modifier': True, 'max_targets': 6},
    'heal': {'kind': 'heal', 'flat': 70, 'upcast_flat': 10},
    'spare-the-dying': {'kind': 'stabilize'},
    'bless': {'kind': 'buff', 'buff': 'bless', 'max_targets': 3, 'upcast_targets': 1, 'concentration': True, 'rounds': 10},
    'shield-of-faith': {'kind': 'buff', 'buff': 'shield-of-faith', 'cost': 'bonus', 'concentration': True, 'rounds': 100},
    'hunters-mark': {'kind': 'mark', 'concentration': True, 'cost': 'bonus', 'rounds': 600},
    'false-life': {'kind': 'temp_hp', 'dice': '1d4', 'flat': 4, 'upcast_flat': 5},
    'greater-restoration': {'kind': 'restore'},
    'lesser-restoration': {'kind': 'restore'},
}
# Spell side effects requiring spatial/material adjudication are explicitly noted.
SPELL_NOTES = {
    'ray-of-frost': '伤害自动结算；速度降低供文字战场裁定。',
    'shocking-grasp': '伤害与失去反应自动结算；金属护甲优势需人工判定。',
    'thunderwave': '豁免与伤害自动；推离距离由抽象战场叙事表示。',
    'disintegrate': '自动结算豁免和伤害；物体/力场与灰烬复活限制由DM裁定。',
    'hex': '额外伤害自动；指定属性检定劣势需DM裁定。',
    'hunters-mark': '武器额外伤害自动；追踪优势由DM裁定。',
}
# Costly consumed material components are not yet inventory-backed.
for _unsupported in ('greater-restoration',):
    SPELL_EFFECTS.pop(_unsupported, None)
FEATURE_AUTOMATED = {'rage', 'second-wind', 'action-surge', 'bardic-inspiration', 'lay-on-hands', 'divine-smite', 'flurry-of-blows', 'patient-defense', 'arcane-recovery', 'font-of-magic', 'sneak-attack', 'extra-attack'}
FEATURES = {
    'rage': ('barbarian', 1, '狂暴', 'bonus', 'self', 'rage'),
    'second-wind': ('fighter', 1, '第二风', 'bonus', 'self', 'second-wind'),
    'action-surge': ('fighter', 2, '动作如潮', 'none', 'self', 'action-surge'),
    'bardic-inspiration': ('bard', 1, '吟游激励', 'bonus', 'ally', 'bardic-inspiration'),
    'lay-on-hands': ('paladin', 1, '圣疗', 'action', 'ally', 'lay-on-hands'),
    'divine-smite': ('paladin', 2, '武器攻击 · 神圣惩击', 'attack', 'enemy', None),
    'flurry-of-blows': ('monk', 2, '疾风连击', 'bonus', 'enemy', 'ki'),
    'patient-defense': ('monk', 2, '闪身防御', 'bonus', 'self', 'ki'),
    'arcane-recovery': ('wizard', 1, '奥术回想', 'none', 'self', 'arcane-recovery'),
    'font-of-magic': ('sorcerer', 2, '灵活施法 · 创造法术位', 'bonus', 'self', 'sorcery-points'),
}


def _spells():
    from .compendium import SPELLS
    view = current_view()
    return view.SPELLS if view is not None else SPELLS


def _effects():
    view = current_view()
    return view.SPELL_EFFECTS if view is not None else SPELL_EFFECTS


def _feature_actions():
    view = current_view()
    return view.ACTION_FEATURES if view is not None else FEATURES


def spell_automation(spell_id):
    from .capabilities import spell_automation as status
    return status(spell_id)


def feature_automation(feature_id):
    from .capabilities import feature_automation as status
    return status(feature_id)


def handles(action_id):
    return action_id.startswith(('cast:', 'feature:')) or action_id == 'end-concentration'


def member(state, member_id):
    item = next((m for m in state['members'] if m['id'] == member_id), None)
    if not item:
        raise ValueError('角色不存在')
    return item


def modern(character):
    return bool(character.get('class_id'))


def _class(c):
    return c.get('class_id', c.get('class', c.get('template_id')))


def _combat(state):
    value = state.get('combat')
    return value if value and value.get('active') else None


def _resource(c, key):
    return c.get('resources', {}).get(key, {}).get('current', 0)


def _spend(c, key, amount=1):
    pool = c.get('resources', {}).get(key)
    if not pool or amount < 0 or pool['current'] < amount:
        raise ValueError('职业资源不足')
    if not pool.get('unlimited'):
        pool['current'] -= amount


def _spell_levels(c, level):
    if level == 0:
        return []
    result = [{'level': int(k), 'source': 'spell', 'current': pool['current']} for k, pool in c.get('spell_slots', {}).items() if int(k) >= level and pool.get('current', 0) > 0]
    pact = c.get('pact_slots') or {}
    if pact.get('level', 0) >= level and pact.get('current', 0) > 0:
        result.append({'level': pact['level'], 'source': 'pact', 'current': pact['current']})
    return sorted(result, key=lambda x: (x['level'], x['source']))


def _select_slot(c, spell_level, options):
    if spell_level == 0:
        if options.get('slot_level') not in (None, 0):
            raise ValueError('戏法不能消耗法术位升环')
        return 0, None
    levels = _spell_levels(c, spell_level)
    requested = options.get('slot_level')
    source = options.get('slot_source')
    selected = next((x for x in levels if (requested is None or x['level'] == requested) and (source is None or x['source'] == source)), None)
    if not selected:
        raise ValueError('没有匹配的可用法术位')
    return selected['level'], selected['source']


def _consume_slot(c, level, source):
    if level:
        pool = c.get('pact_slots') if source == 'pact' else c['spell_slots'][str(level)]
        if not pool or pool['current'] <= 0:
            raise ValueError('法术位不足')
        pool['current'] -= 1


def _known(c, spell):
    sid = spell.get('id', spell.get('index'))
    if spell['level'] == 0:
        return sid in c.get('cantrips', [])
    if _class(c) in {'cleric', 'druid', 'paladin', 'wizard'}:
        return sid in c.get('prepared_spells', []) + c.get('always_prepared_spells', [])
    return sid in c.get('known_spells', [])


def _owned_spell_ids(c):
    return list(dict.fromkeys(c.get('cantrips', []) + c.get('known_spells', []) + c.get('prepared_spells', []) + c.get('spellbook', []) + c.get('always_prepared_spells', [])))


def _round(state):
    return (state.get('combat') or {}).get('round', 0)


def active_conditions(state, c):
    result = []
    for condition in c.get('conditions', []):
        if not isinstance(condition, dict):
            continue
        if condition.get('encounter_scoped'):
            combat = _combat(state)
            if not combat or condition.get('encounter_id') != combat.get('encounter_id'):
                continue
        if condition.get('expires_round') is not None and _round(state) >= condition['expires_round']:
            continue
        if condition.get('scene_id') and condition['scene_id'] != str(state.get('scene_id')):
            continue
        if condition.get('object_id') and state.get('environment', {}).get(str(state.get('scene_id')), {}).get('objects', {}).get(condition['object_id'], {}).get('destroyed'):
            continue
        if condition.get('id') == 'grappled':
            source_id = condition.get('source')
            source = next((m['character'] for m in state.get('members',[]) if m['id']==source_id),None) or next((e for e in (state.get('combat') or {}).get('enemies',[]) if e['id']==source_id),None)
            from . import tactical
            b=tactical.board(state)
            target_id=next((m['id'] for m in state.get('members',[]) if m['character'] is c),None) or next((e['id'] for e in (state.get('combat') or {}).get('enemies',[]) if e is c),None)
            if not source or source.get('hp',0)<=0 or source.get('dead'):continue
            if b:
                a=b['positions'].get(source_id);t=b['positions'].get(target_id)
                if not a or not t or tactical.distance(a,t)>5 or not tactical.visible(b,a,t):continue
            elif source.get('position')=='withdrawn' or c.get('position')=='withdrawn':continue
        owner = condition.get('concentration_owner')
        if owner:
            source = next((m['character'] for m in state['members'] if m['id'] == owner), None)
            if not source or (source.get('concentration') or {}).get('id') != condition.get('concentration_id'):
                continue
        result.append(condition)
    return result


def has_condition(state, c, name):
    return any(x.get('id') == name for x in active_conditions(state, c))


def _condition(state, c, name, rounds=1, **extra):
    c.setdefault('conditions', []).append({'id': name, 'expires_round': _round(state) + rounds, **extra})


def armor_class(state, c):
    return c.get('ac', 10) + (2 if has_condition(state, c, 'shield-of-faith') else 0) + (2 if has_condition(state, c, 'half-cover') else 0)


def attack_advantage(state, attacker, target, *, melee=True):
    return any(has_condition(state, attacker, x) for x in ('helped','hidden')) or any(has_condition(state,target,x) for x in ('blinded','next-hit-advantage')) or (melee and has_condition(state,target,'prone'))


def attack_disadvantage(state, attacker, target=None, *, melee=True):
    return any(has_condition(state,attacker,x) for x in ('blinded','prone','poisoned','attack-disadvantage')) or (not melee and target is not None and has_condition(state,target,'prone'))


def consume_attack_conditions(attacker, target):
    attacker['conditions']=[x for x in attacker.get('conditions',[]) if x.get('id') not in {'helped','hidden','attack-disadvantage'}]
    target['conditions']=[x for x in target.get('conditions',[]) if x.get('id')!='next-hit-advantage']


def prepare_enemy_melee(state, enemy, target):
    """Enemies stand/close using the same abstract movement; grapple stops closing."""
    from .free_actions import _grapple
    from . import tactical
    if tactical.board(state):
        return False  # Grid enemies are exclusively handled by the DM controller.
    spent=0
    if has_condition(state,enemy,'prone') and not _grapple(state,enemy):
        spent+=15
        enemy['conditions']=[x for x in enemy.get('conditions',[]) if x.get('id')!='prone']
    if enemy.get('position')=='withdrawn' or target.get('position')=='withdrawn':
        if _grapple(state,enemy):
            return False
        spent+=15
        enemy['position']='engaged'
        target['position']='engaged'
    state['combat']['movement_spent']=spent
    return True


def end_turn(state, actor):
    from .free_actions import advance_environment
    advance_environment(state)
    for c in [m['character'] for m in state['members']] + (state.get('combat') or {}).get('enemies',[]):
        c['conditions']=[x for x in c.get('conditions',[]) if x.get('expires_on_turn_end')!=actor]


def _budget_reason(state, actor, cost):
    combat = _combat(state)
    if not combat:
        return None
    c = member(state, actor)['character']
    if any(has_condition(state, c, name) for name in ('incapacitated', 'paralyzed', 'stunned', 'unconscious')):
        return '失能状态下不能行动'
    if combat['turn_actor_id'] != actor:
        return '尚未轮到你的回合'
    if cost == 'action' and combat.get('action_used'):
        return '本回合动作已使用'
    if cost == 'attack' and combat.get('action_used') and combat.get('attacks_remaining', 0) <= 0:
        return '本回合攻击动作已用尽'
    if cost == 'bonus' and combat.get('bonus_action_used'):
        return '本回合附赠动作已使用'
    return None


def _spend_budget(state, cost):
    combat = _combat(state)
    if combat:
        if cost == 'action':
            combat['action_used'] = True
            combat['attacks_remaining'] = 0
        elif cost == 'bonus':
            combat['bonus_action_used'] = True


def _targets(state, actor, side):
    if side == 'enemy':
        return [{'id': x['id'], 'name': x['name']} for x in (_combat(state) or {}).get('enemies', []) if x['hp'] > 0]
    return [{'id': m['id'], 'name': m['name']} for m in state['members'] if not m['character'].get('dead') and (side != 'self' or m['id'] == actor)]


def capabilities(state, actor):
    from .capabilities import action_feature_support
    m = member(state, actor)
    c = m['character']
    if not modern(c):
        return []
    common_reason = '角色已经死亡' if c.get('dead') else '角色已倒地，不能行动' if c['hp'] <= 0 else '冒险已结束' if state.get('completed') else None
    result = []
    for sid in _owned_spell_ids(c):
        spell = _spells().get(sid)
        if not spell:
            continue
        recipe = _effects().get(sid)
        meta = spell_automation(sid)
        side = 'ally' if recipe and recipe['kind'] in {'heal', 'stabilize', 'buff', 'restore'} else 'self' if recipe and recipe['kind'] == 'temp_hp' else 'enemy'
        cost = (recipe or {}).get('cost', 'action')
        reason = common_reason or (None if recipe and meta['status'] != 'reference' else meta['reason'])
        if not reason and c.get('rage'):
            reason = '狂暴期间不能施法'
        if not reason and not _known(c, spell):
            reason = '此法术尚未准备'
        if not reason:
            reason = _budget_reason(state, actor, cost)
        combat = _combat(state)
        if not reason and combat and cost == 'bonus' and combat.get('leveled_spell_action'):
            reason = '本回合已用动作施放有环法术，不能再施放附赠动作法术'
        if not reason and combat and cost == 'action' and spell['level'] > 0 and combat.get('bonus_spell_cast'):
            reason = '附赠动作施法后，本回合动作施法仅限戏法'
        levels = _spell_levels(c, spell['level'])
        if not reason and spell['level'] > 0 and not levels:
            reason = '可用法术位已耗尽'
        targets = _targets(state, actor, side)
        if recipe and recipe['kind'] == 'heal':
            targets = [x for x in targets if member(state, x['id'])['character']['hp'] < member(state, x['id'])['character']['max_hp'] and not has_condition(state, member(state, x['id'])['character'], 'healing-blocked')]
        if recipe and recipe['kind'] == 'restore':
            targets = [x for x in targets if any(v.get('id') in {'blinded','deafened','paralyzed','poisoned'} for v in member(state, x['id'])['character'].get('conditions', []) if isinstance(v, dict))]
        if recipe and recipe['kind'] == 'stabilize':
            targets = [x for x in targets if member(state, x['id'])['character']['hp'] == 0 and not member(state, x['id'])['character'].get('stable')]
        if not reason and not targets:
            reason = '当前没有合法目标'
        result.append({'id': 'cast:' + sid, 'label': spell.get('name_zh') or spell['name'], 'description': meta['reason'], 'automation_status': meta['status'], 'kind': 'spell', 'spell_id': sid, 'spell_level': spell['level'], 'effect': (recipe or {}).get('kind'), 'target': side, 'targets': targets, 'action_cost': cost, 'cast_levels': levels, 'max_targets': (recipe or {}).get('max_targets', 1) + ((recipe or {}).get('upcast_targets', 0) * (max([x['level'] for x in levels], default=spell['level']) - spell['level'])), 'area_mode': 'encounter-selection' if (recipe or {}).get('max_targets', 1) > 1 else None, 'supported': bool(recipe) and meta['status'] != 'reference', 'disabled_reason': reason})
    for fid, (cls, level, label, cost, side, resource) in _feature_actions().items():
        if _class(c) != cls or c.get('level', 1) < level:
            continue
        support = action_feature_support(fid)
        reason = common_reason or (None if support['supported'] else support['reason']) or _budget_reason(state, actor, cost)
        if not reason and resource and _resource(c, resource) <= 0:
            reason = '职业资源已耗尽'
        combat = _combat(state)
        if not reason and fid in {'rage', 'action-surge', 'divine-smite', 'flurry-of-blows', 'patient-defense'} and not combat:
            reason = '只能在战斗中使用'
        if not reason and fid == 'rage' and c.get('rage'):
            reason = '已经处于狂暴状态'
        if not reason and fid == 'second-wind' and c['hp'] == c['max_hp']:
            reason = '当前无需治疗'
        if not reason and fid == 'action-surge' and (combat.get('surge_used') or combat.get('attacks_remaining', 0) > 0):
            reason = '每回合只能动作如潮一次；请先完成当前攻击'
        if not reason and fid == 'flurry-of-blows' and not combat.get('attack_action_taken'):
            reason = '需要先在本回合执行攻击动作'
        if not reason and fid == 'arcane-recovery' and combat:
            reason = '奥术回想只能在短休后使用'
        if not reason and fid == 'arcane-recovery' and not c.get('short_rest_ready'):
            reason = '请先完成短休'
        if not reason and fid == 'arcane-recovery' and not any(p['current'] < p['max'] and int(k) <= min(5, (c['level'] + 1) // 2) for k, p in c.get('spell_slots', {}).items()):
            reason = '没有符合条件的已消耗法术位'
        if not reason and fid == 'divine-smite' and not _spell_levels(c, 1):
            reason = '神圣惩击需要至少一环法术位'
        targets = _targets(state, actor, side)
        if fid == 'bardic-inspiration':
            targets = [x for x in targets if x['id'] != actor and not member(state, x['id'])['character'].get('inspiration_die')]
        if fid == 'lay-on-hands':
            targets = [x for x in targets if member(state, x['id'])['character']['hp'] < member(state, x['id'])['character']['max_hp'] and not has_condition(state, member(state, x['id'])['character'], 'healing-blocked')]
        if not reason and not targets:
            reason = '当前没有合法目标'
        result.append({'id': 'feature:' + fid, 'label': label, 'kind': 'feature', 'description': support['reason'] + ' ' + {'bardic-inspiration': '激励骰自动用于目标下一次攻击或豁免（自动消费房规）。', 'arcane-recovery': '短休后恢复一个符合等级上限的法术位；多位分配尚未实现。', 'font-of-magic': '当前使用恢复已有空法术位的房规，不能超出角色位上限。'}.get(fid, ''), 'automation_status': support['status'], 'target': side, 'targets': targets, 'action_cost': cost, 'resource': resource, 'uses_remaining': _resource(c, resource) if resource else None, 'supported': support['supported'], 'disabled_reason': reason, 'cast_levels': _spell_levels(c, 1) if fid == 'divine-smite' else [], 'max_amount': _resource(c, resource) if fid == 'lay-on-hands' else None})
    if c.get('concentration'):
        result.append({'id': 'end-concentration', 'label': '结束专注', 'kind': 'feature', 'target': 'self', 'action_cost': 'none', 'supported': True, 'disabled_reason': common_reason})
    return result


def available_actions(state, actor):
    result = [x for x in capabilities(state, actor) if not x.get('disabled_reason')]
    combat = _combat(state)
    c = member(state, actor)['character']
    if modern(c) and combat and combat['turn_actor_id'] == actor and c['hp'] > 0 and not c.get('dead') and combat.get('action_used') and combat.get('attacks_remaining', 0) > 0:
        result.append({'id': 'attack', 'label': f"继续攻击（剩余{combat['attacks_remaining']}次）", 'kind': 'basic', 'target': 'enemy', 'targets': _targets(state, actor, 'enemy'), 'action_cost': 'attack'})
    return result


def _selected_targets(state, actor, cap, target_id, options, max_targets):
    supplied = options.get('target_ids') or ([target_id] if target_id else [])
    if not supplied and cap['target'] == 'self':
        supplied = [actor]
    if not supplied and len(cap.get('targets', [])) == 1:
        supplied = [cap['targets'][0]['id']]
    if not supplied or len(supplied) > max_targets or len(set(supplied)) != len(supplied):
        raise ValueError('请选择数量合法且不重复的目标')
    legal = {x['id'] for x in cap.get('targets', [])}
    if not set(supplied) <= legal:
        raise ValueError('目标不属于当前合法目标')
    from .tactical import ability_targets
    ability_targets(state,actor,cap['id'],supplied)
    return [next(e for e in state['combat']['enemies'] if e['id'] == sid) if cap['target'] == 'enemy' else member(state, sid)['character'] for sid in supplied], supplied


def _dice(base, extra=0):
    count, die = map(int, base.split('d'))
    return f'{count + extra}d{die}'


def _casting_bonus(c):
    ability = c.get('spellcasting', {}).get('ability') or {'bard': 'cha', 'cleric': 'wis', 'druid': 'wis', 'paladin': 'cha', 'ranger': 'wis', 'sorcerer': 'cha', 'warlock': 'cha', 'wizard': 'int'}.get(_class(c), 'int')
    return rules.modifier(c['abilities'][ability])


def _check_bonus(state, c, base):
    bonus = 0
    if has_condition(state, c, 'bless'):
        bonus += rules.roll_dice('1d4')['total']
    if c.get('inspiration_die'):
        bonus += rules.roll_dice(c.pop('inspiration_die'))['total']
    return base + bonus


def reliable_talent(c, skill_id, result):
    if (_class(c)=='rogue' and c.get('level',1)>=11 and skill_id in c.get('skills',[])
            and result['selected']<10):
        result.update(reliable_talent=True,selected=10,total=10+result['modifier'])
        result['success'] = result['total'] >= result['dc']
    return result


def ability_check(state, c, ability, dc, skill_id=None, *, advantage=False, bonus=0):
    """Apply training only for an explicit skill, retaining authored ability variants."""
    from .characters import SKILL_ABILITIES, skill_bonus
    base = rules.modifier(c['abilities'][ability])
    training = 0
    if modern(c):
        if skill_id is not None:
            if skill_id not in SKILL_ABILITIES:
                raise ValueError('未知检定技能')
            training = skill_bonus(c, skill_id) - rules.modifier(c['abilities'][SKILL_ABILITIES[skill_id]])
        elif _class(c) == 'bard' and c.get('level', 1) >= 2:
            training = c.get('proficiency', 2) // 2
    inspiration = rules.roll_dice(c.pop('inspiration_die'))['total'] if c.get('inspiration_die') else 0
    result = rules.check(base + training + bonus + inspiration, dc,
                         advantage=advantage or (ability == 'str' and bool(c.get('rage'))),
                         disadvantage=has_condition(state, c, 'poisoned'))
    result.update(ability=ability, skill_id=skill_id, proficiency_bonus=training, inspiration_bonus=inspiration)
    return reliable_talent(c,skill_id,result)


def saving_throw(state, c, ability, dc):
    if ability in {'str', 'dex'} and any(has_condition(state, c, name) for name in ('paralyzed', 'stunned', 'unconscious')):
        return {'kind': 'saving_throw', 'success': False, 'dc': dc, 'dice': [], 'reason': '此状态自动失败力量与敏捷豁免'}
    bonus = rules.modifier(c.get('abilities', {}).get(ability, 10))
    if ability in c.get('saving_throws', []):
        bonus += c.get('proficiency', 2)
    bonus += c.get('saving_throw_bonuses', {}).get(ability, 0)
    return rules.check(_check_bonus(state, c, bonus), dc, advantage=ability == 'str' and bool(c.get('rage')))


def _damage_enemy(enemy, amount, damage_type):
    enemy['last_damage_type']=damage_type
    if enemy.get('warded'):amount//=2
    if 'shield' in enemy.get('behaviors',[]):amount=max(0,amount-1)
    immune = enemy.get('damage_immunities', [])
    resist = enemy.get('damage_resistances', [])
    vulnerable = enemy.get('damage_vulnerabilities', [])
    if damage_type in immune:
        amount = 0
    elif damage_type in resist:
        amount //= 2
    if damage_type in vulnerable:
        amount *= 2
    before = enemy['hp']
    enemy['hp'] = max(0, before - amount)
    if before>0 and enemy['hp']==0 and 'undead' in enemy.get('behaviors',[]) and damage_type!='radiant' and not enemy.get('undead_used'):
        enemy['undead_used']=True;enemy['hp']=1
    if amount and 'split' in enemy.get('behaviors',[]) and damage_type in {'slashing','lightning'} and not enemy.get('split_used') and enemy['hp']>0:
        enemy['split_used']=True;enemy['hp']=min(enemy.get('max_hp',enemy['hp']),enemy['hp']+3)
    return amount


def adjust_damage(character, amount, damage_type=None):
    if character.get('rage') and damage_type in {'bludgeoning', 'piercing', 'slashing'}:
        amount //= 2
    return amount


def on_damage(character, amount, state=None):
    if not character.get('concentration'):
        return None
    if character.get('dead') or character['hp'] <= 0:
        character['concentration'] = None
        return {'kind': 'concentration', 'success': False, 'reason': '失去意识'}
    if amount <= 0:
        return None
    bonus = rules.modifier(character['abilities']['con'])
    if 'con' in character.get('saving_throws', []):
        bonus += character.get('proficiency', 2)
    result = saving_throw(state, character, 'con', max(10, amount // 2)) if state else rules.check(bonus, max(10, amount // 2))
    result['kind'] = 'concentration'
    if not result['success']:
        character['concentration'] = None
    character['last_concentration_save'] = result
    return result


def finish_combat(state, events):
    combat = _combat(state)
    if not combat or any(e['hp'] > 0 for e in combat['enemies']):
        return
    combat['active'] = False
    if not combat.get('director_encounter'):
        if state.get('campaign'):
            cleared = state['campaign']['cleared']
            if state['campaign']['node_id'] not in cleared:
                cleared.append(state['campaign']['node_id'])
        else:
            flags = state.setdefault('flags', {})
            flags['scene_resolved'] = True
            if state.get('scene_index') == 1:
                flags['lens'] = True
            if state.get('scene_index') == 3:
                flags['resolution'] = 'fight'
    for m in state['members']:
        c = m['character']
        c.pop('rage', None)
        # The existing project's stabilization aftermath remains an explicit house rule.
        if c['hp'] == 0 and not c.get('dead'):
            c['stable'] = True
    events.append(rules.event('combat', '遭遇结束。幸存倒地角色被稳定伤势（冒险房规）。', encounter_id=combat.get('encounter_id')))


def _spell(state, actor, sid, target_id, options, cap):
    c = member(state, actor)['character']
    spell, recipe = _spells()[sid], _effects()[sid]
    level, source = _select_slot(c, spell['level'], options)
    extra = max(0, level - spell['level'])
    targets, ids = _selected_targets(state, actor, cap, target_id, options, recipe.get('max_targets', 1) + recipe.get('upcast_targets', 0) * extra)
    # All target/resource validation happens before any die is rolled or resource spent.
    _consume_slot(c, level, source)
    _spend_budget(state, cap['action_cost'])
    combat = _combat(state)
    if combat:
        if cap['action_cost'] == 'bonus':
            combat['bonus_spell_cast'] = True
        elif spell['level'] > 0:
            combat['leveled_spell_action'] = True
    if recipe.get('concentration'):
        c['concentration'] = {'id': uuid.uuid4().hex, 'spell_id': sid, 'name': cap['label'], 'expires_round': _round(state) + recipe.get('rounds', 10)}
    events = []
    scale = 1 + int(c['level'] >= 5) + int(c['level'] >= 11) + int(c['level'] >= 17)
    expression = recipe.get('dice')
    if expression:
        expression = _dice(expression, (scale - 1) * int(expression.split('d')[0]) if recipe.get('scale') else recipe.get('upcast', 0) * extra)
    shared_damage = rules.roll_dice(expression) if recipe['kind'] == 'save' else None
    for target, target_actor in zip(targets, ids):
        kind = recipe['kind']
        if kind in {'attack', 'save', 'missile'}:
            iterations = scale if recipe.get('beams') else recipe.get('rays', 1) + recipe.get('upcast_rays', 0) * extra
            if kind == 'missile':
                iterations = 3 + extra
            for _ in range(iterations):
                if target['hp'] <= 0:
                    break
                if kind == 'attack':
                    r = rules.attack_roll(_check_bonus(state, c, _casting_bonus(c) + c.get('proficiency', 2)), armor_class(state, target), expression, advantage=attack_advantage(state,c,target,melee=spell.get('range')=='Touch'), disadvantage=attack_disadvantage(state,c,target,melee=spell.get('range')=='Touch'))
                    consume_attack_conditions(c,target)
                    amount = r['damage']
                elif kind == 'save':
                    r = saving_throw(state, target, recipe['save'], 8 + c.get('proficiency', 2) + _casting_bonus(c))
                    damage = shared_damage
                    amount = damage['total'] + recipe.get('flat', 0)
                    if r['success']:
                        amount = amount // 2 if recipe.get('half') else 0
                    r.update(kind='saving_throw', ability=recipe['save'], damage_dice=damage['dice'], damage=amount)
                else:
                    r = rules.roll_dice('1d4')
                    amount = r['total'] + 1
                    r.update(kind='automatic_hit', success=True, damage=amount)
                extra_damage = 0
                # Hex contributes once per successful attack, never to saves or missile.
                mark = c.get('concentration') or {}
                if kind == 'attack' and r['success'] and mark.get('spell_id') == 'hex' and mark.get('target_id') == target_actor:
                    die = rules.roll_dice('1d6', critical=r.get('critical', False))
                    extra_damage = _damage_enemy(target, die['total'], 'necrotic')
                    r['hex_dice'] = die['dice']
                amount = _damage_enemy(target, amount, recipe.get('type')) + extra_damage
                r['damage'] = amount
                applied = (kind == 'attack' and r.get('success')) or (kind == 'save' and not r.get('success'))
                if applied and recipe.get('condition'):
                    _condition(state, target, recipe['condition'], 1)
                events.append(rules.event('roll', f"{cap['label']}作用于{target.get('name', target_actor)}，造成 {amount} 点伤害。", actor_id=actor, target_id=target_actor, spell_id=sid, slot_level=level, roll=r))
        elif kind == 'heal':
            r = rules.roll_dice(expression) if expression else {'dice': [], 'total': 0}
            total = max(0, r['total'] + recipe.get('flat', 0) + recipe.get('upcast_flat', 0) * extra + (_casting_bonus(c) if recipe.get('modifier') else 0))
            amount = min(target['max_hp'] - target['hp'], total)
            target['hp'] += amount
            if target['hp'] > 0:
                target.update(stable=False, death_successes=0, death_failures=0)
            events.append(rules.event('roll', f"{cap['label']}恢复 {amount} 点生命。", actor_id=actor, target_id=target_actor, spell_id=sid, slot_level=level, roll={**r, 'kind': 'healing', 'healed': amount, 'total': total}))
        elif kind == 'stabilize':
            target.update(stable=True, death_successes=0, death_failures=0)
            events.append(rules.event('spell', '目标已稳定伤势，仍然处于倒地状态。', actor_id=actor, target_id=target_actor, spell_id=sid))
        elif kind == 'buff':
            _condition(state, target, recipe['buff'], recipe['rounds'], concentration_owner=actor, concentration_id=c['concentration']['id'])
            events.append(rules.event('spell', f"{cap['label']}已生效，需要维持专注。", actor_id=actor, target_id=target_actor, spell_id=sid))
        elif kind == 'mark':
            c['concentration']['target_id'] = target_actor
            events.append(rules.event('spell', f"{cap['label']}标记了{target['name']}。", actor_id=actor, target_id=target_actor, spell_id=sid))
        elif kind == 'temp_hp':
            r = rules.roll_dice(expression)
            amount = r['total'] + recipe.get('flat', 0) + recipe.get('upcast_flat', 0) * extra
            c['temp_hp'] = max(c.get('temp_hp', 0), amount)
            events.append(rules.event('roll', f"获得 {amount} 点临时生命；临时生命不叠加。", actor_id=actor, spell_id=sid, roll={**r, 'kind': 'temporary_hp', 'total': amount}))
        elif kind == 'restore':
            removable = {'blinded', 'deafened', 'paralyzed', 'poisoned'}
            matching = next((x for x in target.get('conditions', []) if x.get('id') in removable), None)
            if matching:
                target['conditions'].remove(matching)
            events.append(rules.event('spell', '解除一个失明、耳聋、麻痹或中毒状态；疾病由DM裁定。', actor_id=actor, target_id=target_actor, spell_id=sid))
    finish_combat(state, events)
    return events


def attacks_per_action(c):
    if _class(c) == 'fighter':
        return 4 if c.get('level', 1) >= 20 else 3 if c.get('level', 1) >= 11 else 2 if c.get('level', 1) >= 5 else 1
    return 2 if _class(c) in {'barbarian', 'monk', 'paladin', 'ranger'} and c.get('level', 1) >= 5 else 1


def weapon_attack(state, actor, target_id=None, *, smite=None, unarmed=False, spend_action=True):
    from .world_combat import validate_read_set
    validate_read_set(state)
    c = member(state, actor)['character']
    combat = _combat(state)
    if not combat or c['hp'] <= 0 or c.get('dead') or (spend_action and _budget_reason(state, actor, 'attack')) or combat['turn_actor_id'] != actor:
        raise ValueError('当前无法进行武器攻击')
    living = [e for e in combat['enemies'] if e['hp'] > 0]
    target = next((e for e in living if e['id'] == target_id), None) if target_id else (living[0] if len(living) == 1 else None)
    if target is None:
        raise ValueError('请选择存活的敌方目标')
    from . import tactical
    tactical.target(state,actor,target['id'],tactical.weapon_range(c))
    if not tactical.board(state) and (c.get('position') == 'withdrawn' or target.get('position') == 'withdrawn'):
        raise ValueError('目标已撤远，请先移动接近（抽象近战规则）')
    if spend_action:
        if not combat.get('action_used'):
            combat['attacks_remaining'] = attacks_per_action(c)
            combat['action_used'] = True
            combat['attack_action_taken'] = True
        combat['attacks_remaining'] -= 1
    weapon = c['weapon']
    ability = weapon.get('ability', 'str')
    damage = weapon.get('dice', '1d4')
    if unarmed:
        ability = 'dex' if c['abilities']['dex'] > c['abilities']['str'] else 'str'
        damage = '1d10' if c['level'] >= 17 else '1d8' if c['level'] >= 11 else '1d6' if c['level'] >= 5 else '1d4'
    bonus = rules.modifier(c['abilities'][ability])
    if c.get('rage') and ability == 'str':
        bonus_damage = 4 if c['level'] >= 16 else 3 if c['level'] >= 9 else 2
    else:
        bonus_damage = 0
    melee=not tactical.board(state) or tactical.weapon_range(c)<=5 or unarmed
    advantage = attack_advantage(state,c,target,melee=melee)
    disadvantage = attack_disadvantage(state,c,target,melee=melee)
    if tactical.board(state) and not melee:
        disadvantage=disadvantage or any(e['hp']>0 and tactical.distance(tactical.board(state)['positions'][actor],tactical.board(state)['positions'][e['id']])<=5 for e in combat['enemies'])
    r = rules.attack_roll(_check_bonus(state, c, bonus + c.get('proficiency', 2)), armor_class(state, target), damage, bonus + bonus_damage, advantage=advantage, disadvantage=disadvantage)
    consume_attack_conditions(c,target)
    if r['success']:
        # In the abstract encounter model conscious allies engage the same foes.
        eligible = advantage or any(m['id'] != actor and m['character']['hp'] > 0 and not m['character'].get('dead') for m in state['members'])
        if tactical.board(state):
            eligible=advantage or any(m['id']!=actor and m['character']['hp']>0 and tactical.distance(tactical.board(state)['positions'][m['id']],tactical.board(state)['positions'][target['id']])<=5 for m in state['members'])
        if _class(c) == 'rogue' and not combat.get('sneak_used') and ability == 'dex' and eligible and not disadvantage:
            extra = rules.roll_dice(f"{(c['level'] + 1) // 2}d6", critical=r['critical'])
            r['damage'] += extra['total']
            r['sneak_attack_dice'] = extra['dice']
            combat['sneak_used'] = True
        elemental_damage = 0
        mark = c.get('concentration') or {}
        if mark.get('spell_id') in {'hex', 'hunters-mark'} and mark.get('target_id') == target['id']:
            extra = rules.roll_dice('1d6', critical=r['critical'])
            if mark['spell_id'] == 'hex':
                elemental_damage += _damage_enemy(target, extra['total'], 'necrotic')
            else:
                r['damage'] += extra['total']
            r['mark_dice'] = extra['dice']
        if smite:
            level, source = smite
            _consume_slot(c, level, source)
            extra = rules.roll_dice(f"{min(5, level + 1) + int(target.get('type') in {'undead', 'fiend'})}d8", critical=r['critical'])
            elemental_damage += _damage_enemy(target, extra['total'], 'radiant')
            r['smite_dice'] = extra['dice']
        r['damage'] = _damage_enemy(target, r['damage'], 'bludgeoning' if unarmed else weapon.get('damage_type', 'slashing')) + elemental_damage
    events = [rules.event('roll', f"{'徒手攻击' if unarmed else weapon['name']}击向{target['name']}，造成 {r['damage']} 点伤害。", actor_id=actor, target_id=target['id'], roll=r)]
    finish_combat(state, events)
    return events


def _feature(state, actor, fid, target_id, options, cap):
    c = member(state, actor)['character']
    targets, ids = _selected_targets(state, actor, cap, target_id, options, 1)
    combat = _combat(state)
    if fid == 'divine-smite':
        slot = _select_slot(c, 1, options)
        return weapon_attack(state, actor, ids[0], smite=slot)
    amount = options.get('resource_amount')
    if fid == 'lay-on-hands':
        amount = amount if amount is not None else min(_resource(c, 'lay-on-hands'), targets[0]['max_hp'] - targets[0]['hp'])
        if not isinstance(amount, int) or isinstance(amount, bool) or not 1 <= amount <= min(_resource(c, 'lay-on-hands'), targets[0]['max_hp'] - targets[0]['hp']):
            raise ValueError('圣疗点数不合法')
    if fid == 'arcane-recovery':
        level = options.get('slot_level')
        valid = [int(k) for k, p in c.get('spell_slots', {}).items() if int(k) <= min(5, (c['level'] + 1) // 2) and p['current'] < p['max']]
        level = level if level is not None else max(valid, default=0)
        if level not in valid:
            raise ValueError('奥术回想所选法术位不合法')
    if fid == 'font-of-magic':
        level = options.get('slot_level') or 1
        cost = {1: 2, 2: 3, 3: 5, 4: 6, 5: 7}.get(level)
        pool = c.get('spell_slots', {}).get(str(level))
        if not cost or not pool or pool['current'] >= pool['max'] or _resource(c, 'sorcery-points') < cost:
            raise ValueError('当前无法用术法点恢复此环法术位（仅恢复已有位的房规）')
    resource = FEATURES[fid][-1]
    if resource:
        _spend(c, resource, amount if fid == 'lay-on-hands' else cost if fid == 'font-of-magic' else 1)
    _spend_budget(state, cap['action_cost'])
    events = []
    if fid == 'rage':
        c['rage'] = {'expires_round': _round(state) + 10}
        c['concentration'] = None
    elif fid == 'second-wind':
        r = rules.roll_dice('1d10')
        heal = min(c['max_hp'] - c['hp'], r['total'] + c['level'])
        c['hp'] += heal
        events.append(rules.event('roll', f'第二风恢复 {heal} 点生命。', actor_id=actor, roll={**r, 'kind': 'healing', 'healed': heal}))
    elif fid == 'action-surge':
        combat.update(action_used=False, attacks_remaining=0, surge_used=True)
    elif fid == 'bardic-inspiration':
        targets[0]['inspiration_die'] = '1d12' if c['level'] >= 15 else '1d10' if c['level'] >= 10 else '1d8' if c['level'] >= 5 else '1d6'
    elif fid == 'lay-on-hands':
        targets[0]['hp'] += amount
        targets[0].update(stable=False, death_successes=0, death_failures=0)
    elif fid == 'patient-defense':
        if actor not in combat['dodging']:
            combat['dodging'].append(actor)
    elif fid == 'flurry-of-blows':
        for _ in range(2):
            if not _combat(state) or targets[0]['hp'] <= 0:
                break
            events.extend(weapon_attack(state, actor, ids[0], unarmed=True, spend_action=False))
    elif fid == 'arcane-recovery':
        c['spell_slots'][str(level)]['current'] += 1
        c['short_rest_ready'] = False
    elif fid == 'font-of-magic':
        c['spell_slots'][str(level)]['current'] += 1
    if not events:
        events.append(rules.event('feature', f"{cap['label']}已生效。", actor_id=actor, target_id=ids[0]))
    return events


def apply_action(state, actor, action_id, target_id=None, options=None):
    from .world_combat import validate_read_set
    validate_read_set(state)
    options = options or {}
    allowed = {'slot_level', 'slot_source', 'target_ids', 'resource_amount'}
    if set(options) - allowed:
        raise ValueError('能力参数包含未授权字段')
    cap = next((x for x in capabilities(state, actor) if x['id'] == action_id), None)
    if not cap or cap.get('disabled_reason'):
        raise ValueError(cap.get('disabled_reason') if cap else '角色未获得此能力')
    # Work on a copy: invalid combinations may never partially charge resources.
    working = deepcopy(state)
    if action_id == 'end-concentration':
        member(working, actor)['character']['concentration'] = None
        events = [rules.event('spell', '主动结束专注。', actor_id=actor)]
    elif action_id.startswith('cast:'):
        events = _spell(working, actor, action_id[5:], target_id, options, cap)
    else:
        events = _feature(working, actor, action_id[8:], target_id, options, cap)
    state.clear()
    state.update(working)
    return events


def start_turn(state, actor):
    combat = state['combat']
    combat.update(movement_spent=0,movement_budget=30,bonus_action_used=False, attacks_remaining=0, attack_action_taken=False, bonus_spell_cast=False, leveled_spell_action=False, surge_used=False, sneak_used=False)
    combat['reactions_used'] = [x for x in combat.get('reactions_used', []) if x != actor]
    for c in [m['character'] for m in state['members']] + combat.get('enemies',[]):
        c['conditions'] = [x for x in active_conditions(state, c) if x.get('expires_on_turn_start') != actor]
        if c.get('concentration') and c['concentration'].get('expires_round', float('inf')) <= _round(state):
            c['concentration'] = None
        if c.get('rage') and c['rage'].get('expires_round', float('inf')) <= _round(state):
            c.pop('rage', None)


for _name in ('capabilities', 'available_actions', 'apply_action', 'weapon_attack'):
    globals()[_name] = bound_rules(globals()[_name])
