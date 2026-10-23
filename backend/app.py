from __future__ import annotations

import asyncio
import copy
import json
import os
import secrets
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import content, rules
from .dm import DM
from .store import Store


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateRoom(Input):
    name: str = Field(default="六席之间", min_length=1, max_length=60)
    player_name: str = Field(min_length=1, max_length=32)
    character_id: str = Field(min_length=1, max_length=50)
    mode: Literal["preset", "free", "hybrid"] = "preset"
    theme: str = Field(default="", max_length=600)


class JoinRoom(Input):
    invite_code: str = Field(min_length=6, max_length=20)
    player_name: str = Field(min_length=1, max_length=32)
    character_id: str = Field(min_length=1, max_length=50)


class Command(Input):
    command_id: str = Field(min_length=8, max_length=100)
    expected_version: int = Field(ge=0)
    type: Literal["start", "pause", "resume", "action", "chat", "narrate", "end_turn"]
    payload: dict = Field(default_factory=dict)


class TextPayload(Input):
    text: str = Field(min_length=1, max_length=1500)


class ActionPayload(Input):
    action_id: str = Field(min_length=1, max_length=80)
    target_id: str | None = Field(default=None, max_length=80)


def create_app(db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="HEXBOUND", version="0.1.0")
    store = Store(db_path or os.getenv("HEXBOUND_DB", "data/hexbound.sqlite3"))
    dm = DM()
    locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
    peers: dict[str, dict[WebSocket, str]] = defaultdict(dict)
    limits: dict[str, deque] = defaultdict(deque)
    app.state.store = store
    app.state.dm = dm

    def throttle(key: str, maximum: int):
        now = time.monotonic()
        queue = limits[key]
        while queue and queue[0] < now - 60:
            queue.popleft()
        if len(queue) >= maximum:
            raise HTTPException(429, "操作太频繁，请稍后再试")
        queue.append(now)
        if len(limits) > 5000:
            for old_key in list(limits):
                if not limits[old_key] or limits[old_key][-1] < now - 60:
                    del limits[old_key]

    def auth(room_id: str, authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "请使用此房间的成员凭证")
        member_id = store.authenticate(room_id, authorization[7:])
        if not member_id:
            raise HTTPException(401, "房间凭证无效或已失效")
        return member_id

    def get_state(room_id: str) -> dict:
        state = store.get(room_id)
        if state is None:
            raise HTTPException(404, "房间不存在")
        return state

    def event(state: dict, kind: str, text: str, actor_name: str = "DM", **extra):
        state["events"].append({"id": len(state["events"]) + 1, "kind": kind,
                                "actor_name": actor_name, "text": text, **extra})

    def public(state: dict, viewer: str) -> dict:
        online = set(peers.get(state["id"], {}).values())
        party = []
        for member in state["members"]:
            character = member["character"]
            party.append({**copy.deepcopy(character), "id": member["id"], "name": member["name"],
                          "character_id": character.get("id", member.get("character_id", "")),
                          "online": member["id"] in online})
        scene = state.get("scene") or {"id": "lobby", "title": "故事尚未开始", "text": "邀请伙伴入席，由房主开启冒险。", "objective": "等待队伍集结"}
        scene = {key: scene.get(key, "") for key in ("id", "title", "text", "objective")}
        actions = content.available_actions(state, viewer) if state["status"] == "playing" else []
        return {
            "id": state["id"], "name": state["name"], "mode": state["mode"],
            "status": state["status"], "version": state["version"], "host_id": state["host_id"],
            "invite_code": state["invite_code"], "party": party, "scene": scene,
            "events": copy.deepcopy(state["events"][-150:]), "last_event_seq": len(state["events"]),
            "available_actions": actions, "combat": copy.deepcopy(state.get("combat")),
            "dm_source": state.get("dm_source", "local"), "dm_pending": bool(state.get("dm_pending")),
        }

    async def broadcast(room_id: str):
        state = get_state(room_id)
        async def send(ws, member_id):
            try:
                await asyncio.wait_for(ws.send_json({"type": "snapshot", "room": public(state, member_id)}), timeout=3)
            except Exception:
                peers[room_id].pop(ws, None)
        await asyncio.gather(*(send(ws, member_id) for ws, member_id in list(peers[room_id].items())))

    async def add_dm_response(room_id: str, base_version: int, request_id: str, kind: str,
                              scene: dict, mode: str, theme: str, intent: str, recent: list, actions: list):
        # Network calls intentionally occur outside the room lock and transaction.
        try:
            if kind == "scene":
                generated, source = await dm.scene(scene, mode, theme)
                text = generated["text"]
                suggestion = None
            else:
                text, source, suggestion = await dm.narrate(scene, intent, recent, actions)
                generated = None
        except asyncio.CancelledError:
            # A disconnected/cancelled HTTP task must not permanently block narration.
            async with locks[room_id]:
                current = get_state(room_id)
                if current.get("dm_pending") == request_id:
                    previous = current["version"]
                    current["dm_pending"] = None
                    current["version"] += 1
                    event(current, "system", "DM 请求已取消；已结算的行动保持有效，可以继续冒险。")
                    store.save(current, previous)
            await broadcast(room_id)
            raise
        except Exception:
            text, source, suggestion, generated = "DM 暂时无法回应。已结算的行动保持有效，可以继续使用场景行动。", "fallback", None, None
        async with locks[room_id]:
            current = get_state(room_id)
            if current.get("dm_pending") != request_id:
                return
            previous = current["version"]
            current["dm_pending"] = None
            if previous == base_version:
                if generated is not None:
                    current["scene"] = generated
                current["dm_source"] = source
                event(current, "dm", text, source=source, suggested_action_id=suggestion)
            else:
                event(current, "system", "队伍的行动已推进故事，过期的 DM 回应已略过。")
            current["version"] += 1
            store.save(current, previous)
        await broadcast(room_id)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "service": "hexbound"}

    @app.get("/api/catalog")
    async def catalog():
        return {**content.catalog(), "llm": {"configured": dm.configured, "model": dm.model if dm.configured else "本地叙事"}}

    @app.post("/api/rooms", status_code=201)
    async def create_room(body: CreateRoom, request: Request):
        throttle("create:" + (request.client.host if request.client else "local"), 15)
        if body.mode == "free" and not dm.configured:
            raise HTTPException(422, "自由生成需要服务端配置 LLM；可先选择预设冒险或混合模式")
        try:
            character = content.new_character(body.character_id, body.player_name)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, "未知角色模板") from exc
        member_id, token, room_id = uuid.uuid4().hex, secrets.token_urlsafe(32), uuid.uuid4().hex
        state = {
            **content.initialize_state(body.mode, body.theme),
            "id": room_id, "name": body.name, "invite_code": secrets.token_hex(4).upper(),
            "mode": body.mode, "theme": body.theme, "host_id": member_id,
            "status": "lobby", "version": 0, "events": [], "dm_pending": None,
            "members": [{"id": member_id, "name": body.player_name, "character_id": body.character_id, "character": character}],
        }
        event(state, "system", "六席之间，故事等待第一位讲述者。")
        store.create(state, member_id, token)
        return {"room": public(state, member_id), "member_id": member_id, "token": token, "invite_code": state["invite_code"]}

    @app.post("/api/rooms/join")
    async def join_room(body: JoinRoom, request: Request):
        throttle("join:" + (request.client.host if request.client else "local"), 30)
        room_id = store.find_invite(body.invite_code.upper())
        if room_id is None:
            raise HTTPException(404, "邀请码无效")
        member_id, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
        try:
            character = content.new_character(body.character_id, body.player_name)
            async with locks[room_id]:
                state = store.join(room_id, {"id": member_id, "name": body.player_name,
                                           "character_id": body.character_id, "character": character}, token)
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, str(exc)) from exc
        await broadcast(room_id)
        return {"room": public(state, member_id), "member_id": member_id, "token": token, "invite_code": state["invite_code"]}

    @app.get("/api/rooms/{room_id}")
    async def room(room_id: str, authorization: str | None = Header(default=None)):
        member_id = auth(room_id, authorization)
        return public(get_state(room_id), member_id)

    @app.get("/api/rooms/{room_id}/events")
    async def events(room_id: str, after: int = 0, authorization: str | None = Header(default=None)):
        auth(room_id, authorization)
        if after < 0:
            raise HTTPException(422, "事件序号不能为负数")
        state = get_state(room_id)
        result = state["events"][after:after + 200]
        return {"events": result, "last_event_seq": len(state["events"]), "has_more": after + len(result) < len(state["events"])}

    @app.post("/api/rooms/{room_id}/commands")
    async def command(room_id: str, body: Command, authorization: str | None = Header(default=None)):
        member_id = auth(room_id, authorization)
        throttle("command:" + member_id, 120)
        # Validate payloads before performing any mutation.
        try:
            if body.type in ("chat", "narrate"):
                payload = TextPayload.model_validate(body.payload).model_dump()
            elif body.type == "action":
                payload = ActionPayload.model_validate(body.payload).model_dump()
            else:
                if body.payload:
                    raise ValueError("该命令不接受附加参数")
                payload = {}
        except ValueError as exc:
            raise HTTPException(422, "命令参数无效") from exc
        generated_scenes = None
        # Generation may take seconds; do not hold a database transaction or room lock.
        candidate = get_state(room_id)
        if body.type == "start" and candidate["mode"] == "free" and not candidate.get("scenes"):
            if store.prior_command(room_id, member_id, body.command_id) is not None:
                return {"room": public(candidate, member_id), "replayed": True}
            if candidate["host_id"] != member_id:
                raise HTTPException(403, "只有房主可以开始冒险")
            if candidate["version"] != body.expected_version or candidate["status"] != "lobby":
                raise HTTPException(409, "房间已更新，请同步后重试")
            try:
                generated_scenes = await dm.adventure(candidate["theme"])
            except Exception as exc:
                raise HTTPException(502, "自由剧本生成失败，房间仍在大厅；请检查模型配置后重试") from exc
        pending = None
        async with locks[room_id]:
            prior = store.prior_command(room_id, member_id, body.command_id)
            if prior is not None:
                # Current snapshot avoids regressing UI after a successfully retried write.
                return {"room": public(get_state(room_id), member_id), "replayed": True}
            state = get_state(room_id)
            if state["version"] != body.expected_version:
                raise HTTPException(409, "房间已更新，请同步后重试")
            member = next(m for m in state["members"] if m["id"] == member_id)
            previous = state["version"]
            if body.type in ("start", "pause", "resume") and member_id != state["host_id"]:
                raise HTTPException(403, "只有房主可以执行此操作")
            if body.type == "start":
                if state["status"] != "lobby":
                    raise HTTPException(409, "冒险已经开始")
                state["status"] = "playing"
                if generated_scenes:
                    state["scenes"] = generated_scenes
                    state["scene"] = copy.deepcopy(generated_scenes[0])
                    state["scene_id"] = generated_scenes[0]["id"]
                    state["dm_source"] = "llm"
                event(state, "system", "冒险开始。每一个选择，都将留下回声。")
                if generated_scenes:
                    event(state, "dm", state["scene"]["text"], source="llm")
                else:
                    pending = "scene"
            elif body.type == "pause":
                if state["status"] != "playing":
                    raise HTTPException(409, "当前无法暂停")
                state["status"] = "paused"
                event(state, "system", "房主暂停了冒险。")
            elif body.type == "resume":
                if state["status"] != "paused":
                    raise HTTPException(409, "冒险尚未暂停")
                state["status"] = "playing"
                event(state, "system", "冒险继续。")
            elif body.type == "chat":
                event(state, "chat", payload["text"], member["name"])
            elif body.type == "narrate":
                if state["status"] != "playing":
                    raise HTTPException(409, "请先开始或恢复冒险")
                if state.get("dm_pending"):
                    raise HTTPException(409, "DM 正在回应，请稍候")
                event(state, "intent", payload["text"], member["name"])
                pending = "narrate"
            else:
                if state["status"] != "playing":
                    raise HTTPException(409, "当前不能执行游戏行动")
                old_scene = state.get("scene_id")
                action_id = "end_turn" if body.type == "end_turn" else payload["action_id"]
                try:
                    action_events = rules.apply_action(state, member_id, action_id, payload.get("target_id"))
                except (ValueError, KeyError) as exc:
                    raise HTTPException(422, str(exc)) from exc
                for item in action_events:
                    item = dict(item)
                    actor_id = item.get("actor_id", member_id)
                    actor_name = next((m["name"] for m in state["members"] if m["id"] == actor_id),
                                      (state.get("combat") or {}).get("enemy", {}).get("name", "DM"))
                    event(state, item.pop("kind", "rule"), item.pop("text", ""),
                          item.pop("actor_name", actor_name), **{k: v for k, v in item.items() if k != "id"})
                if state.get("completed"):
                    state["status"] = "finished"
                elif state.get("scene_id") != old_scene:
                    pending = "scene"
            state["version"] += 1
            if pending:
                request_id = uuid.uuid4().hex
                state["dm_pending"] = request_id
            response = {"room": public(state, member_id)}
            store.save(state, previous, (member_id, body.command_id, {"version": state["version"]}))
        await broadcast(room_id)
        if pending:
            await add_dm_response(room_id, state["version"], request_id, pending, copy.deepcopy(state["scene"]),
                                  state["mode"], state["theme"], payload.get("text", ""), copy.deepcopy(state["events"][-8:]), content.available_actions(state, member_id))
            response = {"room": public(get_state(room_id), member_id)}
        return response

    @app.websocket("/api/rooms/{room_id}/ws")
    async def websocket(ws: WebSocket, room_id: str):
        origin = ws.headers.get("origin")
        if origin and origin.split("://", 1)[-1] != ws.headers.get("host"):
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            hello = await asyncio.wait_for(ws.receive_json(), timeout=10)
            token = hello.get("token") if isinstance(hello, dict) else None
            member_id = store.authenticate(room_id, token) if isinstance(token, str) and len(token) <= 200 else None
            if not member_id:
                await ws.close(code=1008, reason="无效成员凭证")
                return
            peers[room_id][ws] = member_id
            await broadcast(room_id)
            while True:
                message = await ws.receive_text()
                if len(message) > 1024:
                    await ws.close(code=1009)
                    break
                if message == "ping":
                    await ws.send_json({"type": "pong"})
        except (WebSocketDisconnect, asyncio.TimeoutError, ValueError):
            pass
        finally:
            peers[room_id].pop(ws, None)
            if peers[room_id]:
                await broadcast(room_id)

    # A crashed process cannot still own an outstanding narrator request.
    with store.connect() as db:
        for row in db.execute("SELECT id,state FROM rooms").fetchall():
            state = json.loads(row["state"])
            if state.get("dm_pending"):
                state["dm_pending"] = None
                state["version"] += 1
                event(state, "system", "服务已恢复；上一次未完成的 DM 请求已取消，可继续行动。")
                db.execute("UPDATE rooms SET state=?,version=? WHERE id=?",
                           (json.dumps(state, ensure_ascii=False), state["version"], state["id"]))

    frontend = Path(__file__).resolve().parent.parent / "frontend"
    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


app = create_app()
