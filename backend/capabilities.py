"""One registry for catalog, sheets, menus and DM tools. IDs are exact."""
from copy import deepcopy
import json
from pathlib import Path

FEATURE_BINDINGS = json.loads((Path(__file__).parent / "data/feature-bindings.json").read_text(encoding="utf-8"))["features"]


def current_bindings():
    from .rules_context import current_view
    view = current_view()
    return view.FEATURE_BINDINGS if view is not None else FEATURE_BINDINGS


def feature_automation(feature_id):
    row = current_bindings().get(feature_id)
    if row is None:
        return {"status": "reference", "reason": "能力不属于当前规则包，不可由目录存在推断可执行。"}
    return {key: deepcopy(row[key]) for key in ("status", "reason")}


def action_feature_support(handler):
    bindings = [row for row in current_bindings().values() if row.get("handler") == handler and row.get("status") in {"automated", "assisted"}]
    return {"supported": bool(bindings), "status": bindings[0]["status"] if bindings else "reference",
            "reason": bindings[0]["reason"] if bindings else "规则包没有为此能力注册可执行处理器。"}


def spell_automation(spell_id):
    from . import abilities, compendium
    from .rules_context import current_view
    view = current_view()
    spells = view.SPELLS if view is not None else compendium.SPELLS
    effects = view.SPELL_EFFECTS if view is not None else abilities.SPELL_EFFECTS
    if spell_id not in spells:
        return {"status": "reference", "reason": "法术不在选定SRD内容包中，不可执行。"}
    effect = effects.get(spell_id)
    if not effect:
        return {"status": "reference", "reason": "完整规则资料已收录；尚无通过验收的效果处理器。"}
    reason = abilities.SPELL_NOTES.get(spell_id, "由服务端校验归属、动作、目标与法术位，执行已声明效果。")
    if effect.get("max_targets", 1) > 1:
        reason += " 当前范围目标仍为抽象遭遇房规，严格空间和友伤尚待验收。"
    # A handler is execution coverage, not evidence that every 5e interaction
    # (space, triggers, components, timing) has passed strict-rule acceptance.
    reason += " 原型效果可执行；严格空间、触发与完整交互仍待P08-P10验收。"
    return {"status": "assisted", "reason": reason}


def audit_registry():
    from . import compendium, abilities
    errors = []
    if set(FEATURE_BINDINGS) != set(compendium.FEATURES):
        errors.append("Feature bindings do not match the selected corpus")
    for spell_id in set(abilities.SPELL_EFFECTS) - set(compendium.SPELLS):
        errors.append("Out-of-package spell handler: " + spell_id)
    known_handlers = set(abilities.FEATURES) | {"sneak-attack", "extra-attack", "skill-bonus", "expertise", "ability-score-improvement"}
    for rid, row in FEATURE_BINDINGS.items():
        if row["handler"] is not None and row["handler"] not in known_handlers:
            errors.append("Unknown feature handler: " + rid)
    return errors
