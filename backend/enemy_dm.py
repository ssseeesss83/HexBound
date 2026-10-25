"""DM's deterministic tactical agent: only frozen recipes, no player endpoint.

Enemy plans never teleport players or request model-authored dice/effects.
"""
from . import tactical as grid, rules, abilities as a


def mechanism(state,events):
    b=grid.board(state);combat=state['combat'];round=combat['round']
    if b['mechanic_round']==round:return
    b['mechanic_round']=round
    living=[m for m in state['members'] if m['character']['hp']>0]
    for warning in b['telegraphs']:
        if warning['due']>round:continue
        cells={(p['x'],p['y']) for p in warning['cells']}
        for m in living:
            p=b['positions'][m['id']]
            if (p['x'],p['y']) in cells:
                roll=a.saving_throw(state,m['character'],'dex',12)
                damage=rules.roll_dice('2d6')['total'];damage=damage//2 if roll['success'] else damage
                result=rules.damage_character(m['character'],damage,damage_type=warning.get('type','acid'),state=state)
                events.append(rules.event('roll',f"预警区域爆发，造成 {result['damage']} 点伤害。",actor_id=m['id'],roll=roll))
    b['telegraphs']=[w for w in b['telegraphs'] if w['due']>round]
    active=any(s['active'] for s in b['switches'])
    if b['mechanic']=='drain' and active:
        for e in combat['enemies']:
            if e['hp']>0:e['hp']=min(e['max_hp'],e['hp']+3)
        events.append(rules.event('mechanism','汲取装置为存活敌人恢复3 HP；关闭两处装置可阻止恢复。'))
    if b['mechanic'] in {'storm','crossfire'} and active and living:
        p=b['positions'][living[(round-1)%len(living)]['id']]
        cells=([dict(x=x,y=p['y']) for x in range(b['width'])] if b['mechanic']=='crossfire'
               else [dict(x=x,y=y) for x in range(max(0,p['x']-1),min(b['width'],p['x']+2))
                     for y in range(max(0,p['y']-1),min(b['height'],p['y']+2))])
        b['telegraphs'].append(dict(cells=cells,due=round+1,type='lightning'))
        events.append(rules.event('mechanism','地面出现预警：下轮爆发前离开标记格，或关闭两处装置。'))
    boss=next((e for e in combat['enemies'] if e.get('attack_count',1)>1 and e['hp']>0),None)
    if boss and boss['hp']<=boss['max_hp']//2 and b['phase']==1:
        b['phase']=2
        events.append(rules.event('mechanism','Boss 进入第二阶段：攻击更加猛烈，每次攻击额外2点伤害；现有先攻和位置不重置。'))
    b['revision']+=1


def turn(state,enemy,events):
    combat=state['combat'];b=grid.board(state)
    mechanism(state,events)
    if enemy['hp']<=0:return
    if any(a.has_condition(state,enemy,c) for c in ['stunned','paralyzed','incapacitated','unconscious']):
        events.append(rules.event('combat','DM：敌人失能，跳过行动。',actor_id=enemy['id']));return
    people=[m for m in state['members'] if m['character']['hp']>0 and not m['character'].get('dead')]
    if not people:return
    start=b['positions'][enemy['id']]
    target=min(people,key=lambda m:(grid.distance(start,b['positions'][m['id']]),m['character']['hp'],m['id']))
    reach=enemy.get('attack_range',5)
    routes=grid.paths(state,enemy['id'],grid.movement_remaining(state,enemy['id']))
    legal=[]
    for (x,y),route in routes.items():
        p=dict(x=x,y=y);t=b['positions'][target['id']]
        if grid.distance(p,t)<=reach and grid.visible(b,p,t):legal.append((route['cost'],x,y))
    if legal:
        _,x,y=min(legal)
    else:
        x,y=min(routes,key=lambda p:(grid.distance(dict(x=p[0],y=p[1]),b['positions'][target['id']]),routes[p]['cost']))
    movement=routes[(x,y)]
    if movement['cost']:
        b['positions'][enemy['id']]=dict(x=x,y=y);combat['movement_spent']=combat.get('movement_spent',0)+movement['cost'];b['revision']+=1
        events.append(rules.event('movement',f"DM：{enemy['name']}移动 {movement['cost']} 尺。",actor_id=enemy['id']))
    try:grid.target(state,enemy['id'],target['id'],reach)
    except ValueError:
        events.append(rules.event('combat',f"DM：{enemy['name']}被地形阻挡，守候通道。",actor_id=enemy['id']));return
    behaviors=enemy.get('behaviors',[])
    if 'regenerate' in behaviors and enemy.get('last_damage_type') not in {'fire','acid'}:
        enemy['hp']=min(enemy['max_hp'],enemy['hp']+3)
    if 'breath' in behaviors and combat['round']>=enemy.get('breath_ready',1):
        source=b['positions'][enemy['id']];aim=b['positions'][target['id']]
        dx,dy=aim['x']-source['x'],aim['y']-source['y']
        if dx or dy:
            end=dict(x=max(0,min(b['width']-1,source['x']+dx*4)),y=max(0,min(b['height']-1,source['y']+dy*4)))
            b['telegraphs'].append(dict(cells=grid.line_cells(source,end)[1:],due=combat['round']+1,type='acid'))
            enemy['breath_ready']=combat['round']+3
            events.append(rules.event('mechanism',f"DM：{enemy['name']}蓄积吐息，标记射线将于下轮爆发；本回合不进行普通攻击。",actor_id=enemy['id']));return
    if 'web' in behaviors and not enemy.get('web_used'):
        enemy['web_used']=True;save=a.saving_throw(state,target['character'],'dex',12)
        if not save['success']:a._condition(state,target['character'],'restrained',1)
        events.append(rules.event('roll','DM：蛛网/束缚预设，敏捷豁免失败则受束缚一轮。',actor_id=enemy['id'],target_id=target['id'],roll=save));return
    for _ in range(enemy.get('attack_count',1)):
        if target['character']['hp']<=0:break
        pack='pack' in behaviors and any(e['id']!=enemy['id'] and e['hp']>0 and grid.distance(b['positions'][e['id']],b['positions'][target['id']])<=5 for e in combat['enemies'])
        roll=rules.attack_roll(enemy['attack_bonus'],a.armor_class(state,target['character']),enemy['damage_dice'],enemy.get('damage_bonus',0)+(2 if b['phase']==2 else 0),
            advantage=pack or a.attack_advantage(state,enemy,target['character']),
            disadvantage=target['id'] in combat.get('dodging',[]) or a.attack_disadvantage(state,enemy))
        result=rules.damage_character(target['character'],roll['damage'],roll['critical'],enemy.get('damage_type','bludgeoning'),state)
        if roll['success'] and 'poison' in behaviors:
            save=a.saving_throw(state,target['character'],'con',11)
            if not save['success']:a._condition(state,target['character'],'poisoned',1)
        if roll['success'] and 'charge' in behaviors and movement['cost']>=15:
            save=a.saving_throw(state,target['character'],'str',12)
            if not save['success']:a._condition(state,target['character'],'prone',1)
        if 'drain' in behaviors:enemy['hp']=min(enemy['max_hp'],enemy['hp']+result['damage']//2)
        events.append(rules.event('roll',f"DM：{enemy['name']}攻击{target['name']}，造成 {result['damage']} 点伤害。",actor_id=enemy['id'],target_id=target['id'],roll=roll))
    combat['action_used']=True
