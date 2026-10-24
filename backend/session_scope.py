"""Persisted text audiences and viewer-local history, independent of voice.

This is the single-party migration layer. Splitting a party is deliberately
not exposed until scene-local mechanical state and shared entities are ready.
"""
from base64 import urlsafe_b64decode, urlsafe_b64encode
from copy import deepcopy
import hashlib
import hmac
import json
import secrets

MAIN_CHANNEL = "party-main"


def initialize(state):
    """Migrate once and freeze historical audiences to existing members."""
    state.setdefault("action_revision", state.get("version", 0))
    if "text_scope" not in state:
        state["text_scope"] = {"schema": 1, "cursor_secret": secrets.token_hex(32),
                               "members": {}, "channels": {MAIN_CHANNEL: {"id": MAIN_CHANNEL, "name": "队内交流"}}}
    for member in state.get("members", []):
        add_member(state, member["id"])
    for event in state.get("events", []):
        if "_audience" not in event:
            stamp_event(state, event)
    return state


def add_member(state, member_id):
    state["text_scope"]["members"].setdefault(member_id, {"channel": MAIN_CHANNEL, "epoch": 1, "seq": 0})


def membership(state, viewer):
    member = state["text_scope"]["members"].get(viewer)
    if member is None or not any(row["id"] == viewer for row in state.get("members", [])):
        raise ValueError("Viewer has no active room membership")
    return member


def stamp_event(state, event, *, audience=None, channel=None):
    if "_audience" in event:
        raise ValueError("Event audiences are immutable")
    scope = state["text_scope"]
    channel = channel or MAIN_CHANNEL
    if channel not in scope["channels"]:
        raise ValueError("Unknown text channel")
    active = {row["id"] for row in state.get("members", [])}
    eligible = {viewer for viewer, row in scope["members"].items() if row["channel"] == channel and viewer in active}
    audience = eligible if audience is None else set(audience)
    if not audience <= eligible:
        raise ValueError("Event audience must belong to its channel")
    event["_channel"] = channel
    event["_audience"] = {}
    for viewer in sorted(audience):
        member = scope["members"][viewer]
        member["seq"] += 1
        event["_audience"][viewer] = {"epoch": member["epoch"], "seq": member["seq"]}
    return event


def visible_to(state, event, viewer):
    member = membership(state, viewer)
    grant = event.get("_audience", {}).get(viewer)
    return bool(grant and grant["epoch"] == member["epoch"] and event.get("_channel") == member["channel"])


def visible_events(state, viewer):
    membership(state, viewer)
    result = []
    for event in state.get("events", []):
        if visible_to(state, event, viewer):
            public = {key: deepcopy(value) for key, value in event.items() if not key.startswith("_")}
            public["id"] = event["_audience"][viewer]["seq"]
            result.append(public)
    return result


def common_memory(state, recipients):
    """DM memory is the recipients' knowledge intersection, never host-wide."""
    recipients = set(recipients)
    for viewer in recipients:
        membership(state, viewer)
    return common_rows(state, state.get("events", []), recipients)


def common_rows(state, rows, recipients):
    return [{key: deepcopy(value) for key, value in event.items() if not key.startswith("_") and key != "id"}
            for event in rows if recipients and all(visible_to(state, event, viewer) for viewer in recipients)]


def remember(state, row, channel=MAIN_CHANNEL):
    row["_channel"] = channel
    row["_audience"] = {viewer: {"epoch": member["epoch"]}
                        for viewer, member in state["text_scope"]["members"].items() if member["channel"] == channel}
    return row


def scope_key(state, viewer):
    member = membership(state, viewer)
    return {"viewer": viewer, "channel": member["channel"], "epoch": member["epoch"]}


def audience_key(state):
    return [scope_key(state, member["id"]) for member in sorted(state.get("members", []), key=lambda row: row["id"])]


def _b64(value):
    return urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value):
    return urlsafe_b64decode(value + "=" * (-len(value) % 4))


def history_cursor(state, viewer, position):
    payload = _b64(json.dumps({**scope_key(state, viewer), "position": position}, sort_keys=True).encode())
    signature = hmac.new(bytes.fromhex(state["text_scope"]["cursor_secret"]), payload.encode(), hashlib.sha256).digest()
    return payload + "." + _b64(signature)


def read_cursor(state, viewer, cursor):
    try:
        if not isinstance(cursor, str) or len(cursor) > 1024:
            raise ValueError()
        payload, signature = cursor.split(".")
        expected = hmac.new(bytes.fromhex(state["text_scope"]["cursor_secret"]), payload.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_decode(signature), expected):
            raise ValueError()
        row = json.loads(_decode(payload))
        if {key: row.get(key) for key in ("viewer", "channel", "epoch")} != scope_key(state, viewer):
            raise ValueError()
        position = row["position"]
        if not isinstance(position, int) or isinstance(position, bool) or position < 0:
            raise ValueError()
        return position
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise ValueError("History cursor does not match the current viewer and channel") from None


def history_page(state, viewer, *, after=0, cursor=None, limit=200):
    after = read_cursor(state, viewer, cursor) if cursor is not None else after
    if not isinstance(after, int) or isinstance(after, bool) or after < 0:
        raise ValueError("Invalid viewer-local event position")
    visible = visible_events(state, viewer)
    pending = [event for event in visible if event["id"] > after]
    page = pending[:limit]
    position = page[-1]["id"] if page else after
    return {"events": page, "last_event_seq": visible[-1]["id"] if visible else 0,
            "has_more": len(pending) > limit, "cursor": history_cursor(state, viewer, position)}
