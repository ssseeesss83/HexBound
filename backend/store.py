"""Small, transaction-safe SQLite persistence. Intended for one app worker."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
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
                CREATE TABLE IF NOT EXISTS commands (
                    room_id TEXT NOT NULL, member_id TEXT NOT NULL,
                    command_id TEXT NOT NULL, response TEXT NOT NULL,
                    PRIMARY KEY(room_id, member_id, command_id)
                );
            """)

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

    def create(self, state: dict, member_id: str, token: str):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO rooms VALUES (?, ?, ?, ?)",
                       (state["id"], state["invite_code"], state["version"], json.dumps(state, ensure_ascii=False)))
            db.execute("INSERT INTO members VALUES (?, ?, ?)", (member_id, state["id"], token_hash(token)))

    def get(self, room_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT state FROM rooms WHERE id=?", (room_id,)).fetchone()
        return json.loads(row["state"]) if row else None

    def find_invite(self, invite: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT id FROM rooms WHERE invite_code=?", (invite,)).fetchone()
        return row["id"] if row else None

    def authenticate(self, room_id: str, token: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT id FROM members WHERE room_id=? AND token_hash=?",
                             (room_id, token_hash(token))).fetchone()
        return row["id"] if row else None

    def join(self, room_id: str, member: dict, token: str) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM rooms WHERE id=?", (room_id,)).fetchone()
            if not row:
                raise ValueError("房间不存在")
            state = json.loads(row["state"])
            if state["status"] != "lobby":
                raise ValueError("冒险已开始，无法加入新角色")
            if len(state["members"]) >= 6:
                raise ValueError("六席已满，请加入其他房间")
            state["members"].append(member)
            state["version"] += 1
            db.execute("INSERT INTO members VALUES (?, ?, ?)", (member["id"], room_id, token_hash(token)))
            db.execute("UPDATE rooms SET state=?, version=? WHERE id=?",
                       (json.dumps(state, ensure_ascii=False), state["version"], room_id))
        return state

    def prior_command(self, room_id: str, member_id: str, command_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT response FROM commands WHERE room_id=? AND member_id=? AND command_id=?",
                             (room_id, member_id, command_id)).fetchone()
        return json.loads(row["response"]) if row else None

    def save(self, state: dict, previous_version: int, receipt: tuple[str, str, dict] | None = None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE rooms SET state=?, version=? WHERE id=? AND version=?",
                                 (json.dumps(state, ensure_ascii=False), state["version"], state["id"], previous_version)).rowcount
            if changed != 1:
                raise ValueError("房间已更新，请刷新后重试")
            if receipt:
                member_id, command_id, response = receipt
                db.execute("INSERT INTO commands VALUES (?, ?, ?, ?)",
                           (state["id"], member_id, command_id, json.dumps(response, ensure_ascii=False)))
