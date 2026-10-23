"""Server-authoritative, testable SRD 5.1 subset. No LLM dependency."""
import re
import secrets
from . import content

def modifier(score):
    return (score - 10) // 2

def roll_dice(expression, *, critical=False):
    match = re.fullmatch(r"([1-9][0-9]?)d(4|6|8|10|12|20|100)", expression)
    if not match:
        raise ValueError("非法骰式")
    count, sides = map(int, match.groups())
    count *= 2 if critical else 1
    if count > 100:
        raise ValueError("骰子数量超限")
    dice = [secrets.randbelow(sides) + 1 for _ in range(count)]
    return {"expression": expression, "dice": dice, "total": sum(dice)}

def check(bonus=0, dc=10, *, advantage=False, disadvantage=False):
    use_two = bool(advantage) != bool(disadvantage)
    dice = roll_dice("2d20" if use_two else "1d20")["dice"]
    selected = (max(dice) if advantage else min(dice)) if use_two else dice[0]
    return {"kind": "check", "dice": dice, "selected": selected, "modifier": bonus, "total": selected + bonus, "dc": dc, "success": selected + bonus >= dc, "advantage": bool(advantage and not disadvantage), "disadvantage": bool(disadvantage and not advantage)}

def attack_roll(bonus, ac, damage_dice, damage_bonus=0, *, advantage=False, disadvantage=False):
    result = check(bonus, ac, advantage=advantage, disadvantage=disadvantage)
    result.update({"kind": "attack", "ac": ac, "critical": result["selected"] == 20})
    result["success"] = result["selected"] == 20 or (result["selected"] != 1 and result["total"] >= ac)
    result["damage_dice"] = []
    result["damage"] = 0
    if result["success"]:
        damage = roll_dice(damage_dice, critical=result["critical"])
        result["damage_dice"] = damage["dice"]
        result["damage"] = max(0, damage["total"] + damage_bonus)
    return result

def damage_character(c, amount, critical=False):
    if c.get("dead"):
        return
    before = c["hp"]
    c["hp"] = max(0, before - amount)
    if c["hp"] == 0 and amount > 0:
        c["stable"] = False
        if amount - before >= c["max_hp"]:
            c["dead"] = True
        elif before == 0:
            c["death_failures"] += 2 if critical else 1
            c["dead"] = c["death_failures"] >= 3

def death_save(c):
    if c["hp"] > 0 or c.get("stable") or c.get("dead"):
        return None
    result = check(0, 10)
    result["kind"] = "death_save"
    if result["selected"] == 20:
        c.update(hp=1, death_successes=0, death_failures=0, stable=False)
    elif result["selected"] == 1:
        c["death_failures"] += 2
    elif result["success"]:
        c["death_successes"] += 1
    else:
        c["death_failures"] += 1
    c["dead"] = c["death_failures"] >= 3
    c["stable"] = c["hp"] == 0 and c["death_successes"] >= 3 and not c["dead"]
    return result

def event(kind, text, **kwargs):
    return {"kind": kind, "text": text, **kwargs}

def _member(state, actor):
    m = next((m for m in state["members"] if m["id"] == actor), None)
    if not m:
        raise ValueError("角色不存在")
    return m

def _defeat(state, events):
    if all(m["character"].get("dead") or (m["character"]["hp"] == 0 and m["character"].get("stable")) for m in state["members"]):
        state["combat"]["active"] = False
        state["completed"] = True
        state["ending"] = "队伍已无法继续这次冒险。幸存者等待救援，你们的经历留在了远行者的记录中。"
        events.append(event("ending", state["ending"]))
        return True
    return False

def start_combat(state):
    participants = []
    events = []
    for m in state["members"]:
        if not m["character"].get("dead"):
            r = check(modifier(m["character"]["abilities"]["dex"]))
            participants.append((r["total"], m["id"]))
            events.append(event("roll", f"{m['name']} 掷出先攻 {r['total']}", actor_id=m["id"], roll={**r, "kind": "initiative"}))
    r = check(0)
    participants.append((r["total"], "enemy"))
    order = [p[1] for p in sorted(participants, key=lambda p: (-p[0], p[1]))]
    hp = 7 + 3 * len(state["members"])
    state["combat"] = {"active": True, "round": 1, "order": order, "index": 0, "turn_actor_id": order[0], "action_used": False, "dodging": [], "enemy": {"id": "enemy", "name": state.get("enemy_name", "守卫" if state.get("mode") == "free" else "盐壳守卫"), "hp": hp, "max_hp": hp, "ac": 11}}
    state["combat"]["enemies"] = [state["combat"]["enemy"]]
    events.append(event("combat", f"{state['combat']['enemy']['name']}阻断了前路。战斗开始。"))
    _auto_turns(state, events)
    return events

def _step(state):
    combat = state["combat"]
    combat["index"] = (combat["index"] + 1) % len(combat["order"])
    if combat["index"] == 0:
        combat["round"] += 1
    combat["turn_actor_id"] = combat["order"][combat["index"]]
    combat["action_used"] = False

def _auto_turns(state, events):
    combat = state["combat"]
    for _ in range(len(combat["order"]) + 1):
        if _defeat(state, events):
            return
        actor = combat["turn_actor_id"]
        if actor != "enemy":
            c = _member(state, actor)["character"]
            if c.get("dead") or c.get("stable"):
                _step(state)
                continue
            if actor in combat["dodging"]:
                combat["dodging"].remove(actor)
            return
        targets = [m for m in state["members"] if m["character"]["hp"] > 0 and not m["character"].get("dead")]
        if targets:
            target = targets[secrets.randbelow(len(targets))]
            r = attack_roll(2, target["character"]["ac"], "1d4", disadvantage=target["id"] in combat["dodging"])
            damage_character(target["character"], r["damage"], r["critical"])
            events.append(event("roll", f"{combat['enemy']['name']}攻击 {target['name']}，造成 {r['damage']} 点伤害。", actor_id="enemy", target_id=target["id"], roll=r))
        _step(state)

def apply_action(state, member_id, action_id, target_id=None):
    if action_id not in {a["id"] for a in content.available_actions(state, member_id)}:
        raise ValueError("当前不可执行此动作")
    if action_id in {"advance", "rest"} and state.get("host_member_id", state.get("host_id")) not in (None, member_id):
        raise ValueError("仅房主可以执行此动作")
    m = _member(state, member_id)
    c = m["character"]
    events = []
    combat = state.get("combat")
    in_combat = bool(combat and combat.get("active"))
    if action_id == "heal":
        target = _member(state, target_id or member_id)
        tc = target["character"]
        if tc.get("dead"):
            raise ValueError("药水不能复活死亡角色")
        if tc["hp"] == tc["max_hp"]:
            raise ValueError("目标无需治疗")
        r = roll_dice("2d4")
        amount = min(tc["max_hp"] - tc["hp"], r["total"] + 2)
        tc.update(hp=tc["hp"] + amount, death_successes=0, death_failures=0, stable=False)
        c["potions"] -= 1
        if in_combat:
            combat["action_used"] = True
        events.append(event("roll", f"{m['name']} 使用药水，{target['name']} 恢复 {amount} 点生命。", actor_id=member_id, roll={**r, "kind": "healing", "modifier": 2, "total": r["total"] + 2, "healed": amount}))
    elif in_combat:
        if action_id == "attack":
            if target_id not in (None, "enemy"):
                raise ValueError("非法攻击目标")
            bonus = modifier(c["abilities"][c["weapon"]["ability"]])
            r = attack_roll(bonus + c["proficiency"], combat["enemy"]["ac"], c["weapon"]["dice"], bonus)
            combat["enemy"]["hp"] = max(0, combat["enemy"]["hp"] - r["damage"])
            combat["enemies"] = [combat["enemy"]]
            combat["action_used"] = True
            events.append(event("roll", f"{m['name']} 使用{c['weapon']['name']}，造成 {r['damage']} 点伤害。", actor_id=member_id, roll=r))
            if combat["enemy"]["hp"] == 0:
                combat["active"] = False
                state.setdefault("flags", {})["scene_resolved"] = True
                if state.get("scene_index") == 1:
                    state["flags"]["lens"] = True
                if state.get("scene_index") == 3:
                    state["flags"]["resolution"] = "fight"
                for member in state["members"]:
                    # Adventure-specific aftermath: surviving downed heroes are stabilized.
                    if member["character"]["hp"] == 0 and not member["character"].get("dead"):
                        member["character"]["stable"] = True
                events.append(event("combat", "对手倒下了。幸存的倒地队友已被稳定伤势，可以由药水救治（冒险房规）。"))
        elif action_id == "dodge":
            combat["dodging"].append(member_id)
            combat["action_used"] = True
            events.append(event("action", f"{m['name']} 专注闪避，直到下次回合开始。"))
        elif action_id == "end_turn":
            if c["hp"] == 0:
                r = death_save(c)
                if r:
                    events.append(event("roll", f"{m['name']} 进行死亡豁免。", actor_id=member_id, roll=r))
            _step(state)
            _auto_turns(state, events)
    elif action_id == "rest":
        state["rest_used"] = True
        for member in state["members"]:
            tc = member["character"]
            if not tc.get("dead"):
                tc.update(hp=tc["max_hp"], death_successes=0, death_failures=0, stable=False)
        events.append(event("rest", "你们在避风处休整，恢复全部生命。这次冒险唯一的休整机会已用尽（简化房规）。"))
    elif action_id == "advance":
        state["scene_index"] = min(state.get("scene_index", 0) + 1, len(state.get("scenes") or content.SCENES) - 1)
        state["scene"] = content.scene_for(state)
        state["scene_id"] = state["scene"]["id"]
        state["flags"]["scene_resolved"] = False
        state["completed"] = state["scene_index"] == len(state.get("scenes") or content.SCENES) - 1
        if state["completed"]:
            if state.get("mode") != "free":
                state["scene"] = content.ending_scene(state)
            state["ending"] = state["scene"]["text"]
        events.append(event("ending" if state["completed"] else "scene", state["scene"]["text"]))
    elif action_id == "fight":
        state.setdefault("flags", {}).setdefault("attempted", {})[f"{state.get('scene_index', 0)}:fight"] = True
        events.extend(start_combat(state))
    else:
        action = next(a for a in content.scene_for(state)["actions"] if a["id"] == action_id)
        index = state.get("scene_index", 0)
        flags = state.setdefault("flags", {})
        # The complete oath is a scenario-specific source of advantage, locked before rolling.
        oath_advantage = state.get("mode") != "free" and index == 3 and action_id == "parley" and bool(flags.get("oath"))
        r = check(modifier(c["abilities"][action["ability"]]), action["dc"], advantage=oath_advantage)
        r["ability"] = action["ability"]
        flags.setdefault("attempted", {})[f"{state.get('scene_index', 0)}:{action_id}"] = True
        flags["scene_resolved"] = True
        if index == 1:
            flags["lens"] = True
        if index == 2 and action_id == "investigate":
            flags["oath"] = r["success"]
        if index == 2 and action_id == "repair":
            flags["safe_path"] = r["success"]
        if index == 3:
            flags["resolution"] = action_id
            flags["released"] = action_id == "parley" and r["success"] and bool(flags.get("oath"))
        if not r["success"]:
            flags["pressure"] = flags.get("pressure", 0) + 1
        text = content.outcome_text(index, action_id, r["success"]) if state.get("mode") != "free" else ("行动打开了一条安全的道路。" if r["success"] else "你付出了时间与风险，但仍找到了继续前进的线索。")
        if state.get("mode") != "free" and index == 3 and action_id == "parley" and r["success"] and not flags.get("oath"):
            text = "守望者相信你的善意，允许你点亮灯芯；但没有完整誓言，他仍无法离开。你答应陪他坐到天亮。"
        events.append(event("roll", text, actor_id=member_id, roll=r))
        if index == 1 and not r["success"]:
            events.extend(start_combat(state))
    return events
