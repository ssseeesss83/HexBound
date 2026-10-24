"""Small, transaction-safe SQLite persistence. Intended for one app worker."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from copy import deepcopy
from pathlib import Path
from contextlib import contextmanager

from .maintenance import SCHEMA_VERSION, check_database_version, backup_database
from .scene_storage import pack as pack_scene, unpack as unpack_scene, STORAGE_VERSION as SCENE_STORAGE_VERSION


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if Path(path).is_file():
            with self.connect() as db:
                version = check_database_version(db)
                populated = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rooms'").fetchone()
            if version < SCHEMA_VERSION and populated:
                backup_database(path, Path(path).parent / "backups" / f"pre-schema-{SCHEMA_VERSION}-{uuid.uuid4().hex}.zip")
        with self.connect() as db:
            check_database_version(db)
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS rooms (
                    id TEXT PRIMARY KEY, invite_code TEXT NOT NULL UNIQUE,
                    version INTEGER NOT NULL, state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS members (
                    id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id),
                    token_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS members_room ON members(room_id);
                CREATE TABLE IF NOT EXISTS heroes (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                    version INTEGER NOT NULL, payload TEXT NOT NULL,
                    active_room_id TEXT
                );
                CREATE INDEX IF NOT EXISTS heroes_owner ON heroes(owner_id);
                CREATE TABLE IF NOT EXISTS commands (
                    room_id TEXT NOT NULL, member_id TEXT NOT NULL,
                    command_id TEXT NOT NULL, response TEXT NOT NULL,
                    PRIMARY KEY(room_id, member_id, command_id)
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(members)")}
            if "user_id" not in columns:
                db.execute("ALTER TABLE members ADD COLUMN user_id TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS members_room_user ON members(room_id,user_id) WHERE user_id IS NOT NULL")
            db.execute("CREATE TABLE IF NOT EXISTS rules_packages (version TEXT PRIMARY KEY, ruleset_id TEXT NOT NULL, digest TEXT NOT NULL, metadata TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS rules_records (package_version TEXT NOT NULL REFERENCES rules_packages(version), kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(package_version,kind,id))")
            db.execute("CREATE TABLE IF NOT EXISTS rules_activation (ruleset_id TEXT PRIMARY KEY, package_version TEXT NOT NULL REFERENCES rules_packages(version))")
            db.execute("CREATE TABLE IF NOT EXISTS group_plans (id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id), actor_id TEXT NOT NULL, created_at REAL NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS rules_documents (package_version TEXT NOT NULL REFERENCES rules_packages(version), page INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(package_version,page))")
            from .session_scope import initialize
            from .world_environment import migrate
            from .world_combat import migrate as migrate_combat
            for row in db.execute("SELECT id,state FROM rooms").fetchall():
                payload = json.loads(row["state"])
                state = unpack_scene(payload)
                if "text_scope" not in state or "action_revision" not in state or payload.get("scene_storage_version") != SCENE_STORAGE_VERSION or payload.get("world_environment_version") != 1 or payload.get("world_combat_version") != 1:
                    initialize(state)
                    canonical = migrate_combat(migrate(pack_scene(state)))
                    db.execute("UPDATE rooms SET state=? WHERE id=?", (json.dumps(canonical, ensure_ascii=False), row["id"]))
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, state: dict, member_id: str, token: str, user_id: str | None = None):
        from .session_scope import initialize
        initialize(state)
        from .rules_identity import RULESET_ID, PACKAGE_VERSION, ENGINE_PROFILE
        from .rules_context import active_version
        state.setdefault("ruleset_id", RULESET_ID)
        state.setdefault("rules_package_version", active_version())
        state.setdefault("engine_profile", ENGINE_PROFILE)
        if state.get("campaign_package"):
            state["campaign_package"].setdefault("rules_package_version", state["rules_package_version"])
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._bind_hero(db, state, state["members"][0], user_id)
            from .world_environment import migrate
            from .world_combat import migrate as migrate_combat
            migrated = unpack_scene(migrate_combat(migrate(pack_scene(state))))
            state.clear()
            state.update(migrated)
            db.execute("INSERT INTO rooms VALUES (?, ?, ?, ?)",
                       (state["id"], state["invite_code"], state["version"], json.dumps(pack_scene(state), ensure_ascii=False)))
            db.execute("INSERT INTO members (id,room_id,token_hash,user_id) VALUES (?, ?, ?, ?)", (member_id, state["id"], token_hash(token), user_id))

    def get(self, room_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT state FROM rooms WHERE id=?", (room_id,)).fetchone()
        return unpack_scene(json.loads(row["state"])) if row else None

    def find_invite(self, invite: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT id FROM rooms WHERE invite_code=?", (invite,)).fetchone()
        return row["id"] if row else None

    def authenticate(self, room_id: str, token: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT id FROM members WHERE room_id=? AND token_hash=? AND user_id IS NULL",
                             (room_id, token_hash(token))).fetchone()
        return row["id"] if row else None

    def account_member(self, room_id: str, user_id: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT id FROM members WHERE room_id=? AND user_id=?", (room_id, user_id)).fetchone()
        return row["id"] if row else None

    def account_rooms(self, user_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT r.state,m.id AS member_id FROM rooms r JOIN members m ON m.room_id=r.id WHERE m.user_id=? ORDER BY r.rowid DESC LIMIT 100", (user_id,)).fetchall()
        result = []
        for row in rows:
            state = unpack_scene(json.loads(row["state"]))
            from .scene_storage import for_actor
            state = for_actor(state, row["member_id"])
            member = next((m for m in state["members"] if m["id"] == row["member_id"]), {})
            result.append({"room_id": state["id"], "room_name": state["name"], "player_name": member.get("name", ""), "status": state["status"], "mode": state["mode"], "member_id": row["member_id"], "host": state["host_id"] == row["member_id"], "party_size": len(state["members"]), "scene_title": state.get("scene", {}).get("title", ""), "invite_code": state["invite_code"]})
        return result

    def claim(self, room_id: str, token: str, user_id: str) -> str:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id,user_id FROM members WHERE room_id=? AND token_hash=?", (room_id, token_hash(token))).fetchone()
            if not row or row["user_id"] is not None:
                raise ValueError("旧成员凭证无效或席位已经认领")
            if db.execute("SELECT 1 FROM members WHERE room_id=? AND user_id=?", (room_id, user_id)).fetchone():
                raise ValueError("此账号已在房间中拥有席位")
            updated = db.execute("UPDATE members SET user_id=? WHERE id=? AND user_id IS NULL", (user_id, row["id"])).rowcount
            if updated != 1:
                raise ValueError("此席位已经认领")
            state_row = db.execute("SELECT state FROM rooms WHERE id=?", (room_id,)).fetchone()
            state = unpack_scene(json.loads(state_row["state"]))
            member = next((m for m in state.get("members",[]) if m["id"] == row["id"]), None)
            if member is not None:
                self._bind_hero(db,state,member,user_id)
            state["version"] = state.get("version",0) + 1
            db.execute("UPDATE rooms SET state=?,version=? WHERE id=?", (json.dumps(pack_scene(state),ensure_ascii=False),state["version"],room_id))
            return row["id"]

    def join(self, room_id: str, member: dict, token: str, user_id: str | None = None) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM rooms WHERE id=?", (room_id,)).fetchone()
            if not row:
                raise ValueError("房间不存在")
            state = unpack_scene(json.loads(row["state"]))
            if user_id and db.execute("SELECT 1 FROM members WHERE room_id=? AND user_id=?", (room_id, user_id)).fetchone():
                return state
            if state["status"] != "lobby":
                raise ValueError("冒险已开始，无法加入新角色")
            if len(state["members"]) >= 6:
                raise ValueError("六席已满，请加入其他房间")
            self._bind_hero(db, state, member, user_id)
            state["members"].append(member)
            from .session_scope import add_member
            add_member(state, member["id"])
            state["action_revision"] += 1
            state["version"] += 1
            db.execute("INSERT INTO members (id,room_id,token_hash,user_id) VALUES (?, ?, ?, ?)", (member["id"], room_id, token_hash(token), user_id))
            db.execute("UPDATE rooms SET state=?, version=? WHERE id=?",
                       (json.dumps(pack_scene(state), ensure_ascii=False), state["version"], room_id))
        return state

    def prior_command(self, room_id: str, member_id: str, command_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT response FROM commands WHERE room_id=? AND member_id=? AND command_id=?",
                             (room_id, member_id, command_id)).fetchone()
        return json.loads(row["response"]) if row else None

    def prepare_scene_merge(self, room_id, actor, source, target):
        """Internal table operation; keep its read-set on the server."""
        from .world_state import prepare_merge, WorldConflict
        room = self.get(room_id)
        if not room or room.get("host_id") != actor:
            raise WorldConflict("只有房主可以准备桌务合队")
        return prepare_merge(pack_scene(room), source, target)

    def commit_scene_merge(self, room_id, actor, plan, command_id):
        """Membership, revocation, one table event and receipt commit together.

        No public route calls this until place/entity/runtime integration passes.
        """
        from .world_state import commit_merge, WorldConflict, MergePlan
        from .session_scope import stamp_event
        if not isinstance(plan, MergePlan):
            raise WorldConflict("合队需要服务端保存的计划")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM rooms WHERE id=?", (room_id,)).fetchone()
            room = json.loads(row["state"]) if row else None
            if not room or room.get("host_id") != actor:
                raise WorldConflict("只有房主可以提交桌务合队")
            prior = db.execute("SELECT response FROM commands WHERE room_id=? AND member_id=? AND command_id=?", (room_id, actor, command_id)).fetchone()
            if prior:
                response = json.loads(prior["response"])
                if response.get("operation") != "scene_merge" or response.get("source") != plan.source or response.get("target") != plan.target:
                    raise WorldConflict("命令 ID 已用于其他操作")
                return {**response, "replayed": True}
            receipt = commit_merge(room, plan, command_id)
            room["version"] += 1
            item = {"id": len(room["events"]) + 1, "kind": "system", "actor_name": "DM", "text": "小队已在安全检查点合队。"}
            stamp_event(room, item, channel=room["scene_instances"][plan.target]["channel_id"])
            room["events"].append(item)
            response = {**receipt, "operation": "scene_merge", "version": room["version"]}
            db.execute("UPDATE rooms SET state=?,version=? WHERE id=?", (json.dumps(room, ensure_ascii=False), room["version"], room_id))
            db.execute("INSERT INTO commands VALUES (?,?,?,?)", (room_id, actor, command_id, json.dumps(response, ensure_ascii=False)))
            return response

    def save(self, state: dict, previous_version: int, receipt: tuple[str, str, dict] | None = None):
        from .session_scope import initialize
        initialize(state)
        from .world_environment import prepare_save
        prepare_save(state)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._sync_heroes(db, state)
            changed = db.execute("UPDATE rooms SET state=?, version=? WHERE id=? AND version=?",
                                 (json.dumps(pack_scene(state), ensure_ascii=False), state["version"], state["id"], previous_version)).rowcount
            if changed != 1:
                raise ValueError("房间已更新，请刷新后重试")
            if receipt:
                member_id, command_id, response = receipt
                db.execute("INSERT INTO commands VALUES (?, ?, ?, ?)",
                           (state["id"], member_id, command_id, json.dumps(response, ensure_ascii=False)))

    def _bind_hero(self, db, state, member, user_id, *, mark_build=True):
        from .rules_identity import LEGACY_PACKAGE
        def require_same_package(character):
            if character.get("rules_package_version", LEGACY_PACKAGE) != state.get("rules_package_version", LEGACY_PACKAGE):
                raise ValueError("角色与房间规则版本不同，请先完成显式迁移后再加入。")

        require_same_package(member["character"])
        target_level = state.get("starting_level", 1)

        def mark_template():
            if mark_build:
                member.update(build_ready=member["character"].get("level", 1) >= target_level,
                              can_rebuild=True, character_origin="template")

        if not user_id:
            if member.get("hero_id"):
                raise ValueError("请登录后使用永久角色")
            mark_template()
            return
        hero_id = member.get("hero_id")
        if hero_id:
            hero = db.execute("SELECT * FROM heroes WHERE id=? AND owner_id=?", (hero_id,user_id)).fetchone()
            if not hero:
                raise ValueError("角色不存在或不属于此账号")
            if hero["active_room_id"] and hero["active_room_id"] != state["id"]:
                old = db.execute("SELECT state FROM rooms WHERE id=?", (hero["active_room_id"],)).fetchone()
                if old and json.loads(old["state"])["status"] != "finished":
                    raise ValueError("该角色仍在另一场冒险中，请完成后再加入新冒险")
            canonical = deepcopy(json.loads(hero["payload"]))
            require_same_package(canonical)
            level = canonical.get("level", 1)
            if level > target_level:
                raise ValueError(f"角色等级 {level} 高于冒险起始等级 {target_level}，无法加入")
            member["character"] = canonical
            if mark_build:
                member.update(build_ready=level == target_level, can_rebuild=False, character_origin="existing")
            member["character"]["name"] = member["name"]
            member["character_id"] = member["character"].get("class_id",member.get("character_id"))
            clock = state.setdefault("progression", {"mode":"xp","world_minutes":0})
            clock["world_minutes"] = max(clock.get("world_minutes",0),member["character"].get("world_minutes",0))
            db.execute("UPDATE heroes SET active_room_id=?,version=version+1 WHERE id=?", (state["id"],hero_id))
        else:
            if db.execute("SELECT COUNT(*) FROM heroes WHERE owner_id=?", (user_id,)).fetchone()[0] >= 100:
                raise ValueError("账号最多保留100名角色")
            mark_template()
            hero_id = uuid.uuid4().hex
            member["hero_id"] = hero_id
            db.execute("INSERT INTO heroes VALUES(?,?,1,?,?)", (hero_id,user_id,json.dumps(member["character"],ensure_ascii=False),state["id"]))

    def _sync_heroes(self, db, state):
        for member in state["members"]:
            context = state.get("member_contexts", {}).get(member["id"], {})
            sid = context.get("scene_instance_id", "scene-main")
            if sid == state.get("_scene_execution_view", "scene-main"):
                clock = state.get("progression", {})
            else:
                clock = state.get("scene_instances", {}).get(sid, {}).get("local", {}).get("progression_clock", {})
            member["character"]["world_minutes"] = max(member["character"].get("world_minutes",0),clock.get("world_minutes",0))
            hero_id = member.get("hero_id")
            if not hero_id:
                continue
            hero = db.execute("SELECT payload,active_room_id FROM heroes WHERE id=?", (hero_id,)).fetchone()
            if not hero or hero["active_room_id"] != state["id"]:
                continue
            payload = json.dumps(member["character"],ensure_ascii=False)
            if json.loads(hero["payload"]) != member["character"]:
                db.execute("UPDATE heroes SET payload=?,version=version+1 WHERE id=?", (payload,hero_id))

    def owns_active_hero(self, room_id, member_id):
        state = self.get(room_id)
        member = next((m for m in state["members"] if m["id"]==member_id), None) if state else None
        if not member or not member.get("hero_id"):
            return True  # legacy guest characters live solely in their room
        with self.connect() as db:
            row = db.execute("SELECT active_room_id FROM heroes WHERE id=?", (member["hero_id"],)).fetchone()
            return bool(row and row["active_room_id"] == room_id)

    def migrate_heroes(self):
        """Bind old account-owned seats once; preserve wounded characters and progress."""
        from .characters import migrate_character
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT id,state FROM rooms").fetchall():
                state = unpack_scene(json.loads(row["state"]))
                changed = False
                from .rules_identity import RULESET_ID, LEGACY_PACKAGE, ENGINE_PROFILE
                for key, value in (("ruleset_id", RULESET_ID), ("rules_package_version", LEGACY_PACKAGE), ("engine_profile", ENGINE_PROFILE)):
                    if key not in state:
                        state[key] = value
                        changed = True
                for member in state["members"]:
                    owner = db.execute("SELECT user_id FROM members WHERE id=?",(member["id"],)).fetchone()
                    migrated = migrate_character(member["character"])
                    if migrated != member["character"]:
                        member["character"] = migrated
                        changed = True
                    if owner and owner["user_id"] and not member.get("hero_id"):
                        self._bind_hero(db,state,member,owner["user_id"], mark_build="starting_level" in state)
                        changed = True
                if changed:
                    self._sync_heroes(db,state)
                    state["version"] += 1
                    db.execute("UPDATE rooms SET state=?,version=? WHERE id=?",(json.dumps(pack_scene(state),ensure_ascii=False),state["version"],row["id"]))

    def prepare_group_change(self, room_id, actor, operation, *, members=None, source=None, target=None, expected_scope=None):
        """Persist an opaque server plan; expose no foreign scene revisions."""
        from dataclasses import asdict
        import time
        from .scene_groups import prepare_split
        from .world_state import prepare_merge, WorldConflict
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM rooms WHERE id=?', (room_id,)).fetchone()
            room = json.loads(row['state']) if row else None
            if not room or room.get('host_id') != actor:
                raise WorldConflict('只有房主可以准备分队或合队')
            context = room['member_contexts'].get(actor)
            if not context:
                raise WorldConflict('房主没有主动场景')
            own_scene = room['scene_instances'][context['scene_instance_id']]
            current_scope = {'scene_instance_id':context['scene_instance_id'], 'membership_epoch':context['epoch'],
                             'action_revision':own_scene['local'].get('action_revision',0)}
            if expected_scope != current_scope:
                raise WorldConflict('当前场景已变化，请刷新后准备桌务操作')
            if operation == 'split':
                source = context['scene_instance_id']
                target = 'scene-' + uuid.uuid4().hex
                channel = 'group-' + uuid.uuid4().hex
                plan = prepare_split(room,source,target,channel,members)
                arguments = {'source':source,'target':target,'channel':channel,'members':list(plan.members)}
                moved = list(plan.members)
            elif operation == 'merge':
                plan = prepare_merge(room,source,target)
                arguments = {'source':source,'target':target}
                moved = [m['id'] for m in room['members'] if room['member_contexts'][m['id']]['scene_instance_id'] == source]
            else:
                raise WorldConflict('未知分组操作')
            plan_id = uuid.uuid4().hex
            payload = {'operation':operation,'arguments':arguments,'proof':asdict(plan)}
            db.execute('DELETE FROM group_plans WHERE created_at<? OR (room_id=? AND actor_id=?)', (now-1800,room_id,actor))
            db.execute('INSERT INTO group_plans VALUES(?,?,?,?,?)', (plan_id,room_id,actor,now,json.dumps(payload,ensure_ascii=False)))
            preview = {'plan_id':plan_id,'operation':operation,'source':source,'target':target,'members':moved,'expires_in_seconds':1800}
            if operation == 'split':
                candidates = [member['id'] for member in room['members'] if member['id'] in moved]
                old_leader = room['scene_instances'][source].get('leader_id')
                preview['new_leader_id'] = old_leader if old_leader in candidates else (actor if actor in candidates else candidates[0])
            return preview

    def commit_group_change(self, room_id, actor, plan_id, command_id):
        """Validate the saved read-set, then commit scope, events and receipt."""
        from dataclasses import asdict
        import time
        from .scene_groups import prepare_split, commit_split
        from .world_state import prepare_merge, commit_merge, WorldConflict
        from .session_scope import stamp_event
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM rooms WHERE id=?', (room_id,)).fetchone()
            room = json.loads(row['state']) if row else None
            if not room or room.get('host_id') != actor:
                raise WorldConflict('只有房主可以提交分队或合队')
            prior = db.execute('SELECT response FROM commands WHERE room_id=? AND member_id=? AND command_id=?', (room_id,actor,command_id)).fetchone()
            if prior:
                response = json.loads(prior['response'])
                if response.get('group_plan_id') != plan_id:
                    raise WorldConflict('命令 ID 已用于其他操作')
                return {**response,'replayed':True}
            saved = db.execute('SELECT * FROM group_plans WHERE id=? AND room_id=? AND actor_id=?', (plan_id,room_id,actor)).fetchone()
            if not saved or time.time()-saved['created_at'] > 1800:
                raise WorldConflict('分组计划不存在或已过期，请重新准备')
            payload = json.loads(saved['payload'])
            args = payload['arguments']
            if payload['operation'] == 'split':
                plan = prepare_split(room,**args)
            else:
                plan = prepare_merge(room,**args)
            if json.loads(json.dumps(asdict(plan))) != payload['proof']:
                raise WorldConflict('分组计划已过期，场景、成员或实体发生变化')
            if payload['operation'] == 'split':
                result = commit_split(room,plan)
            else:
                result = {**commit_merge(room,plan,command_id),'operation':'scene_merge'}
            room['version'] += 1
            channels = {room['scene_instances'][sid]['channel_id'] for sid in (plan.source,plan.target)}
            for channel in sorted(channels):
                if not any(room['text_scope']['members'][m['id']]['channel'] == channel for m in room['members']):
                    continue
                item = {'id':len(room['events'])+1,'kind':'system','actor_name':'DM','text':'队伍已在安全检查点调整分组。'}
                stamp_event(room,item,channel=channel)
                room['events'].append(item)
            response = {**result,'group_plan_id':plan_id,'version':room['version'],'replayed':False}
            db.execute('UPDATE rooms SET state=?,version=? WHERE id=?', (json.dumps(room,ensure_ascii=False),room['version'],room_id))
            db.execute('INSERT INTO commands VALUES(?,?,?,?)', (room_id,actor,command_id,json.dumps(response,ensure_ascii=False)))
            db.execute('DELETE FROM group_plans WHERE id=?', (plan_id,))
            return response
