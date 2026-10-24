"""Server-only authoritative entities and prepared scene operations.

These operations never roll dice, run an LLM, or accept a client-authored plan.
Callers save the room and command receipt together under the room transaction.
"""
from copy import deepcopy
from dataclasses import dataclass


class WorldConflict(ValueError):
    pass


def initialize(room):
    room.setdefault("world_schema", 1)
    if room["world_schema"] != 1:
        raise WorldConflict("未知世界状态版本")
    room.setdefault("world_places", {})
    room.setdefault("world_entities", {})
    return room


def add_place(room, place_id):
    initialize(room)
    if not isinstance(place_id, str) or not 1 <= len(place_id) <= 200 or place_id in room["world_places"]:
        raise WorldConflict("地点 ID 无效或重复")
    room["world_places"][place_id] = {"id": place_id, "revision": 0, "entity_ids": [],
                                       "active_encounter_id": None, "encounter_owner_scene_id": None}


def add_entity(room, entity_id, place_id, kind, state, source_ref):
    initialize(room)
    if place_id not in room["world_places"] or entity_id in room["world_entities"]:
        raise WorldConflict("实体地点不存在或实体重复")
    if kind not in {"creature", "object", "item"} or not isinstance(state, dict) or not source_ref:
        raise WorldConflict("实体种类、状态或来源无效")
    room["world_entities"][entity_id] = {"id": entity_id, "place_id": place_id, "kind": kind,
        "source_ref": deepcopy(source_ref), "revision": 0, "state": deepcopy(state), "active_encounter_id": None}
    place = room["world_places"][place_id]
    place["entity_ids"].append(entity_id)
    place["revision"] += 1


def _scene(room, sid):
    try:
        return room["scene_instances"][sid]
    except KeyError:
        raise WorldConflict("场景实例不存在") from None


def _place(room, pid):
    if room.get("world_schema") != 1:
        raise WorldConflict("世界状态未初始化或版本未知")
    try:
        return room["world_places"][pid]
    except KeyError:
        raise WorldConflict("权威地点不存在") from None


def _actor_scene(room, actor):
    if not any(member["id"] == actor for member in room.get("members", [])):
        raise WorldConflict("成员不存在")
    try:
        sid = room["member_contexts"][actor]["scene_instance_id"]
    except KeyError:
        raise WorldConflict("成员没有主动场景") from None
    return sid, _scene(room, sid)


def _members(room, sid):
    return tuple(sorted(member["id"] for member in room.get("members", [])
                        if room["member_contexts"].get(member["id"], {}).get("scene_instance_id") == sid))


def _epochs(room, sids):
    result = []
    for sid in sids:
        for actor in _members(room, sid):
            context = room["member_contexts"][actor]
            scope = room["text_scope"]["members"][actor]
            result.append((actor, sid, context["epoch"], scope["channel"], scope["epoch"]))
    return tuple(sorted(result))


def _entity_versions(room, place):
    return tuple(sorted((eid, room["world_entities"][eid]["revision"]) for eid in place["entity_ids"]))


@dataclass(frozen=True)
class EnterPlan:
    actor: str
    scene_id: str
    from_place: str | None
    to_place: str
    action_revision: int
    place_revision: int
    entity_versions: tuple
    member_epochs: tuple


def prepare_enter(room, actor, place_id):
    sid, scene = _actor_scene(room, actor)
    local = scene["local"]
    if local.get("completed") or (local.get("combat") or {}).get("active") or local.get("pending_transition"):
        raise WorldConflict("请先完成当前战斗或待结算步骤")
    place = _place(room, place_id)
    if place["active_encounter_id"] and place["encounter_owner_scene_id"] != sid:
        raise WorldConflict("目标地点已有另一队的活动遭遇，请等待检查点")
    return EnterPlan(actor, sid, scene.get("place_id"), place_id, local.get("action_revision", 0),
                     place["revision"], _entity_versions(room, place), _epochs(room, (sid,)))


def commit_enter(room, plan):
    if not isinstance(plan, EnterPlan) or prepare_enter(room, plan.actor, plan.to_place) != plan:
        raise WorldConflict("进入计划已过期；未执行随机检定或资源消耗")
    scene = _scene(room, plan.scene_id)
    if scene.get("place_id") != plan.to_place:
        scene["place_id"] = plan.to_place
        scene["local"]["action_revision"] = plan.action_revision + 1


def claim_encounter(room, actor, entity_ids, encounter_id, expected_versions):
    """Validate the complete read-set before reserving any entity or rolling."""
    sid, scene = _actor_scene(room, actor)
    place = _place(room, scene.get("place_id"))
    entity_ids = tuple(entity_ids)
    if not isinstance(encounter_id, str) or not 1 <= len(encounter_id) <= 200:
        raise WorldConflict("遭遇 ID 无效")
    if not entity_ids or len(set(entity_ids)) != len(entity_ids) or set(expected_versions) != set(entity_ids):
        raise WorldConflict("遭遇实体及版本清单不完整")
    old = room.get("world_encounter_receipts", {}).get(encounter_id)
    identity = {"scene_id": sid, "place_id": scene.get("place_id"), "entity_ids": sorted(entity_ids)}
    if old is not None:
        if old != identity:
            raise WorldConflict("遭遇 ID 已绑定其他实体或场景")
        return {"replayed": True, "encounter_id": encounter_id, "active": place["active_encounter_id"] == encounter_id}
    if place["active_encounter_id"]:
        if place["active_encounter_id"] == encounter_id and place["encounter_owner_scene_id"] == sid:
            if all(room["world_entities"].get(eid, {}).get("active_encounter_id") == encounter_id for eid in entity_ids):
                return {"replayed": True, "encounter_id": encounter_id}
        raise WorldConflict("地点已有唯一活动遭遇")
    entities = []
    for eid in entity_ids:
        entity = room["world_entities"].get(eid)
        if not entity or entity["place_id"] != scene.get("place_id") or entity["kind"] != "creature":
            raise WorldConflict("遭遇实体不属于当前地点")
        if entity["revision"] != expected_versions[eid] or entity["active_encounter_id"]:
            raise WorldConflict("实体版本或遭遇归属已变化")
        if entity["state"].get("hp", 1) <= 0 or entity["state"].get("dead"):
            raise WorldConflict("不能重新生成已经死亡的实体")
        entities.append(entity)
    place.update(active_encounter_id=encounter_id, encounter_owner_scene_id=sid, revision=place["revision"] + 1)
    for entity in entities:
        entity.update(active_encounter_id=encounter_id, revision=entity["revision"] + 1)
    room.setdefault("world_encounter_receipts", {})[encounter_id] = identity
    return {"replayed": False, "encounter_id": encounter_id}


def write_entities(room, actor, changes, expected_versions, *, encounter_id=None):
    sid, scene = _actor_scene(room, actor)
    place = _place(room, scene.get("place_id"))
    if set(changes) != set(expected_versions):
        raise WorldConflict("实体写入缺少完整版本条件")
    targets = []
    for eid, state in changes.items():
        entity = room["world_entities"].get(eid)
        if not entity or entity["place_id"] != scene.get("place_id") or not isinstance(state, dict):
            raise WorldConflict("不能修改场景外实体")
        if entity["revision"] != expected_versions[eid]:
            raise WorldConflict("实体版本已变化")
        if place["active_encounter_id"] and (place["encounter_owner_scene_id"] != sid or encounter_id != place["active_encounter_id"]):
            raise WorldConflict("实体属于另一活动遭遇")
        targets.append((entity, deepcopy(state)))
    changed = False
    for entity, state in targets:
        if entity["state"] != state:
            entity.update(state=state, revision=entity["revision"] + 1)
            changed = True
    if changed:
        place["revision"] += 1


def release_encounter(room, actor, encounter_id):
    sid, scene = _actor_scene(room, actor)
    place = _place(room, scene.get("place_id"))
    if place["active_encounter_id"] != encounter_id or place["encounter_owner_scene_id"] != sid:
        raise WorldConflict("不能结束其他场景的遭遇")
    for eid in place["entity_ids"]:
        entity = room["world_entities"][eid]
        if entity["active_encounter_id"] == encounter_id:
            entity.update(active_encounter_id=None, revision=entity["revision"] + 1)
    place.update(active_encounter_id=None, encounter_owner_scene_id=None, revision=place["revision"] + 1)


@dataclass(frozen=True)
class MergePlan:
    source: str
    target: str
    place_id: str
    clock: int
    revisions: tuple
    entity_versions: tuple
    member_epochs: tuple


def prepare_merge(room, source, target):
    if room.get("status") not in {"playing", "paused"}:
        raise WorldConflict("请在活动冒险的安全检查点合队")
    if source == target:
        raise WorldConflict("合队需要两个不同场景")
    a, b = _scene(room, source), _scene(room, target)
    if not _members(room, source) or not _members(room, target):
        raise WorldConflict("合队场景必须包含有效成员")
    if not a.get("place_id") or a.get("place_id") != b.get("place_id"):
        raise WorldConflict("合队双方必须位于同一地点")
    place = _place(room, a["place_id"])
    if place["active_encounter_id"]:
        raise WorldConflict("地点仍有活动遭遇")
    clocks = []
    for scene in (a, b):
        local = scene["local"]
        if local.get("completed") or (local.get("combat") or {}).get("active") or any(local.get(key) for key in ("pending_transition", "pending_choice", "reaction_windows")):
            raise WorldConflict("请先完成战斗、选择或待结算步骤")
        if scene.get("channel_id") not in room["text_scope"]["channels"]:
            raise WorldConflict("目标文字频道不存在")
        if any(room["text_scope"]["members"][actor]["channel"] != scene["channel_id"] for actor in _members(room, scene["id"])):
            raise WorldConflict("成员场景与文字频道不一致")
        clocks.append(local.get("progression_clock", {}).get("world_minutes", 0))
    if clocks[0] != clocks[1]:
        raise WorldConflict("逻辑时间不同，不能自动快进合队")
    return MergePlan(source, target, a["place_id"], clocks[0],
                     (a["local"].get("action_revision", 0), b["local"].get("action_revision", 0), place["revision"]),
                     _entity_versions(room, place), _epochs(room, (source, target)))


def commit_merge(room, plan, command_id):
    if not isinstance(plan, MergePlan) or not isinstance(command_id, str) or not 8 <= len(command_id) <= 200:
        raise WorldConflict("合队计划或命令 ID 无效")
    receipts = room.get("group_command_receipts", {})
    if command_id in receipts:
        old = receipts[command_id]
        if old["source"] != plan.source or old["target"] != plan.target:
            raise WorldConflict("合队命令 ID 已用于其他操作")
        return {**deepcopy(old), "replayed": True}
    if prepare_merge(room, plan.source, plan.target) != plan:
        raise WorldConflict("合队计划已过期")
    source, target = _scene(room, plan.source), _scene(room, plan.target)
    moved = _members(room, plan.source)
    for actor in moved:
        context = room["member_contexts"][actor]
        context.update(scene_instance_id=plan.target, epoch=context["epoch"] + 1)
        scope = room["text_scope"]["members"][actor]
        scope.update(channel=target["channel_id"], epoch=scope["epoch"] + 1, seq=0)
    for scene in (source, target):
        local = scene["local"]
        local["action_revision"] = local.get("action_revision", 0) + 1
        local["dm_pending"] = None
        local.setdefault("director", {})["proposals"] = {}
        scene["membership_revision"] = scene.get("membership_revision", 0) + 1
    receipt = {"source": plan.source, "target": plan.target, "members": list(moved), "replayed": False}
    room.setdefault("group_command_receipts", {})[command_id] = deepcopy(receipt)
    return receipt
