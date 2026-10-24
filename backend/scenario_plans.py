"""Pure validation for frozen scenario options and legacy prototype handlers."""
from copy import deepcopy

from . import abilities as a, campaign, content
from .action_menu import available


def prepare(state, actor, action_id, target_id, options):
    from .world_combat import preflight_place
    if action_id == 'end_turn':
        raise ValueError('结束回合请使用回合控制入口')
    if any(value not in (None, []) for value in options.values()):
        raise ValueError('剧情行动不接受额外能力参数')
    cap = next((row for row in available(state, actor) if row['id'] == action_id), None)
    if not cap:
        raise ValueError('当前不可执行此动作')
    from . import attempts
    attempts.require(state, actor, action_id)
    c = a.member(state, actor)['character']
    combat = a._combat(state)
    if combat:
        reason = a._budget_reason(state, actor, 'attack' if action_id == 'attack' else 'action')
        if reason:
            raise ValueError(reason)
    resources, ids = [], []
    card = None
    if state.get('campaign'):
        if action_id.startswith('node:'):
            action = next(row for row in campaign._node(state)['actions'] if row['id'] == action_id[5:])
            if target_id is not None:
                raise ValueError('节点行动不接受客户端目标')
            for destination in {action.get(key) for key in ('next_node_id', 'success_node_id', 'failure_node_id')} - {None, ''}:
                preflight_place(state, destination)
            if action.get('skill_id'):
                card = campaign._skill(state, action['skill_id'])
                if card['effect'] != 'check':
                    raise ValueError('节点能力必须是已发布的检定')
        elif action_id.startswith('skill:'):
            card = campaign._skill(state, action_id[6:])
        elif action_id not in {'attack', 'dodge'}:
            raise ValueError('剧情行动没有可用处理器')
    elif action_id == 'advance':
        index = min(state.get('scene_index', 0) + 1, len(state.get('scenes') or content.SCENES) - 1)
        preflight_place(state, content.scene_for({**state, 'scene_index': index})['id'])
    elif action_id == 'fight' or (not combat and action_id not in {'heal', 'rest'} and state.get('scene_index', 0) == 1):
        preflight_place(state, state.get('scene_id') or content.scene_for(state)['id'])
    if card:
        remaining = campaign._remaining(state, actor, card)
        if remaining == 0:
            raise ValueError('剧情能力次数已用尽')
        if remaining is not None:
            resources.append(dict(type='scenario_use', id=card['id'], amount=1, remaining=remaining))
    effect = card['effect'] if card else {'attack':'attack', 'dodge':'defend', 'heal':'heal'}.get(action_id)
    if effect == 'attack':
        living = [row for row in combat['enemies'] if row['hp'] > 0] if combat else []
        target = next((row for row in living if row['id'] == target_id), None) if target_id else (living[0] if len(living) == 1 else None)
        if not target:
            raise ValueError('请选择存活的敌方目标')
        if not state.get('campaign') and target['id'] != 'enemy':
            raise ValueError('旧版单敌处理器不支持这个目标')
        ids = [target['id']]
    elif effect == 'heal':
        target = next((row for row in state['members'] if row['id'] == (target_id or actor)), None)
        if not target or target['character'].get('dead') or target['character']['hp'] >= target['character']['max_hp']:
            raise ValueError('请选择当前场景需要治疗的存活成员')
        if card and card['target'] == 'self' and target['id'] != actor:
            raise ValueError('该技能仅能作用于自己')
        ids = [target['id']]
        if not card:
            if c.get('potions', 0) < 1:
                raise ValueError('没有治疗药水')
            resources.append(dict(type='item', id='healing-potion', amount=1))
    elif effect == 'defend':
        if target_id not in (None, actor):
            raise ValueError('防御只能作用于自己')
        ids = [actor]
    elif target_id is not None:
        raise ValueError('剧情检定与移动不接受客户端目标')
    cap = deepcopy(cap)
    # Legacy weapon attacks and scenario skills each consume the whole action.
    cap['action_cost'] = 'action' if combat else 'none'
    cap['description'] = cap.get('description') or '按冻结剧本与当前原型处理器结算；检定和伤害结果尚未发生。'
    return cap, ids, resources
