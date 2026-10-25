"""Authored reasoning puzzles: correct reasoning is never rerolled randomly."""
from . import story_transitions as routes, rules


def prepare(state,actor,action):
    scope=routes._guard(state,actor)
    character=next(m['character'] for m in state['members'] if m['id']==actor)
    if character.get('dead') or character['hp']<=0:raise ValueError('角色当前无法解谜')
    view,facts,node=routes._source(state)
    parts=action.split(':')
    if len(parts)!=3:raise ValueError('谜题选项无效')
    puzzle=next((p for p in node.get('puzzles',[]) if p['id']==parts[1]),None)
    if not puzzle or parts[2] not in puzzle['choices']:raise ValueError('当前没有这个谜题选项')
    if facts['facts'][puzzle['solved_fact']]['value']:raise ValueError('谜题已经解决')
    key=node['id']+':'+action
    if key in state['campaign'].get('puzzle_receipts',[]):raise ValueError('这个方案已尝试，请依据提示调整')
    return dict(scope=scope,node_id=node['id'],puzzle_id=puzzle['id'],choice=parts[2],
        label=puzzle['choices'][parts[2]],revision=facts['revision'],receipt=key)


def resolve(state,actor,action,plan):
    if prepare(state,actor,action)!=plan:raise ValueError('谜题状态已变化')
    _,_,node=routes._source(state)
    puzzle=next(p for p in node['puzzles'] if p['id']==plan['puzzle_id'])
    state['campaign'].setdefault('puzzle_receipts',[]).append(plan['receipt'])
    facts=state['campaign']['story_state']
    if plan['choice']==puzzle['correct']:
        row=facts['facts'][puzzle['solved_fact']];row['value']=True;row['revision']+=1;facts['revision']+=1
        text=puzzle['success_text']
    else:
        character=next(m['character'] for m in state['members'] if m['id']==actor)
        character['hp']=max(1,character['hp']-2)
        text=puzzle['failure_text']+' 本方案造成最多2点擦伤（不会致死），不会阻断正确解法。'
    return [rules.event('puzzle',text,actor_id=actor)]


def menu(state,actor):
    try:_,_,node=routes._source(state)
    except (ValueError,KeyError):return []
    result=[]
    for puzzle in node.get('puzzles',[]):
        for choice in puzzle['choices']:
            id='story-puzzle:'+puzzle['id']+':'+choice
            try:plan=prepare(state,actor,id)
            except ValueError:continue
            result.append(dict(id=id,label=plan['label'],kind='puzzle',target='none',action_cost='none'))
    return result
