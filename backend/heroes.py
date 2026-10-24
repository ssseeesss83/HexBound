"""Account-owned persistent characters and the read-only rules compendium API."""
from __future__ import annotations
import json
import uuid
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from .accounts import require_user


class HeroInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NewHero(HeroInput):
    class_id: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=32)
    choices: dict = Field(default_factory=dict)
    build: dict | None = None
    starting_level: int = Field(default=1, ge=1, le=20, strict=True)


class EditHero(HeroInput):
    expected_version: int = Field(ge=1)
    operation: Literal["level_up", "spells", "rebuild"]
    choices: dict = Field(default_factory=dict)
    build: dict | None = None
    starting_level: int = Field(default=1, ge=1, le=20, strict=True)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def can_rebuild(row, db, character):
    """An unbound, unused build can be revised; adventure state cannot be reset."""
    from . import characters
    from .character_builds import finalize
    if row["active_room_id"] or character.get("ever_adventured"):
        return False
    # A historical room reference remains disqualifying even after manual unbind.
    history = db.execute("SELECT 1 FROM rooms, json_each(rooms.state, '$.members') AS member WHERE json_extract(member.value, '$.hero_id')=? LIMIT 1", (row["id"],)).fetchone()
    if history:
        return False
    try:
        if character.get("build"):
            original = finalize(character["build"], character.get("starting_level", 1))
        else:
            if character.get("level", 1) != 1 or character.get("growth_history"):
                return False
            choices = {key: character[key] for key in ("skills", "expertise", "subclass_id", "cantrips", "known_spells", "prepared_spells", "spellbook") if key in character}
            original = characters.create_character(character["class_id"], character["name"], choices,
                abilities=character["abilities"] if character.get("ability_generation") == "custom-house-rule" else None,
                profile=character.get("profile"))
    except (ValueError, KeyError, TypeError):
        return False
    fields = ("level", "xp", "milestone_credits", "abilities", "hp", "max_hp", "resources", "spell_slots", "pact_slots", "hit_dice", "growth_history", "dead", "stable", "death_successes", "death_failures", "potions")
    return not character.get("conditions") and all(character.get(key) == original.get(key) for key in fields)


def hero_view(row, db):
    from . import characters
    character = characters.migrate_character(json.loads(row["payload"]))
    active = row["active_room_id"]
    room = db.execute("SELECT state FROM rooms WHERE id=?", (active,)).fetchone() if active else None
    room_status = json.loads(room["state"])["status"] if room else None
    return {"id": row["id"], "version": row["version"], "character": characters.character_sheet(character),
            "active_room_id": active, "active_room_status": room_status,
            "available": not room or room_status == "finished", "advancement": characters.level_up_preview(character),
            "can_rebuild": can_rebuild(row, db, character), "build": character.get("build")}


def create_hero_router(store):
    router = APIRouter()

    @router.get("/api/my/characters")
    async def list_heroes(request: Request):
        user = require_user(request)
        with store.connect() as db:
            rows = db.execute("SELECT * FROM heroes WHERE owner_id=? ORDER BY rowid DESC LIMIT 100", (user["id"],)).fetchall()
            return {"items": [hero_view(row, db) for row in rows]}

    @router.post("/api/my/characters", status_code=201)
    async def new_hero(body: NewHero, request: Request):
        from . import characters
        user = require_user(request)
        try:
            if body.build is not None:
                from .character_builds import finalize
                if body.choices or (body.class_id is not None and body.class_id != body.build.get("class_id")) or (body.name is not None and body.name != body.build.get("name")):
                    raise ValueError("build路径不能提交冲突的职业、姓名或独立choices")
                character = finalize(body.build, body.starting_level)
            else:
                if body.starting_level != 1:
                    raise ValueError("高等级创建必须提交完整逐级build")
                if body.class_id is None or body.name is None:
                    raise ValueError("创建角色需提供职业和姓名，或完整build")
                character = characters.create_character(body.class_id, body.name, body.choices)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM heroes WHERE owner_id=?", (user["id"],)).fetchone()[0] >= 100:
                raise HTTPException(409, "每个账号最多保留100名角色")
            hero_id = uuid.uuid4().hex
            db.execute("INSERT INTO heroes(id,owner_id,version,payload,active_room_id) VALUES(?,?,1,?,NULL)", (hero_id, user["id"], encode(character)))
            return hero_view(db.execute("SELECT * FROM heroes WHERE id=?", (hero_id,)).fetchone(), db)

    @router.get("/api/my/characters/{hero_id}")
    async def get_hero(hero_id: str, request: Request):
        user = require_user(request)
        with store.connect() as db:
            row = db.execute("SELECT * FROM heroes WHERE id=? AND owner_id=?", (hero_id,user["id"])).fetchone()
            if not row:
                raise HTTPException(404, "角色不存在")
            return hero_view(row,db)

    @router.patch("/api/my/characters/{hero_id}")
    async def edit_hero(hero_id: str, body: EditHero, request: Request):
        from . import characters
        user = require_user(request)
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM heroes WHERE id=? AND owner_id=?", (hero_id,user["id"])).fetchone()
            if not row:
                raise HTTPException(404, "角色不存在")
            if row["version"] != body.expected_version:
                raise HTTPException(409, "角色已更新，请刷新后重试")
            # Finished characters remain bound until their next adventure, avoiding
            # two competing authoritative copies in room and vault.
            if row["active_room_id"]:
                raise HTTPException(409, "请进入角色所属冒险管理成长和法术；可在新冒险继续使用已结束冒险的角色")
            character = characters.migrate_character(json.loads(row["payload"]))
            try:
                if body.operation != "rebuild" and (body.build is not None or "starting_level" in body.model_fields_set):
                    raise ValueError("build与starting_level仅用于rebuild")
                if body.operation == "rebuild":
                    from .character_builds import finalize
                    if not can_rebuild(row, db, character):
                        raise HTTPException(409, "仅未绑定且从未冒险或成长的原始角色可重建")
                    if body.build is None or body.choices:
                        raise ValueError("重建需完整build，不能混用独立choices")
                    character = finalize(body.build, body.starting_level)
                elif body.operation == "level_up":
                    character = characters.level_up(character, body.choices)
                else:
                    character = characters.manage_spells(character, body.choices)
            except (ValueError, KeyError) as exc:
                raise HTTPException(422, str(exc)) from exc
            db.execute("UPDATE heroes SET payload=?,version=version+1 WHERE id=?", (encode(character),hero_id))
            return hero_view(db.execute("SELECT * FROM heroes WHERE id=?", (hero_id,)).fetchone(),db)

    @router.get("/api/compendium")
    async def compendium_list(kind: Literal["classes","skills","spells","features","subclasses"] = "classes",
                              q: str = Query(default="",max_length=100), class_id: str | None = None,
                              level: int | None = Query(default=None,ge=0,le=20), page: int = Query(default=1,ge=1),
                              page_size: int = Query(default=50,ge=1,le=100)):
        from . import compendium
        from .rules_context import current_view
        compendium = current_view() or compendium
        tables = {"classes":compendium.CLASSES,"skills":compendium.SKILLS,"spells":compendium.SPELLS,
                  "features":compendium.FEATURES,"subclasses":compendium.SUBCLASSES}
        values=[]
        for key, item in tables[kind].items():
            if q and q.casefold() not in (item.get("name","")+item.get("name_zh","")+key).casefold():
                continue
            refs = item.get("classes",[]) or ([item["class"]] if item.get("class") else [])
            if class_id and class_id not in [x.get("index",x.get("id")) if isinstance(x,dict) else x for x in refs] and not (kind=="classes" and key==class_id):
                continue
            if level is not None and item.get("level") != level:
                continue
            view = {"id":key,"name":item.get("name_zh") or item.get("name",key),"name_en":item.get("name",key),
                    "level":item.get("level"),"description":item.get("desc",[]),"classes":refs}
            if kind in ("spells","features"):
                detail = compendium.lookup(kind,key)
                view.update(automation_status=detail["automation_status"],automation_reason=detail["automation_reason"])
            values.append(view)
        return {"items":values[(page-1)*page_size:page*page_size],"total":len(values),"page":page,"page_size":page_size,"ruleset":"SRD 5.1 / 2014"}

    @router.get("/api/compendium/{kind}/{item_id}")
    async def compendium_detail(kind: str, item_id: str):
        from . import compendium
        from .rules_context import current_view
        compendium = current_view() or compendium
        tables={"classes":compendium.CLASSES,"skills":compendium.SKILLS,"spells":compendium.SPELLS,
                "features":compendium.FEATURES,"subclasses":compendium.SUBCLASSES}
        if kind not in tables or item_id not in tables[kind]:
            raise HTTPException(404,"规则条目不存在")
        return compendium.lookup(kind,item_id)

    return router
