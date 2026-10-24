"""Published content runtime: typed cards, node graphs, authoritative combat.

No user-authored code or LLM text is executed. A package is copied when a
campaign starts, so editing/publishing its source cannot rewrite a live game.
"""
from copy import deepcopy
import secrets
import uuid
from . import rules


def _member(state, member_id):
    found = next((m for m in state["members"] if m["id"] == member_id), None)
    if not found:
        raise ValueError("角色不存在")
    return found


def _node(state):
    return next(n for n in state["campaign"]["package"]["scenario"]["nodes"] if n["id"] == state["campaign"]["node_id"])


def _skill(state, skill_id):
    card = state["campaign"]["package"]["skills"].get(skill_id)
    if not card:
        raise ValueError("技能不属于当前剧本快照")
    return card


def _remaining(state, actor, skill):
    limit = skill.get("uses")
    spent = state["campaign"]["spent"].get(actor, {}).get(skill["id"], 0)
    return None if limit is None else max(0, limit - spent)


def _spend(state, actor, skill):
    if _remaining(state, actor, skill) == 0:
        raise ValueError("技能使用次数已耗尽")
    uses = state["campaign"]["spent"].setdefault(actor, {})
    uses[skill["id"]] = uses.get(skill["id"], 0) + 1


def _is_host(state, actor):
    return state.get("_scene_leader_id", state.get("host_member_id", state.get("host_id"))) in (None, actor)


def _conscious(state):
    return [m for m in state["members"] if m["character"]["hp"] > 0 and not m["character"].get("dead")]


def validate_package(package):
    """Defense in depth; Studio performs the full publishing validation."""
    scenario = package["scenario"]
    if scenario.get('schema_version', 1) != 1:
        raise ValueError('此剧情图尚未接入当前运行器')
    nodes = scenario["nodes"]
    if not nodes or len({n["id"] for n in nodes}) != len(nodes):
        raise ValueError("节点为空或ID重复")
    ids = {n["id"] for n in nodes}
    if scenario["entry_node_id"] not in ids:
        raise ValueError("入口节点不存在")
    for skill_id in scenario.get("skill_ids", []):
        if skill_id not in package["skills"]:
            raise ValueError("缺少已发布技能")
    for skill in package["skills"].values():
        if skill.get("effect") not in EFFECT_HANDLERS or skill.get("target") not in EFFECT_TARGETS.get(skill.get("effect"), set()):
            raise ValueError("技能效果和目标不匹配")
        if skill.get("ability") not in {"str", "dex", "con", "int", "wis", "cha"}:
            raise ValueError("非法技能属性")
        if skill.get("uses") is not None and not 1 <= skill["uses"] <= 20:
            raise ValueError("非法技能次数")
        if skill["effect"] in {"attack", "heal"}:
            _validate_dice(skill["dice"])
    for monster in package["monsters"].values():
        if not 1 <= monster["hp"] <= 10000 or not 1 <= monster["ac"] <= 50:
            raise ValueError("非法怪物数值")
        _validate_dice(monster["damage_dice"])
    for node in nodes:
        if node.get("ending") and (node.get("actions") or node.get("monster_ids")):
            raise ValueError("结局节点不能含行动或遭遇")
        actions = node.get("actions", [])
        if len({a["id"] for a in actions}) != len(actions):
            raise ValueError("节点动作ID重复")
        for mid in node.get("monster_ids", []):
            if mid not in package["monsters"]:
                raise ValueError("缺少已发布怪物")
        for action in actions:
            sid = action.get("skill_id")
            if sid and (sid not in package["skills"] or package["skills"][sid]["effect"] != "check"):
                raise ValueError("节点挑战仅支持check技能")
            for key in ("next_node_id", "success_node_id", "failure_node_id"):
                if action.get(key) and action[key] not in ids:
                    raise ValueError("节点路由不存在")


def _validate_dice(expression):
    import re
    if not re.fullmatch(r"([1-9]|1[0-9]|20)d(4|6|8|10|12|20)", expression):
        raise ValueError("内容骰式仅允许1–20枚d4/d6/d8/d10/d12/d20")


def start_campaign(state, package):
    validate_package(package)
    state["campaign"] = {"package": deepcopy(package), "node_id": package["scenario"]["entry_node_id"], "spent": {}, "cleared": [], "visited": []}
    state["completed"] = False
    state["combat"] = None
    events = []
    _enter(state, state["campaign"]["node_id"], events)
    return events


def _enter(state, node_id, events):
    from .world_combat import enter_place
    enter_place(state, node_id)
    state["campaign"]["node_id"] = node_id
    node = _node(state)
    state["scene_id"] = node_id
    # Never put the full graph or routes in scene; API serializes only this view.
    state["scene"] = {"id": node_id, "title": node["title"], "text": node["text"], "objective": node.get("objective", ""), "eyebrow": state["campaign"]["package"]["scenario"]["name"], "objects": deepcopy(node.get("objects", []))}
    from .world_environment import attach_current
    attach_current(state)
    state["combat"] = None
    state["campaign"]["visited"].append(node_id)
    state["completed"] = bool(node.get("ending"))
    events.append(rules.event("ending" if state["completed"] else "scene", node["text"]))
    if state["completed"]:
        state["ending"] = node["text"]
    elif node.get("monster_ids") and node_id not in state["campaign"]["cleared"]:
        _start_combat(state, node, events)


def _start_combat(state, node, events):
    enemies = []
    rolls = []
    for index, mid in enumerate(node["monster_ids"]):
        card = deepcopy(state["campaign"]["package"]["monsters"][mid])
        card.update(id=f"enemy:{index}:{mid}", card_id=mid, max_hp=card["hp"])
        enemies.append(card)
    from .world_combat import begin, bind
    enemies, encounter_id = begin(state, enemies, spawn_key=node.get("spawn_key"))
    if not enemies:
        state["combat"] = None
        return
    for card in enemies:
        r = rules.check(card.get("initiative_bonus", 0))
        rolls.append((r["total"], card["id"]))
        events.append(rules.event("roll", f"{card['name']} 的先攻为 {r['total']}。", actor_id=card["id"], roll={**r, "kind": "initiative"}))
    for m in state["members"]:
        if m["character"].get("dead"):
            continue
        r = rules.check(rules.modifier(m["character"]["abilities"]["dex"]))
        rolls.append((r["total"], m["id"]))
        events.append(rules.event("roll", f"{m['name']} 的先攻为 {r['total']}。", actor_id=m["id"], roll={**r, "kind": "initiative"}))
    order = [actor for _, actor in sorted(rolls, key=lambda x: (-x[0], x[1]))]
    state["combat"] = {"active": True, "round": 1, "index": 0, "order": order, "turn_actor_id": order[0], "action_used": False, "dodging": [], "enemies": enemies}
    state["combat"].update(encounter_id=uuid.uuid4().hex, scene_id=state.get("scene_id"), bonus_action_used=False, reactions_used=[])
    bind(state, encounter_id)
    events.append(rules.event("combat", "遭遇开始。行动顺序已经由服务器确定。"))
    _auto(state, events)


def _step(state):
    c = state["combat"]
    from . import abilities
    abilities.end_turn(state,c["turn_actor_id"])
    c["index"] = (c["index"] + 1) % len(c["order"])
    if c["index"] == 0:
        c["round"] += 1
    c["turn_actor_id"] = c["order"][c["index"]]
    c["action_used"] = False
    abilities.start_turn(state,c["turn_actor_id"])


def _auto(state, events):
    c = state["combat"]
    for _ in range(len(c["order"]) + 1):
        survivors = [m for m in state["members"] if not m["character"].get("dead")]
        if not survivors or all(m["character"]["hp"] == 0 and m["character"].get("stable") for m in survivors):
            c["active"] = False
            state["completed"] = True
            state["ending"] = "队伍已无法继续这次冒险。你们的经历留在了远行者的记录中。"
            events.append(rules.event("ending", state["ending"]))
            return
        actor = c["turn_actor_id"]
        enemy = next((e for e in c["enemies"] if e["id"] == actor), None)
        if enemy:
            targets = _conscious(state)
            if enemy["hp"] > 0 and targets:
                target = targets[secrets.randbelow(len(targets))]
                from . import abilities
                if not abilities.prepare_enemy_melee(state,enemy,target["character"]):
                    _step(state)
                    continue
                r = rules.attack_roll(enemy["attack_bonus"], abilities.armor_class(state, target["character"]), enemy["damage_dice"], enemy.get("damage_bonus", 0), advantage=abilities.attack_advantage(state,enemy,target["character"]), disadvantage=target["id"] in c["dodging"] or abilities.attack_disadvantage(state,enemy))
                abilities.consume_attack_conditions(enemy,target["character"])
                outcome = rules.damage_character(target["character"], r["damage"], r["critical"], enemy.get("damage_type", "bludgeoning"), state)
                r["damage"] = outcome["damage"]
                if outcome["concentration"]:
                    events.append(rules.event("roll", "进行专注豁免。", actor_id=target["id"], roll=outcome["concentration"]))
                enemy["conditions"] = [x for x in enemy.get("conditions", []) if x.get("id") != "attack-disadvantage"]
                events.append(rules.event("roll", f"{enemy['name']} 攻击 {target['name']}，造成 {r['damage']} 点伤害。", actor_id=actor, target_id=target["id"], roll=r))
            _step(state)
            continue
        character = _member(state, actor)["character"]
        if character.get("dead") or (character["hp"] == 0 and character.get("stable")):
            _step(state)
            continue
        if actor in c["dodging"]:
            c["dodging"].remove(actor)
        return


def available_actions(state, member_id):
    if state.get("completed"):
        return []
    m = _member(state, member_id)
    character = m["character"]
    combat = state.get("combat")
    package = state["campaign"]["package"]
    if combat and combat.get("active"):
        if combat["turn_actor_id"] != member_id or character.get("dead"):
            return []
        end = {"id": "end_turn", "label": "结束回合" if character["hp"] > 0 else "进行死亡豁免 / 等待救援"}
        if character["hp"] == 0 or combat["action_used"]:
            return [end]
        enemy_targets = [{"id": e["id"], "name": e["name"]} for e in combat["enemies"] if e["hp"] > 0]
        actions = [{"id": "attack", "label": "使用装备武器攻击", "effect": "attack", "target": "enemy", "targets": enemy_targets, "uses_remaining": None}, {"id": "dodge", "label": "闪避", "effect": "defend", "target": "self", "uses_remaining": None}, end]
        for sid in package["scenario"].get("skill_ids", []):
            if character.get("class_id") and sid not in character.get("custom_skill_ids", []):
                continue
            skill = _skill(state, sid)
            remaining = _remaining(state, member_id, skill)
            if skill["effect"] == "check" or remaining == 0:
                continue
            targets = enemy_targets if skill["target"] == "enemy" else [{"id": p["id"], "name": p["name"]} for p in state["members"] if not p["character"].get("dead") and (skill["target"] == "ally" or p["id"] == member_id) and (skill["effect"] != "heal" or p["character"]["hp"] < p["character"]["max_hp"])]
            if not targets:
                continue
            actions.append({"id": f"skill:{sid}", "label": skill["name"], "description": skill.get("description", ""), "effect": skill["effect"], "target": skill["target"], "targets": targets, "remaining": remaining, "uses_remaining": remaining})
        return actions
    if not _conscious(state):
        return []
    actions = []
    for action in _node(state).get("actions", []):
        sid = action.get("skill_id")
        if sid:
            if character.get("dead") or character["hp"] <= 0 or _remaining(state, member_id, _skill(state, sid)) == 0:
                continue
        elif not _is_host(state, member_id):
            continue
        actions.append({"id": f"node:{action['id']}", "label": action["label"], "party_action": not bool(sid), "host_only": not bool(sid) and "_scene_leader_id" not in state, "leader_only": not bool(sid), "effect": "check" if sid else "move", "target": "none", "uses_remaining": _remaining(state, member_id, _skill(state, sid)) if sid else None, "remaining": _remaining(state, member_id, _skill(state, sid)) if sid else None})
    if character["hp"] > 0 and not character.get("dead"):
        for sid in package["scenario"].get("skill_ids", []):
            if character.get("class_id") and sid not in character.get("custom_skill_ids", []):
                continue
            card = _skill(state, sid)
            remaining = _remaining(state, member_id, card)
            if card["effect"] != "heal" or remaining == 0:
                continue
            targets = [{"id": m["id"], "name": m["name"]} for m in state["members"] if not m["character"].get("dead") and m["character"]["hp"] < m["character"]["max_hp"] and (card["target"] == "ally" or m["id"] == member_id)]
            if targets:
                actions.append({"id": f"skill:{sid}", "label": card["name"], "description": card.get("description", ""), "effect": "heal", "target": card["target"], "targets": targets, "remaining": remaining, "uses_remaining": remaining})
    return actions


def _effect_attack(state, member_id, skill, target_id):
    character = _member(state, member_id)["character"]
    combat = state["combat"]
    events = []
    living = [e for e in combat["enemies"] if e["hp"] > 0]
    target = next((e for e in living if e["id"] == target_id), None) if target_id else (living[0] if len(living) == 1 else None)
    if target is None:
        raise ValueError("请选择存活的敌方目标")
    ability = skill["ability"] if skill else character["weapon"]["ability"]
    bonus = rules.modifier(character["abilities"][ability]) + (skill.get("bonus", 0) if skill else 0)
    if skill:
        _spend(state, member_id, skill)
    r = rules.attack_roll(bonus + character["proficiency"], target["ac"], skill["dice"] if skill else character["weapon"]["dice"], bonus)
    target["hp"] = max(0, target["hp"] - r["damage"])
    events.append(rules.event("roll", f"{skill['name'] if skill else character['weapon']['name']}击向{target['name']}，造成 {r['damage']} 点伤害。", actor_id=member_id, target_id=target["id"], roll=r))
    return events[0]


def _effect_heal(state, member_id, skill, target_id):
    character = _member(state, member_id)["character"]
    combat = state["combat"]
    events = []
    target = _member(state, target_id or member_id)
    if skill["target"] == "self" and target["id"] != member_id:
        raise ValueError("该技能仅能作用于自己")
    tc = target["character"]
    if tc.get("dead") or tc["hp"] >= tc["max_hp"]:
        raise ValueError("目标死亡或无需治疗")
    _spend(state, member_id, skill)
    r = rules.roll_dice(skill["dice"])
    total = max(0, r["total"] + skill.get("bonus", 0))
    healed = min(tc["max_hp"] - tc["hp"], total)
    tc["hp"] += healed
    if tc["hp"] > 0:
        tc.update(death_successes=0, death_failures=0, stable=False)
    events.append(rules.event("roll", f"{skill['name']}为{target['name']}恢复 {healed} 点生命。", actor_id=member_id, target_id=target["id"], roll={**r, "kind": "healing", "modifier": skill.get("bonus", 0), "total": total, "healed": healed}))
    return events[0]


def _effect_defend(state, member_id, skill, target_id):
    character = _member(state, member_id)["character"]
    combat = state["combat"]
    events = []
    if target_id not in (None, member_id):
        raise ValueError("防御只能作用于自己")
    if skill:
        _spend(state, member_id, skill)
    combat["dodging"].append(member_id)
    events.append(rules.event("action", "你进入防御姿态，直到下回合开始，来袭攻击具有劣势。", actor_id=member_id))
    return events[0]


def _effect_check(state, member_id, skill, target_id):
    if target_id is not None:
        raise ValueError("检定不能使用客户端目标")
    character = _member(state, member_id)["character"]
    _spend(state, member_id, skill)
    from . import abilities
    r = abilities.ability_check(state, character, skill["ability"], skill.get("dc", 12), skill.get("proficiency_skill"), bonus=skill.get("bonus", 0))
    r["ability"] = skill["ability"]
    return rules.event("roll", f"{skill['name']}：{'成功' if r['success'] else '失败'}。", actor_id=member_id, roll=r)


EFFECT_HANDLERS = {"attack": _effect_attack, "heal": _effect_heal, "check": _effect_check, "defend": _effect_defend}
EFFECT_TARGETS = {"attack": {"enemy"}, "heal": {"self", "ally"}, "check": {"scene"}, "defend": {"self"}}

def apply_action(state, member_id, action_id, target_id=None):
    from .world_combat import validate_read_set
    validate_read_set(state)
    from . import abilities
    if action_id != "end_turn" and state.get("combat", {}) and state["combat"].get("active"):
        reason = abilities._budget_reason(state, member_id, "attack" if action_id == "attack" else "action")
        if reason:
            raise ValueError(reason)
    if action_id == "attack" and abilities.modern(_member(state, member_id)["character"]):
        return abilities.weapon_attack(state, member_id, target_id)
    if action_id not in {a["id"] for a in available_actions(state, member_id)}:
        raise ValueError("当前不可执行此动作")
    character = _member(state, member_id)["character"]
    events = []
    if action_id.startswith("node:"):
        action = next(a for a in _node(state)["actions"] if a["id"] == action_id[5:])
        if target_id is not None:
            raise ValueError("节点行动不接受客户端目标")
        sid = action.get("skill_id")
        next_node = action.get("next_node_id")
        from .world_combat import preflight_place
        for destination in {action.get(key) for key in ("next_node_id", "success_node_id", "failure_node_id")} - {None, ""}:
            preflight_place(state, destination)
        if sid:
            skill = _skill(state, sid)
            outcome = EFFECT_HANDLERS[skill["effect"]](state, member_id, skill, None)
            r = outcome["roll"]
            next_node = action.get("success_node_id" if r["success"] else "failure_node_id") or next_node
            events.append(outcome)
        else:
            events.append(rules.event("action", action["label"], actor_id=member_id))
        if next_node:
            _enter(state, next_node, events)
        return events
    combat = state["combat"]
    if action_id == "end_turn":
        if character["hp"] == 0:
            r = rules.death_save(character)
            if r:
                events.append(rules.event("roll", "进行死亡豁免。", actor_id=member_id, roll=r))
        _step(state)
        _auto(state, events)
        return events
    skill = _skill(state, action_id[6:]) if action_id.startswith("skill:") else None
    effect = skill["effect"] if skill else ("attack" if action_id == "attack" else "defend")
    events.append(EFFECT_HANDLERS[effect](state, member_id, skill, target_id))
    in_combat = bool(combat and combat.get("active"))
    if in_combat:
        combat["action_used"] = True
        combat["attacks_remaining"] = 0
    if in_combat and all(e["hp"] <= 0 for e in combat["enemies"]):
        combat["active"] = False
        if not combat.get("director_encounter"):
            state["campaign"]["cleared"].append(state["campaign"]["node_id"])
        for m in state["members"]:
            if m["character"]["hp"] == 0 and not m["character"].get("dead"):
                m["character"]["stable"] = True
        events.append(rules.event("combat", "遭遇结束。倒地幸存者被稳定伤势（冒险房规），前方的道路重新开放。"))
    return events
