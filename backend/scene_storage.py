"""Canonical scene storage with a legacy-shaped, single-scene execution view.

The view is transient. Characters, packages, campaign-wide resource usage and
reward receipts have one persisted owner at room level. No split API yet.
"""
from copy import deepcopy

MAIN_SCENE = "scene-main"
LOCAL_FIELDS = frozenset({"scene", "scene_id", "scene_index", "flags", "combat", "environment",
                          "director", "dm_pending", "dm_source", "completed", "ending", "rest_used",
                          "action_revision"})
CAMPAIGN_CURSOR = frozenset({"node_id", "visited"})


def pack(view):
    """Serialize an execution view; never run rules or call scene entry hooks."""
    room = deepcopy(view)
    if room.get("scene_storage_version", 1) != 1:
        raise ValueError("Unsupported scene storage version")
    is_view = room.pop("_scene_execution_view", None) == MAIN_SCENE
    instances = room.setdefault("scene_instances", {})
    instance = instances.setdefault(MAIN_SCENE, {"id": MAIN_SCENE, "local": {}})
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
    contexts = room.setdefault("member_contexts", {})
    for member in room.get("members", []):
        contexts.setdefault(member["id"], {"scene_instance_id": MAIN_SCENE, "epoch": 1})
    room["scene_storage_version"] = 1
    return room


def unpack(payload):
    """Resolve the primary scene for old rule functions during migration.

    Multiple-scene execution is a separate stage; this adapter must not guess
    which non-primary scene should be allowed to mutate shared room data.
    """
    if "scene_instances" not in payload:
        payload = pack(payload)
    room = deepcopy(payload)
    if room.get("scene_storage_version") != 1:
        raise ValueError("Unsupported scene storage version")
    instance = room["scene_instances"].get(MAIN_SCENE)
    if instance is None:
        raise ValueError("Primary scene instance is missing")
    local = instance["local"]
    room.update({key: value for key, value in local.items() if key in LOCAL_FIELDS})
    if isinstance(room.get("campaign"), dict):
        room["campaign"] = {**room["campaign"], **local.get("campaign_cursor", {})}
    room["_scene_execution_view"] = MAIN_SCENE
    return room


def legacy_shape(view):
    """For migration verification: original fields, without new storage metadata."""
    value = deepcopy(view)
    for key in ("scene_instances", "member_contexts", "scene_storage_version", "_scene_execution_view"):
        value.pop(key, None)
    return value
