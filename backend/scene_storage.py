"""Canonical scene storage with a legacy-shaped, scoped execution view.

The view is transient. Characters, packages, campaign-wide resource usage and
reward receipts have one persisted owner at room level. No split API yet.
"""
from copy import deepcopy

MAIN_SCENE = "scene-main"
STORAGE_VERSION = 2
LOCAL_FIELDS = frozenset({"scene", "scene_id", "scene_index", "flags", "combat", "environment",
                          "director", "dm_pending", "dm_source", "completed", "ending", "rest_used",
                          "action_revision"})
CAMPAIGN_CURSOR = frozenset({"node_id", "visited"})


def pack(view):
    """Serialize an execution view; never run rules or call scene entry hooks."""
    room = deepcopy(view)
    if room.get("scene_storage_version", STORAGE_VERSION) not in {1, STORAGE_VERSION}:
        raise ValueError("Unsupported scene storage version")
    active_scene = room.pop("_scene_execution_view", None)
    is_view = active_scene is not None
    active_scene = active_scene or MAIN_SCENE
    all_members = room.pop("_room_members", None)
    previous_status = room.pop("_room_status", None)
    room.pop("_text_channel", None)
    if all_members is not None:
        room["members"] = all_members
    instances = room.setdefault("scene_instances", {})
    instance = instances.setdefault(active_scene, {"id": active_scene, "local": {}, "channel_id": "party-main"})
    local = instance["local"] = {} if is_view else instance["local"]
    # Copy values only if present: a minimal pre-account row remains minimal.
    for key in LOCAL_FIELDS:
        if key in room:
            local[key] = room.pop(key)
    if isinstance(room.get("campaign"), dict):
        campaign = room["campaign"]
        cursor = local.setdefault("campaign_cursor", {})
        for key in CAMPAIGN_CURSOR:
            if key in campaign:
                cursor[key] = campaign.pop(key)
    if isinstance(room.get("progression"), dict):
        local["progression_clock"] = {key: value for key, value in room["progression"].items() if key != "mode"}
        room["progression"] = {key: value for key, value in room["progression"].items() if key == "mode"}
    contexts = room.setdefault("member_contexts", {})
    for member in room.get("members", []):
        contexts.setdefault(member["id"], {"scene_instance_id": MAIN_SCENE, "epoch": 1})
    if previous_status and room.get("status") == "finished" and not all(row["local"].get("completed") for row in instances.values()):
        room["status"] = previous_status
    if previous_status and room.get("status") != previous_status and room.get("status") in {"paused", "playing"}:
        for sid, other in instances.items():
            if sid != active_scene:
                other["local"]["action_revision"] = other["local"].get("action_revision", 0) + 1
    room["scene_storage_version"] = STORAGE_VERSION
    return room


def unpack(payload, scene_id=MAIN_SCENE):
    """Resolve explicit scene locals; for_actor also applies member visibility.

    The default primary view supports room-level persistence operations, not
    actor authorization. HTTP operations must use the authenticated context.
    """
    if "scene_instances" not in payload:
        payload = pack(payload)
    room = deepcopy(payload)
    if room.get("scene_storage_version") not in {1, STORAGE_VERSION}:
        raise ValueError("Unsupported scene storage version")
    instance = room["scene_instances"].get(scene_id)
    if instance is None:
        raise ValueError("Requested scene instance is missing")
    local = instance["local"]
    room.update({key: value for key, value in local.items() if key in LOCAL_FIELDS})
    if isinstance(room.get("campaign"), dict):
        room["campaign"] = {**room["campaign"], **local.get("campaign_cursor", {})}
    if isinstance(room.get("progression"), dict):
        room["progression"] = {**room["progression"], **local.get("progression_clock", {})}
    room["_scene_execution_view"] = scene_id
    return room


def for_scene(room, scene_id):
    view = unpack(pack(room), scene_id)
    view["_room_members"] = view.get("members", [])
    view["members"] = [member for member in view["_room_members"]
                       if view["member_contexts"].get(member["id"], {}).get("scene_instance_id") == scene_id]
    view["_room_status"] = view.get("status")
    view["_text_channel"] = view["scene_instances"][scene_id].get("channel_id", "party-main")
    return view


def for_actor(room, actor):
    context = room.get("member_contexts", {}).get(actor)
    scene_id = context["scene_instance_id"] if context else MAIN_SCENE
    view = for_scene(room, scene_id)
    if not any(member["id"] == actor for member in view["members"]):
        raise ValueError("Actor has no active scene membership")
    return view


def legacy_shape(view):
    """For migration verification: original fields, without new storage metadata."""
    value = deepcopy(view)
    for key in ("scene_instances", "member_contexts", "scene_storage_version", "_scene_execution_view", "_room_members", "_room_status", "_text_channel"):
        value.pop(key, None)
    return value
