"""Offline 2014 / SRD 5.1 compendium with traceable, unabridged source data.

Constants retain all upstream fields. Runtime APIs return deep copies so that
character creation and user-facing catalog callers cannot mutate the archive.
Full catalog coverage does not imply automated adjudication of every rule.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
import re

DATA_DIR = Path(__file__).resolve().parent / "data"
EDITION = "2014"
SRD_VERSION = "5.1"
RULESET_ID = "dnd5e-2014-srd5.1"
SOURCE = json.loads((DATA_DIR / "source-manifest.json").read_text(encoding="utf-8"))
_COVERAGE = json.loads((DATA_DIR / "official/source-coverage.json").read_text(encoding="utf-8"))
_SPELL_PAGES = {row["local_record_id"]: [row["printed_page"]] for row in _COVERAGE["official_spell_inventory"]}
_CHAPTERS = {row["id"]: row["printed_pages"] for row in _COVERAGE["chapters"]}
_SOURCE_CHAPTERS = {
    "Races": "races", "Subraces": "races", "Traits": "races", "Backgrounds": "backgrounds", "Feats": "feats",
    "Skills": "abilities-skills-saves", "Ability-Scores": "abilities-skills-saves", "Conditions": "conditions",
    "Equipment": "equipment", "Equipment-Categories": "equipment", "Weapon-Properties": "equipment",
    "Magic-Items": "magic-items", "Languages": "alignment-languages-inspiration", "Alignments": "alignment-languages-inspiration",
    "Magic-Schools": "spellcasting", "Damage-Types": "combat", "Proficiencies": "equipment",
}
_RULE_PAGES = {
    "the-order-of-combat": (90, 91), "movement-and-position": (91, 93), "actions-in-combat": (93, 94),
    "making-an-attack": (94, 96), "cover": (96, 96), "damage-and-healing": (96, 99),
    "mounted-combat": (99, 99), "underwater-combat": (99, 99),
    "ability-scores-and-modifiers": (76, 76), "advantage-and-disadvantage": (76, 77),
    "proficiency-bonus": (77, 77), "ability-checks": (77, 79), "using-each-ability": (79, 83), "saving-throws": (83, 83),
    "time": (84, 84), "movement": (84, 86), "the-environment": (86, 87), "resting": (87, 88), "between-adventures": (88, 89),
    "what-is-a-spell": (100, 101), "casting-a-spell": (101, 104), "standard-exchange-rates": (62, 62),
    "objects": (203, 203), "poisons": (204, 205), "attunement": (206, 206),
    "wearing-and-wielding-items": (206, 206), "activating-an-item": (206, 207), "sentient-magic-items": (251, 252),
    "fantasy-historical-pantheons": (360, 362), "the-planes-of-existence": (363, 365),
    "traps": (195, 198), "diseases": (199, 200), "madness": (201, 202),
}

CLASS_NAMES_ZH = {
    "barbarian": "野蛮人", "bard": "吟游诗人", "cleric": "牧师", "druid": "德鲁伊",
    "fighter": "战士", "monk": "武僧", "paladin": "圣武士", "ranger": "游侠",
    "rogue": "游荡者", "sorcerer": "术士", "warlock": "邪术师", "wizard": "法师",
}
SKILL_NAMES_ZH = {
    "acrobatics": "杂技", "animal-handling": "驯兽", "arcana": "奥秘", "athletics": "运动",
    "deception": "欺瞒", "history": "历史", "insight": "洞悉", "intimidation": "威吓",
    "investigation": "调查", "medicine": "医药", "nature": "自然", "perception": "察觉",
    "performance": "表演", "persuasion": "游说", "religion": "宗教", "sleight-of-hand": "巧手",
    "stealth": "隐匿", "survival": "求生",
}
SUBCLASS_NAMES_ZH = {
    "berserker": "狂战士道途", "lore": "逸闻学院", "life": "生命领域", "land": "大地结社",
    "champion": "冠军勇士", "open-hand": "散打宗", "devotion": "奉献之誓", "hunter": "猎人",
    "thief": "盗贼", "draconic": "龙族血脉", "fiend": "邪魔宗主", "evocation": "塑能学派",
}
# Project-local display names, not an assertion that an official Chinese SRD exists.
# Unmapped spells retain their original English name instead of guessed translations.
SPELL_NAMES_ZH = {
    "acid-arrow": "强酸箭", "acid-splash": "酸液飞溅", "aid": "援助术", "alarm": "警报术",
    "alter-self": "变身术", "animate-dead": "操纵死尸", "antimagic-field": "反魔法力场",
    "arcane-lock": "秘法锁", "bane": "灾祸术", "banishment": "放逐术", "barkskin": "树肤术",
    "beacon-of-hope": "希望信标", "bless": "祝福术", "blindness-deafness": "目盲术／耳聋术",
    "blur": "朦胧术", "burning-hands": "燃烧之手", "call-lightning": "召雷术",
    "charm-person": "魅惑人类", "chill-touch": "冻寒之触",
    "cloudkill": "死云术", "command": "命令术", "comprehend-languages": "通晓语言",
    "cone-of-cold": "寒冰锥", "counterspell": "法术反制", "create-food-and-water": "造粮术",
    "cure-wounds": "疗伤术", "dancing-lights": "舞光术", "darkness": "黑暗术",
    "darkvision": "黑暗视觉", "daylight": "昼明术", "death-ward": "防死结界",
    "detect-evil-and-good": "侦测善恶", "detect-magic": "侦测魔法", "detect-thoughts": "侦测思想",
    "dimension-door": "任意门", "disguise-self": "易容术", "disintegrate": "解离术",
    "dispel-magic": "解除魔法", "druidcraft": "德鲁伊伎俩", "eldritch-blast": "魔能爆",
    "enhance-ability": "强化属性", "enlarge-reduce": "变巨术／缩小术", "entangle": "纠缠术",
    "expeditious-retreat": "脚底抹油", "faerie-fire": "妖火", "false-life": "虚假生命",
    "fear": "恐惧术", "feather-fall": "羽落术", "find-familiar": "获得魔宠",
    "find-steed": "召唤坐骑", "fire-bolt": "火焰箭", "fireball": "火球术",
    "flame-strike": "焰击术", "flaming-sphere": "炽焰法球", "fly": "飞行术",
    "fog-cloud": "云雾术", "freedom-of-movement": "行动自如", "goodberry": "神莓术",
    "grease": "油腻术", "greater-invisibility": "高等隐形术", "greater-restoration": "高等复原术",
    "guidance": "神导术", "guiding-bolt": "曳光弹", "gust-of-wind": "造风术",
    "haste": "加速术", "heal": "医疗术", "healing-word": "治愈真言",
    "heat-metal": "灼热金属", "hellish-rebuke": "炼狱叱喝", "heroism": "英雄气概",
    "hold-monster": "怪物定身术", "hold-person": "人类定身术", "hunters-mark": "猎人印记",
    "ice-storm": "冰风暴", "identify": "鉴定术", "inflict-wounds": "致伤术",
    "invisibility": "隐形术", "jump": "跳跃术", "knock": "敲击术",
    "lesser-restoration": "次级复原术", "levitate": "浮空术", "light": "光亮术",
    "lightning-bolt": "闪电束", "longstrider": "大步奔行", "mage-armor": "法师护甲",
    "mage-hand": "法师之手", "magic-missile": "魔法飞弹", "magic-weapon": "魔化武器",
    "mass-cure-wounds": "群体疗伤术", "mass-healing-word": "群体治愈真言", "mending": "修复术",
    "message": "传讯术", "minor-illusion": "次级幻影", "mirror-image": "镜影术",
    "misty-step": "迷踪步", "moonbeam": "月华之光", "poison-spray": "毒气喷溅",
    "polymorph": "变形术", "prayer-of-healing": "治疗祷言", "prestidigitation": "魔法伎俩",
    "produce-flame": "燃火术", "protection-from-evil-and-good": "防护善恶", "raise-dead": "死者复活",
    "ray-of-frost": "冷冻射线", "remove-curse": "移除诅咒", "resistance": "提升抗性",
    "revivify": "回生术", "sacred-flame": "圣火术", "sanctuary": "庇护术",
    "scorching-ray": "灼热射线", "see-invisibility": "识破隐形", "shield": "护盾术",
    "shield-of-faith": "虔诚护盾", "shillelagh": "橡棍术", "shocking-grasp": "电爪",
    "silence": "沉默术", "silent-image": "无声幻影", "sleep": "睡眠术",
    "slow": "缓慢术", "spare-the-dying": "维生术", "speak-with-animals": "动物交谈",
    "speak-with-dead": "死者交谈", "spider-climb": "蛛行术", "spike-growth": "荆棘丛生",
    "spirit-guardians": "灵体卫士", "spiritual-weapon": "灵体武器", "stinking-cloud": "臭云术",
    "stoneskin": "石肤术", "suggestion": "暗示术", "thaumaturgy": "奇术",
    "thunderwave": "雷鸣波", "true-strike": "克敌机先", "vampiric-touch": "吸血鬼之触",
    "vicious-mockery": "恶毒嘲笑", "wall-of-fire": "火墙术", "water-breathing": "水下呼吸",
    "web": "蛛网术", "wish": "祈愿术",
}
ABILITY_NAMES_ZH = {"str": "力量", "dex": "敏捷", "con": "体质", "int": "智力", "wis": "感知", "cha": "魅力"}

def _load(name, translations=None):
    records = json.loads((DATA_DIR / "srd2014" / f"5e-SRD-{name}.json").read_text(encoding="utf-8"))
    result = {}
    for original in records:
        row = copy.deepcopy(original)
        row["id"] = row["index"]
        if translations and row["id"] in translations:
            row["name_zh"] = translations[row["id"]]
        row["display_name"] = row.get("name_zh", row.get("name", row["id"]))
        row["edition"] = EDITION
        row["srd_version"] = SRD_VERSION
        row["ruleset_id"] = RULESET_ID
        chapter = row.get("class", {}).get("index", row["index"] if name == "Classes" else _SOURCE_CHAPTERS.get(name))
        pages = _SPELL_PAGES.get(row["index"], []) if name == "Spells" else _CHAPTERS.get(chapter, [])
        if name == "Monsters":
            pages = _CHAPTERS["monster-statblocks"] + _CHAPTERS["miscellaneous-creatures"] + _CHAPTERS["npc-statblocks"]
        if name == "Rule-Sections":
            lo, hi = _RULE_PAGES[row["index"]]
            pages = list(range(lo, hi + 1))
        if name == "Rules":
            pages = _CHAPTERS.get({"using-ability-scores": "abilities-skills-saves", "appendix": "conditions"}.get(row["index"], row["index"]), [])
        row["source_refs"] = {"candidate_file": f"srd2014/5e-SRD-{name}.json", "candidate_id": row["index"],
                              "official_document": "official/SRD_CC_v5.1.pdf", "printed_pages": pages,
                              "mapping_type": "chapter_reference" if name != "Spells" else "official_heading"}
        result[row["id"]] = row
    return result

CLASSES = _load("Classes", CLASS_NAMES_ZH)
SKILLS = _load("Skills", SKILL_NAMES_ZH)
SPELLS = _load("Spells", SPELL_NAMES_ZH)
for _spell in SPELLS.values():
    _spell.setdefault("higher_level", [])
FEATURES = _load("Features")
SUBCLASSES = _load("Subclasses", SUBCLASS_NAMES_ZH)
LEVELS = _load("Levels")
MONSTERS = _load("Monsters")
EQUIPMENT = _load("Equipment")
PROFICIENCIES = _load("Proficiencies")
CONDITIONS = _load("Conditions")
ABILITY_SCORES = _load("Ability-Scores", ABILITY_NAMES_ZH)
RACES = _load("Races")
SUBRACES = _load("Subraces")
TRAITS = _load("Traits")
BACKGROUNDS = _load("Backgrounds")
FEATS = _load("Feats")
MAGIC_ITEMS = _load("Magic-Items")
MAGIC_SCHOOLS = _load("Magic-Schools")
DAMAGE_TYPES = _load("Damage-Types")
LANGUAGES = _load("Languages")
ALIGNMENTS = _load("Alignments")
EQUIPMENT_CATEGORIES = _load("Equipment-Categories")
WEAPON_PROPERTIES = _load("Weapon-Properties")
RULES = _load("Rules")
RULE_SECTIONS = _load("Rule-Sections")

CLASS_LEVELS = {class_id: {} for class_id in CLASSES}
SUBCLASS_LEVELS = {subclass_id: {} for subclass_id in SUBCLASSES}
for _record in LEVELS.values():
    if "subclass" in _record:
        SUBCLASS_LEVELS[_record["subclass"]["index"]][_record["level"]] = _record
    else:
        CLASS_LEVELS[_record["class"]["index"]][_record["level"]] = _record
CLASS_CASTING_ABILITIES = {
    key: card["spellcasting"]["spellcasting_ability"]["index"]
    for key, card in CLASSES.items() if "spellcasting" in card
}

# Official SRD 5.1, page 56: Character Advancement (level-indexed mapping).
XP_THRESHOLDS = dict(enumerate((0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000,
                                85000, 100000, 120000, 140000, 165000, 195000, 225000, 265000, 305000, 355000), start=1))

ERRATA = json.loads((DATA_DIR / "errata-overlay.json").read_text(encoding="utf-8"))
for _fix in ERRATA["corrections"]:
    if _fix["operation"] == "append_missing_spell":
        _subclass = SUBCLASSES[_fix["record"]]
        _spell_id = _fix["spell_id"]
        if not any(entry["spell"]["index"] == _spell_id for entry in _subclass.get("spells", [])):
            _class_id, _level = _fix["class_id"], _fix["class_level"]
            _subclass.setdefault("spells", []).append({
                "prerequisites": [{"index": f"{_class_id}-{_level}", "type": "level", "name": f"{CLASSES[_class_id]['name']} {_level}", "url": f"/api/2014/classes/{_class_id}/levels/{_level}"}],
                "spell": {"index": _spell_id, "name": SPELLS[_spell_id]["name"], "url": SPELLS[_spell_id]["url"]},
            })
            _subclass.setdefault("source_corrections", []).append(_fix["id"])

CANONICAL_OVERLAY = json.loads((DATA_DIR / "canonical-overlay.json").read_text(encoding="utf-8"))
for _correction in CANONICAL_OVERLAY["corrections"]:
    for _feature_id in _correction["records"]:
        _tables = {"features": FEATURES, "levels": LEVELS, "spells": SPELLS, "monsters": MONSTERS}
        _feature = _tables[_correction.get("kind", "features")][_feature_id]
        if _correction["operation"] == "replace_description":
            _feature["desc"] = copy.deepcopy(_correction["paragraphs"])
        elif _correction["operation"] == "replace_fragments":
            for _old, _new in _correction["replacements"]:
                _matches = sum(len(re.findall(re.escape(_old), paragraph, re.I)) for paragraph in _feature["desc"])
                if _matches != 1:
                    raise ValueError(f"Canonical correction no longer matches source: {_correction['id']}")
                _feature["desc"] = [re.sub(re.escape(_old), lambda match: _new, paragraph, flags=re.I) for paragraph in _feature["desc"]]
        elif _correction["operation"] == "annotate_derived":
            _feature["source_text_kind"] = "derived_advancement_alias"
            _feature["source_note"] = _correction["note"]
        elif _correction["operation"] == "set_field":
            _target = _feature
            for _part in _correction["path"][:-1]:
                _target = _target[_part]
            _last = _correction["path"][-1]
            if "expected" in _correction and _target.get(_last) != _correction["expected"]:
                raise ValueError(f"Canonical correction no longer matches source: {_correction['id']}")
            _target[_last] = copy.deepcopy(_correction["value"])
        elif _correction["operation"] == "named_action":
            _action = next(row for row in _feature["actions"] if row["name"] == _correction["action_name"])
            if _action["attack_bonus"] != _correction["expected"]:
                raise ValueError(f"Canonical action no longer matches source: {_correction['id']}")
            _action["attack_bonus"] = _correction["value"]
            _action["desc"] = _action["desc"].replace(f"+{_correction['expected']} to hit", f"+{_correction['value']} to hit")
        else:
            raise ValueError("Unknown canonical correction operation")
        _feature.setdefault("source_corrections", []).append(_correction["id"])
        _feature["source_refs"]["canonical_page"] = _correction["page"]
        _feature["source_refs"]["canonical_heading"] = _correction["heading"]

COLLECTIONS = {
    "classes": CLASSES, "skills": SKILLS, "spells": SPELLS, "features": FEATURES, "subclasses": SUBCLASSES,
    "levels": LEVELS, "monsters": MONSTERS, "equipment": EQUIPMENT, "proficiencies": PROFICIENCIES,
    "conditions": CONDITIONS, "ability-scores": ABILITY_SCORES, "races": RACES, "subraces": SUBRACES,
    "traits": TRAITS, "backgrounds": BACKGROUNDS, "feats": FEATS, "magic-items": MAGIC_ITEMS,
    "magic-schools": MAGIC_SCHOOLS, "damage-types": DAMAGE_TYPES, "languages": LANGUAGES,
    "alignments": ALIGNMENTS, "equipment-categories": EQUIPMENT_CATEGORIES,
    "weapon-properties": WEAPON_PROPERTIES, "rules": RULES, "rule-sections": RULE_SECTIONS,
}
ALIASES = {"class": "classes", "skill": "skills", "spell": "spells", "feature": "features", "subclass": "subclasses",
           "monster": "monsters", "condition": "conditions", "race": "races", "level": "levels"}


def _kind(kind):
    normalized = ALIASES.get(kind, kind)
    if normalized not in COLLECTIONS:
        raise ValueError("未知规则资料类别")
    return normalized


def _automation(kind, record_id):
    fallback = {"status": "reference", "reason": "已收录完整规则文本；尚未注册可自动结算的处理器，需要主持人裁定。"}
    resolver_name = {"spells": "spell_automation", "features": "feature_automation"}.get(kind)
    if resolver_name is None:
        return None
    try:
        module = importlib.import_module(".abilities", package=__package__)
        resolver = getattr(module, resolver_name, None)
        result = resolver(record_id) if resolver else fallback
        if isinstance(result, dict) and result.get("status") in {"automated", "assisted", "reference"}:
            return {"status": result["status"], "reason": str(result.get("reason", fallback["reason"]))}
    except ImportError:
        pass
    return fallback


def lookup(kind, record_id, *, _collections=None):
    """Return every source field plus localized metadata and actual handler status."""
    from .rules_context import current_view
    collections = _collections or (current_view().COLLECTIONS if current_view() is not None else COLLECTIONS)
    collection = _kind(kind)
    if record_id not in collections[collection]:
        raise ValueError("规则条目不存在")
    result = copy.deepcopy(collections[collection][record_id])
    automation = _automation(collection, record_id)
    if automation is not None:
        result["automation_status"] = automation["status"]
        result["automation_reason"] = automation["reason"]
    return result


def class_level(class_id, level):
    from .rules_context import current_view
    if current_view() is not None:
        return current_view().class_level(class_id, level)
    if class_id not in CLASS_LEVELS or not isinstance(level, int) or isinstance(level, bool) or level not in CLASS_LEVELS[class_id]:
        raise ValueError("职业等级必须是存在职业的1至20级")
    return copy.deepcopy(CLASS_LEVELS[class_id][level])


def get_catalog(kind=None, q="", class_id=None, level=None, school=None, limit=100, offset=0, *, _collections=None):
    """Search local source records. `level` is exact; spell levels include 0.

    No kind returns an overview for selection UIs. A kind returns a paginated
    {items,total,...} object containing complete (not truncated) source records.
    """
    from .rules_context import current_view
    collections = _collections or (current_view().COLLECTIONS if current_view() is not None else COLLECTIONS)
    if kind is None:
        return {"edition": EDITION, "srd_version": SRD_VERSION, "counts": {key: len(value) for key, value in collections.items()},
                "classes": [{"id": row["id"], "name": row["name"], "name_zh": row.get("name_zh"), "display_name": row["display_name"], "hit_die": row["hit_die"], "subclasses": copy.deepcopy(row["subclasses"])} for row in collections["classes"].values()],
                "skills": [copy.deepcopy(row) for row in collections["skills"].values()],
                "subclasses": [copy.deepcopy(row) for row in collections["subclasses"].values()],
                "source": {"repository": SOURCE["source_repository"], "commit": SOURCE["source_commit"], "rules_license": SOURCE["rules_license"], "structure_license": SOURCE["structure_license"]}}
    collection = _kind(kind)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ValueError("每页条数须为1至500")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("偏移量不能为负数")
    if class_id is not None and class_id not in collections["classes"]:
        raise ValueError("职业不存在")
    if level is not None and (not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= 20):
        raise ValueError("等级筛选值无效")
    if school is not None and school not in collections["magic-schools"]:
        raise ValueError("魔法学派不存在")
    query = str(q).strip().casefold()
    records = []
    for record in collections[collection].values():
        if class_id:
            classes = {reference["index"] for reference in record.get("classes", [])}
            if "class" in record:
                classes.add(record["class"]["index"])
            if collection == "classes":
                classes.add(record["id"])
            if class_id not in classes:
                continue
        if level is not None and record.get("level") != level:
            continue
        if school and record.get("school", {}).get("index") != school:
            continue
        searchable = " ".join([record["id"], record.get("name", ""), record.get("name_zh", ""), " ".join(record.get("desc", [])) if isinstance(record.get("desc"), list) else str(record.get("desc", ""))]).casefold()
        if query and query not in searchable:
            continue
        records.append(record)
    records.sort(key=lambda row: (row.get("level", -1), row.get("name", row["id"]), row["id"]))
    return {"items": [lookup(collection, row["id"], _collections=collections) for row in records[offset:offset + limit]], "total": len(records),
            "offset": offset, "limit": limit, "kind": collection, "edition": EDITION, "srd_version": SRD_VERSION}


def verify_source_integrity():
    """Useful for CI/release audits; normal startup does not need any network."""
    errors = []
    for file in SOURCE["files"]:
        path = DATA_DIR / file["file"]
        if not path.is_file():
            errors.append(f"Missing {file['file']}")
            continue
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != file["sha256"]:
            errors.append(f"SHA256 mismatch: {file['file']}")
        if len(raw) != file["bytes"]:
            errors.append(f"Byte count mismatch: {file['file']}")
        try:
            records = json.loads(raw)
        except (ValueError, UnicodeError):
            errors.append(f"Invalid JSON: {file['file']}")
            continue
        if not isinstance(records, list) or len(records) != file["records"]:
            errors.append(f"Record count mismatch: {file['file']}")
    license_path = DATA_DIR / "5e-database-LICENSE.md"
    if not license_path.is_file():
        errors.append("Missing upstream license")
    elif hashlib.sha256(license_path.read_bytes()).hexdigest() != SOURCE["license_sha256"]:
        errors.append("Upstream license integrity mismatch")
    return errors
