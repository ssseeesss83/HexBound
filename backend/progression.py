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
    if before.get("status") == "playing" and (moved or resolved):
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
