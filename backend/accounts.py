"""Local accounts, revocable opaque sessions and role-based authorization.

Passwords use salted scrypt. Session identifiers never enter JavaScript: only
their hashes are stored server-side and a HttpOnly cookie carries the secret.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query, Request, Response, WebSocket
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

COOKIE_NAME = "hexbound_session"
ROLE_NAMES = ("player", "creator", "admin")
PASSWORD_MIN = 10
USERNAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,31}$"
FORCED_PASSWORD_PATHS = {"/api/auth/me", "/api/auth/change-password", "/api/auth/logout", "/api/auth/logout-all"}
KDF_SLOTS = threading.BoundedSemaphore(4)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def enabled(name, default=False):
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def valid_password(value):
    if not isinstance(value, str) or not PASSWORD_MIN <= len(value) <= 128:
        raise ValueError("密码须为10至128个字符")
    if value.isspace():
        raise ValueError("密码不能全部为空白字符")
    return value


def hash_password(password):
    valid_password(password)
    salt = secrets.token_bytes(16)
    with KDF_SLOTS:
        digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=5, dklen=32)
    return "scrypt$16384$8$5$" + salt.hex() + "$" + digest.hex()


def verify_password(password, encoded):
    if not isinstance(password, str) or len(password) > 128:
        return False
    try:
        algorithm, n, r, p, salt_hex, expected_hex = encoded.split("$")
        if (algorithm, n, r) != ("scrypt", "16384", "8") or p not in {"1", "5"}:
            return False
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(expected_hex)
        if len(salt) != 16 or len(expected) != 32:
            return False
        with KDF_SLOTS:
            actual = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=int(p), dklen=32)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def digest_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


class AccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Register(AccountInput):
    username: str = Field(pattern=USERNAME_PATTERN)
    password: str = Field(min_length=PASSWORD_MIN, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=40)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):
        return valid_password(value)

    @field_validator("display_name")
    @classmethod
    def validate_name(cls, value):
        if value is not None and not value.strip():
            raise ValueError("显示名称不能为空")
        return value.strip() if value is not None else None


class Login(AccountInput):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ChangePassword(AccountInput):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=PASSWORD_MIN, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value):
        return valid_password(value)


class AccountUpdate(AccountInput):
    expected_version: int = Field(ge=1, strict=True)
    role: Literal["player", "creator", "admin"] | None = None
    disabled: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def has_change(self):
        if self.role is None and self.disabled is None:
            raise ValueError("至少指定角色或启用状态")
        return self


class ResetPassword(AccountInput):
    expected_version: int = Field(ge=1, strict=True)
    new_password: str = Field(min_length=PASSWORD_MIN, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value):
        return valid_password(value)


class AccountService:
    def __init__(self, store):
        self.store = store
        self.rate_buckets = defaultdict(deque)
        self.rate_lock = threading.Lock()
        self.session_seconds = max(300, min(30 * 86400, int(os.getenv("HEXBOUND_SESSION_TTL_SECONDS", str(7 * 86400)))))
        self.dummy_hash = hash_password("not-a-real-account-password")
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('player','creator','admin')),
                    disabled INTEGER NOT NULL DEFAULT 0,
                    must_change_password INTEGER NOT NULL DEFAULT 0,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_sessions (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES accounts(id),
                    csrf_token TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_user ON account_sessions(user_id);
                CREATE INDEX IF NOT EXISTS sessions_expiry ON account_sessions(expires_at);
                CREATE TABLE IF NOT EXISTS account_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL,
                    actor_id TEXT, actor_username TEXT, target_id TEXT, target_username TEXT,
                    details_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            db.execute("DELETE FROM account_sessions WHERE expires_at<=?", (time.time(),))
        self.bootstrap()

    @staticmethod
    def user(row):
        return {"id": row["id"], "username": row["username"], "display_name": row["display_name"],
                "role": row["role"], "disabled": bool(row["disabled"]), "must_change_password": bool(row["must_change_password"]),
                "version": row["version"], "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def get(self, db, user_id):
        row = db.execute("SELECT * FROM accounts WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "账号不存在")
        return row

    @staticmethod
    def audit(db, action, actor=None, target=None, details=None):
        db.execute("INSERT INTO account_audit(action,actor_id,actor_username,target_id,target_username,details_json,created_at) VALUES(?,?,?,?,?,?,?)",
                   (action, actor["id"] if actor else None, actor["username"] if actor else None,
                    target["id"] if target else None, target["username"] if target else None,
                    json.dumps(details or {}, ensure_ascii=False), utc_now()))

    def bootstrap(self):
        username = os.getenv("HEXBOUND_BOOTSTRAP_ADMIN_USERNAME", "").strip().lower()
        password = os.getenv("HEXBOUND_BOOTSTRAP_ADMIN_PASSWORD", "")
        if not username or not password:
            return
        with self.store.connect() as db:
            if db.execute("SELECT 1 FROM account_meta WHERE key='bootstrap_complete'").fetchone():
                return
        if not re.fullmatch(USERNAME_PATTERN, username):
            raise ValueError("HEXBOUND_BOOTSTRAP_ADMIN_USERNAME 须为3至32位英文、数字或_.-")
        encoded = hash_password(password)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM account_meta WHERE key='bootstrap_complete'").fetchone():
                return
            # Never elevate an existing ordinary account or reset its password.
            existing = db.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
            if existing:
                if existing["role"] != "admin":
                    raise ValueError("初始管理员用户名已被非管理员账号占用；请选择其他用户名")
                db.execute("INSERT INTO account_meta VALUES('bootstrap_complete','1')")
                return
            user_id, stamp = uuid.uuid4().hex, utc_now()
            db.execute("INSERT INTO accounts VALUES(?,?,?,?, 'admin',0,0,1,?,?)", (user_id, username, username, encoded, stamp, stamp))
            self.audit(db, "bootstrap_admin", target=self.get(db, user_id))
            db.execute("INSERT INTO account_meta VALUES('bootstrap_complete','1')")

    def throttle(self, key, limit, window):
        with self.rate_lock:
            current = time.monotonic()
            bucket = self.rate_buckets[key]
            while bucket and bucket[0] <= current - window:
                bucket.popleft()
            if len(bucket) >= limit:
                raise HTTPException(429, "尝试过于频繁，请稍后再试")
            bucket.append(current)
            if len(self.rate_buckets) > 5000:
                for old in list(self.rate_buckets):
                    if self.rate_buckets[old] and self.rate_buckets[old][-1] < current - 3600:
                        del self.rate_buckets[old]

    def new_session(self, db, user_id):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        created = time.time()
        db.execute("DELETE FROM account_sessions WHERE expires_at<=?", (created,))
        db.execute("INSERT INTO account_sessions VALUES(?,?,?,?,?)", (digest_token(token), user_id, csrf, created, created + self.session_seconds))
        return token, csrf

    @staticmethod
    def check_live_session(db, user_id, session_id):
        if not db.execute("SELECT 1 FROM account_sessions WHERE id=? AND user_id=? AND expires_at>?", (session_id, user_id, time.time())).fetchone():
            raise HTTPException(401, "此登录会话已被撤销，请重新登录")

    def authenticate(self, token):
        if not isinstance(token, str) or not 20 <= len(token) <= 200:
            raise HTTPException(401, "请先登录")
        with self.store.connect() as db:
            session = db.execute("SELECT * FROM account_sessions WHERE id=? AND expires_at>?", (digest_token(token), time.time())).fetchone()
            if session is None:
                raise HTTPException(401, "登录已过期，请重新登录")
            account = self.get(db, session["user_id"])
            if account["disabled"]:
                raise HTTPException(401, "账号已停用")
            return self.user(account), dict(session)

    def register(self, body):
        username = body.username.lower()
        encoded = hash_password(body.password)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM accounts WHERE username=?", (username,)).fetchone():
                raise HTTPException(409, "用户名已被使用")
            user_id, stamp = uuid.uuid4().hex, utc_now()
            db.execute("INSERT INTO accounts VALUES(?,?,?,?, 'player',0,0,1,?,?)", (user_id, username, body.display_name or body.username, encoded, stamp, stamp))
            token, csrf = self.new_session(db, user_id)
            user = self.user(self.get(db, user_id))
            self.audit(db, "register", actor=user, target=user)
        return user, token, csrf

    def login(self, body):
        username = body.username.strip().lower()
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
        encoded = row["password_hash"] if row else self.dummy_hash
        correct = verify_password(body.password, encoded)
        if not row or not correct or row["disabled"]:
            with self.store.connect() as db:
                self.audit(db, "login_failed", target=row, details={"username": username})
            raise HTTPException(401, "用户名或密码错误，或账号不可用")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Password/role may have changed during the intentionally slow KDF.
            current = self.get(db, row["id"])
            if current["disabled"] or current["password_hash"] != encoded:
                raise HTTPException(401, "账号状态已更新，请重新登录")
            token, csrf = self.new_session(db, current["id"])
            user = self.user(current)
            self.audit(db, "login", actor=user, target=user)
        return user, token, csrf

    def change_password(self, user_id, session_id, current_password, new_password):
        with self.store.connect() as db:
            old = self.get(db, user_id)
        if not verify_password(current_password, old["password_hash"]):
            raise HTTPException(403, "当前密码不正确")
        if current_password == new_password:
            raise HTTPException(422, "新密码不能与当前密码相同")
        encoded = hash_password(new_password)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.check_live_session(db, user_id, session_id)
            current = self.get(db, user_id)
            if current["disabled"] or current["password_hash"] != old["password_hash"] or current["version"] != old["version"]:
                raise HTTPException(409, "账号状态已变化，请重新登录")
            db.execute("UPDATE accounts SET password_hash=?,must_change_password=0,version=version+1,updated_at=? WHERE id=?", (encoded, utc_now(), user_id))
            db.execute("DELETE FROM account_sessions WHERE user_id=?", (user_id,))
            token, csrf = self.new_session(db, user_id)
            user = self.user(self.get(db, user_id))
            self.audit(db, "change_password", actor=user, target=user)
        return user, token, csrf

    def revoke(self, user, token, all_sessions=False):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if all_sessions:
                db.execute("DELETE FROM account_sessions WHERE user_id=?", (user["id"],))
            else:
                db.execute("DELETE FROM account_sessions WHERE id=? AND user_id=?", (digest_token(token), user["id"]))
            self.audit(db, "logout_all" if all_sessions else "logout", actor=user, target=user)


def get_account_service(store):
    service = getattr(store, "accounts_service", None)
    if service is None:
        service = AccountService(store)
        store.accounts_service = service
    return service


def check_origin(request):
    origin = request.headers.get("origin")
    if origin:
        try:
            parsed = urlsplit(origin)
        except ValueError as exc:
            raise HTTPException(403, "无效请求来源") from exc
        expected_scheme = {"ws": "http", "wss": "https"}.get(request.url.scheme, request.url.scheme)
        if parsed.scheme != expected_scheme or parsed.netloc.lower() != request.headers.get("host", "").lower():
            raise HTTPException(403, "跨站请求被拒绝")


def require_user(request: Request, roles=None):
    service = get_account_service(request.app.state.store)
    user, session = service.authenticate(request.cookies.get(COOKIE_NAME))
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        check_origin(request)
        csrf = request.headers.get("x-csrf-token", "")
        if not csrf or not hmac.compare_digest(csrf.encode(), session["csrf_token"].encode()):
            raise HTTPException(403, "安全校验已失效，请刷新页面后重试")
    if user["must_change_password"] and request.url.path not in FORCED_PASSWORD_PATHS:
        raise HTTPException(403, "请先修改管理员重置的临时密码")
    if roles is not None and user["role"] not in roles:
        raise HTTPException(403, "当前账号没有此操作权限")
    request.state.account = user
    request.state.account_session = session
    return user


def authenticate_websocket(websocket: WebSocket):
    check_origin(websocket)
    user, _ = get_account_service(websocket.app.state.store).authenticate(websocket.cookies.get(COOKIE_NAME))
    if user["must_change_password"]:
        raise HTTPException(403, "请先修改临时密码")
    return user


def create_accounts_router(store):
    service = get_account_service(store)
    router = APIRouter()

    def set_cookie(response, request, token):
        secure = enabled("HEXBOUND_COOKIE_SECURE", request.url.scheme == "https")
        response.set_cookie(COOKIE_NAME, token, max_age=service.session_seconds, httponly=True, secure=secure, samesite="lax", path="/")
        response.headers["Cache-Control"] = "no-store"

    def login_result(result, response, request):
        user, token, csrf = result
        set_cookie(response, request, token)
        return {"user": user, "csrf_token": csrf}

    def client_ip(request):
        return request.client.host if request.client else "unknown"

    @router.get("/api/auth/status")
    async def status():
        with store.connect() as db:
            has_admin = bool(db.execute("SELECT 1 FROM accounts WHERE role='admin' AND disabled=0 LIMIT 1").fetchone())
        return {"registration_enabled": enabled("HEXBOUND_ALLOW_REGISTRATION", True), "bootstrap_admin_configured": has_admin}

    @router.post("/api/auth/register", status_code=201)
    async def register(body: Register, request: Request, response: Response):
        check_origin(request)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise HTTPException(415, "注册请求必须使用 JSON")
        if not enabled("HEXBOUND_ALLOW_REGISTRATION", True):
            raise HTTPException(403, "注册已关闭，请联系管理员")
        service.throttle("register:" + client_ip(request), 10, 3600)
        result = await asyncio.to_thread(service.register, body)
        return login_result(result, response, request)

    @router.post("/api/auth/login")
    async def login(body: Login, request: Request, response: Response):
        check_origin(request)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise HTTPException(415, "登录请求必须使用 JSON")
        ip = client_ip(request)
        service.throttle("login-ip:" + ip, 50, 300)
        service.throttle("login-user:" + ip + ":" + body.username.strip().lower(), 12, 900)
        service.throttle("login-identity:" + body.username.strip().lower(), 30, 300)
        return login_result(await asyncio.to_thread(service.login, body), response, request)

    @router.get("/api/auth/me")
    async def me(request: Request, response: Response):
        user = require_user(request)
        response.headers["Cache-Control"] = "no-store"
        return {"user": user, "csrf_token": request.state.account_session["csrf_token"]}

    @router.post("/api/auth/logout")
    async def logout(request: Request, response: Response):
        user = require_user(request)
        service.revoke(user, request.cookies[COOKIE_NAME])
        response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")
        return {"ok": True}

    @router.post("/api/auth/logout-all")
    async def logout_all(request: Request, response: Response):
        user = require_user(request)
        service.revoke(user, request.cookies[COOKIE_NAME], all_sessions=True)
        response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")
        return {"ok": True}

    @router.post("/api/auth/change-password")
    async def change_password(body: ChangePassword, request: Request, response: Response):
        user = require_user(request)
        service.throttle("change-password:" + user["id"], 10, 900)
        result = await asyncio.to_thread(service.change_password, user["id"], request.state.account_session["id"], body.current_password, body.new_password)
        return login_result(result, response, request)

    @router.get("/api/admin/users")
    async def list_users(request: Request, page: int = Query(default=1, ge=1, le=1_000_000), page_size: int = Query(default=20, ge=1, le=100),
                         q: str = Query(default="", max_length=80), role: Literal["player", "creator", "admin"] | None = None, disabled: bool | None = None):
        require_user(request, roles={"admin"})
        clauses, args = ["1=1"], []
        if q:
            clauses.append("(username LIKE ? OR display_name LIKE ?)")
            args.extend(["%" + q + "%"] * 2)
        if role is not None:
            clauses.append("role=?")
            args.append(role)
        if disabled is not None:
            clauses.append("disabled=?")
            args.append(int(disabled))
        where = " AND ".join(clauses)
        with store.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM accounts WHERE " + where, args).fetchone()[0]
            rows = db.execute("SELECT * FROM accounts WHERE " + where + " ORDER BY created_at,id LIMIT ? OFFSET ?", args + [page_size, (page - 1) * page_size]).fetchall()
        return {"items": [service.user(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    def admin_in_transaction(db, actor_id, session_id):
        service.check_live_session(db, actor_id, session_id)
        actor = service.get(db, actor_id)
        if actor["disabled"] or actor["role"] != "admin" or actor["must_change_password"]:
            raise HTTPException(403, "管理员状态已更新，请重新登录")
        return actor

    @router.patch("/api/admin/users/{user_id}")
    async def update_user(user_id: str, body: AccountUpdate, request: Request):
        actor = require_user(request, roles={"admin"})
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            actor = admin_in_transaction(db, actor["id"], request.state.account_session["id"])
            target = service.get(db, user_id)
            if target["version"] != body.expected_version:
                raise HTTPException(409, "账号已更新，请刷新列表后重试")
            role = body.role if body.role is not None else target["role"]
            disabled = int(body.disabled) if body.disabled is not None else target["disabled"]
            if target["role"] == "admin" and not target["disabled"] and (role != "admin" or disabled):
                count = db.execute("SELECT COUNT(*) FROM accounts WHERE role='admin' AND disabled=0").fetchone()[0]
                if count <= 1:
                    raise HTTPException(409, "不能停用或降级最后一位有效管理员")
            changed = role != target["role"] or disabled != target["disabled"]
            if changed:
                db.execute("UPDATE accounts SET role=?,disabled=?,version=version+1,updated_at=? WHERE id=?", (role, disabled, utc_now(), user_id))
                db.execute("DELETE FROM account_sessions WHERE user_id=?", (user_id,))
                service.audit(db, "update_account", actor=actor, target=target, details={"previous_role": target["role"], "role": role, "previous_disabled": bool(target["disabled"]), "disabled": bool(disabled)})
            return service.user(service.get(db, user_id))

    @router.post("/api/admin/users/{user_id}/reset-password")
    async def reset_password(user_id: str, body: ResetPassword, request: Request):
        actor = require_user(request, roles={"admin"})
        encoded = await asyncio.to_thread(hash_password, body.new_password)
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            actor = admin_in_transaction(db, actor["id"], request.state.account_session["id"])
            target = service.get(db, user_id)
            if target["version"] != body.expected_version:
                raise HTTPException(409, "账号已更新，请刷新列表后重试")
            db.execute("UPDATE accounts SET password_hash=?,must_change_password=1,version=version+1,updated_at=? WHERE id=?", (encoded, utc_now(), user_id))
            db.execute("DELETE FROM account_sessions WHERE user_id=?", (user_id,))
            service.audit(db, "reset_password", actor=actor, target=target)
            return service.user(service.get(db, user_id))

    @router.get("/api/admin/audit")
    async def audit_log(request: Request, page: int = Query(default=1, ge=1, le=1_000_000), page_size: int = Query(default=20, ge=1, le=100), action: str = Query(default="", max_length=40)):
        require_user(request, roles={"admin"})
        where, args = ("WHERE action=?", [action]) if action else ("", [])
        with store.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM account_audit " + where, args).fetchone()[0]
            rows = db.execute("SELECT * FROM account_audit " + where + " ORDER BY id DESC LIMIT ? OFFSET ?", args + [page_size, (page - 1) * page_size]).fetchall()
        return {"items": [{"id": row["id"], "action": row["action"], "actor_username": row["actor_username"], "target_username": row["target_username"], "details": json.loads(row["details_json"]), "created_at": row["created_at"]} for row in rows], "total": total, "page": page, "page_size": page_size}

    return router
