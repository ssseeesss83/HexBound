"""SRD 5.1/2014 single-class character advancement, owned choices and resources.

Pure copy-on-write character operations. The caller owns authorization, room
transactions, milestone awards and rest timing. Catalog content is reference
material unless an executable feature is explicitly marked automated.
"""
from copy import deepcopy
import secrets

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")
XP_THRESHOLDS = (0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000, 85000, 100000, 120000, 140000, 165000, 195000, 225000, 265000, 305000, 355000)
CLASS_NAMES = dict(zip(("barbarian", "bard", "cleric", "druid", "fighter", "monk", "paladin", "ranger", "rogue", "sorcerer", "warlock", "wizard"), ("野蛮人", "吟游诗人", "牧师", "德鲁伊", "战士", "武僧", "圣武士", "游侠", "游荡者", "术士", "邪术师", "法师")))
PRIORITIES = {
    "barbarian": "str con dex wis cha int", "bard": "cha dex con wis int str",
    "cleric": "wis con str cha dex int", "druid": "wis con dex int cha str",
    "fighter": "str con dex wis cha int", "monk": "dex wis con str int cha",
    "paladin": "str cha con wis dex int", "ranger": "dex wis con str int cha",
    "rogue": "dex con int wis cha str", "sorcerer": "cha con dex wis int str",
    "warlock": "cha con dex wis int str", "wizard": "int con dex wis cha str",
}
SKILL_ABILITIES = {
    "acrobatics": "dex", "animal-handling": "wis", "arcana": "int", "athletics": "str",
    "deception": "cha", "history": "int", "insight": "wis", "intimidation": "cha",
    "investigation": "int", "medicine": "wis", "nature": "int", "perception": "wis",
    "performance": "cha", "persuasion": "cha", "religion": "int", "sleight-of-hand": "dex",
    "stealth": "dex", "survival": "wis",
}
SKILL_NAMES = dict(zip(SKILL_ABILITIES, ("杂技", "驯兽", "奥秘", "运动", "欺瞒", "历史", "洞悉", "威吓", "调查", "医药", "自然", "察觉", "表演", "游说", "宗教", "巧手", "隐匿", "求生")))
SUBCLASS_LEVEL = {"barbarian": 3, "bard": 3, "cleric": 1, "druid": 2, "fighter": 3, "monk": 3, "paladin": 3, "ranger": 3, "rogue": 3, "sorcerer": 1, "warlock": 1, "wizard": 2}
CASTING_ABILITIES = {"bard": "cha", "cleric": "wis", "druid": "wis", "paladin": "cha", "ranger": "wis", "sorcerer": "cha", "warlock": "cha", "wizard": "int"}
PREPARING = {"cleric", "druid", "paladin", "wizard"}
AUTOMATED_FEATURE_PREFIXES = ("second-wind", "action-surge", "rage", "bardic-inspiration", "lay-on-hands", "divine-smite", "ki-flurry", "ki-patient", "arcane-recovery", "font-of-magic", "sneak-attack", "extra-attack", "jack-of-all-trades", "bard-expertise", "expertise", "ability-score-improvement")
RESOURCE_NAMES = {"rage": "狂暴", "bardic-inspiration": "诗人激励", "channel-divinity": "引导神力", "wild-shape": "荒野形态", "second-wind": "回气", "action-surge": "动作如潮", "indomitable": "不屈", "ki": "气", "lay-on-hands": "圣疗", "divine-sense": "神圣感知", "sorcery-points": "术法点", "arcane-recovery": "奥术回想", "eldritch-master": "魔能掌控"}
CHOICE_FIELDS = {"skills", "bonus_skills", "subclass_id", "asi", "known_spells", "prepared_spells", "cantrips", "expertise", "spellbook", "magical_secrets", "arcanum"}
SPELL_PRIORITY = ["eldritch-blast", "fire-bolt", "sacred-flame", "vicious-mockery", "poison-spray", "ray-of-frost", "chill-touch", "spare-the-dying", "shocking-grasp", "light", "mage-hand", "cure-wounds", "healing-word", "magic-missile", "burning-hands", "bless", "shield-of-faith", "false-life", "thunderwave", "acid-arrow", "scorching-ray", "fireball", "lightning-bolt"]


def _data():
    from . import compendium
    return compendium


def modifier(score):
    return (score - 10) // 2


def _choice_dict(choices):
    if choices is None:
        return {}
    if not isinstance(choices, dict) or set(choices) - CHOICE_FIELDS:
        raise ValueError("角色选项包含不允许修改的字段")
    return deepcopy(choices)


def _ids(value, field):
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value) or len(set(value)) != len(value):
        raise ValueError(f"{field}必须是无重复的ID列表")
    return list(value)


def _class(character):
    return character.get("class_id") or {"warden": "cleric", "scholar": "wizard"}.get(character.get("class", character.get("template_id")), character.get("class", character.get("template_id")))


def _level_record(class_id, level):
    levels = _data().CLASS_LEVELS[class_id]
    return levels.get(level, levels.get(str(level), {}))


def _class_skills(class_id):
    source = _data().CLASSES[class_id]
    for choice in source.get("proficiency_choices", []):
        options = choice.get("from", {}).get("options", [])
        ids = [x.get("item", {}).get("index", "").removeprefix("skill-") for x in options if x.get("item", {}).get("index", "").startswith("skill-")]
        if ids:
            return choice["choose"], [i for i in ids if i in SKILL_ABILITIES]
        if "any" in choice.get("desc", "").lower() and "skill" in choice.get("desc", "").lower():
            return choice["choose"], list(SKILL_ABILITIES)
    return (3 if class_id == "bard" else 4 if class_id == "rogue" else 2), list(SKILL_ABILITIES)


def _subclasses(class_id):
    return [s for s in _data().SUBCLASSES.values() if s.get("class", {}).get("index") == class_id]


def _features(c):
    result = {}
    for level in range(1, c["level"] + 1):
        for ref in _level_record(c["class_id"], level).get("features", []):
            fid = ref.get("id", ref.get("index"))
            f = _data().FEATURES.get(fid, ref)
            if f.get("subclass") and f["subclass"].get("index") != c.get("subclass_id"):
                continue
            result[fid] = {"id": fid, "name": f.get("name_zh", f.get("name", fid)), "level": f.get("level", level), "description": "\n".join(f.get("desc", [])), "automated": fid.startswith(AUTOMATED_FEATURE_PREFIXES), "note": "已接入规则处理器" if fid.startswith(AUTOMATED_FEATURE_PREFIXES) else "规则参考：复杂效果尚需主持人裁定，不会自动生成数值"}
    for level, row in _data().SUBCLASS_LEVELS.get(c.get("subclass_id"), {}).items():
        if int(level) > c["level"]:
            continue
        for ref in row.get("features", []):
            fid = ref["index"]
            f = _data().FEATURES.get(fid, ref)
            # Use granted level references, not every child choice in the catalog.
            # For example, ten dragon ancestry alternatives are not ten owned traits.
            result.setdefault(fid, {"id": fid, "name": f.get("name_zh", f.get("name", fid)), "level": int(level), "description": "\n".join(f.get("desc", [])), "automated": False, "note": "子职业规则参考；未声明自动化的效果需主持人裁定"})
    return sorted(result.values(), key=lambda f: (f["level"], f["id"]))


def _merge_pool(old, maximum, recharge, *, initialize=False, **extra):
    if initialize or old is None:
        current = maximum
    else:
        # Growing the pool grants only newly gained capacity, never restores spent uses.
        current = max(0, min(maximum, old.get("current", 0) + max(0, maximum - old.get("max", maximum))))
    return {"max": maximum, "current": current, "recharge": recharge, **extra}


def _resources(c, initialize=False):
    cls, level, cha = c["class_id"], c["level"], modifier(c["abilities"]["cha"])
    caps = {}
    def add(key, amount, recharge="long", automated=False, **extra):
        caps[key] = _merge_pool(c.get("resources", {}).get(key), amount, recharge, initialize=initialize, name=RESOURCE_NAMES.get(key, key), automated=automated, **extra)
    if cls == "barbarian":
        add("rage", 6 if level >= 17 else 5 if level >= 12 else 4 if level >= 6 else 3 if level >= 3 else 2, automated=True, unlimited=level == 20)
    if cls == "bard":
        add("bardic-inspiration", max(1, cha), "short" if level >= 5 else "long", True, die=12 if level >= 15 else 10 if level >= 10 else 8 if level >= 5 else 6)
    if cls == "cleric" and level >= 2:
        add("channel-divinity", 3 if level >= 18 else 2 if level >= 6 else 1, "short")
    if cls == "druid" and level >= 2:
        add("wild-shape", 2, "short", unlimited=level == 20)
    if cls == "fighter":
        add("second-wind", 1, "short", True)
        if level >= 2:
            add("action-surge", 2 if level >= 17 else 1, "short", True)
        if level >= 9:
            add("indomitable", 3 if level >= 17 else 2 if level >= 13 else 1)
    if cls == "monk" and level >= 2:
        add("ki", level, "short", True)
    if cls == "paladin":
        add("lay-on-hands", level * 5, automated=True)
        add("divine-sense", max(0, 1 + cha))
        if level >= 3:
            add("channel-divinity", 1, "short")
    if cls == "sorcerer" and level >= 2:
        add("sorcery-points", level, automated=True)
    if cls == "wizard":
        add("arcane-recovery", 1, automated=True, slot_levels=(level + 1) // 2)
    if cls == "warlock":
        for spell_level, required in ((6, 11), (7, 13), (8, 15), (9, 17)):
            if level >= required:
                add(f"mystic-arcanum-{spell_level}", 1)
        if level == 20:
            add("eldritch-master", 1)
    c["resources"] = caps


def _subclass_spells(c):
    result = []
    sub = _data().SUBCLASSES.get(c.get("subclass_id"), {})
    for item in sub.get("spells", []):
        prerequisites = item.get("prerequisites", [])
        levels = [int(p["index"].rsplit("-", 1)[-1]) for p in prerequisites if p.get("type") == "level" and p.get("index", "").rsplit("-", 1)[-1].isdigit()]
        if not levels or max(levels) <= c["level"]:
            result.append(item["spell"]["index"])
    return sorted(set(result))


def _spell_meta(c, initialize=False):
    cls, level = c["class_id"], c["level"]
    row = _level_record(cls, level).get("spellcasting", {})
    ability = CASTING_ABILITIES.get(cls)
    maxima = {str(n): row.get(f"spell_slots_level_{n}", 0) for n in range(1, 10)}
    maximum_level = max((int(k) for k, v in maxima.items() if v), default=0)
    if cls == "warlock":
        capacity = maxima.get(str(maximum_level), 0)
        c["pact_slots"] = _merge_pool(c.get("pact_slots"), capacity, "short", initialize=initialize, level=maximum_level)
        c["spell_slots"] = {}
    else:
        c["spell_slots"] = {k: _merge_pool(c.get("spell_slots", {}).get(k), v, "long", initialize=initialize) for k, v in maxima.items() if v}
        c["pact_slots"] = {"max": 0, "current": 0, "level": 0, "recharge": "short"}
    prepared = max(1, (level // 2 if cls == "paladin" else level) + modifier(c["abilities"][ability])) if cls in PREPARING and maximum_level else 0
    known = row.get("spells_known", 0)
    if cls == "bard" and c.get("subclass_id") == "lore" and level >= 6:
        known += 2
    c["spellcasting"] = {"ability": ability, "known_limit": known, "prepared_limit": prepared, "cantrips_limit": row.get("cantrips_known", 0) + (1 if cls == "druid" and c.get("subclass_id") == "land" and level >= 2 else 0), "max_spell_level": maximum_level, "save_dc": 8 + c["proficiency"] + modifier(c["abilities"][ability]) if ability else None, "attack_bonus": c["proficiency"] + modifier(c["abilities"][ability]) if ability else None}
    c["always_prepared_spells"] = _subclass_spells(c) if cls in {"cleric", "druid", "paladin"} else []


def eligible_spells(character, *, cantrips=False, any_class=False, exact_level=None):
    c = character
    cls = c["class_id"]
    expanded = set(_subclass_spells(c))
    limit = c["spellcasting"]["max_spell_level"]
    selected = [sid for sid, spell in _data().SPELLS.items() if
        (any_class or cls in {x["index"] for x in spell.get("classes", [])} or sid in expanded)
        and (spell["level"] == exact_level if exact_level is not None else spell["level"] == 0 if cantrips else 1 <= spell["level"] <= limit)]
    return sorted(selected, key=lambda sid: (SPELL_PRIORITY.index(sid) if sid in SPELL_PRIORITY else 999, sid))


def _list_choice(c, choices, field, allowed, maximum, *, minimum=0, default=None, preserve=False, replace_one=False):
    old = list(c.get(field, []))
    selected = _ids(choices[field], field) if field in choices else list(default if default is not None else old)
    if any(s not in allowed for s in selected) or not minimum <= len(selected) <= maximum:
        raise ValueError(f"{field}数量或职业/等级条件不合法（允许{minimum}–{maximum}项）")
    if preserve and not set(old).issubset(selected):
        raise ValueError(f"{field}不能移除已经获得的选项")
    if replace_one and len(set(old) - set(selected)) > 1:
        raise ValueError("每次升级至多替换一个已知法术")
    c[field] = selected


def _spell_choices(c, choices, *, initial=False, advancing=False):
    meta, cls = c["spellcasting"], c["class_id"]
    cantrips = eligible_spells(c, cantrips=True)
    old_cantrips = c.get("cantrips", [])
    defaults = old_cantrips + [s for s in cantrips if s not in old_cantrips][:max(0, meta["cantrips_limit"] - len(old_cantrips))]
    _list_choice(c, choices, "cantrips", cantrips, meta["cantrips_limit"], minimum=meta["cantrips_limit"], default=defaults, preserve=not initial)
    allowed = eligible_spells(c)
    # Magical secrets are chosen once at their feature levels and become bard spells.
    secrets_count = (2 if cls == "bard" and c.get("subclass_id") == "lore" and c["level"] >= 6 else 0) + (sum(c["level"] >= n for n in (10, 14, 18)) * 2 if cls == "bard" else 0)
    secrets_allowed = eligible_spells(c, any_class=True) + eligible_spells(c, any_class=True, cantrips=True)
    old_secrets = c.get("magical_secrets", [])
    defaults = old_secrets + [s for s in secrets_allowed if s not in old_secrets and s not in allowed][:max(0, secrets_count - len(old_secrets))]
    _list_choice(c, choices, "magical_secrets", secrets_allowed, secrets_count, minimum=secrets_count, default=defaults, preserve=True)
    allowed = list(dict.fromkeys(allowed + c["magical_secrets"]))
    if cls == "wizard":
        if choices.get("known_spells"):
            raise ValueError("法师通过法术书与准备列表管理法术，不使用已知法术选择")
        expected = 6 + 2 * (c["level"] - 1)
        old = c.get("spellbook", [])
        defaults = old + [s for s in allowed if s not in old][:max(0, expected - len(old))]
        _list_choice(c, choices, "spellbook", allowed, expected, minimum=expected, default=defaults, preserve=True)
        # Each new level supplies exactly two eligible additions; existing book remains.
        c["known_spells"] = []
    elif meta["known_limit"]:
        old = c.get("known_spells", [])
        required = list(c["magical_secrets"])
        defaults = list(dict.fromkeys(old + required))
        defaults += [s for s in allowed if s not in defaults][:max(0, meta["known_limit"] - len(defaults))]
        _list_choice(c, choices, "known_spells", allowed, meta["known_limit"], minimum=meta["known_limit"], default=defaults, replace_one=advancing)
        if not set(required).issubset(c["known_spells"]):
            raise ValueError("已选魔法奥秘必须包含在已知法术中")
        c["spellbook"] = []
    else:
        if choices.get("known_spells") or choices.get("spellbook"):
            raise ValueError("此职业没有已知法术/法术书选择")
        c["known_spells"], c["spellbook"] = [], []
    if meta["prepared_limit"]:
        preparation_pool = c["spellbook"] if cls == "wizard" else allowed
        preparation_pool = [s for s in preparation_pool if s not in c["always_prepared_spells"]]
        defaults = [s for s in c.get("prepared_spells", []) if s in preparation_pool][:meta["prepared_limit"]]
        if initial or not defaults:
            defaults = preparation_pool[:meta["prepared_limit"]]
        _list_choice(c, choices, "prepared_spells", preparation_pool, meta["prepared_limit"], default=defaults)
    else:
        if choices.get("prepared_spells"):
            raise ValueError("此职业不使用准备法术")
        c["prepared_spells"] = []
    arcanum = deepcopy(c.get("arcanum", {}))
    supplied = choices.get("arcanum", arcanum)
    if not isinstance(supplied, dict):
        raise ValueError("玄奥秘法必须为等级到法术的映射")
    required_levels = [n for n, at in ((6, 11), (7, 13), (8, 15), (9, 17)) if cls == "warlock" and c["level"] >= at]
    if set(supplied) - {str(n) for n in required_levels}:
        raise ValueError("尚未获得该等级玄奥秘法")
    for n in required_levels:
        options = eligible_spells(c, exact_level=n)
        selected = supplied.get(str(n), options[0] if options else None)
        if selected not in options or (str(n) in arcanum and arcanum[str(n)] != selected):
            raise ValueError("玄奥秘法职业不符或试图替换固定选择")
        arcanum[str(n)] = selected
    c["arcanum"] = arcanum
    owned_ritual_pool = c["spellbook"] if cls == "wizard" else c["known_spells"] if cls == "bard" else c["prepared_spells"] + c["always_prepared_spells"] if cls in {"cleric", "druid"} else []
    c["ritual_spells"] = [s for s in owned_ritual_pool if _data().SPELLS[s].get("ritual")]


def _derived(c, *, initialize=False):
    c["proficiency"] = 2 + (c["level"] - 1) // 4
    c["saving_throws"] = [s["index"] for s in _data().CLASSES[c["class_id"]].get("saving_throws", [])]
    if c["class_id"] == "monk" and c["level"] >= 14:
        c["saving_throws"] = list(ABILITIES)
    if c["class_id"] == "rogue" and c["level"] >= 15:
        c["saving_throws"] = sorted(set(c["saving_throws"] + ["wis"]))
    c["skill_modifiers"] = {s: skill_bonus(c, s) for s in SKILL_ABILITIES}
    c["save_modifiers"] = {a: saving_throw_bonus(c, a) for a in ABILITIES}
    c["features"] = _features(c)
    _resources(c, initialize)
    _spell_meta(c, initialize)
    c["ruleset"] = "srd-5.1"
    c["character_schema_version"] = 1
    c["class"] = c["class_id"]
    c["class_name"] = CLASS_NAMES[c["class_id"]]
    if not c.get("legacy_ac_lock"):
        _, c["ac"] = _default_equipment(c["class_id"], c["abilities"])
        if c.get("subclass_id") == "draconic":
            c["ac"] = max(c["ac"], 13 + modifier(c["abilities"]["dex"]))


def skill_bonus(character, skill_id):
    if skill_id not in SKILL_ABILITIES:
        raise ValueError("未知技能")
    bonus = modifier(character["abilities"][SKILL_ABILITIES[skill_id]])
    proficiency = 2 + (character.get("level", 1) - 1) // 4
    if skill_id in character.get("expertise", []):
        return bonus + 2 * proficiency
    if skill_id in character.get("skills", []):
        return bonus + proficiency
    if _class(character) == "bard" and character.get("level", 1) >= 2:
        return bonus + proficiency // 2
    if _class(character) == "fighter" and character.get("subclass_id") == "champion" and character.get("level", 1) >= 7 and SKILL_ABILITIES[skill_id] in {"str", "dex", "con"}:
        return bonus + (proficiency + 1) // 2
    return bonus


def saving_throw_bonus(character, ability):
    if ability not in ABILITIES:
        raise ValueError("未知豁免属性")
    saves = character.get("saving_throws", [])
    return modifier(character["abilities"][ability]) + (2 + (character.get("level", 1) - 1) // 4 if ability in saves else 0)


def _default_equipment(class_id, abilities):
    dex = modifier(abilities["dex"])
    weapons = {"barbarian": ("巨斧", "str", "1d12"), "fighter": ("长剑", "str", "1d8"), "paladin": ("长剑", "str", "1d8"), "rogue": ("细剑", "dex", "1d8"), "ranger": ("长弓", "dex", "1d8"), "bard": ("细剑", "dex", "1d8"), "cleric": ("硬头锤", "str", "1d6"), "monk": ("短剑", "dex", "1d6"), "druid": ("木杖", "str", "1d6")}
    name, ability, dice = weapons.get(class_id, ("匕首", "dex", "1d4"))
    ac = 18 if class_id in {"fighter", "paladin"} else 14 + min(2, dex) + 2 if class_id == "cleric" else 14 + min(2, dex) if class_id == "ranger" else 10 + dex + modifier(abilities["con"]) if class_id == "barbarian" else 10 + dex + modifier(abilities["wis"]) if class_id == "monk" else 11 + dex + 2 if class_id == "druid" else 11 + dex if class_id in {"rogue", "bard", "warlock"} else 10 + dex
    return {"name": name, "ability": ability, "dice": dice}, ac


def validate_abilities(abilities):
    if not isinstance(abilities, dict) or set(abilities) != set(ABILITIES) or any(type(value) is not int or not 8 <= value <= 20 for value in abilities.values()):
        raise ValueError("自定义属性必须为六项 8–20 的整数（自定义房规）")
    return deepcopy(abilities)


def validate_profile(profile):
    if profile is None:
        return {"appearance": "", "personality": "", "background": "", "talents": []}
    if not isinstance(profile, dict) or set(profile) - {"appearance", "personality", "background", "talents"}:
        raise ValueError("人物叙事资料包含未知字段")
    result = {}
    for key in ("appearance", "personality", "background"):
        value = profile.get(key, "")
        if not isinstance(value, str) or len(value) > 3000:
            raise ValueError(f"{key}必须为最多3000字符的文本")
        result[key] = value.strip()
    talents = profile.get("talents", [])
    if not isinstance(talents, list) or len(talents) > 20 or any(not isinstance(value, str) or not 1 <= len(value.strip()) <= 300 for value in talents):
        raise ValueError("叙事天赋最多20项，每项1–300字符；不赋予数值能力")
    result["talents"] = [value.strip() for value in talents]
    return result


def create_character(class_id, name="冒险者", choices=None, *, abilities=None, profile=None):
    choices = _choice_dict(choices)
    if class_id not in CLASS_NAMES or class_id not in _data().CLASSES:
        raise ValueError("请选择SRD十二职业之一")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 32:
        raise ValueError("角色名长度必须为1–32")
    if choices.get("asi"):
        raise ValueError("1级创建不能获得属性提升")
    if choices.get("bonus_skills"):
        raise ValueError("1级创建没有学院额外技能")
    custom_abilities = abilities is not None
    abilities = validate_abilities(abilities) if custom_abilities else dict(zip(PRIORITIES[class_id].split(), (15, 14, 13, 12, 10, 8)))
    profile = validate_profile(profile)
    count, options = _class_skills(class_id)
    skills = _ids(choices.get("skills", options[:count]), "skills")
    if len(skills) != count or not set(skills).issubset(options):
        raise ValueError("职业技能数量或选项不合法")
    subs = _subclasses(class_id)
    subclass = choices.get("subclass_id")
    if SUBCLASS_LEVEL[class_id] == 1:
        subclass = subclass or subs[0]["index"]
        if subclass not in [s["index"] for s in subs]:
            raise ValueError("子职业不属于当前职业")
    elif subclass:
        raise ValueError("尚未到选择子职业的等级")
    weapon, ac = _default_equipment(class_id, abilities)
    die = _data().CLASSES[class_id]["hit_die"]
    hp = die + modifier(abilities["con"])
    c = {"id": class_id, "template_id": class_id, "class_id": class_id, "name": name.strip(), "level": 1, "xp": 0, "milestone_credits": 0, "abilities": abilities, "skills": skills, "expertise": [], "subclass_id": subclass, "hp": hp, "max_hp": hp, "ac": ac, "weapon": weapon, "hit_dice": {"die": die, "max": 1, "current": 1}, "resources": {}, "spell_slots": {}, "pact_slots": {}, "death_successes": 0, "death_failures": 0, "stable": False, "dead": False, "potions": 2, "growth_history": [], "notes": ["标准数组按职业固定分配；尚未叠加种族、背景或专长收益。", "此人物提供完整单职业成长数据；仅标记自动化的能力会由脚本执行。"]}
    c["profile"] = profile
    c["ability_generation"] = "custom-house-rule" if custom_abilities else "standard-array"
    if custom_abilities:
        c["notes"][0] = "自定义属性8–20房规；叙事背景与天赋不授予数值收益。"
    if class_id == "rogue":
        expert = _ids(choices.get("expertise", skills[:2]), "expertise")
        if len(expert) != 2 or not set(expert).issubset(skills):
            raise ValueError("游荡者1级需从已熟练技能中选择两项专精")
        c["expertise"] = expert
    elif choices.get("expertise"):
        raise ValueError("此等级尚未获得专精")
    _derived(c, initialize=True)
    _spell_choices(c, choices, initial=True)
    if subclass == "draconic":
        c["hp"] += 1
        c["max_hp"] += 1
        c["ac"] = max(c["ac"], 13 + modifier(abilities["dex"]))
    return c


def migrate_character(character):
    """Idempotent legacy upgrade; never heal, re-roll HP or restore spent pools."""
    c = deepcopy(character)
    if c.get("character_schema_version") == 1:
        return c
    cls = _class(c)
    base = create_character(cls, c.get("name", "冒险者"))
    for key, value in base.items():
        c.setdefault(key, deepcopy(value))
    c["class_id"] = cls
    c["legacy_ac_lock"] = True
    c.setdefault("legacy_template_id", character.get("template_id", character.get("class")))
    c["notes"] = list(c.get("notes", [])) + ["旧存档迁移：保留原HP、装备与属性；不追补历史属性或生命收益。"]
    # Existing wounds and all explicitly stored resource values take priority.
    _derived(c, initialize=False)
    return c


normalize_character = migrate_character


def _asi_levels(cls):
    return {4, 8, 12, 16, 19} | ({6, 14} if cls == "fighter" else {10} if cls == "rogue" else set())


def level_up_preview(character):
    c = migrate_character(character)
    current, target = c["level"], c["level"] + 1
    if current >= 20:
        return {"eligible": False, "can_level_up": False, "target_level": None, "reason": "已达到20级", "required_choices": {}}
    future = deepcopy(c)
    future["level"] = target
    _derived(future)
    need_subclass = target == SUBCLASS_LEVEL[c["class_id"]] and not c.get("subclass_id")
    expertise_total = (2 if target >= 1 else 0) + (2 if target >= 6 else 0) if c["class_id"] == "rogue" else (2 if target >= 3 else 0) + (2 if target >= 10 else 0) if c["class_id"] == "bard" else 0
    meta = future["spellcasting"]
    eligible = c.get("xp", 0) >= XP_THRESHOLDS[target - 1] or c.get("milestone_credits", 0) > 0
    subclasses = [{"id": s["index"], "name": s.get("name_zh", s["name"])} for s in _subclasses(c["class_id"])] if need_subclass else []
    secret_count = ((2 if c.get("subclass_id") == "lore" and target >= 6 else 0) + 2 * sum(target >= n for n in (10, 14, 18))) if c["class_id"] == "bard" else 0
    arcanum_choices = {str(n): eligible_spells(future, exact_level=n) for n, at in ((6, 11), (7, 13), (8, 15), (9, 17)) if c["class_id"] == "warlock" and target >= at and str(n) not in c.get("arcanum", {})}
    return {"eligible": eligible, "can_level_up": eligible, "target_level": target, "xp_required": XP_THRESHOLDS[target - 1], "xp_current": c.get("xp", 0), "reason": "可以升级" if eligible else "经验或里程碑不足", "required_choices": {"subclass": subclasses, "asi": {"points": 2, "max": 20} if target in _asi_levels(c["class_id"]) else None, "known_spells_count": meta["known_limit"], "prepared_spells_limit": meta["prepared_limit"], "cantrips_count": meta["cantrips_limit"] + (1 if c["class_id"] == "druid" and target == 2 else 0), "spellbook_count": 6 + 2 * (target - 1) if c["class_id"] == "wizard" else 0, "expertise_count": expertise_total, "bonus_skills_count": 3 if c["class_id"] == "bard" and target == 3 else 0, "magical_secrets_count": secret_count}, "eligible_magical_secrets": eligible_spells(future, any_class=True) + eligible_spells(future, any_class=True, cantrips=True) if secret_count else [], "arcanum_choices": arcanum_choices, "eligible_spells": eligible_spells(future), "eligible_cantrips": eligible_spells(future, cantrips=True), "skills": list(c["skills"]), "new_features": [f for f in future["features"] if f["level"] == target], "hp_gain_before_asi": _data().CLASSES[c["class_id"]]["hit_die"] // 2 + 1 + modifier(c["abilities"]["con"])}


def level_up(character, choices=None, progression="xp"):
    choices = _choice_dict(choices)
    c = migrate_character(character)
    if c.get("dead"):
        raise ValueError("死亡角色不能升级")
    preview = level_up_preview(c)
    if c["level"] >= 20:
        raise ValueError("不能超过20级")
    if progression not in {"xp", "milestone"}:
        raise ValueError("未知成长方式")
    if progression == "xp" and c.get("xp", 0) < preview["xp_required"]:
        raise ValueError("升级经验不足")
    if progression == "milestone" and c.get("milestone_credits", 0) <= 0:
        raise ValueError("没有可用的里程碑")
    if "skills" in choices:
        raise ValueError("升级不能重新分配初始技能")
    old_level, old_con = c["level"], modifier(c["abilities"]["con"])
    target = old_level + 1
    suboptions = preview["required_choices"]["subclass"]
    if suboptions:
        selected = choices.get("subclass_id")
        if selected not in [x["id"] for x in suboptions]:
            raise ValueError("本级必须选择合法子职业")
        c["subclass_id"] = selected
    elif "subclass_id" in choices and choices["subclass_id"] != c.get("subclass_id"):
        raise ValueError("不能替换已选子职业或提前选择")
    if target == 3 and c["class_id"] == "bard" and c.get("subclass_id") == "lore":
        options = [sid for sid in SKILL_ABILITIES if sid not in c["skills"]]
        selected = _ids(choices.get("bonus_skills", options[:3]), "bonus_skills")
        if len(selected) != 3 or not set(selected).issubset(options):
            raise ValueError("逸闻学院需要选择三项新的技能熟练")
        c["skills"].extend(selected)
    elif choices.get("bonus_skills"):
        raise ValueError("本级没有额外技能熟练")
    asi = choices.get("asi", {})
    if target in _asi_levels(c["class_id"]):
        if not isinstance(asi, dict) or not asi or set(asi) - set(ABILITIES) or any(type(v) is not int or not 0 <= v <= 2 for v in asi.values()) or sum(asi.values()) != 2:
            raise ValueError("本级属性提升必须分配恰好2点")
        if any(c["abilities"][a] + v > 20 for a, v in asi.items()):
            raise ValueError("属性提升不能超过20")
        for a, v in asi.items():
            c["abilities"][a] += v
    elif asi:
        raise ValueError("此等级没有属性提升")
    expertise_total = preview["required_choices"]["expertise_count"]
    if expertise_total > len(c["expertise"]):
        expert = _ids(choices.get("expertise", []), "expertise")
        if len(expert) != expertise_total or not set(c["expertise"]).issubset(expert) or not set(expert).issubset(c["skills"]):
            raise ValueError("专精选项必须保留原项，并从已熟练技能补足本级数量")
        c["expertise"] = expert
    elif "expertise" in choices and choices["expertise"] != c["expertise"]:
        raise ValueError("本级不能更换专精")
    c["level"] = target
    if c["class_id"] == "barbarian" and target == 20:
        c["abilities"]["str"] = min(24, c["abilities"]["str"] + 4)
        c["abilities"]["con"] = min(24, c["abilities"]["con"] + 4)
    new_con = modifier(c["abilities"]["con"])
    gain = max(1, _data().CLASSES[c["class_id"]]["hit_die"] // 2 + 1 + new_con) + old_level * (new_con - old_con)
    if c.get("subclass_id") == "draconic":
        gain += 1
    c["max_hp"] += gain
    if c["hp"] > 0:
        c["hp"] = min(c["max_hp"], c["hp"] + gain)
    c["hit_dice"] = {"die": _data().CLASSES[c["class_id"]]["hit_die"], "max": target, "current": c["hit_dice"]["current"] + 1}
    _derived(c)
    _spell_choices(c, choices, advancing=True)
    c["growth_history"].append({"from": old_level, "to": target, "choices": deepcopy(choices), "hp_gain": gain, "progression": progression})
    return c


def add_xp(character, amount):
    if type(amount) is not int or not 0 <= amount <= 1_000_000:
        raise ValueError("经验奖励必须为合法非负整数")
    c = migrate_character(character)
    c["xp"] = c.get("xp", 0) + amount
    return c


def manage_spells(character, choices):
    """Preparation only. Caller requires out-of-combat/preparation time.

    Known spells, cantrips, spellbook and permanent secrets are exclusively
    selected through creation/advancement, never freely swapped here.
    """
    if not isinstance(choices, dict) or set(choices) != {"prepared_spells"}:
        raise ValueError("此操作只能调整准备法术；已知法术和戏法须在升级时选择")
    c = migrate_character(character)
    if c["class_id"] not in PREPARING or c["spellcasting"]["prepared_limit"] == 0:
        raise ValueError("此角色不使用准备法术")
    _spell_choices(c, choices)
    return c


def consume_resource(character, resource_id, amount=1):
    if type(amount) is not int or amount < 1:
        raise ValueError("资源消耗必须为正整数")
    pool = character.get("resources", {}).get(resource_id)
    if not pool:
        raise ValueError("角色尚未获得该职业资源")
    if pool.get("unlimited"):
        return
    if pool["current"] < amount:
        raise ValueError("职业资源不足")
    pool["current"] -= amount


def consume_spell_slot(character, level, pact=False):
    if type(level) is not int or not 1 <= level <= 9:
        raise ValueError("非法法术位等级")
    pool = character.get("pact_slots") if pact else character.get("spell_slots", {}).get(str(level))
    if not pool or (pact and pool.get("level") != level) or pool.get("current", 0) < 1:
        raise ValueError("没有可用的该等级法术位")
    pool["current"] -= 1


def short_rest(character, hit_dice=0):
    c = migrate_character(character)
    if c.get("dead"):
        raise ValueError("休息不能复活死亡角色")
    if type(hit_dice) is not int or not 0 <= hit_dice <= c["hit_dice"]["current"]:
        raise ValueError("生命骰数量不足或不合法")
    rolls = [secrets.randbelow(c["hit_dice"]["die"]) + 1 for _ in range(hit_dice)]
    heal = sum(max(0, die + modifier(c["abilities"]["con"])) for die in rolls)
    c["hp"] = min(c["max_hp"], c["hp"] + heal)
    c["hit_dice"]["current"] -= hit_dice
    for pool in c["resources"].values():
        if pool["recharge"] == "short":
            pool["current"] = pool["max"]
    c["pact_slots"]["current"] = c["pact_slots"]["max"]
    if c["hp"] > 0:
        c.update(death_successes=0, death_failures=0, stable=False)
    c["last_rest"] = {"kind": "short", "hit_dice_spent": hit_dice, "dice": rolls, "healing": heal}
    c["short_rest_ready"] = True
    return c


def long_rest(character):
    c = migrate_character(character)
    if c.get("dead") or c["hp"] < 1:
        raise ValueError("长休需要角色存活且开始时至少1HP，不能复活或自动救起")
    c["hp"] = c["max_hp"]
    for pool in list(c["resources"].values()) + list(c["spell_slots"].values()) + [c["pact_slots"]]:
        pool["current"] = pool["max"]
    c["hit_dice"]["current"] = min(c["hit_dice"]["max"], c["hit_dice"]["current"] + max(1, c["level"] // 2))
    c.update(death_successes=0, death_failures=0, stable=False)
    c["last_rest"] = {"kind": "long", "hit_dice_recovered": max(1, c["level"] // 2)}
    return c


def character_sheet(character):
    c = migrate_character(character)
    c["skill_details"] = [{"id": sid, "name": SKILL_NAMES[sid], "ability": ability, "modifier": skill_bonus(c, sid), "proficient": sid in c["skills"], "expertise": sid in c["expertise"]} for sid, ability in SKILL_ABILITIES.items()]
    c["save_details"] = [{"id": a, "modifier": saving_throw_bonus(c, a), "proficient": a in c["saving_throws"]} for a in ABILITIES]
    owned = set(c.get("cantrips", []) + c.get("known_spells", []) + c.get("prepared_spells", []) + c.get("always_prepared_spells", []) + c.get("spellbook", []) + list(c.get("arcanum", {}).values()))
    c["spell_details"] = [{"id": sid, "name": spell.get("name_zh", spell["name"]), "level": spell["level"], "ritual": spell.get("ritual", False), "concentration": spell.get("concentration", False), "casting_time": spell.get("casting_time"), "range": spell.get("range"), "description": "\n".join(spell.get("desc", [])), "prepared": sid in c.get("prepared_spells", []) + c.get("always_prepared_spells", []), "known": sid in c.get("known_spells", []), "in_spellbook": sid in c.get("spellbook", []), "automation": "以行动列表中是否可执行为准；法术目录本身不代表已自动化"} for sid, spell in _data().SPELLS.items() if sid in owned]
    c["level_up"] = level_up_preview(c)
    return c
