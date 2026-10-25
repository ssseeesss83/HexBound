"""Opt-in frozen 5-foot grid. No rendering or model text supplies authority."""
from collections import deque
from copy import deepcopy
import math
import re


def board(state):
    return (state.get('combat') or {}).get('board')


def initialize(state, config):
    if not config: return
    from .schemas import Battlefield
    config = Battlefield.model_validate(config).model_dump()
    positions = {}
    for i,m in enumerate(state['members']): positions[m['id']] = dict(x=1,y=i+1)
    for i,e in enumerate(state['combat']['enemies']): positions[e['id']] = dict(x=config['width']-2,y=i+1)
    switches = [dict(id='seal-a',x=4,y=2,active=True),dict(id='seal-b',x=config['width']-5,y=config['height']-3,active=True)]
    occupied = {(p['x'],p['y']) for p in config['walls']}
    for s in switches:
        if (s['x'],s['y']) in occupied: config['walls'].remove(dict(x=s['x'],y=s['y']))
    state['combat']['board'] = dict(**config,positions=positions,revision=0,
        switches=switches,telegraphs=[],phase=1,mechanic_round=0)
    state['combat'].update(movement_spent=0,movement_budget=30,spatial_profile='grid-v1')
    if config['mechanic']=='anchors':
        for e in state['combat']['enemies']:e['warded']=True


def distance(a,b):
    return 5*max(abs(a['x']-b['x']),abs(a['y']-b['y']))


def creature(state,actor):
    member = next((m['character'] for m in state['members'] if m['id']==actor),None)
    return member if member is not None else next((e for e in state['combat']['enemies'] if e['id']==actor),None)


def occupied(state,except_actor=None):
    return {(p['x'],p['y']) for actor,p in board(state)['positions'].items()
            if actor!=except_actor and not (creature(state,actor) or {}).get('dead')
            and ((creature(state,actor) or {}).get('hp',0)>0 or actor in {m['id'] for m in state['members']})}


def paths(state,actor,budget):
    from . import abilities
    b = board(state); start=b['positions'][actor]
    walls={(p['x'],p['y']) for p in b['walls']}; blocked=walls|occupied(state,actor)
    difficult={(p['x'],p['y']) for p in b['difficult']}
    origin=(start['x'],start['y']); costs={origin:0}; routes={origin:[]}; pending=deque([origin])
    while pending:
        x,y=pending.popleft()
        for dx,dy in [(0,1),(1,0),(0,-1),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)]:
            target=(x+dx,y+dy)
            if not (0<=target[0]<b['width'] and 0<=target[1]<b['height']) or target in blocked: continue
            if dx and dy and ((x+dx,y) in blocked or (x,y+dy) in blocked): continue
            cost=costs[(x,y)]+(10 if target in difficult else 5)*(2 if abilities.has_condition(state,creature(state,actor),'prone') else 1)
            if cost>budget or cost>=costs.get(target,10**9): continue
            costs[target]=cost; routes[target]=routes[(x,y)]+[dict(x=target[0],y=target[1])];pending.append(target)
    return {key:dict(cost=cost,path=routes[key]) for key,cost in costs.items()}


def line_cells(a,b):
    x,y=a['x'],a['y']; dx=abs(b['x']-x); dy=abs(b['y']-y)
    sx=1 if x<b['x'] else -1; sy=1 if y<b['y'] else -1; err=dx-dy; cells=[]
    while True:
        cells.append(dict(x=x,y=y))
        if (x,y)==(b['x'],b['y']): return cells
        e=2*err
        if e>-dy: err-=dy;x+=sx
        if e<dx: err+=dx;y+=sy


def visible(b,a,target):
    walls={(p['x'],p['y']) for p in b['walls']}
    cells=line_cells(a,target)
    for first,second in zip(cells,cells[1:]):
        if (second['x'],second['y']) in walls: return False
        if first['x']!=second['x'] and first['y']!=second['y'] and (
            (first['x'],second['y']) in walls or (second['x'],first['y']) in walls): return False
    return True


def target(state,actor,target_id,reach=5):
    b=board(state)
    if not b:return
    a=b['positions'].get(actor); t=b['positions'].get(target_id)
    if not a or not t:raise ValueError('目标不在当前战场')
    if distance(a,t)>reach:raise ValueError(f'目标超出 {reach} 尺范围，请先移动')
    if not visible(b,a,t):raise ValueError('墙体阻挡视线')


def weapon_range(character):
    weapon=character.get('weapon',{})
    # Existing character weapons are melee adapters unless explicitly ranged.
    if type(weapon.get('range')) is int:return weapon['range']
    return {'长弓':150,'Longbow':150,'短弓':80,'Shortbow':80,'轻弩':80,'Light Crossbow':80}.get(weapon.get('name'),5)


def ability_targets(state,actor,action_id,ids):
    if not board(state):return
    reach=5
    if action_id.startswith('cast:'):
        from . import abilities
        spell=abilities._spells()[action_id[5:]]
        text=spell.get('range','Touch')
        area_reach={'burning-hands':15,'thunderwave':15,'cone-of-cold':60,'lightning-bolt':100}
        if action_id[5:] in area_reach:text=str(area_reach[action_id[5:]])+' feet'
        number=re.search(r'\d+',text)
        reach=int(number.group()) if number else (0 if text=='Self' else 5)
        if text=='Self' and any(id!=actor for id in ids):raise ValueError('该法术只能作用于自己')
    elif action_id in {'feature:bardic-inspiration'}:reach=60
    elif action_id in {'feature:divine-smite','feature:flurry-of-blows','attack'}:
        reach=weapon_range(creature(state,actor)) if action_id=='attack' else 5
    for id in ids:target(state,actor,id,reach)
    if action_id.startswith('cast:') and len(ids)>1:
        sid=action_id[5:];b=board(state);origin=b['positions'][actor];anchor=b['positions'][ids[0]]
        if sid in {'fireball','mass-healing-word','mass-cure-wounds'}:
            radius=20 if sid=='fireball' else 30
            if any(distance(anchor,b['positions'][id])>radius for id in ids):raise ValueError('所选目标不在同一作用区域')
        if sid=='lightning-bolt':
            dx,dy=anchor['x']-origin['x'],anchor['y']-origin['y']
            if not (dx or dy):raise ValueError('请选择射线方向')
            if any(dx*(b['positions'][id]['x']-origin['x'])+dy*(b['positions'][id]['y']-origin['y'])<=0 for id in ids):raise ValueError('闪电束目标须位于同一前向射线')
            if any(abs(dx*(b['positions'][id]['y']-origin['y'])-dy*(b['positions'][id]['x']-origin['x']))>max(abs(dx),abs(dy)) for id in ids):
                raise ValueError('闪电束目标须在同一条5尺宽射线上')
        if sid in {'burning-hands','cone-of-cold'}:
            dx,dy=anchor['x']-origin['x'],anchor['y']-origin['y']
            for id in ids:
                p=b['positions'][id];vx,vy=p['x']-origin['x'],p['y']-origin['y']
                if vx*dx+vy*dy<=0 or abs(dx*vy-dy*vx)>vx*dx+vy*dy:raise ValueError('目标不在同一扇形方向')


def movement_remaining(state,actor):
    from . import abilities
    c=creature(state,actor)
    if not c or c.get('dead') or c.get('hp',0)<=0:return 0
    if any(abilities.has_condition(state,c,x) for x in ['grappled','restrained','paralyzed','stunned','unconscious','incapacitated']):return 0
    return max(0,state['combat'].get('movement_budget',30)-state['combat'].get('movement_spent',0))


def prepare(state,actor,action_id,destination=None):
    from . import abilities
    combat=abilities._combat(state);b=board(state)
    if not combat or not b or combat['turn_actor_id']!=actor:raise ValueError('只能在自己的战棋回合操作')
    c=abilities.member(state,actor)['character']
    if c['hp']<=0 or c.get('dead'):raise ValueError('角色当前无法行动')
    if action_id=='grid:move':
        from .schemas import GridPoint
        p=GridPoint.model_validate(destination).model_dump()
        route=paths(state,actor,movement_remaining(state,actor)).get((p['x'],p['y']))
        if not route or not route['cost']:raise ValueError('目标格不可达、被占据或移动不足')
        return dict(destination=p,**route,action_cost='movement',label='移动至选定格')
    if action_id.startswith('grid:seal-'):
        reason=abilities._budget_reason(state,actor,'action')
        if reason:raise ValueError(reason)
        switch=next((s for s in b['switches'] if s['id']==action_id[5:] and s['active']),None)
        if not switch or distance(b['positions'][actor],switch)>5 or not visible(b,b['positions'][actor],switch):raise ValueError('需要移动至装置旁5尺内')
        return dict(switch_id=switch['id'],cost=0,action_cost='action',label='关闭场地装置')
    raise ValueError('未知战场操作')


def resolve(state,actor,action_id,options):
    from . import rules,abilities
    plan=prepare(state,actor,action_id,options.get('destination'));b=board(state)
    if action_id=='grid:move':
        b['positions'][actor]=plan['destination'];state['combat']['movement_spent']=state['combat'].get('movement_spent',0)+plan['cost']
        c=creature(state,actor);c.pop('cover',None)
        c['conditions']=[x for x in c.get('conditions',[]) if x.get('id')!='hidden']
        for unit in [m['character'] for m in state['members']]+state['combat']['enemies']:
            unit['conditions']=[x for x in unit.get('conditions',[]) if x.get('id')!='grappled' or x in abilities.active_conditions(state,unit)]
        text=f"移动至 ({plan['destination']['x']+1},{plan['destination']['y']+1})，消耗 {plan['cost']} 尺移动。"
    else:
        next(s for s in b['switches'] if s['id']==plan['switch_id'])['active']=False
        if not any(s['active'] for s in b['switches']):
            for e in state['combat']['enemies']:e['warded']=False
            b['telegraphs']=[w for w in b['telegraphs'] if w.get('source')!='scene']
        abilities._spend_budget(state,'action');text='关闭场地装置，消耗一个动作；装置不会因刷新恢复。'
    b['revision']+=1
    return [rules.event('movement' if action_id=='grid:move' else 'mechanism',text,actor_id=actor)]


def projection(state,actor):
    b=board(state)
    if not b:return None
    view=deepcopy(b);view['cell_feet']=5
    view['movement_remaining']=movement_remaining(state,actor) if state['combat']['turn_actor_id']==actor else 0
    view['reachable']=[dict(x=x,y=y,cost=r['cost']) for (x,y),r in paths(state,actor,view['movement_remaining']).items()] if actor in b['positions'] else []
    view['attackable']=[]
    from . import abilities
    view['ranges']={'attack':weapon_range(creature(state,actor))}
    for cap in abilities.capabilities(state,actor):
        if cap['id'].startswith('cast:'):
            text=abilities._spells()[cap['id'][5:]].get('range','Touch')
            area={'burning-hands':15,'thunderwave':15,'cone-of-cold':60,'lightning-bolt':100}
            if cap['id'][5:] in area:text=str(area[cap['id'][5:]])+' feet'
            number=re.search(r'\d+',text)
            view['ranges'][cap['id']]=int(number.group()) if number else (0 if text=='Self' else 5)
        elif cap['id'].startswith('feature:'):view['ranges'][cap['id']]=60 if cap['id']=='feature:bardic-inspiration' else 5
    origin=b['positions'].get(actor)
    view['visible_cells']=[dict(x=x,y=y) for x in range(b['width']) for y in range(b['height']) if origin and visible(b,origin,dict(x=x,y=y))]
    for enemy in state['combat']['enemies']:
        if enemy['hp']<=0:continue
        try:target(state,actor,enemy['id'],weapon_range(creature(state,actor)));view['attackable'].append(enemy['id'])
        except ValueError:pass
    return view


def menu(state,actor):
    if not board(state):return []
    result=[]
    for s in board(state)['switches']:
        try:plan=prepare(state,actor,'grid:'+s['id'])
        except ValueError:continue
        result.append(dict(id='grid:'+s['id'],label=plan['label'],target='none',action_cost='action',kind='tactical'))
    return result
