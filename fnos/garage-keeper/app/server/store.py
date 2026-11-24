"""数据持久层：SQLite 单文件，零第三方依赖。

数据目录优先级：GARAGE_DATA > TRIM_PKGVAR > <应用根>/var
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

_HERE = Path(__file__).resolve().parent          # <APPDEST>/server
APPDEST = _HERE.parent                           # <APPDEST>
UI_DIR = APPDEST / "ui"

SCHEMA_VERSION = 2
PBKDF2_ITER = 150_000
SESSION_COOKIE = "gk_session"
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "garage123"


def _resolve_data_dir() -> Path:
    for key in ("GARAGE_DATA", "TRIM_PKGVAR"):
        value = os.environ.get(key)
        if value:
            return Path(value)
    return APPDEST.parent / "var"


DATA_DIR = _resolve_data_dir()
DB_PATH = Path(os.environ.get("GARAGE_DB") or (DATA_DIR / "garage.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    plate           TEXT,
    vtype           TEXT    NOT NULL DEFAULT 'ice',
    brand           TEXT,
    model           TEXT,
    year            INTEGER,
    color           TEXT,
    vin             TEXT,
    init_odometer   REAL    NOT NULL DEFAULT 0,
    tank_capacity   REAL,
    battery_capacity REAL,
    insurer         TEXT,
    policy_no       TEXT,
    insurance_due   TEXT,
    inspect_due     TEXT,
    tax_due         TEXT,
    register_date   TEXT,
    tire_spec       TEXT,
    note            TEXT,
    archived        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS energy_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id  INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL,
    date        TEXT    NOT NULL,
    odometer    REAL,
    quantity    REAL    NOT NULL,
    unit_price  REAL,
    cost        REAL,
    station     TEXT,
    is_full     INTEGER NOT NULL DEFAULT 1,
    range_delta REAL,
    soc_start   REAL,
    soc_end     REAL,
    note        TEXT,
    source      TEXT    NOT NULL DEFAULT 'manual',
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS service_records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id    INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
    rtype         TEXT    NOT NULL,
    date          TEXT    NOT NULL,
    odometer      REAL,
    items         TEXT    NOT NULL,
    cost          REAL,
    shop          TEXT,
    note          TEXT,
    next_date     TEXT,
    next_odometer REAL,
    source        TEXT    NOT NULL DEFAULT 'manual',
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id   INTEGER REFERENCES vehicles(id) ON DELETE CASCADE,
    title        TEXT    NOT NULL,
    due_date     TEXT,
    due_odometer REAL,
    note         TEXT,
    status       TEXT    NOT NULL DEFAULT 'open',
    done_at      TEXT,
    created_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT    NOT NULL,
    salt          TEXT    NOT NULL,
    display_name  TEXT,
    role          TEXT    NOT NULL DEFAULT 'member',
    disabled      INTEGER NOT NULL DEFAULT 0,
    must_change   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL,
    last_login    TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT    PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT    NOT NULL,
    expires_at TEXT    NOT NULL,
    ip         TEXT,
    user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_energy_vehicle_date ON energy_records(vehicle_id, date);
CREATE INDEX IF NOT EXISTS idx_service_vehicle_date ON service_records(vehicle_id, date);
CREATE INDEX IF NOT EXISTS idx_reminder_status ON reminders(status);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
"""

DEFAULT_SETTINGS: dict[str, str] = {
    "ai_enabled": "1",
    "ai_base_url": os.environ.get("HERMES_BASE_URL", "http://127.0.0.1:11434/v1"),
    "ai_model": os.environ.get("HERMES_MODEL", "hermes3:8b"),
    "ai_api_key": os.environ.get("HERMES_API_KEY", ""),
    "ai_timeout": "60",
    "ai_temperature": "0.1",
    "currency": "¥",
    "distance_unit": "km",
    "default_vehicle_id": "",
    "last_backup_at": "",
}


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


@contextmanager
def get_conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(bootstrap: tuple[str, str] | None = None) -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO NOTHING",
                (key, value),
            )
        if count_users(conn) == 0:
            user, password = resolve_bootstrap(bootstrap)
            must_change = 1 if password == DEFAULT_ADMIN_PASS else 0
            display = "管理员" if user.lower() == DEFAULT_ADMIN_USER else None
            create_user(conn, user, password, display, "admin", must_change)


# ------------------------------------------------------------------ 账号与会话
def resolve_bootstrap(bootstrap: tuple[str, str] | None = None) -> tuple[str, str]:
    """账号初始化来源：显式入参 > 环境变量 > 默认值。"""
    user = (bootstrap[0] if bootstrap else "") or os.environ.get("GARAGE_ADMIN_USER") or DEFAULT_ADMIN_USER
    password = (bootstrap[1] if bootstrap else "") or os.environ.get("GARAGE_ADMIN_PASS") or DEFAULT_ADMIN_PASS
    return user.strip() or DEFAULT_ADMIN_USER, password


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITER)
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    try:
        calc, _ = hash_password(password, salt)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calc, str(password_hash))


def count_users(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"])


def public_user(row: Any) -> dict:
    """对外暴露的用户字段（绝不包含口令材料）。"""
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"] or row["username"],
        "role": row["role"],
        "disabled": int(row["disabled"]),
        "must_change": int(row["must_change"]),
        "created_at": row["created_at"],
        "last_login": row["last_login"],
    }


def create_user(conn: sqlite3.Connection, username: str, password: str,
                display_name: str | None = None, role: str = "member",
                must_change: int = 0) -> int:
    password_hash, salt = hash_password(password)
    cur = conn.execute(
        "INSERT INTO users(username, password_hash, salt, display_name, role, disabled,"
        " must_change, created_at) VALUES(?,?,?,?,?,0,?,?)",
        (username.strip(), password_hash, salt, display_name, role, must_change, now_iso()),
    )
    return int(cur.lastrowid)


def set_password(conn: sqlite3.Connection, user_id: int, password: str, must_change: int = 0) -> None:
    password_hash, salt = hash_password(password)
    conn.execute(
        "UPDATE users SET password_hash = ?, salt = ?, must_change = ? WHERE id = ?",
        (password_hash, salt, must_change, user_id),
    )


def create_session(conn: sqlite3.Connection, user_id: int, days: int = 7,
                   ip: str | None = None, user_agent: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(days=days)).replace(microsecond=0).isoformat()
    conn.execute(
        "INSERT INTO sessions(token, user_id, created_at, expires_at, ip, user_agent)"
        " VALUES(?,?,?,?,?,?)",
        (token, user_id, now_iso(), expires, ip, (user_agent or "")[:200]),
    )
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now_iso(),))
    return token


def session_user(conn: sqlite3.Connection, token: str | None) -> dict | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT u.*, s.token AS session_token, s.expires_at AS session_expires"
        " FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
        (token,),
    ).fetchone()
    if not row:
        return None
    if str(row["session_expires"]) < now_iso() or row["disabled"]:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        return None
    user = public_user(row)
    user["session_token"] = row["session_token"]
    return user


def drop_session(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def rows(rows_obj: Iterable[sqlite3.Row]) -> list:
    return [dict(r) for r in rows_obj]


def get_settings(conn: sqlite3.Connection) -> dict:
    data = dict(DEFAULT_SETTINGS)
    for r in conn.execute("SELECT key, value FROM settings"):
        data[r["key"]] = r["value"]
    return data


def save_settings(conn: sqlite3.Connection, updates: dict) -> dict:
    for key, value in updates.items():
        if key not in DEFAULT_SETTINGS:
            continue
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, "" if value is None else str(value)),
        )
    return get_settings(conn)
