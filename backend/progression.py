"""Scripted rewards and world time. All mutations are saved with command receipts."""
from . import characters


def award(state, before):
    events=[]
    ledger=state.setdefault("reward_ledger", [])
    progression=state.setdefault("progression", {"mode":"xp","world_minutes":0})
    old=before.get("combat") or {}
    new=state.get("combat") or {}
    rewards=[]
    if old.get("active") and not new.get("active") and new.get("enemies") and all(e["hp"] <= 0 for e in new["enemies"]):
        key="battle:" + str(new.get("encounter_id") or before.get("scene_id"))
        total=sum(max(0,int(e.get("xp",50))) for e in new["enemies"])
        rewards.append((key,total,"战胜遭遇"))
    moved=before.get("scene_id") != state.get("scene_id")
    resolved=not before.get("flags",{}).get("scene_resolved") and state.get("flags",{}).get("scene_resolved")
    native = state.get('campaign',{}).get('package',{}).get('scenario',{}).get('schema_version')==2
    checkpoint=state.get('campaign',{}).get('package',{}).get('scenario',{}).get('checkpoints',{}).get(state.get('scene_id')) if native else None
    if checkpoint and moved and before.get('status')=='playing':
        key='checkpoint:'+state['scene_id']
        if key not in ledger:
            ledger.append(key)
            if checkpoint['rest']:
                progression['world_minutes']=progression.get('world_minutes',0)+1440
                for member in state['members']:
                    if not member['character'].get('dead'):
                        member['character']=characters.long_rest(member['character'])
                        member['character']['last_long_rest_end']=progression['world_minutes']
                progression['last_long_rest_end']=progression['world_minutes']
                events.append(dict(kind='rest',text='队伍在安全据点休整一天，恢复生命与职业资源；已完成的遭遇、谜题和装置保持原状。'))
            if checkpoint['xp']:
                eligible=sum(not m['character'].get('dead') for m in state['members'])
                rewards.append(('objective:chapter:'+state['scene_id'],checkpoint['xp']*eligible,'完成航标章节'))
    if native and state.get('completed') and not before.get('completed') and before.get('status') == 'playing' and any(
        n['id']==state.get('scene_id') and n['kind']=='ending'
        for n in state['campaign']['package']['scenario']['nodes']):
        # v0.9 original adventure policy, not an SRD XP rule. Per-room ledger
        # makes every authored ending equivalent and prevents replay farming.
        scenario = state['campaign']['package']['scenario']
        rewards.append(('objective:ending:'+scenario['id'],300*len([m for m in state['members'] if not m['character'].get('dead')]),'完成冒险'))
    if not native and before.get("status") == "playing" and (moved or resolved):
        # An original campaign reward, explicitly distinct from SRD monster XP.
        rewards.append(("objective:"+str(before.get("scene_id")),100*len(state["members"]),"完成场景目标"))
        if moved:
            progression["world_minutes"] = progression.get("world_minutes",0)+60
    for key,total,label in rewards:
        if key in ledger:
            continue
        ledger.append(key)
        eligible=[m for m in state["members"] if not m["character"].get("dead")]
        amount=total//max(1,len(eligible))
        for member in eligible:
            if progression.get("mode") == "milestone":
                # One milestone per objective, not per monster or free-text check.
                if not key.startswith("objective:"):
                    continue
                member["character"]["milestone_credits"]=member["character"].get("milestone_credits",0)+1
            else:
                member["character"]=characters.add_xp(member["character"],amount)
        if progression.get("mode") != "milestone" or key.startswith("objective:"):
            events.append({"kind":"reward","text":label+ ("，获得一个升级里程碑。" if progression.get("mode")=="milestone" else f"，每位存活角色获得 {amount} XP。"),"reward_id":key,"xp_each":amount if progression.get("mode")!="milestone" else 0})
    return events
