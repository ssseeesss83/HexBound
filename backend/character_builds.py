"""Validated, deterministic character creation replay. No client-derived stats.

The caller controls permitted starting level and ownership. Custom 8..20 ability
scores are an explicit house rule; narrative talents never confer mechanics.
Preview may be incomplete, but finalization never fills missing player choices.
"""
from copy import deepcopy

from . import characters as c

PAYLOAD_FIELDS = {"class_id", "name", "abilities", "profile", "choices", "levels"}


def _payload(payload, target_level):
    if type(target_level) is not int or not 1 <= target_level <= 20:
        raise ValueError("起始等级必须为1–20整数")
    if not isinstance(payload, dict) or set(payload) - PAYLOAD_FIELDS:
        raise ValueError("建角输入包含不允许的字段；等级、XP、HP和资源均由服务器计算")
    result = deepcopy(payload)
    if not isinstance(result.get("class_id"), str) or result["class_id"] not in c.CLASS_NAMES:
        raise ValueError("请选择SRD十二职业之一")
    result.setdefault("name", "冒险者")
    if "abilities" in result:
        c.validate_abilities(result["abilities"])
    c.validate_profile(result.get("profile"))
    result["choices"] = c._choice_dict(result.get("choices"))
    result.setdefault("levels", [])
    if not isinstance(result["levels"], list) or len(result["levels"]) > target_level - 1:
        raise ValueError("逐级选择不得超过目标等级，禁止跳级")
    for step in result["levels"]:
        if not isinstance(step, dict) or set(step) != {"choices"} or not isinstance(step["choices"], dict):
            raise ValueError("每级必须是仅含choices对象的记录，禁止提交level或XP")
        c._choice_dict(step["choices"])
    return result


def _requirements(character, *, initial=False):
    meta = character["spellcasting"]
    cls, level = character["class_id"], character["level"]
    secrets = (2 if character.get("subclass_id") == "lore" and level >= 6 else 0) + 2 * sum(level >= n for n in (10,14,18)) if cls == "bard" else 0
    expertise = (2 + (2 if level >= 6 else 0)) if cls == "rogue" else (2 if level >= 3 else 0) + (2 if level >= 10 else 0) if cls == "bard" else 0
    return {"subclass": [{"id": s["index"], "name": s.get("name_zh", s["name"])} for s in c._subclasses(cls)] if level == c.SUBCLASS_LEVEL[cls] else [],
            "asi": {"points": 2, "max": 20} if not initial and level in c._asi_levels(cls) else None,
            "known_spells_count": meta["known_limit"], "prepared_spells_limit": meta["prepared_limit"],
            "cantrips_count": meta["cantrips_limit"], "spellbook_count": 6 + 2*(level-1) if cls == "wizard" else 0,
            "expertise_count": expertise, "bonus_skills_count": 3 if cls == "bard" and level == 3 and character.get("subclass_id") == "lore" else 0,
            "magical_secrets_count": secrets}


def _missing(required, choices, old=None, *, initial=False, arcanum=None):
    old = old or {}
    fields = []
    if initial and "skills" not in choices:
        fields.append("skills")
    if required["subclass"] and "subclass_id" not in choices:
        fields.append("subclass_id")
    if required["asi"] and "asi" not in choices:
        fields.append("asi")
    for field, count_key in (("known_spells", "known_spells_count"), ("cantrips", "cantrips_count"), ("spellbook", "spellbook_count"), ("expertise", "expertise_count"), ("magical_secrets", "magical_secrets_count")):
        if required[count_key] > len(old.get(field, [])) and field not in choices:
            fields.append(field)
    if required["bonus_skills_count"] and "bonus_skills" not in choices:
        fields.append("bonus_skills")
    if required["prepared_spells_limit"] and (initial or not old.get("prepared_spells")) and "prepared_spells" not in choices:
        fields.append("prepared_spells")
    if arcanum and ("arcanum" not in choices or not isinstance(choices["arcanum"], dict) or not set(arcanum).issubset(choices["arcanum"])):
        fields.append("arcanum")
    return fields


def _creation_options(provisional):
    count, ids = c._class_skills(provisional["class_id"])
    return {"skills": {"count": count, "options": [{"id": key, "name": c.SKILL_NAMES[key]} for key in ids]},
            "subclass": _requirements(provisional, initial=True)["subclass"],
            "required_choices": _requirements(provisional, initial=True),
            "eligible_spells": c.eligible_spells(provisional), "eligible_cantrips": c.eligible_spells(provisional, cantrips=True),
            "abilities": {"min": 8, "max": 20, "mode": "custom-house-rule", "default": dict(zip(c.PRIORITIES[provisional["class_id"]].split(), (15,14,13,12,10,8)))},
            "talents": {"mode": "narrative-only", "max_items": 20, "max_length": 300},
            "feature_policy": "正式能力随职业、子职业和逐级选择获得；叙事天赋不授予属性、法术、熟练或资源。未自动化特性仅供参考。"}


def _next(character, choices=None):
    choices = choices or {}
    future = deepcopy(character)
    future["level"] += 1
    if choices.get("subclass_id"):
        future["subclass_id"] = choices["subclass_id"]
    # Preview reflects legitimate ASI effects on preparation capacity; level_up
    # remains the final authority on point budget and subclass membership.
    asi = choices.get("asi", {})
    if isinstance(asi, dict):
        for ability, value in asi.items():
            if ability in c.ABILITIES and type(value) is int and 0 <= value <= 2:
                future["abilities"][ability] = min(20, future["abilities"][ability]+value)
    c._derived(future)
    preview = c.level_up_preview(character)
    preview["eligible"] = preview["can_level_up"] = True
    preview["reason"] = "起始等级逐级构建；仍须提交合法选择"
    preview["required_choices"] = _requirements(future)
    preview["eligible_spells"] = c.eligible_spells(future)
    preview["eligible_cantrips"] = c.eligible_spells(future, cantrips=True)
    return preview


def build_preview(payload, target_level=1):
    """Replay completed levels; expose the first missing choice without defaults."""
    payload = _payload(payload, target_level)
    initial = payload["choices"]
    provisional = c.create_character(payload["class_id"], payload["name"], initial,
                                     abilities=payload.get("abilities"), profile=payload.get("profile"))
    options = _creation_options(provisional)
    missing = _missing(options["required_choices"], initial, initial=True)
    response = {"character": None, "creation_options": options, "required_choices": options["required_choices"],
                "next_level": 1, "target_level": target_level, "completed_levels": 0,
                "ready": False, "missing_choices": missing, "advancement": None}
    if missing:
        return response
    character = provisional
    for step in payload["levels"]:
        choices = step["choices"]
        advancement = _next(character, choices)
        missing = _missing(advancement["required_choices"], choices, character, arcanum=advancement.get("arcanum_choices"))
        if missing:
            response.update(character=character, required_choices=advancement["required_choices"], next_level=character["level"]+1,
                            completed_levels=character["level"], missing_choices=missing, advancement=advancement)
            return response
        qualified = deepcopy(character)
        qualified["xp"] = c.XP_THRESHOLDS[character["level"]]
        # Do not allow the legacy default picker to replenish an intentionally
        # empty prepared list when no new preparation choice was submitted.
        if "prepared_spells" not in choices:
            choices = {**choices, "prepared_spells": list(character.get("prepared_spells", []))}
        character = c.level_up(qualified, choices)
    ready = character["level"] == target_level
    advancement = None if ready else _next(character)
    response.update(character=character, required_choices={} if ready else advancement["required_choices"],
                    next_level=None if ready else character["level"]+1, completed_levels=character["level"], ready=ready,
                    missing_choices=[] if ready else _missing(advancement["required_choices"], {}, character, arcanum=advancement.get("arcanum_choices")), advancement=advancement)
    return response


def finalize(payload, target_level=1):
    """Return a fully reviewed build. Callers must enforce room starting level."""
    validated = _payload(payload, target_level)
    if len(validated["levels"]) != target_level - 1:
        raise ValueError("必须逐级提交恰好目标等级减一条升级选择")
    preview = build_preview(validated, target_level)
    if not preview["ready"]:
        raise ValueError(f"第{preview['next_level']}级缺少显式选择：{', '.join(preview['missing_choices'])}")
    character = deepcopy(preview["character"])
    character["starting_level"] = target_level
    character["xp"] = c.XP_THRESHOLDS[target_level - 1]
    character["milestone_credits"] = 0
    character["build"] = validated
    return character


def build_character(payload, target_level=1):
    return finalize(payload, target_level)


def prepare_level(character, choices):
    """One reviewed pre-adventure level; preserve injuries and earned credits."""
    choices = c._choice_dict(choices)
    if character.get("level", 1) >= 20:
        raise ValueError("不能超过20级")
    advancement = _next(character, choices)
    missing = _missing(advancement["required_choices"], choices, character, arcanum=advancement.get("arcanum_choices"))
    if missing:
        raise ValueError("升级缺少显式选择：" + ", ".join(missing))
    qualified = deepcopy(character)
    credits = qualified.get("milestone_credits", 0)
    qualified["milestone_credits"] = max(1, credits)
    if "prepared_spells" not in choices:
        choices["prepared_spells"] = list(character.get("prepared_spells", []))
    result = c.level_up(qualified, choices, progression="milestone")
    result["milestone_credits"] = credits
    result["xp"] = max(character.get("xp", 0), c.XP_THRESHOLDS[result["level"] - 1])
    return result
