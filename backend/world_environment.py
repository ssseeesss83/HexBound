"""Object authority migration and explicit, version-checked view writeback."""
from copy import deepcopy

from . import world_state as world

VIEW_KEYS = ("_object_read_set", "_object_origin_place")


def place_id(room, node_id):
    package = (room.get("campaign") or {}).get("package") or room.get("campaign_package") or {}
    scenario = package.get("scenario", {})
    node = next((row for row in scenario.get("nodes", []) if row["id"] == node_id), {})
    return node.get("place_id") or "place:" + str(scenario.get("id", "preset")) + ":" + str(node_id)


def _definitions(room, node_id, scene=None):
    if scene and scene.get("id") == node_id:
        return scene.get("objects", [])
    package = (room.get("campaign") or {}).get("package") or room.get("campaign_package") or {}
    return next((row.get("objects", []) for row in package.get("scenario", {}).get("nodes", []) if row["id"] == node_id), [])


def _initial(definition, saved=None):
    value = deepcopy(definition)
    value.update(deepcopy(saved or {}))
    value.setdefault("hp", definition.get("hp", 10))
    value.setdefault("burning", "fire" in definition.get("tags", []))
    return value


def _ensure_place(room, pid):
    if pid not in room["world_places"]:
        world.add_place(room, pid)


def _entity_id(pid, object_id):
    return "object:" + pid + ":" + object_id


def migrate(canonical):
    """Pure staged migration; disagreeing old copies abort instead of guessing."""
    room = deepcopy(canonical)
    world.initialize(room)
    observed = {}
    for scene in room.get("scene_instances", {}).values():
        local = scene["local"]
        current_id = local.get("scene_id") or local.get("scene", {}).get("id", "lobby")
        scene["place_id"] = place_id(room, current_id)
        _ensure_place(room, scene["place_id"])
        environment = local.get("environment", {})
        definitions = _definitions(room, current_id, local.get("scene"))
        if definitions:
            local["environment"] = environment
            environment.setdefault(current_id, {"objects": {}, "tick": 0})
        for node_id, env in environment.items():
            if "entity_refs" in env:
                continue
            pid = place_id(room, node_id)
            _ensure_place(room, pid)
            specs = {row["id"]: row for row in _definitions(room, node_id, local.get("scene"))}
            saved = env.get("objects", {})
            # Old environmental objects remain even when their authored source
            # is not the current node; do not silently discard physical state.
            refs = {}
            for oid in set(specs) | set(saved):
                value = _initial(specs.get(oid, {"id": oid}), saved.get(oid))
                eid = _entity_id(pid, oid)
                if eid in observed and observed[eid] != value:
                    raise world.WorldConflict("旧存档同一物件存在冲突副本，需先核对：" + eid)
                observed[eid] = value
                if eid not in room["world_entities"]:
                    world.add_entity(room, eid, pid, "object", value, {"node_id": node_id, "object_id": oid})
                elif room["world_entities"][eid]["state"] != value:
                    raise world.WorldConflict("旧物件与权威实体状态冲突：" + eid)
                refs[oid] = eid
            env.pop("objects", None)
            env["entity_refs"] = refs
            timestamp = local.get("progression_clock", {}).get("world_minutes", 0) * 60 + env.get("elapsed_seconds", 0)
            place = room["world_places"][pid]
            place["last_environment_time"] = max(place.get("last_environment_time", 0), timestamp)
    room["world_environment_version"] = 1
    return room


def materialize(view):
    if view.get("world_environment_version") != 1:
        return view
    read_set = {}
    for env in view.get("environment", {}).values():
        if "entity_refs" not in env:
            continue
        objects = {}
        for oid, eid in env["entity_refs"].items():
            entity = view["world_entities"].get(eid)
            if entity is None or entity["kind"] != "object":
                raise world.WorldConflict("物件实体引用不存在")
            objects[oid] = {**deepcopy(entity["state"]), "entity_id": eid, "entity_revision": entity["revision"]}
            read_set[eid] = entity["revision"]
        env["objects"] = objects
    view["_object_read_set"] = read_set
    sid = view.get("_scene_execution_view", "scene-main")
    view["_object_origin_place"] = view["scene_instances"][sid].get("place_id")
    return view


def commit_view(view):
    """Validate all changed objects against their captured entity revisions."""
    if view.get("world_environment_version") != 1:
        return view
    changes, expected = {}, {}
    for env in view.get("environment", {}).values():
        for oid, eid in env.get("entity_refs", {}).items():
            if oid not in env.get("objects", {}):
                continue
            value = {key: deepcopy(item) for key, item in env["objects"][oid].items() if key not in {"entity_id", "entity_revision"}}
            entity = view["world_entities"][eid]
            if value == entity["state"]:
                continue
            if entity["place_id"] != view.get("_object_origin_place"):
                raise world.WorldConflict("不能通过场景缓存修改其他地点的物件")
            changes[eid] = value
            if eid not in view.get("_object_read_set", {}):
                raise world.WorldConflict("物件变更缺少读取版本")
            expected[eid] = view["_object_read_set"][eid]
    if changes:
        sid = view.get("_scene_execution_view", "scene-main")
        actor = next((member["id"] for member in view.get("members", [])
                      if view["member_contexts"].get(member["id"], {}).get("scene_instance_id") == sid), None)
        if actor is None:
            raise world.WorldConflict("没有合法参与者，不能提交物件变更")
        world.write_entities(view, actor, changes, expected, encounter_id=(view.get("combat") or {}).get("encounter_id"))
        for eid in changes:
            view["_object_read_set"][eid] = view["world_entities"][eid]["revision"]
    return view


def validate_read_set(view):
    if view.get("world_environment_version") != 1:
        return
    node_id = view.get("scene_id") or view.get("scene", {}).get("id")
    for eid in view.get("environment", {}).get(node_id, {}).get("entity_refs", {}).values():
        entity = view["world_entities"].get(eid)
        if not entity or entity["kind"] != "object" or entity["revision"] != view.get("_object_read_set", {}).get(eid):
            raise world.WorldConflict("物件读取版本已变化；未执行随机检定或消耗")


def prepare_save(view):
    commit_view(view)
    from .world_combat import commit_view as commit_combat
    commit_combat(view)
    return attach_current(view)


def attach_current(view):
    """Call after rule execution/entry and before persistence, never from a GET."""
    if view.get("world_environment_version") != 1:
        return view
    sid = view.get("_scene_execution_view", "scene-main")
    node_id = view.get("scene_id") or view.get("scene", {}).get("id", "lobby")
    pid = place_id(view, node_id)
    _ensure_place(view, pid)
    if view.get("world_combat_version") == 1 and view["scene_instances"][sid].get("place_id") != pid:
        raise world.WorldConflict("地点变更必须先提交进入计划")
    view["scene_instances"][sid]["place_id"] = pid
    definitions = _definitions(view, node_id, view.get("scene"))
    if definitions:
        env = view.setdefault("environment", {}).setdefault(node_id, {"tick": 0})
        refs = env.setdefault("entity_refs", {})
        for spec in definitions:
            oid = spec["id"]
            eid = _entity_id(pid, oid)
            if eid not in view["world_entities"]:
                world.add_entity(view, eid, pid, "object", _initial(spec), {"node_id": node_id, "object_id": oid})
            refs[oid] = eid
    return materialize(view)


def freeze(view):
    """Pure serialization guard; it never writes shared entity state."""
    if view.get("world_environment_version") != 1:
        return view
    for env in view.get("environment", {}).values():
        if "entity_refs" not in env:
            continue
        for oid, eid in env["entity_refs"].items():
            if oid in env.get("objects", {}):
                value = {key: item for key, item in env["objects"][oid].items() if key not in {"entity_id", "entity_revision"}}
                if value != view["world_entities"][eid]["state"]:
                    raise world.WorldConflict("物件变更尚未按读取版本提交")
        env.pop("objects", None)
    for key in VIEW_KEYS:
        view.pop(key, None)
    return view


def environment_tick(view, elapsed_seconds):
    """Deduplicate the same physical time beat across observers of a place."""
    if view.get("world_environment_version") != 1:
        return True
    sid = view.get("_scene_execution_view", "scene-main")
    pid = view["scene_instances"][sid]["place_id"]
    place = view["world_places"][pid]
    timestamp = view.get("progression", {}).get("world_minutes", 0) * 60 + elapsed_seconds
    if timestamp <= place.get("last_environment_time", 0):
        return False
    place["last_environment_time"] = timestamp
    place["revision"] += 1
    return True
