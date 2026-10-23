"""Original adventure content and server-owned level-one character templates."""
from copy import deepcopy

TEMPLATES = {
    "fighter": {"label": "铁卫", "role": "近战守护", "max_hp": 12, "ac": 16, "abilities": {"str": 16, "dex": 12, "con": 14, "int": 10, "wis": 13, "cha": 8}, "weapon": {"name": "长剑", "ability": "str", "dice": "1d8"}},
    "rogue": {"label": "游猎者", "role": "敏捷探索", "max_hp": 10, "ac": 14, "abilities": {"str": 10, "dex": 16, "con": 14, "int": 13, "wis": 12, "cha": 8}, "weapon": {"name": "短剑", "ability": "dex", "dice": "1d6"}},
    "warden": {"label": "守灯人", "role": "洞察交涉", "max_hp": 11, "ac": 15, "abilities": {"str": 14, "dex": 12, "con": 14, "int": 10, "wis": 16, "cha": 8}, "weapon": {"name": "短矛", "ability": "str", "dice": "1d6"}},
    "scholar": {"label": "行脚学者", "role": "调查学识", "max_hp": 10, "ac": 13, "abilities": {"str": 10, "dex": 14, "con": 14, "int": 16, "wis": 12, "cha": 8}, "weapon": {"name": "匕首", "ability": "dex", "dice": "1d4"}},
}
SCENES = [
    {"id": "dock", "title": "雨夜码头", "eyebrow": "第一幕 · 雾港", "text": "灯塔熄灭后的第三夜，船只仍朝礁石驶去。守夜人将一枚盐蚀铜钥匙放在桌上：‘天亮以前，把那束光带回来。’雨幕后的脚印通向旧海关。", "actions": [{"id": "investigate", "label": "俯身查看潮湿的脚印", "ability": "wis", "dc": 10}, {"id": "parley", "label": "询问不肯离港的摆渡人", "ability": "cha", "dc": 10}]},
    {"id": "customs", "title": "废弃海关", "eyebrow": "第二幕 · 失落透镜", "text": "倾倒的关税账簿浸在盐水中。一枚灯塔透镜压在铁柜下，门外的盐壳守卫正缓慢巡逻。", "actions": [{"id": "investigate", "label": "寻找铁柜机关与旧账册", "ability": "int", "dc": 12}, {"id": "parley", "label": "向门外的守卫报出委托", "ability": "cha", "dc": 12}, {"id": "fight", "label": "拔出武器，拦住盐壳守卫"}]},
    {"id": "stairs", "title": "盐水阶梯", "eyebrow": "第三幕 · 被遗忘的誓言", "text": "每一级台阶都刻着同一个名字。绞盘早已锈死，但墙上的誓言仍然清晰：‘灯在，人归。’上方传来像潮汐般的呼吸。", "actions": [{"id": "investigate", "label": "辨认墙上被抹去的姓名", "ability": "int", "dc": 12}, {"id": "repair", "label": "合力转动锈蚀绞盘", "ability": "str", "dc": 12}]},
    {"id": "lantern", "title": "灯塔顶层", "eyebrow": "第四幕 · 最后一盏灯", "text": "守望者站在空无一物的灯座前，手掌里握着最后一粒火。他以为没有人会来接替他。窗外的浓雾已经漫过海平线。", "actions": [{"id": "repair", "label": "把透镜装回灯座", "ability": "int", "dc": 12}, {"id": "parley", "label": "念出旧誓言，请他放下职责", "ability": "wis", "dc": 12}, {"id": "fight", "label": "击碎束缚灯芯的盐壳"}]},
    {"id": "dawn", "title": "黎明之后", "eyebrow": "尾声 · 你的故事已被记住", "text": "雾被灯光割开。第一艘归船缓缓靠岸，码头上的人终于放下了一夜未熄的手灯。你们把名字留在新的守夜簿上。", "actions": []},
]

OUTCOMES = {
    (0, "investigate"): ("脚印里夹着蓝色碎玻璃。你认出这是灯塔透镜的碎片；搬走透镜的人进入了旧海关。", "雨水冲散脚印。你绕了远路，才在海关门口发现蓝色碎玻璃；身后的雾更浓了。"),
    (0, "parley"): ("摆渡人终于开口：‘守望者不是失踪，他只是忘了怎样回家。去海关找旧值夜簿。’", "摆渡人拒绝谈论名字，却把海关方向指给了你。他收走铜钥匙作为报酬，留下另一条绕行小径。"),
    (1, "investigate"): ("你按旧账册找到铁柜机关，无声取出了完整透镜。透镜边缘刻着一段未写完的守夜誓言。", "机关猛地弹开，透镜落入你的怀中，但警铃也惊醒了门外的盐壳守卫。"),
    (1, "parley"): ("守卫听见守夜人的委托，递出透镜，后退到门侧。它的动作像是仍在遵守很多年前的命令。", "你拿到了桌上的透镜，但守卫只听懂了‘带走’二字。盐壳手臂横在出口前。"),
    (2, "investigate"): ("被刮去的姓名在斜光下重新显现。你读出了完整誓言：‘灯在，人归；天明之后，由我替你。’", "你没能认全姓名，只抄下半句誓言。守望者也许能听懂，但你无法确定。"),
    (2, "repair"): ("绞盘转动，吊篮将你们稳稳送上塔顶。你还留下了一条能够撤退的安全通路。", "绞盘齿轮崩裂，你们只好踩着湿滑石阶攀上塔顶。潮水已经淹没了来路。"),
    (3, "repair"): ("透镜与灯芯重新相接。你终于将光调向海面；守望者缓缓松开了攥紧的手。", "透镜的裂纹使光束断断续续。你用自己的行囊撑住灯座，总算让它坚持到了天亮。"),
    (3, "parley"): ("守望者听见你的承诺，第一次转头看向归家的方向。灯芯留在你手中，他走进了晨雾。", "守望者不肯离开。你答应与他共同守完这最后一夜，他终于允许你点亮灯芯。"),
}

def outcome_text(index, action_id, success):
    pair = OUTCOMES.get((index, action_id))
    return pair[0 if success else 1] if pair else ("行动打开了一条安全的道路。" if success else "你付出了时间与风险，但仍找到了继续前进的线索。")

def ending_scene(state):
    scene = deepcopy(SCENES[-1])
    flags = state.get("flags", {})
    route = flags.get("resolution", "repair")
    if route == "parley" and flags.get("released"):
        scene["title"] = "不必再独自守夜"
        scene["text"] = "晨光落在空出的守夜椅上。那位被困多年的守望者终于回家，雾港迎来了第一艘归船。你把完整誓言刻在灯座旁：天明之后，由我替你。"
    elif route == "parley":
        scene["title"] = "最后一夜的约定"
        scene["text"] = "你们陪守望者坐到天亮。灯重新亮了，他却仍未离开。下一次来访时，你答应带来那个被抹去的名字。"
    elif route == "fight":
        scene["title"] = "破壳后的火"
        scene["text"] = "盐壳在黎明前碎裂，灯芯恢复了光亮。归船得以靠岸，但守望者的往事也随束缚一起散入海风。你们救下了港口，留下一个再无人回答的问题。"
    else:
        scene["title"] = "归航的灯"
        scene["text"] = "你将海关带回的透镜稳稳装入灯座，航道重新显现在海面。人们把你们的名字写进守夜簿，守望者终于能放下那粒握了太久的火。"
    if flags.get("pressure", 0) >= 2:
        scene["text"] += "赶在光亮出现之前，已有两艘船擦伤了船底；雾港会记住救援，也会记住这一夜的代价。"
    if flags.get("safe_path"):
        scene["text"] += "修好的吊篮让港民能够送来补给，灯塔不再与小镇隔绝。"
    return scene

def new_character(template_id, name="冒险者"):
    if template_id not in TEMPLATES:
        raise ValueError("未知角色原型")
    c = deepcopy(TEMPLATES[template_id])
    c.update({"name": name, "id": template_id, "class_name": c["label"], "class": template_id, "template_id": template_id, "level": 1, "hp": c["max_hp"], "proficiency": 2, "potions": 2, "death_successes": 0, "death_failures": 0, "stable": False, "dead": False})
    return c

def initial_scene(mode="preset", theme=""):
    return deepcopy(SCENES[0])

def initialize_state(mode="preset", theme=""):
    return {"scene_id": "dock", "scene": initial_scene(mode, theme), "scene_index": 0, "flags": {}, "combat": None, "completed": False, "rest_used": False, "mode": mode, "theme": theme}

def scene_for(state):
    scenes = state.get("scenes") or SCENES
    return deepcopy(scenes[state.get("scene_index", 0)])

def available_actions(state, member_id):
    if state.get("completed"):
        return []
    members = state.get("members", [])
    member = next((m for m in members if m["id"] == member_id), None)
    if not member:
        return []
    c = member["character"]
    combat = state.get("combat")
    # Advancing/resting directs the whole party; a host's incapacitated character
    # must not prevent conscious companions from finishing the adventure.
    party_actions = []
    conscious_party = any(m["character"]["hp"] > 0 and not m["character"].get("dead") for m in members)
    is_host = state.get("host_member_id", state.get("host_id")) in (None, member_id)
    if not (combat and combat.get("active")) and conscious_party and is_host:
        if state.get("flags", {}).get("scene_resolved"):
            party_actions.append({"id": "advance", "label": "与队伍继续前行", "host_only": True, "party_action": True})
        if not state.get("rest_used") and any(not m["character"].get("dead") and m["character"]["hp"] < m["character"]["max_hp"] for m in members):
            party_actions.append({"id": "rest", "label": "在避风处休整（全队一次）", "host_only": True, "party_action": True})
    if c.get("dead"):
        return party_actions
    if combat and combat.get("active"):
        if combat.get("turn_actor_id") != member_id:
            return []
        if c["hp"] == 0:
            return [{"id": "end_turn", "label": "等待救援 / 进行死亡豁免"}]
        if combat.get("action_used"):
            return [{"id": "end_turn", "label": "结束回合"}]
        actions = [{"id": "attack", "label": "攻击当前敌人"}, {"id": "dodge", "label": "闪避，等待时机"}, {"id": "end_turn", "label": "结束回合"}]
    else:
        if c["hp"] <= 0:
            return party_actions
        actions = [{"id": a["id"], "label": a["label"]} for a in scene_for(state)["actions"] if not state.get("flags", {}).get("attempted", {}).get(f"{state.get('scene_index', 0)}:{a['id']}")]
        actions.extend(party_actions)
    if c.get("potions", 0) > 0 and c["hp"] > 0:
        actions.append({"id": "heal", "label": "使用治疗药水（可选择队友）"})
    return actions

def catalog():
    return {"characters": [{"id": k, **deepcopy(v)} for k, v in TEMPLATES.items()], "title": "HEXBOUND · 六席之间", "templates": [{"id": k, **deepcopy(v)} for k, v in TEMPLATES.items()], "scenarios": [{"id": "last-lantern", "title": "雾港最后一盏灯", "description": "一次穿越迷雾、寻找失落誓言的原创短篇冒险。", "duration": "30–60 分钟"}], "modes": [{"id": "preset", "label": "预设冒险"}, {"id": "free", "label": "自由生成"}, {"id": "hybrid", "label": "混合模式"}], "rules": {"baseline": "SRD 5.1 核心规则子集", "supported": ["属性检定", "优势/劣势", "先攻", "武器攻击与暴击", "每回合一次动作", "死亡豁免", "治疗药水"], "limitations": ["固定1级简化原型，不是完整职业", "无完整法术、专长、种族与升级", "无战术网格、机会攻击和完整状态系统", "休整采用全队一次恢复的明确房规", "战斗胜利后存活倒地队友自动稳定伤势的房规", "死亡豁免由倒地角色点击结束回合触发；自然20恢复1HP但本轮不再行动（简化时序）"]}}
