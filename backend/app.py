from __future__ import annotations

import asyncio
import copy
import json
import os
import secrets
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import content, rules, campaign, characters, abilities, compendium, director, progression, free_actions, character_builds, character_ai, tactical
from .dm import DM,PlayerDM
from .dm_scheduler import DMScheduler
from .generation_jobs import GenerationJobs
from .story_coordinator import StoryCoordinator
from . import story_requests
from .store import Store
from . import rules_packages
from .rules_context import active_store, using_version
from . import session_scope
from . import scene_storage
from . import play_policy
from .heroes import create_hero_router
from .studio import create_studio_router, compile_scenario
from .accounts import create_accounts_router, require_user, authenticate_websocket


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateRoom(Input):
    name: str = Field(default="六席之间", min_length=1, max_length=60)
    player_name: str = Field(min_length=1, max_length=32)
    character_id: str = Field(default="fighter", min_length=1, max_length=50)
    hero_id: str | None = Field(default=None, min_length=1, max_length=64)
    mode: Literal["preset"] = "preset"
    theme: str = Field(default="", max_length=600)
    scenario_id: str | None = Field(default=None, max_length=80)
    # Accepted for old clients; never grants runtime authoring privileges.
    interaction_mode: Literal["guided", "freeform", "assisted"] = "assisted"
    starting_level: int | None = Field(default=None, ge=1, le=20, strict=True)
    progression_mode: Literal["xp", "milestone"] = "xp"


class JoinRoom(Input):
    invite_code: str = Field(min_length=6, max_length=20)
    player_name: str = Field(min_length=1, max_length=32)
    character_id: str = Field(default="fighter", min_length=1, max_length=50)
    hero_id: str | None = Field(default=None, min_length=1, max_length=64)


class ClaimSeat(Input):
    token: str = Field(min_length=16, max_length=200)


class Command(Input):
    command_id: str = Field(min_length=8, max_length=100)
    expected_version: int = Field(ge=0)
    expected_action_revision: int | None = Field(default=None, ge=0, strict=True)
    expected_scene_instance_id: str | None = Field(default=None, max_length=100)
    expected_membership_epoch: int | None = Field(default=None, ge=1, strict=True)
    type: Literal["start", "pause", "resume", "action", "chat", "narrate", "end_turn", "set_interaction", "scene_edit", "level_up", "manage_spells", "rest", "equip_skills", "director_propose", "capability_propose", "director_resolve", "director_cancel", "configure_character", "prepare_level_up"]
    payload: dict = Field(default_factory=dict)


class TextPayload(Input):
    text: str = Field(min_length=1, max_length=1500)


class IntentPayload(TextPayload):
    skill_id: str | None = Field(default=None, max_length=40)


class GroupScope(Input):
    scene_instance_id: str = Field(min_length=1, max_length=100)
    membership_epoch: int = Field(ge=1, strict=True)
    action_revision: int = Field(ge=0, strict=True)


class GroupPrepare(Input):
    operation: Literal["split", "merge"]
    expected_scope: GroupScope
    members: list[str] = Field(default_factory=list, max_length=5)
    source: str | None = Field(default=None, min_length=1, max_length=100)
    target: str | None = Field(default=None, min_length=1, max_length=100)


class GroupCommit(Input):
    plan_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    command_id: str = Field(min_length=8, max_length=100)


class RetryPrepare(Input):
    expected_scope: GroupScope


class RetryCommit(Input):
    plan_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class ActionPayload(Input):
    destination: dict | None = None
    action_id: str = Field(min_length=1, max_length=80)
    target_id: str | None = Field(default=None, max_length=80)
    slot_level: int | None = Field(default=None, ge=1, le=9, strict=True)
    slot_source: Literal["spell", "pact"] | None = None
    target_ids: list[str] = Field(default_factory=list, max_length=12)
    resource_amount: int | None = Field(default=None, ge=1, le=100, strict=True)
    skill_id: str | None = Field(default=None, max_length=40)


class InteractionPayload(Input):
    mode: Literal["guided", "freeform", "assisted"]


class SceneEditPayload(Input):
    title: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=1800)
    objective: str = Field(default="", max_length=180)


class LevelPayload(Input):
    choices: dict = Field(default_factory=dict)


class BuildPayload(Input):
    build: dict


class BuildPreviewPayload(BuildPayload):
    target_level: int = Field(default=1, ge=1, le=20, strict=True)


class BuildAIPayload(BuildPreviewPayload):
    prompt: str = Field(default="", max_length=2000)


class SpellPayload(Input):
    prepared_spells: list[str] = Field(max_length=40)


class RestPayload(Input):
    kind: Literal["short", "long"]
    hit_dice: int = Field(default=0, ge=0, le=20)


class SkillsPayload(Input):
    skill_ids: list[str] = Field(max_length=4)


class ProposalPayload(Input):
    proposal_id: str = Field(min_length=1, max_length=100)


def create_app(db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="HEXBOUND", version="0.10.0")
    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Validation responses must never echo passwords or other submitted secrets.
        return JSONResponse(status_code=422, content={"detail": [
            {key: error[key] for key in ("loc", "msg", "type") if key in error}
            for error in exc.errors()
        ]}, headers={"Cache-Control": "no-store"})

    store = Store(db_path or os.getenv("HEXBOUND_DB", "data/hexbound.sqlite3"))
    installed_rules = rules_packages.install_package(store, rules_packages.build_legacy_package())
    jobs = GenerationJobs(store)
    scheduler = DMScheduler(jobs,DM())
    dm = PlayerDM(scheduler)
    coordinator = StoryCoordinator(jobs,scheduler,lambda room_id:broadcast(room_id))
    @asynccontextmanager
    async def lifespan(application):
        nonlocal scheduler,coordinator
        if scheduler.snapshot()['closed']:
            scheduler = DMScheduler(jobs,DM())
            dm.scheduler = scheduler
            application.state.dm_scheduler = scheduler
            coordinator = StoryCoordinator(jobs,scheduler,lambda room_id:broadcast(room_id))
            application.state.story_coordinator = coordinator
        coordinator.start()
        scheduler.start()
        try:
            yield
        finally:
            try:
                await scheduler.close()
            finally:
                await coordinator.close()
    app.router.lifespan_context = lifespan
    locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
    peers: dict[str, dict[WebSocket, str]] = defaultdict(dict)
    peer_tokens: dict[WebSocket, str] = {}
    limits: dict[str, deque] = defaultdict(deque)
    app.state.store = store
    app.state.dm = dm
    app.state.dm_scheduler = scheduler
    app.state.generation_jobs = jobs
    app.state.story_coordinator = coordinator
    app.state.rules_package = installed_rules
    app.include_router(create_accounts_router(store))
    app.include_router(create_hero_router(store))
    with active_store(store):
        store.migrate_heroes()
    app.include_router(create_studio_router(store, dm))

    def actions_for(state, member_id):
        from .action_menu import available
        return available(state, member_id)

    def append_rule_events(state, items, fallback_actor):
        for item in items:
            item = dict(item)
            actor_id = item.get("actor_id", fallback_actor)
            actors = [{"id": m["id"], "name": m["name"]} for m in state["members"]]
            actors += (state.get("combat") or {}).get("enemies", [])
            actor_name = next((a["name"] for a in actors if a["id"] == actor_id), "DM")
            event(state, item.pop("kind", "rule"), item.pop("text", ""),
                  item.pop("actor_name", actor_name), **{k: v for k, v in item.items() if k != "id"})

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

    def allow_guests() -> bool:
        return os.getenv("HEXBOUND_ALLOW_GUESTS", "0") == "1"

    def room_user(request: Request) -> dict | None:
        # An invalid or revoked account cookie must never fall back to guest access.
        if request.cookies.get("hexbound_session") or not allow_guests():
            return require_user(request)
        return None

    def auth(room_id: str, authorization: str | None, request: Request) -> str:
        user = room_user(request)
        if user:
            member_id = store.account_member(room_id, user["id"])
            if not member_id:
                raise HTTPException(403, "此账号不是房间成员；旧存档请先认领席位")
            return member_id
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "请使用此房间的成员凭证")
        member_id = store.authenticate(room_id, authorization[7:])
        if not member_id:
            raise HTTPException(401, "房间凭证无效或已失效")
        return member_id

    def socket_member(ws: WebSocket, room_id: str) -> str | None:
        if ws.cookies.get("hexbound_session") or not allow_guests():
            user = authenticate_websocket(ws)
            return store.account_member(room_id, user["id"])
        token = peer_tokens.get(ws)
        return store.authenticate(room_id, token) if token else None

    def get_state(room_id: str) -> dict:
        state = store.get(room_id)
        if state is None:
            raise HTTPException(404, "房间不存在")
        return state

    def event(state: dict, kind: str, text: str, actor_name: str = "DM", **extra):
        session_scope.initialize(state)
        item = {"id": len(state["events"]) + 1, "kind": kind,
                "actor_name": actor_name, "text": text, **extra}
        session_scope.stamp_event(state, item)
        state["events"].append(item)

    def bind_response_scope(request, state, viewer):
        context = state["member_contexts"][viewer]
        text = state["text_scope"]["members"][viewer]
        proof = {"room_id":state["id"], "viewer":viewer, "scene":context["scene_instance_id"],
                 "membership_epoch":context["epoch"], "channel":text["channel"], "text_epoch":text["epoch"]}
        proofs = getattr(request.state, "response_scopes", {})
        proofs[(state["id"],viewer)] = proof
        request.state.response_scopes = proofs
        return proof

    def public(state: dict, viewer: str, request=None) -> dict:
        state = scene_storage.for_actor(state, viewer)
        if request is not None:
            bind_response_scope(request, state, viewer)
        with active_store(store), using_version(state.get("rules_package_version", rules_packages.LEGACY_PACKAGE)):
            return _public(state, viewer)

    def _public(state: dict, viewer: str) -> dict:
        journal = session_scope.visible_events(state, viewer)
        online = set(peers.get(state["id"], {}).values())
        party = []
        for member in state["members"]:
            character = member["character"]
            visible = {key:copy.deepcopy(character[key]) for key in (
                "name","class_id","class_name","class","template_id","level","xp","proficiency","abilities",
                "hp","max_hp","ac","weapon","potions","death_successes","death_failures","stable","dead",
                "resources","spell_slots","pact_slots","hit_dice","conditions","concentration","skill_proficiencies",
                "expertise","saving_throw_proficiencies","milestone_credits"
            ) if key in character}
            if member["id"] == viewer:
                visible["hero_id"] = member.get("hero_id")
            party.append({**visible, "id": member["id"], "name": member["name"],
                          "character_id": character.get("id", member.get("character_id", "")),
                          "online": member["id"] in online,
                          "build_ready": member.get("build_ready", True),
                          "can_rebuild": state["status"] == "lobby" and member.get("can_rebuild", False)})
        scene = state.get("scene") or {"id": "lobby", "title": "故事尚未开始", "text": "邀请伙伴入席，由房主开启冒险。", "objective": "等待队伍集结"}
        scene = {key: scene.get(key, "") for key in ("id", "title", "text", "objective")}
        actions = actions_for(state, viewer) if state["status"] == "playing" else []
        return {
            "id": state["id"], "name": state["name"], "mode": state["mode"],
            "ruleset_id": state.get("ruleset_id", rules_packages.RULESET_ID),
            "rules_package_version": state.get("rules_package_version", rules_packages.LEGACY_PACKAGE),
            "engine_profile": state.get("engine_profile", rules_packages.ENGINE_PROFILE),
            "status": state["status"], "version": state["version"], "host_id": state["host_id"],
            "action_revision": state["action_revision"],
            "scene_instance_id": state["_scene_execution_view"],
            "scene_leader_id": state["_scene_leader_id"],
            "membership_epoch": state["member_contexts"][viewer]["epoch"],
            "invite_code": state["invite_code"], "party": party, "scene": scene,
            "starting_level": state.get("starting_level", 1),
            "events": journal[-150:], "last_event_seq": journal[-1]["id"] if journal else 0,
            "text_scope": session_scope.scope_key(state, viewer),
            "available_actions": actions, "combat": copy.deepcopy(state.get("combat")),
            "dm_source": state.get("dm_source", "local"), "dm_pending": bool(state.get("dm_pending")),
            "play_mode": play_policy.PLAY_MODE,
            "play_policy_version": play_policy.POLICY_VERSION,
            "interaction_mode": "assisted",
            "scenario": state.get("scenario_summary"),
            "progression": state.get("progression", {"mode":"xp","world_minutes":0}),
            "combat_capabilities": abilities.capabilities(state,viewer),
            "route_wait": coordinator.status(state,viewer),
            "battlefield": tactical.projection(state,viewer),
            "route_retry_available": coordinator.can_retry(state,viewer),
            "free_actions": free_actions.context(state,viewer),
            "director_proposals": [director.public_proposal(p,state) for actor,p in state.get("director",{}).get("proposals",{}).items() if actor==viewer],
        }

    async def broadcast_room(room_id: str):
        state = get_state(room_id)
        async def send(ws, member_id):
            try:
                if socket_member(ws, room_id) != member_id:
                    await ws.close(code=1008, reason="会话已失效")
                    peers[room_id].pop(ws, None)
                    peer_tokens.pop(ws, None)
                    return
                await asyncio.wait_for(ws.send_json({"type": "snapshot", "room": public(get_state(room_id), member_id)}), timeout=3)
            except Exception:
                peers[room_id].pop(ws, None)
                peer_tokens.pop(ws, None)
                try:
                    await ws.close(code=1008, reason="会话已失效")
                except Exception:
                    pass
        await asyncio.gather(*(send(ws, member_id) for ws, member_id in list(peers[room_id].items())))

    app.state.broadcast_room = broadcast_room
    async def broadcast(room_id):
        await app.state.broadcast_room(room_id)

    async def add_dm_response(room_id: str, base_action_revision: int, request_id: str, kind: str,
                              scene: dict, mode: str, theme: str, intent: str, recent: list, actions: list,
                              interaction_mode: str = "guided", audience_scope=None, scene_instance_id=scene_storage.MAIN_SCENE):
        # Network calls intentionally occur outside the room lock and transaction.
        try:
            # Announcing the committed action belongs to the same cancellation
            # boundary as narration; slow WS delivery must not strand pending.
            await broadcast(room_id)
            if kind == "scene" and interaction_mode == "assisted" and dm.configured:
                text, source, suggestion = await dm.narrate(scene, "介绍眼前的局势，并建议一个可选行动；不要代替玩家决定。", recent, actions)
                generated = None
            elif kind == "scene":
                generated, source = await dm.scene(scene, mode, theme)
                text = generated["text"]
                suggestion = None
            else:
                text, source, suggestion = await dm.narrate(scene, intent, recent, actions)
                generated = None
        except asyncio.CancelledError:
            # A disconnected/cancelled HTTP task must not permanently block narration.
            async with locks[room_id]:
                current = scene_storage.for_scene(get_state(room_id), scene_instance_id)
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
            current = scene_storage.for_scene(get_state(room_id), scene_instance_id)
            if current.get("dm_pending") != request_id:
                return
            previous = current["version"]
            current["dm_pending"] = None
            if current["action_revision"] == base_action_revision and session_scope.audience_key(current) == audience_scope:
                if generated is not None:
                    current["scene"] = generated
                    current["action_revision"] += 1
                current["dm_source"] = source
                event(current, "dm", text, source=source, suggested_action_id=suggestion)
            else:
                event(current, "system", "队伍的行动已推进故事，过期的 DM 回应已略过。")
            current["version"] += 1
            store.save(current, previous)
        await broadcast(room_id)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        parts = request.url.path.split("/")
        pinned = store.get(parts[3]) if len(parts) > 3 and parts[1:3] == ["api", "rooms"] and parts[3] not in {"join", "mine"} else None
        version = pinned.get("rules_package_version", rules_packages.LEGACY_PACKAGE) if pinned else None
        with active_store(store):
            try:
                with using_version(version):
                    response = await call_next(request)
            except ValueError as exc:
                if str(exc).startswith("Pinned rules package is unavailable:"):
                    return JSONResponse(status_code=409, content={"detail": "房间锁定的规则包不可用，请先恢复对应规则版本。"})
                raise
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        proofs = list(getattr(request.state, "response_scopes", {}).values())
        if proofs and response.status_code < 400:
            try:
                for proof in proofs:
                    if request.cookies.get("hexbound_session") or request.headers.get("authorization"):
                        if auth(proof["room_id"], request.headers.get("authorization"), request) != proof["viewer"]:
                            raise HTTPException(403, "房间身份已变化")
                    latest = get_state(proof["room_id"])
                    current = bind_response_scope(request, latest, proof["viewer"])
                    if current != proof:
                        return JSONResponse(status_code=409, headers={"Cache-Control":"no-store", "X-Content-Type-Options":"nosniff", "Referrer-Policy":"same-origin"},
                            content={"detail":"队伍范围已变化，请重新载入。", "retry_same_command":True})
            except (HTTPException, KeyError, ValueError):
                return JSONResponse(status_code=403, headers={"Cache-Control":"no-store", "X-Content-Type-Options":"nosniff", "Referrer-Policy":"same-origin"}, content={"detail":"当前房间授权已失效，请重新登录。", "retry_same_command":True})
        return response

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "service": "hexbound"}

    @app.get("/api/catalog")
    async def catalog():
        base = content.catalog()
        presets=[]
        for cid, item in compendium.CLASSES.items():
            c=characters.create_character(cid, item.get("name_zh") or item["name"])
            presets.append({"id":cid,"name":item.get("name_zh") or item["name"],"label":item.get("name_zh") or item["name"],
                            "class_name":item.get("name_zh") or item["name"],"role":"SRD 5.1 核心职业","max_hp":c["max_hp"],"ac":c["ac"],"abilities":c["abilities"],"description":"1—20级成长与独立角色档案"})
        base["characters"]=presets
        base["templates"]=presets
        base["modes"] = [{"id": "preset", "label": "剧本 + AI DM"}]
        base["standard_skills"] = [{"id": sid, "name": director.SKILL_NAMES[sid], "ability": ability}
                                   for sid, ability in director.SKILL_ABILITIES.items()]
        base["rules"]["supported"] += ["12核心职业与18技能档案","1—20级升级与法术管理","个人动作和法术资源"]
        base["rules"]["limitations"] = ["2014 SRD 5.1规则；完整目录与自动化能力分别标识","复杂空间、召唤及未注册效果仅供规则查阅","不包含扩展书专有职业与全部子职业；暂不支持多职业","种族/背景目前使用明确的通用预设，非完整选择系统"]
        return {**base, "auth": {"allow_guests": allow_guests()}, "llm": {"configured": dm.configured, "model": dm.model if dm.configured else "本地叙事"}}

    @app.post("/api/character-builds/preview")
    async def preview_build(body: BuildPreviewPayload, request: Request):
        room_user(request)
        try:
            return character_builds.build_preview(body.build, body.target_level)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/character-builds/ai")
    async def suggest_build(body: BuildAIPayload, request: Request):
        user = room_user(request)
        throttle("build-ai:" + (user["id"] if user else request.client.host), 12)
        try:
            return await character_ai.suggest(dm, body.build, body.target_level, body.prompt)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/rooms", status_code=201)
    async def create_room(body: CreateRoom, request: Request):
        user = room_user(request)
        throttle("create:" + (request.client.host if request.client else "local"), 15)
        package = compile_scenario(store, body.scenario_id) if body.scenario_id else None
        try:
            with using_version(package.get('rules_package_version') if package else None):
                character = characters.create_character(body.character_id, body.player_name)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, "未知角色模板") from exc
        member_id, token, room_id = uuid.uuid4().hex, secrets.token_urlsafe(32), uuid.uuid4().hex
        state = {
            **content.initialize_state(body.mode, body.theme),
            "id": room_id, "name": body.name, "invite_code": secrets.token_hex(4).upper(),
            "mode": body.mode, "theme": body.theme, "host_id": member_id,
            "status": "lobby", "version": 0, "events": [], "dm_pending": None,
            "interaction_mode": "assisted",
            "starting_level": body.starting_level or (package["scenario"].get("starting_level",3) if package else 3),
            "progression": {"mode":body.progression_mode,"world_minutes":0},
            "reward_ledger": [],
            "members": [{"id": member_id, "name": body.player_name, "character_id": body.character_id, "character": character, "hero_id":body.hero_id}],
        }
        if package:
            state["campaign_package"] = copy.deepcopy(package)
            state["scenario_summary"] = {"id": body.scenario_id, "name": package["scenario"]["name"],
                                         "revisions": package.get("revisions", {})}
            state["scene"] = {"id": "lobby", "title": package["scenario"]["name"],
                              "text": "已锁定发布版本。邀请同伴后开始探索。", "objective": "等待队伍集结"}
        event(state, "system", "六席之间，故事等待第一位讲述者。")
        try:
            store.create(state, member_id, token, user["id"] if user else None)
        except ValueError as exc:
            raise HTTPException(409,str(exc)) from exc
        return {"room": public(state, member_id, request), "member_id": member_id, "token": None if user else token, "invite_code": state["invite_code"]}

    @app.post("/api/rooms/join")
    async def join_room(body: JoinRoom, request: Request):
        user = room_user(request)
        throttle("join:" + (request.client.host if request.client else "local"), 30)
        room_id = store.find_invite(body.invite_code.upper())
        if room_id is None:
            raise HTTPException(404, "邀请码无效")
        member_id, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
        try:
            target_room = get_state(room_id)
            with using_version(target_room.get("rules_package_version", rules_packages.LEGACY_PACKAGE)):
                character = characters.create_character(body.character_id, body.player_name)
            async with locks[room_id]:
                user = room_user(request)
                state = store.join(room_id, {"id": member_id, "name": body.player_name,
                                           "character_id": body.character_id, "character": character, "hero_id":body.hero_id}, token, user["id"] if user else None)
                if user:
                    member_id = store.account_member(room_id, user["id"])
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, str(exc)) from exc
        await broadcast(room_id)
        return {"room": public(state, member_id, request), "member_id": member_id, "token": None if user else token, "invite_code": state["invite_code"]}

    @app.get("/api/my/rooms")
    async def my_rooms(request: Request):
        user = require_user(request)
        items = store.account_rooms(user["id"])
        for item in items:
            bind_response_scope(request,get_state(item["room_id"]),item["member_id"])
        return {"items":items}

    @app.post("/api/rooms/{room_id}/resume")
    async def resume_seat(room_id: str, request: Request):
        user = require_user(request)
        member_id = store.account_member(room_id, user["id"])
        if not member_id:
            raise HTTPException(403, "此账号没有该房间的席位")
        state = get_state(room_id)
        return {"room": public(state, member_id, request), "member_id": member_id, "token": None, "invite_code": state["invite_code"]}

    @app.post("/api/rooms/{room_id}/claim")
    async def claim_seat(room_id: str, body: ClaimSeat, request: Request):
        user = require_user(request)
        throttle("claim:" + user["id"], 20)
        async with locks[room_id]:
            user = require_user(request)
            try:
                member_id = store.claim(room_id, body.token, user["id"])
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            state = get_state(room_id)
        await broadcast(room_id)
        return {"room": public(state, member_id, request), "member_id": member_id, "token": None, "invite_code": state["invite_code"]}

    @app.get("/api/rooms/{room_id}")
    async def room(room_id: str, request: Request, authorization: str | None = Header(default=None)):
        member_id = auth(room_id, authorization, request)
        return public(get_state(room_id), member_id, request)

    @app.get("/api/rooms/{room_id}/groups")
    async def groups(room_id: str, request: Request, authorization: str | None = Header(default=None)):
        actor = auth(room_id, authorization, request)
        state = get_state(room_id)
        if state["host_id"] != actor:
            raise HTTPException(403, "只有房主可以查看分组桌务")
        bind_response_scope(request,state,actor)
        # Table administration shows a roster, never foreign scenes or counters.
        result = []
        for sid in state["scene_instances"]:
            occupants = [{"id":m["id"], "name":m["name"]} for m in state["members"]
                         if state["member_contexts"][m["id"]]["scene_instance_id"] == sid]
            if occupants:
                result.append({"id":sid, "members":occupants})
        return {"groups":result}

    @app.post("/api/rooms/{room_id}/groups/prepare")
    async def prepare_groups(room_id: str, body: GroupPrepare, request: Request, authorization: str | None = Header(default=None)):
        actor = auth(room_id, authorization, request)
        throttle("groups:" + actor, 20)
        if (body.operation == "split" and (body.source is not None or body.target is not None)) or (body.operation == "merge" and (body.members or not body.source or not body.target)):
            raise HTTPException(422, "分组参数无效")
        async with locks[room_id]:
            if auth(room_id, authorization, request) != actor:
                raise HTTPException(403, "房间身份已变化")
            if get_state(room_id)["host_id"] != actor:
                raise HTTPException(403, "只有房主可以准备分组桌务")
            try:
                prepared = store.prepare_group_change(room_id, actor, body.operation, members=body.members,
                    source=body.source, target=body.target, expected_scope=body.expected_scope.model_dump())
                bind_response_scope(request,get_state(room_id),actor)
                return prepared
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc

    @app.post("/api/rooms/{room_id}/groups/commit")
    async def commit_groups(room_id: str, body: GroupCommit, request: Request, authorization: str | None = Header(default=None)):
        actor = auth(room_id, authorization, request)
        async with locks[room_id]:
            if auth(room_id, authorization, request) != actor:
                raise HTTPException(403, "房间身份已变化")
            if get_state(room_id)["host_id"] != actor:
                raise HTTPException(403, "只有房主可以提交分组桌务")
            try:
                receipt = store.commit_group_change(room_id,actor,body.plan_id,body.command_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            result = {"room":public(get_state(room_id),actor,request), "group_change":receipt}
        await broadcast(room_id)
        return result

    @app.post("/api/rooms/{room_id}/route-retry/prepare")
    async def prepare_route_retry(room_id: str, body: RetryPrepare, request: Request, authorization: str | None = Header(default=None)):
        actor=auth(room_id,authorization,request)
        throttle('route-retry:'+actor,20)
        async with locks[room_id]:
            if auth(room_id,authorization,request)!=actor:raise HTTPException(403,'房间身份已变化')
            try:
                result=story_requests.create_retry_review(jobs,room_id,actor,body.expected_scope.model_dump(),now=scheduler.clock())
            except ValueError as exc:raise HTTPException(409,str(exc)) from exc
            bind_response_scope(request,get_state(room_id),actor)
            return result

    @app.post("/api/rooms/{room_id}/route-retry/confirm")
    async def confirm_route_retry(room_id: str, body: RetryCommit, request: Request, authorization: str | None = Header(default=None)):
        actor=auth(room_id,authorization,request)
        throttle('route-retry-confirm:'+actor,60)
        with scheduler.player_activity(preempt=False):
            async with locks[room_id]:
                if auth(room_id,authorization,request)!=actor:raise HTTPException(403,'房间身份已变化')
                try:
                    result=story_requests.confirm_retry_review(jobs,room_id,actor,body.plan_id,now=scheduler.clock())
                except ValueError as exc:raise HTTPException(409,str(exc)) from exc
                response=dict(room=public(get_state(room_id),actor,request),
                    route_retry=dict(plan_id=body.plan_id,replayed=result['replayed'],additional_attempts=1))
        scheduler.wake()
        coordinator.completed(result['job']['id'])
        await broadcast(room_id)
        return response

    @app.get("/api/rooms/{room_id}/characters/{target_member_id}")
    async def character_detail(room_id: str, target_member_id: str, request: Request, authorization: str | None = Header(default=None)):
        viewer=auth(room_id,authorization,request)
        state=scene_storage.for_actor(get_state(room_id), viewer)
        bind_response_scope(request,state,viewer)
        target=next((m for m in state["members"] if m["id"]==target_member_id),None)
        if not target:
            raise HTTPException(404,"角色不存在")
        c=characters.migrate_character(target["character"])
        sheet=characters.character_sheet(c)
        package=state.get("campaign",{}).get("package") or state.get("campaign_package") or {}
        sheet["available_custom_skills"]=[card for card in package.get("skills",{}).values() if card["effect"]!="check"]
        sheet["equipped_custom_skill_ids"]=c.get("custom_skill_ids",[])
        setup = {"target_level": state.get("starting_level",1), "can_rebuild": state["status"] == "lobby" and target.get("can_rebuild",False), "ready": target.get("build_ready",True)}
        preview_character = copy.deepcopy(c)
        if state["status"] == "lobby" and c["level"] < setup["target_level"]:
            preview_character["milestone_credits"] = max(1, c.get("milestone_credits",0))
        return {"character":sheet,"setup":setup,"advancement":characters.level_up_preview(preview_character),"owner":viewer==target_member_id and store.owns_active_hero(room_id,target_member_id),"hero_id":target.get("hero_id") if viewer==target_member_id else None}

    @app.get("/api/rooms/{room_id}/events")
    async def events(room_id: str, request: Request, after: int = 0, cursor: str | None = None, authorization: str | None = Header(default=None)):
        viewer = auth(room_id, authorization, request)
        if after < 0:
            raise HTTPException(422, "事件序号不能为负数")
        state = get_state(room_id)
        bind_response_scope(request,state,viewer)
        try:
            return session_scope.history_page(state, viewer, after=after, cursor=cursor)
        except ValueError as exc:
            raise HTTPException(409, "历史记录范围已变化，请重新载入。") from exc

    @app.post("/api/rooms/{room_id}/commands")
    async def command(room_id: str, body: Command, request: Request, authorization: str | None = Header(default=None)):
        member_id = auth(room_id, authorization, request)
        throttle("command:" + member_id, 120)
        def matches_revision(state):
            context = state["member_contexts"][member_id]
            if body.expected_scene_instance_id is not None and context["scene_instance_id"] != body.expected_scene_instance_id:
                return False
            if body.expected_membership_epoch is not None and context["epoch"] != body.expected_membership_epoch:
                return False
            if len(state["scene_instances"]) > 1 and (body.expected_scene_instance_id is None or body.expected_membership_epoch is None):
                return False
            if body.type == "chat":
                return True
            if body.expected_action_revision is not None:
                return state["action_revision"] == body.expected_action_revision
            return state["version"] == body.expected_version
        # Validate payloads before performing any mutation.
        try:
            if body.type == "director_propose":
                payload = IntentPayload.model_validate(body.payload).model_dump()
            elif body.type in ("chat", "narrate"):
                payload = TextPayload.model_validate(body.payload).model_dump()
            elif body.type in ("action", "capability_propose"):
                payload = ActionPayload.model_validate(body.payload).model_dump()
            elif body.type == "set_interaction":
                payload = InteractionPayload.model_validate(body.payload).model_dump()
            elif body.type == "scene_edit":
                payload = SceneEditPayload.model_validate(body.payload).model_dump()
            elif body.type == "configure_character":
                payload = BuildPayload.model_validate(body.payload).model_dump()
            elif body.type in ("prepare_level_up","level_up","manage_spells","rest","equip_skills","director_resolve","director_cancel"):
                model={"prepare_level_up":LevelPayload,"level_up":LevelPayload,"manage_spells":SpellPayload,"rest":RestPayload,"equip_skills":SkillsPayload,"director_resolve":ProposalPayload,"director_cancel":ProposalPayload}[body.type]
                payload=model.model_validate(body.payload).model_dump()
            else:
                if body.payload:
                    raise ValueError("该命令不接受附加参数")
                payload = {}
        except ValueError as exc:
            raise HTTPException(422, "命令参数无效") from exc
        # Generation may take seconds; do not hold a database transaction or room lock.
        candidate = scene_storage.for_actor(get_state(room_id), member_id)
        if store.prior_command(room_id,member_id,body.command_id) is not None:
            return {"room":public(candidate,member_id,request),"replayed":True}
        # Successful legacy receipts replay above. New roleplay declarations use
        # exactly the same planning/confirmation boundary as the action form.
        if body.type == "narrate":
            body = body.model_copy(update={"type": "director_propose"})
        if body.type == "action":
            body = body.model_copy(update={"type": "capability_propose"})
        try:
            play_policy.validate_command(candidate, body.type)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not matches_revision(candidate):
            raise HTTPException(409,"房间已更新，请同步后重试")
        if body.type == "start" and candidate["host_id"] != member_id:
            raise HTTPException(403,"只有房主可以开始冒险")
        if body.type == "start" and any(not m.get("build_ready",True) for m in candidate["members"]):
            raise HTTPException(409,"所有玩家须先完成起始等级构筑")
        # Completed retries, malformed payloads and stale scopes return above
        # without cancelling work that began after the original command.
        if body.type=='chat':
            return await execute_prepared(room_id,body,request,authorization,member_id,payload,candidate,matches_revision)
        # Pure rules use no model permit and may finish while a remote
        # background call is pending. PlayerDM preempts only when a real model
        # call needs realtime capacity; invalid actions cannot burn plot jobs.
        with scheduler.player_activity(preempt=False):
            return await execute_prepared(room_id,body,request,authorization,member_id,payload,candidate,matches_revision)

    async def execute_prepared(room_id,body,request,authorization,member_id,payload,candidate,matches_revision):
        proposed = None
        if body.type in ("director_propose", "capability_propose"):
            if candidate["status"] != "playing":
                raise HTTPException(409,"请先开始或恢复冒险")
            try:
                if body.type == 'capability_propose':
                    from .world_combat import validate_read_set
                    try:
                        if payload['action_id']!='story-cancel':
                            validate_read_set(candidate)
                    except ValueError as exc:
                        raise HTTPException(409, str(exc)) from exc
                    proposed = director.propose_selected(candidate, member_id, payload['action_id'], payload.get('target_id'),
                                                         {key:value for key,value in payload.items() if key not in {'action_id','target_id'}})
                else:
                    throttle("director:"+member_id,12)
                    proposed = await director.propose(dm,copy.deepcopy(candidate),member_id,payload["text"], skill_id=payload.get("skill_id"))
            except ValueError as exc:
                raise HTTPException(422,str(exc)) from exc
        pending = None
        async with locks[room_id]:
            # Recheck after a potentially long model call; revoked sessions cannot commit.
            if auth(room_id, authorization, request) != member_id:
                raise HTTPException(403, "房间身份已变化")
            prior = store.prior_command(room_id, member_id, body.command_id)
            if prior is not None:
                # Current snapshot avoids regressing UI after a successfully retried write.
                return {"room": public(get_state(room_id), member_id, request), "replayed": True}
            state = scene_storage.for_actor(get_state(room_id), member_id)
            if not matches_revision(state):
                raise HTTPException(409, "房间已更新，请同步后重试")
            from .world_combat import validate_read_set, enter_place
            try:
                stored = state.get('director',{}).get('proposals',{}).get(member_id)
                cancellation = (proposed or {}).get('proposal') if body.type=='capability_propose' else stored if body.type=='director_resolve' and stored and stored['id']==payload['proposal_id'] else None
                cancel_only = bool(cancellation and cancellation['decision']['kind']=='capability'
                                   and cancellation['decision']['action_id']=='story-cancel'
                                   and cancellation['plan']['executor']=='story_cancel')
                if not cancel_only and body.type not in {"chat", "narrate", "director_propose", "director_cancel", "pause", "resume"}:
                    validate_read_set(state)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            member = next(m for m in state["members"] if m["id"] == member_id)
            previous = state["version"]
            before_action = copy.deepcopy(state)
            if body.type in ("start", "pause", "resume", "set_interaction", "scene_edit") and member_id != state["host_id"]:
                raise HTTPException(403, "只有房主可以执行此操作")
            if body.type == "start":
                if state["status"] != "lobby":
                    raise HTTPException(409, "冒险已经开始")
                if any(not m.get("build_ready",True) for m in state["members"]):
                    raise HTTPException(409,"所有玩家须先完成起始等级构筑")
                state["status"] = "playing"
                if state.get("campaign_package"):
                    for player in state["members"]:
                        pool = [sid for sid in state["campaign_package"]["scenario"].get("skill_ids",[]) if state["campaign_package"]["skills"][sid]["effect"] != "check"]
                        chosen = player["character"].get("custom_skill_ids")
                        player["character"]["custom_skill_ids"] = pool[:4] if chosen is None else [sid for sid in chosen if sid in pool][:4]
                        if state['campaign_package']['scenario']['id']=='book-eight-beacons' and 'beacon-hammer' not in player['character']['custom_skill_ids']:
                            player['character']['custom_skill_ids']=player['character']['custom_skill_ids'][:3]+['beacon-hammer']
                    append_rule_events(state, campaign.start_campaign(state, state["campaign_package"]), member_id)
                    if state.get("completed"):
                        state["status"] = "finished"
                event(state, "system", "冒险开始。每一个选择，都将留下回声。")
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
            elif body.type in ("director_propose", "capability_propose"):
                if director.public_proposal(proposed["proposal"], state)["stale"]:
                    raise HTTPException(409, "场景或交流范围已变化，请重新提出行动。")
                state.setdefault("director",{}).setdefault("proposals",{})[member_id]=proposed["proposal"]
                event(state,"intent",proposed['proposal']['intent'],member["name"])
                event(state,"dm",proposed["text"],source=proposed["source"],
                      adjudication_pending=True, proposal_id=proposed["proposal"]["id"])
            elif body.type == "director_cancel":
                own = state.get("director",{}).get("proposals",{}).get(member_id)
                if not own or own["id"] != payload["proposal_id"]:
                    raise HTTPException(409,"提案已变化，请刷新后重试")
                state["director"]["proposals"].pop(member_id,None)
            elif body.type == "director_resolve":
                if state["status"] != "playing":
                    raise HTTPException(409,"请先恢复冒险")
                proposal=state.get("director",{}).get("proposals",{}).get(member_id)
                if not proposal or proposal["id"] != payload["proposal_id"]:
                    raise HTTPException(409,"提案不存在或已被处理，请重新表达行动")
                old_scene = state.get('scene_id')
                try:
                    append_rule_events(state,director.resolve(state,member_id,proposal),member_id)
                except (ValueError,KeyError) as exc:
                    raise HTTPException(422,str(exc)) from exc
                state["director"]["proposals"].pop(member_id,None)
                if proposal["decision"]["kind"] == 'capability' and state.get('scene_id') != old_scene:
                    pending = 'scene'
                elif proposal["decision"]["kind"] in {"free_action", "capability"} and (proposal.get('plan') or {}).get('executor') not in {'story_route','story_cancel'} and dm.configured and not state.get("dm_pending"):
                    pending = "narrate"
                if state.get("completed"):
                    state["status"]="finished"
            elif body.type in ("configure_character", "prepare_level_up"):
                if state["status"] != "lobby":
                    raise HTTPException(409,"起始构筑只能在开团前调整")
                if not store.owns_active_hero(room_id,member_id):
                    raise HTTPException(409,"该角色已进入另一场冒险")
                target_level = state.get("starting_level",1)
                try:
                    if body.type == "configure_character":
                        if not member.get("can_rebuild",False):
                            raise HTTPException(409,"已有角色保留历史构筑，请逐级补足等级")
                        updated = character_builds.build_character(payload["build"],target_level)
                    else:
                        if member["character"].get("level",1) >= target_level:
                            raise HTTPException(409,"已达到本桌起始等级")
                        updated = character_builds.prepare_level(member["character"],payload["choices"])
                    member["character"] = updated
                    member["name"] = updated["name"]
                    member["character_id"] = updated["class_id"]
                    member["build_ready"] = updated["level"] == target_level
                    event(state,"character",f"{member['name']} 已确认 {updated['level']} 级构筑。",member["name"])
                except (ValueError,KeyError) as exc:
                    raise HTTPException(422,str(exc)) from exc
            elif body.type in ("level_up","manage_spells","rest","equip_skills"):
                if body.type == "level_up" and state["status"] == "lobby" and "starting_level" in state:
                    raise HTTPException(409,"开团前请通过起始等级流程确认升级")
                if state.get("combat",{}) and state["combat"].get("active"):
                    raise HTTPException(409,"请在战斗结束后管理成长、准备能力或休息")
                if not store.owns_active_hero(room_id,member_id):
                    raise HTTPException(409,"该角色已进入另一场冒险，请在那里管理成长")
                c=characters.migrate_character(member["character"])
                try:
                    if body.type=="level_up":
                        mode=state.get("progression",{}).get("mode","xp")
                        if mode=="milestone" and c.get("milestone_credits",0)<1:
                            raise ValueError("尚未获得升级里程碑")
                        updated=characters.level_up(c,payload["choices"],progression=mode)
                        if mode=="milestone": updated["milestone_credits"]=c.get("milestone_credits",0)-1
                        member["character"]=updated
                        event(state,"level_up",f"{member['name']} 升至 {updated['level']} 级。",member["name"])
                    elif body.type=="manage_spells":
                        member["character"]=characters.manage_spells(c,payload)
                        event(state,"character","更新了准备法术。",member["name"])
                    elif body.type=="equip_skills":
                        skills=payload["skill_ids"]
                        package=state.get("campaign",{}).get("package") or state.get("campaign_package") or {}
                        pool=package.get("skills",{})
                        if len(set(skills))!=len(skills) or any(sid not in pool or pool[sid]["effect"]=="check" for sid in skills):
                            raise ValueError("请选择剧情提供的个人能力卡，不能重复或装备场景检定")
                        c["custom_skill_ids"]=skills
                        member["character"]=c
                        event(state,"character","调整了个人剧情能力。剩余次数不会因重新装备而恢复。",member["name"])
                    else:
                        clock=state.setdefault("progression",{"mode":"xp","world_minutes":0})
                        if payload["kind"]=="long":
                            if member_id!=state["host_id"]:
                                raise HTTPException(403,"由房主发起全队长休")
                            now=clock.get("world_minutes",0)
                            if now-clock.get("last_long_rest_end",-1440)<1440:
                                raise ValueError("游戏时间24小时内只能受益于一次长休")
                            resting = [p for p in state["members"] if not p["character"].get("dead") and store.owns_active_hero(room_id,p["id"])]
                            if any(now-p["character"].get("last_long_rest_end",-1440)<1440 for p in resting):
                                raise ValueError("队伍中有人在游戏时间24小时内已经长休；冷却会随角色跨冒险保留")
                            for player in resting:
                                player["character"]=characters.long_rest(player["character"])
                                player["character"]["last_long_rest_end"]=now+480
                            clock["world_minutes"]=now+480
                            clock["last_long_rest_end"]=now+480
                            event(state,"rest","队伍完成8小时长休，恢复生命与相应职业资源。",member["name"])
                        else:
                            member["character"]=characters.short_rest(c,payload["hit_dice"])
                            clock["world_minutes"]=clock.get("world_minutes",0)+60
                            event(state,"rest",f"{member['name']} 完成1小时短休，消耗 {payload['hit_dice']} 枚生命骰。",member["name"])
                except (ValueError,KeyError) as exc:
                    raise HTTPException(422,str(exc)) from exc
            else:
                if body.type != 'end_turn':
                    raise HTTPException(422, '未知游戏行动入口')
                if state["status"] != "playing":
                    raise HTTPException(409, "当前不能执行游戏行动")
                old_scene = state.get("scene_id")
                action_id = "end_turn"
                try:
                    executor = campaign if state.get("campaign") else rules
                    action_events = executor.apply_action(state, member_id, action_id)
                except (ValueError, KeyError) as exc:
                    raise HTTPException(422, str(exc)) from exc
                append_rule_events(state, action_events, member_id)
                if state.get("completed"):
                    state["status"] = "finished"
                elif state.get("scene_id") != old_scene:
                    pending = "scene"
                elif dm.configured and not state.get("dm_pending"):
                    pending = "narrate"
            state["version"] += 1
            if body.type != "chat":
                state["action_revision"] += 1
            if body.type in ("action","end_turn","director_resolve"):
                append_rule_events(state,progression.award(state,before_action),member_id)
            if pending:
                request_id = uuid.uuid4().hex
                state["dm_pending"] = request_id
            response = {"room": public(state, member_id, request)}
            store.save(state, previous, (member_id, body.command_id, {"version": state["version"]}))
        if body.type in {'start','director_resolve','end_turn'}:
            coordinator.refresh(room_id,member_id)
            response = {"room": public(get_state(room_id),member_id,request)}
        if pending:
            await add_dm_response(room_id, state["action_revision"], request_id, pending, copy.deepcopy(state["scene"]),
                                  state["mode"], state["theme"], payload.get("text", "请依据刚刚确认的结果描述后果，并建议下一步合法行动。"), play_policy.confirmed_events(session_scope.common_memory(state, [m["id"] for m in state["members"]]))[-8:], actions_for(state, member_id), "assisted", session_scope.audience_key(state), state["_scene_execution_view"])
            response = {"room": public(get_state(room_id), member_id, request)}
        else:
            await broadcast(room_id)
        auth(room_id, authorization, request)
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
            if isinstance(token, str) and len(token) <= 200:
                peer_tokens[ws] = token
            member_id = socket_member(ws, room_id)
            if not member_id:
                await ws.close(code=1008, reason="无效成员凭证")
                return
            peers[room_id][ws] = member_id
            await broadcast(room_id)
            while True:
                if socket_member(ws, room_id) != member_id:
                    await ws.close(code=1008, reason="会话已失效")
                    break
                try:
                    message = await asyncio.wait_for(ws.receive_text(), timeout=2)
                except asyncio.TimeoutError:
                    continue
                if socket_member(ws, room_id) != member_id:
                    await ws.close(code=1008, reason="会话已失效")
                    break
                if len(message) > 1024:
                    await ws.close(code=1009)
                    break
                if message == "ping":
                    await ws.send_json({"type": "pong"})
        except HTTPException:
            try:
                await ws.close(code=1008, reason="账号会话已失效")
            except Exception:
                pass
        except (WebSocketDisconnect, asyncio.TimeoutError, ValueError, RuntimeError):
            pass
        finally:
            peers[room_id].pop(ws, None)
            peer_tokens.pop(ws, None)
            if peers[room_id]:
                await broadcast(room_id)

    # A crashed process cannot still own an outstanding narrator request.
    with store.connect() as db:
        for row in db.execute("SELECT id,state FROM rooms").fetchall():
            from .scene_storage import unpack as unpack_scene, pack as pack_scene
            state = unpack_scene(json.loads(row["state"]))
            changed = False
            for sid in state["scene_instances"]:
                current = scene_storage.for_scene(state, sid)
                if not current.get("dm_pending"):
                    continue
                current["dm_pending"] = None
                current["version"] += 1
                event(current, "system", "服务已恢复；上一次未完成的 DM 请求已取消，可继续行动。")
                state = unpack_scene(pack_scene(current))
                changed = True
            if changed:
                db.execute("UPDATE rooms SET state=?,version=? WHERE id=?",
                           (json.dumps(pack_scene(state), ensure_ascii=False), state["version"], state["id"]))

    frontend = Path(__file__).resolve().parent.parent / "frontend"
    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


app = create_app()
