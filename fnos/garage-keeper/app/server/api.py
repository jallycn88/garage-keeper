"""HTTP 接口层：仅依赖 Python 标准库，接口语义与原 FastAPI 版本保持一致。

设计要点
- 单进程多线程（ThreadingHTTPServer），每个请求独立 SQLite 连接；
- 统一 JSON 错误体 {"detail": "..."}，与前端 api() 的错误解析对齐；
- 静态资源与前端同源，无需额外反向代理即可直接访问。
"""
from __future__ import annotations

import hmac
import json
import mimetypes
import os
import re
import socket
import socketserver
import sys
import threading
import time
import traceback
import urllib.parse
from datetime import date, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import backup
import calc
import nlp
import store

APP_VERSION = "1.1.0"
AUTH_TOKEN = (os.environ.get("GARAGE_TOKEN") or "").strip()
UI_DIR = store.UI_DIR
SESSION_COOKIE = store.SESSION_COOKIE
PUBLIC_API = {"/api/auth/state", "/api/auth/login", "/api/auth/setup"}
MIN_PASSWORD = 6

LOG = sys.stderr


# ------------------------------------------------------------------ 基础设施
class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class Raw:
    """非 JSON 响应（文件下载等）。"""

    def __init__(self, body: bytes, content_type: str, status: int = 200, headers=None):
        self.body = body
        self.content_type = content_type
        self.status = status
        self.headers = headers or {}


class Request:
    def __init__(self, handler: BaseHTTPRequestHandler, method: str, path: str, query: dict, body: bytes,
                 user: dict | None = None):
        self.handler = handler
        self.method = method
        self.path = path
        self.query = query
        self.body = body
        self.user = user or {}

    def json(self):
        if not self.body:
            raise ApiError(422, "请求体不能为空")
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(422, "请求体不是合法 JSON")

    def arg(self, name, default=None):
        value = self.query.get(name)
        return default if value in (None, "") else value

    def arg_int(self, name, default=None):
        value = self.arg(name)
        if value is None:
            return default
        try:
            return int(float(value))
        except ValueError:
            return default


ROUTES: list[tuple[str, re.Pattern, object]] = []


def route(method: str, pattern: str):
    regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")

    def decorator(fn):
        ROUTES.append((method, regex, fn))
        return fn

    return decorator


def _num(value, default=None):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return default


def _text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_date(value):
    if not value:
        return None
    d = calc.parse_date(value)
    return d.strftime("%Y-%m-%d") if d else None


def _check_date(value, field="日期"):
    if not value:
        raise ApiError(422, f"{field}不能为空")
    d = calc.parse_date(value)
    if not d:
        raise ApiError(422, f"{field}格式应为 YYYY-MM-DD")
    return d.strftime("%Y-%m-%d")


def _vehicle(conn, vid):
    try:
        vid = int(vid)
    except (TypeError, ValueError):
        raise ApiError(404, "车辆不存在")
    row = conn.execute("SELECT * FROM vehicles WHERE id = ?", (vid,)).fetchone()
    if not row:
        raise ApiError(404, "车辆不存在")
    return dict(row)


def _touch_vehicle(conn, vid):
    try:
        conn.execute("UPDATE vehicles SET updated_at = ? WHERE id = ?", (store.now_iso(), int(vid)))
    except (TypeError, ValueError):
        pass


def _allowed_kinds(vtype: str):
    if vtype == "ev":
        return ("charge",)
    if vtype == "phev":
        return ("fuel", "charge")
    return ("fuel",)


def save_energy(conn, data, source="manual"):
    vehicle = _vehicle(conn, data.get("vehicle_id"))
    allowed = _allowed_kinds(vehicle["vtype"])
    kind = (data.get("kind") or allowed[0])
    if kind not in allowed:
        kind = allowed[0]
    quantity = _num(data.get("quantity"), 0.0) or 0.0
    if quantity <= 0:
        raise ApiError(422, "加油量/充电量必须大于 0")
    cost = _num(data.get("cost"))
    unit_price = _num(data.get("unit_price"))
    if cost is None and unit_price is not None:
        cost = round(quantity * unit_price, 2)
    if unit_price is None and cost is not None:
        unit_price = round(cost / quantity, 3)
    cur = conn.execute(
        "INSERT INTO energy_records(vehicle_id, kind, date, odometer, quantity, unit_price, cost, station,"
        " is_full, range_delta, soc_start, soc_end, note, source, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            vehicle["id"], kind, _check_date(data.get("date")),
            _num(data.get("odometer")), quantity, unit_price, cost,
            _text(data.get("station")), 0 if data.get("is_full") in (0, False, "0", "false") else 1,
            _num(data.get("range_delta")), _num(data.get("soc_start")), _num(data.get("soc_end")),
            _text(data.get("note")), source, store.now_iso(),
        ),
    )
    return int(cur.lastrowid)


def save_service(conn, data, source="manual"):
    vehicle = _vehicle(conn, data.get("vehicle_id"))
    items = (data.get("items") or "").strip()
    if not items:
        raise ApiError(422, "项目名称不能为空")
    rtype = data.get("rtype") or "maintenance"
    if rtype not in ("maintenance", "repair", "expense"):
        rtype = "maintenance"
    next_date = data.get("next_date")
    if next_date:
        next_date = _check_date(next_date, "下次日期")
    cur = conn.execute(
        "INSERT INTO service_records(vehicle_id, rtype, date, odometer, items, cost, shop, note,"
        " next_date, next_odometer, source, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            vehicle["id"], rtype, _check_date(data.get("date")),
            _num(data.get("odometer")), items, _num(data.get("cost")), _text(data.get("shop")),
            _text(data.get("note")), next_date, _num(data.get("next_odometer")), source, store.now_iso(),
        ),
    )
    return int(cur.lastrowid)


# ------------------------------------------------------------------ 账号与会话
_FAILS: dict[str, list[float]] = {}
_FAIL_LOCK = threading.Lock()
FAIL_WINDOW = 300
FAIL_LIMIT = 8


def _throttled(key: str) -> bool:
    now = time.time()
    with _FAIL_LOCK:
        bucket = [t for t in _FAILS.get(key, []) if now - t < FAIL_WINDOW]
        _FAILS[key] = bucket
        return len(bucket) >= FAIL_LIMIT


def _record_fail(key: str) -> None:
    now = time.time()
    with _FAIL_LOCK:
        _FAILS.setdefault(key, []).append(now)


def _clear_fail(key: str) -> None:
    with _FAIL_LOCK:
        _FAILS.pop(key, None)


def _client_ip(handler) -> str:
    forwarded = handler.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return handler.client_address[0] if handler.client_address else "?"


def cookie_token(handler) -> str | None:
    raw = handler.headers.get("Cookie")
    if not raw:
        return None
    try:
        jar = SimpleCookie()
        jar.load(raw)
    except Exception:
        return None
    morsel = jar.get(SESSION_COOKIE)
    return morsel.value if morsel else None


LEGACY_USER = {
    "id": 0, "username": "token", "display_name": "访问令牌", "role": "admin",
    "disabled": 0, "must_change": 0, "session_token": "", "legacy": True,
}


def authenticate(handler) -> dict | None:
    token = cookie_token(handler)
    if token:
        with store.get_conn() as conn:
            user = store.session_user(conn, token)
        if user:
            return user
    header_token = (handler.headers.get("X-Auth-Token") or "").strip()
    if AUTH_TOKEN and header_token and hmac.compare_digest(header_token, AUTH_TOKEN):
        return dict(LEGACY_USER)
    return None


def view_user(user: dict | None) -> dict | None:
    """对外返回的用户视图：剔除服务端会话令牌。"""
    if not user:
        return None
    return {k: v for k, v in user.items() if k != "session_token"}


def require_admin(req: Request) -> None:
    if (req.user or {}).get("role") != "admin":
        raise ApiError(403, "需要管理员权限")


def _clean_username(value) -> str:
    username = str(value or "").strip()
    if not re.match(r"^[A-Za-z0-9_.\-]{2,32}$", username):
        raise ApiError(422, "账号需为 2-32 位字母、数字、下划线、点或短横线")
    return username


def _clean_password(value) -> str:
    password = str(value or "")
    if len(password) < MIN_PASSWORD:
        raise ApiError(422, f"密码至少 {MIN_PASSWORD} 位")
    if len(password) > 128:
        raise ApiError(422, "密码过长")
    return password


def _other_admins(conn, exclude_id: int) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) AS c FROM users WHERE role = 'admin' AND disabled = 0 AND id <> ?",
        (exclude_id,),
    ).fetchone()["c"])


@route("GET", "/api/auth/state")
def auth_state(req):
    with store.get_conn() as conn:
        total = store.count_users(conn)
    user = req.user or None
    return {
        "auth_required": True,
        "version": APP_VERSION,
        "setup_needed": total == 0,
        "min_password": MIN_PASSWORD,
        "logged_in": bool(user),
        "user": view_user(user),
    }


@route("POST", "/api/auth/setup")
def auth_setup(req):
    data = req.json()
    with store.get_conn() as conn:
        if store.count_users(conn) > 0:
            raise ApiError(403, "系统已存在账号，无法重复初始化")
        username = _clean_username(data.get("username"))
        password = _clean_password(data.get("password"))
        display = _text(data.get("display_name")) or username
        store.create_user(conn, username, password, display, "admin", 0)
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        token = store.create_session(conn, row["id"], 14, _client_ip(req.handler),
                                     req.handler.headers.get("User-Agent"))
        user = store.public_user(row)
    req.handler.set_cookie(token, 14 * 86400)
    return {"ok": True, "user": view_user(user)}


@route("POST", "/api/auth/login")
def auth_login(req):
    data = req.json()
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")
    remember = bool(data.get("remember"))
    if not username or not password:
        raise ApiError(422, "请输入账号与密码")

    ip = _client_ip(req.handler)
    key = f"{ip}|{username.lower()}"
    if _throttled(key) or _throttled(ip):
        raise ApiError(429, "尝试次数过多，请 5 分钟后再试")

    with store.get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        ok = bool(row) and not row["disabled"] and store.verify_password(password, row["password_hash"], row["salt"])
        if not ok:
            _record_fail(key)
            _record_fail(ip)
            raise ApiError(401, "账号或密码错误")
        _clear_fail(key)
        _clear_fail(ip)
        days = 14 if remember else 1
        token = store.create_session(conn, row["id"], days, ip, req.handler.headers.get("User-Agent"))
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (store.now_iso(), row["id"]))
        user = store.public_user(row)
    req.handler.set_cookie(token, days * 86400)
    return {"ok": True, "user": view_user(user)}


@route("POST", "/api/auth/logout")
def auth_logout(req):
    token = cookie_token(req.handler)
    with store.get_conn() as conn:
        store.drop_session(conn, token)
    req.handler.set_cookie("", 0)
    return {"ok": True}


@route("GET", "/api/auth/me")
def auth_me(req):
    return {"user": view_user(req.user)}


@route("POST", "/api/auth/password")
def auth_password(req):
    user = (req.user or {})
    if user.get("legacy"):
        raise ApiError(400, "访问令牌模式下不支持修改密码")
    data = req.json()
    old = str(data.get("old_password") or "")
    new = _clean_password(data.get("new_password"))
    with store.get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not row or not store.verify_password(old, row["password_hash"], row["salt"]):
            raise ApiError(400, "原密码不正确")
        if old == new:
            raise ApiError(422, "新密码不能与原密码相同")
        store.set_password(conn, row["id"], new, 0)
        conn.execute("DELETE FROM sessions WHERE user_id = ? AND token <> ?",
                     (row["id"], user.get("session_token") or ""))
    return {"ok": True}


@route("GET", "/api/auth/users")
def auth_users(req):
    require_admin(req)
    with store.get_conn() as conn:
        items = [store.public_user(r) for r in
                 conn.execute("SELECT * FROM users ORDER BY role = 'admin' DESC, id")]
    return {"items": items}


@route("POST", "/api/auth/users")
def auth_user_create(req):
    require_admin(req)
    data = req.json()
    username = _clean_username(data.get("username"))
    password = _clean_password(data.get("password"))
    role = "admin" if data.get("role") == "admin" else "member"
    display = _text(data.get("display_name")) or username
    with store.get_conn() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise ApiError(409, "该账号已存在")
        flag = data.get("must_change", True)
        must_change = 0 if flag in (0, False, "0", "false") else 1
        uid = store.create_user(conn, username, password, display, role, must_change)
    return {"ok": True, "id": uid}


@route("PUT", "/api/auth/users/{uid}")
def auth_user_update(req, uid):
    require_admin(req)
    data = req.json()
    user_id = int(uid)
    with store.get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise ApiError(404, "账号不存在")
        role = row["role"]
        disabled = int(row["disabled"])
        if "role" in data:
            role = "admin" if data.get("role") == "admin" else "member"
        if "disabled" in data:
            disabled = 1 if data.get("disabled") else 0
        if row["role"] == "admin" and (role != "admin" or disabled) and _other_admins(conn, user_id) == 0:
            raise ApiError(400, "至少需要保留一个可用的管理员账号")
        if user_id == (req.user or {}).get("id") and (role != "admin" or disabled):
            raise ApiError(400, "不能修改自己的角色或停用自己")
        conn.execute(
            "UPDATE users SET display_name = ?, role = ?, disabled = ? WHERE id = ?",
            (_text(data.get("display_name")) or row["display_name"] or row["username"], role, disabled, user_id),
        )
        if disabled:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return {"ok": True}


@route("POST", "/api/auth/users/{uid}/password")
def auth_user_reset(req, uid):
    require_admin(req)
    data = req.json()
    password = _clean_password(data.get("password"))
    user_id = int(uid)
    with store.get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise ApiError(404, "账号不存在")
        store.set_password(conn, user_id, password, 1)
        if user_id != (req.user or {}).get("id"):
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return {"ok": True}


@route("DELETE", "/api/auth/users/{uid}")
def auth_user_delete(req, uid):
    require_admin(req)
    user_id = int(uid)
    if user_id == (req.user or {}).get("id"):
        raise ApiError(400, "不能删除当前登录账号")
    with store.get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise ApiError(404, "账号不存在")
        if row["role"] == "admin" and _other_admins(conn, user_id) == 0:
            raise ApiError(400, "至少需要保留一个可用的管理员账号")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return {"ok": True}


# ------------------------------------------------------------------ 基础
@route("GET", "/healthz")
def healthz(req):
    return {"ok": True, "version": APP_VERSION}


@route("GET", "/api/meta")
def meta(req):
    with store.get_conn() as conn:
        vehicles = [
            {"id": r["id"], "name": r["name"], "plate": r["plate"]}
            for r in conn.execute("SELECT id, name, plate FROM vehicles ORDER BY id")
        ]
    return {
        "version": APP_VERSION,
        "today": store.today_iso(),
        "auth_required": True,
        "user": view_user(req.user),
        "data_dir": str(store.DATA_DIR),
        "db_path": str(store.DB_PATH),
        "vtypes": calc.VTYPE_LABEL,
        "rtypes": calc.RTYPE_LABEL,
        "kinds": calc.KIND_LABEL,
        "vehicles": vehicles,
    }


# ------------------------------------------------------------------ 车辆
@route("GET", "/api/vehicles")
def list_vehicles(req):
    with store.get_conn() as conn:
        vehicles = [dict(r) for r in conn.execute("SELECT * FROM vehicles WHERE archived = 0 ORDER BY id")]
        out = []
        for v in vehicles:
            s = calc.vehicle_summary(conn, v)
            out.append({
                **v,
                "summary": {
                    "current_odometer": s["current_odometer"],
                    "total_distance": s["total_distance"],
                    "total_cost": s["total_cost"],
                    "month_cost": s["month_cost"],
                    "cost_per_km": s["cost_per_km"],
                    "record_count": s["record_count"],
                    "fuel_consumption": s["fuel_consumption"],
                    "charge_consumption": s["charge_consumption"],
                    "last_record_date": (s["last_energy"] or {}).get("date") or (s["last_service"] or {}).get("date"),
                },
            })
    return {"items": out}


def _vehicle_payload(body):
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError(422, "车辆名称不能为空")
    vtype = str(body.get("vtype") or "ice").lower()
    if vtype not in ("ice", "ev", "phev"):
        vtype = "ice"
    year = body.get("year")
    try:
        year = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        year = None
    return {
        "name": name,
        "plate": _text(body.get("plate")),
        "vtype": vtype,
        "brand": _text(body.get("brand")),
        "model": _text(body.get("model")),
        "year": year,
        "color": _text(body.get("color")),
        "vin": _text(body.get("vin")),
        "init_odometer": _num(body.get("init_odometer"), 0.0) or 0.0,
        "tank_capacity": _num(body.get("tank_capacity")),
        "battery_capacity": _num(body.get("battery_capacity")),
        "insurer": _text(body.get("insurer")),
        "policy_no": _text(body.get("policy_no")),
        "insurance_due": _optional_date(body.get("insurance_due")),
        "inspect_due": _optional_date(body.get("inspect_due")),
        "tax_due": _optional_date(body.get("tax_due")),
        "register_date": _optional_date(body.get("register_date")),
        "tire_spec": _text(body.get("tire_spec")),
        "note": _text(body.get("note")),
        "archived": 1 if body.get("archived") else 0,
    }


@route("POST", "/api/vehicles")
def create_vehicle(req):
    data = _vehicle_payload(req.json())
    with store.get_conn() as conn:
        now = store.now_iso()
        cur = conn.execute(
            "INSERT INTO vehicles(name, plate, vtype, brand, model, year, color, vin, init_odometer,"
            " tank_capacity, battery_capacity, insurer, policy_no, insurance_due, inspect_due, tax_due,"
            " register_date, tire_spec, note, archived, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data["name"], data["plate"], data["vtype"], data["brand"], data["model"], data["year"],
                data["color"], data["vin"], data["init_odometer"], data["tank_capacity"],
                data["battery_capacity"], data["insurer"], data["policy_no"], data["insurance_due"],
                data["inspect_due"], data["tax_due"], data["register_date"], data["tire_spec"],
                data["note"], data["archived"], now, now,
            ),
        )
        return {"id": int(cur.lastrowid)}


@route("GET", "/api/vehicles/{vid}")
def get_vehicle(req, vid):
    with store.get_conn() as conn:
        vehicle = _vehicle(conn, vid)
        summary = calc.vehicle_summary(conn, vehicle)
        reminders = calc.build_reminders(conn, [vehicle])
        return {"vehicle": vehicle, "summary": summary, "reminders": reminders}


@route("PUT", "/api/vehicles/{vid}")
def update_vehicle(req, vid):
    data = _vehicle_payload(req.json())
    with store.get_conn() as conn:
        vehicle = _vehicle(conn, vid)
        conn.execute(
            "UPDATE vehicles SET name=?, plate=?, vtype=?, brand=?, model=?, year=?, color=?, vin=?,"
            " init_odometer=?, tank_capacity=?, battery_capacity=?, insurer=?, policy_no=?, insurance_due=?,"
            " inspect_due=?, tax_due=?, register_date=?, tire_spec=?, note=?, archived=?, updated_at=?"
            " WHERE id=?",
            (
                data["name"], data["plate"], data["vtype"], data["brand"], data["model"], data["year"],
                data["color"], data["vin"], data["init_odometer"], data["tank_capacity"],
                data["battery_capacity"], data["insurer"], data["policy_no"], data["insurance_due"],
                data["inspect_due"], data["tax_due"], data["register_date"], data["tire_spec"],
                data["note"], data["archived"], store.now_iso(), vehicle["id"],
            ),
        )
        return {"ok": True}


@route("DELETE", "/api/vehicles/{vid}")
def delete_vehicle(req, vid):
    with store.get_conn() as conn:
        vehicle = _vehicle(conn, vid)
        energy = conn.execute("SELECT COUNT(*) c FROM energy_records WHERE vehicle_id=?", (vehicle["id"],)).fetchone()["c"]
        service = conn.execute("SELECT COUNT(*) c FROM service_records WHERE vehicle_id=?", (vehicle["id"],)).fetchone()["c"]
        conn.execute("DELETE FROM vehicles WHERE id=?", (vehicle["id"],))
        return {"ok": True, "deleted": {"energy": energy, "service": service}}


# ------------------------------------------------------------------ 能耗记录
@route("GET", "/api/energy")
def list_energy(req):
    sql = ("SELECT e.*, v.name AS vehicle_name, v.vtype FROM energy_records e "
           "JOIN vehicles v ON v.id = e.vehicle_id WHERE 1=1")
    params = []
    vehicle_id = req.arg_int("vehicle_id")
    kind = req.arg("kind")
    date_from = req.arg("from")
    date_to = req.arg("to")
    limit = req.arg_int("limit", 300) or 300
    if vehicle_id:
        sql += " AND e.vehicle_id = ?"
        params.append(vehicle_id)
    if kind:
        sql += " AND e.kind = ?"
        params.append(kind)
    if date_from:
        sql += " AND e.date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND e.date <= ?"
        params.append(date_to)
    sql += " ORDER BY e.date DESC, e.id DESC LIMIT ?"
    params.append(max(1, min(limit, 2000)))
    with store.get_conn() as conn:
        items = [dict(r) for r in conn.execute(sql, params)]
        total = conn.execute("SELECT COUNT(*) c FROM energy_records").fetchone()["c"]
    return {
        "items": items,
        "totals": {
            "count": len(items),
            "quantity": round(sum(float(i["quantity"] or 0) for i in items), 2),
            "cost": round(sum(float(i["cost"] or 0) for i in items), 2),
            "all_count": total,
        },
    }


@route("POST", "/api/energy")
def create_energy(req):
    body = req.json()
    with store.get_conn() as conn:
        new_id = save_energy(conn, body, "manual")
        _touch_vehicle(conn, body.get("vehicle_id"))
        return {"id": new_id}


@route("PUT", "/api/energy/{rid}")
def update_energy(req, rid):
    body = req.json()
    with store.get_conn() as conn:
        row = conn.execute("SELECT * FROM energy_records WHERE id=?", (int(rid),)).fetchone()
        if not row:
            raise ApiError(404, "记录不存在")
        vehicle = _vehicle(conn, body.get("vehicle_id"))
        allowed = _allowed_kinds(vehicle["vtype"])
        kind = body.get("kind") or row["kind"]
        if kind not in allowed:
            kind = allowed[0]
        quantity = _num(body.get("quantity"), 0.0) or 0.0
        if quantity <= 0:
            raise ApiError(422, "加油量/充电量必须大于 0")
        cost = _num(body.get("cost"))
        unit_price = _num(body.get("unit_price"))
        if cost is None and unit_price is not None:
            cost = round(quantity * unit_price, 2)
        if unit_price is None and cost is not None:
            unit_price = round(cost / quantity, 3)
        conn.execute(
            "UPDATE energy_records SET vehicle_id=?, kind=?, date=?, odometer=?, quantity=?, unit_price=?,"
            " cost=?, station=?, is_full=?, range_delta=?, soc_start=?, soc_end=?, note=? WHERE id=?",
            (
                vehicle["id"], kind, _check_date(body.get("date")), _num(body.get("odometer")), quantity,
                unit_price, cost, _text(body.get("station")),
                0 if body.get("is_full") in (0, False, "0", "false") else 1,
                _num(body.get("range_delta")), _num(body.get("soc_start")), _num(body.get("soc_end")),
                _text(body.get("note")), int(rid),
            ),
        )
        _touch_vehicle(conn, vehicle["id"])
        return {"ok": True}


@route("DELETE", "/api/energy/{rid}")
def delete_energy(req, rid):
    with store.get_conn() as conn:
        conn.execute("DELETE FROM energy_records WHERE id=?", (int(rid),))
        return {"ok": True}


# ------------------------------------------------------------------ 保养维修
@route("GET", "/api/service")
def list_service(req):
    sql = ("SELECT s.*, v.name AS vehicle_name FROM service_records s "
           "JOIN vehicles v ON v.id = s.vehicle_id WHERE 1=1")
    params = []
    vehicle_id = req.arg_int("vehicle_id")
    rtype = req.arg("rtype")
    date_from = req.arg("from")
    date_to = req.arg("to")
    limit = req.arg_int("limit", 300) or 300
    if vehicle_id:
        sql += " AND s.vehicle_id = ?"
        params.append(vehicle_id)
    if rtype:
        sql += " AND s.rtype = ?"
        params.append(rtype)
    if date_from:
        sql += " AND s.date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND s.date <= ?"
        params.append(date_to)
    sql += " ORDER BY s.date DESC, s.id DESC LIMIT ?"
    params.append(max(1, min(limit, 2000)))
    with store.get_conn() as conn:
        items = [dict(r) for r in conn.execute(sql, params)]
        total = conn.execute("SELECT COUNT(*) c FROM service_records").fetchone()["c"]
    return {
        "items": items,
        "totals": {
            "count": len(items),
            "cost": round(sum(float(i["cost"] or 0) for i in items), 2),
            "all_count": total,
        },
    }


@route("POST", "/api/service")
def create_service(req):
    body = req.json()
    with store.get_conn() as conn:
        new_id = save_service(conn, body, "manual")
        _touch_vehicle(conn, body.get("vehicle_id"))
        return {"id": new_id}


@route("PUT", "/api/service/{rid}")
def update_service(req, rid):
    body = req.json()
    with store.get_conn() as conn:
        row = conn.execute("SELECT * FROM service_records WHERE id=?", (int(rid),)).fetchone()
        if not row:
            raise ApiError(404, "记录不存在")
        vehicle = _vehicle(conn, body.get("vehicle_id"))
        items = (body.get("items") or "").strip()
        if not items:
            raise ApiError(422, "项目名称不能为空")
        rtype = body.get("rtype")
        if rtype not in ("maintenance", "repair", "expense"):
            rtype = "maintenance"
        conn.execute(
            "UPDATE service_records SET vehicle_id=?, rtype=?, date=?, odometer=?, items=?, cost=?, shop=?,"
            " note=?, next_date=?, next_odometer=? WHERE id=?",
            (
                vehicle["id"], rtype, _check_date(body.get("date")), _num(body.get("odometer")), items,
                _num(body.get("cost")), _text(body.get("shop")), _text(body.get("note")),
                _optional_date(body.get("next_date")), _num(body.get("next_odometer")), int(rid),
            ),
        )
        _touch_vehicle(conn, vehicle["id"])
        return {"ok": True}


@route("DELETE", "/api/service/{rid}")
def delete_service(req, rid):
    with store.get_conn() as conn:
        conn.execute("DELETE FROM service_records WHERE id=?", (int(rid),))
        return {"ok": True}


# ------------------------------------------------------------------ 提醒
@route("GET", "/api/reminders")
def list_reminders(req):
    with store.get_conn() as conn:
        vehicles = [dict(r) for r in conn.execute("SELECT * FROM vehicles WHERE archived = 0 ORDER BY id")]
        return {"items": calc.build_reminders(conn, vehicles)}


@route("POST", "/api/reminders")
def create_reminder(req):
    body = req.json()
    title = (body.get("title") or "").strip()
    if not title:
        raise ApiError(422, "提醒标题不能为空")
    with store.get_conn() as conn:
        vehicle = _vehicle(conn, body.get("vehicle_id"))
        cur = conn.execute(
            "INSERT INTO reminders(vehicle_id, title, due_date, due_odometer, note, status, created_at)"
            " VALUES(?,?,?,?,?, 'open', ?)",
            (vehicle["id"], title, _optional_date(body.get("due_date")),
             _num(body.get("due_odometer")), _text(body.get("note")), store.now_iso()),
        )
        return {"id": int(cur.lastrowid)}


@route("POST", "/api/reminders/{rid}/done")
def done_reminder(req, rid):
    with store.get_conn() as conn:
        conn.execute("UPDATE reminders SET status='done', done_at=? WHERE id=?", (store.now_iso(), int(rid)))
        return {"ok": True}


@route("DELETE", "/api/reminders/{rid}")
def delete_reminder(req, rid):
    with store.get_conn() as conn:
        conn.execute("DELETE FROM reminders WHERE id=?", (int(rid),))
        return {"ok": True}


# ------------------------------------------------------------------ 总览
@route("GET", "/api/overview")
def get_overview(req):
    with store.get_conn() as conn:
        vehicles = [dict(r) for r in conn.execute("SELECT * FROM vehicles WHERE archived = 0 ORDER BY id")]
        return calc.overview(conn, vehicles)


# ------------------------------------------------------------------ Hermes 智能录入
@route("POST", "/api/ai/parse")
def ai_parse(req):
    body = req.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise ApiError(422, "请输入要记录的内容")
    with store.get_conn() as conn:
        vehicles = [dict(r) for r in conn.execute("SELECT * FROM vehicles ORDER BY id")]
        settings = store.get_settings(conn)
    if not vehicles:
        raise ApiError(400, "请先建立车辆档案，再进行自然语言录入")

    default_vid = body.get("vehicle_id")
    try:
        default_vid = int(default_vid) if default_vid not in (None, "") else None
    except (TypeError, ValueError):
        default_vid = None
    if not default_vid and settings.get("default_vehicle_id"):
        try:
            default_vid = int(settings["default_vehicle_id"])
        except ValueError:
            default_vid = None

    source, error, items = "hermes", None, None
    if settings.get("ai_enabled") == "1":
        try:
            items, error = nlp.call_hermes(text, settings, vehicles, default_vid)
        except Exception as exc:  # 网络/服务异常一律降级
            error = f"Hermes 调用失败：{type(exc).__name__}: {exc}"
            items = None
    else:
        error = "Hermes 已在设置中停用"

    if items is None:
        source = "rule"
        items = nlp.rule_parse(text, vehicles, default_vid)

    return {
        "ok": True,
        "source": source,
        "model": settings.get("ai_model") if source == "hermes" else "本地规则引擎",
        "fallback_reason": error,
        "items": items,
    }


@route("POST", "/api/ai/commit")
def ai_commit(req):
    items = req.json()
    if isinstance(items, dict):
        items = items.get("items") or []
    if not isinstance(items, list) or not items:
        raise ApiError(422, "没有可保存的记录")
    created, errors = [], []
    with store.get_conn() as conn:
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                if item.get("record_type") == "service":
                    rid = save_service(conn, item, "hermes")
                    created.append({"record_type": "service", "id": rid})
                else:
                    rid = save_energy(conn, item, "hermes")
                    created.append({"record_type": "energy", "id": rid})
                _touch_vehicle(conn, item.get("vehicle_id"))
            except ApiError as exc:
                errors.append(exc.detail)
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
    return {"ok": not errors, "created": created, "errors": errors}


@route("POST", "/api/ai/test")
def ai_test(req):
    with store.get_conn() as conn:
        settings = store.get_settings(conn)
        vehicles = [dict(r) for r in conn.execute("SELECT * FROM vehicles ORDER BY id")]
    if not vehicles:
        return {"ok": False, "message": "请先建立车辆档案后再测试"}
    try:
        items, error = nlp.call_hermes(
            "测试：今天加满 40 升，里程 10000，花了 320 元", settings, vehicles, vehicles[0]["id"]
        )
    except Exception as exc:
        return {"ok": False, "message": f"连接失败：{type(exc).__name__}: {exc}"}
    if items is None:
        return {"ok": False, "message": error or "连接失败"}
    return {"ok": True, "message": f"Hermes 连接正常，已解析 {len(items)} 条记录", "sample": items[0] if items else None}


# ------------------------------------------------------------------ 设置
@route("GET", "/api/settings")
def get_settings(req):
    with store.get_conn() as conn:
        return store.get_settings(conn)


@route("PUT", "/api/settings")
def put_settings(req):
    body = req.json()
    if not isinstance(body, dict):
        raise ApiError(422, "设置项格式不正确")
    with store.get_conn() as conn:
        return store.save_settings(conn, body)


# ------------------------------------------------------------------ 备份 / 导出 / 恢复
@route("GET", "/api/export/json")
def export_json(req):
    with store.get_conn() as conn:
        settings = store.get_settings(conn)
        payload = backup.build_backup(conn, settings)
        conn.execute("UPDATE settings SET value=? WHERE key='last_backup_at'", (store.now_iso(),))
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    filename = backup.export_filename("garage-backup", "json")
    return Raw(
        body,
        "application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@route("GET", "/api/export/csv")
def export_csv(req):
    table = req.arg("table", "energy")
    if table not in ("energy", "service", "vehicles"):
        raise ApiError(422, "table 仅支持 energy / service / vehicles")
    with store.get_conn() as conn:
        text, filename = backup.to_csv(conn, table)
    return Raw(
        text.encode("utf-8"),
        "text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@route("POST", "/api/import")
def import_backup(req):
    require_admin(req)
    body = req.json()
    if not isinstance(body, dict):
        raise ApiError(422, "备份文件格式不正确")
    mode = body.get("mode") or "merge"
    if mode not in ("merge", "replace"):
        mode = "merge"
    try:
        data = backup.load_backup_payload(body.get("data"))
    except ValueError as exc:
        raise ApiError(422, str(exc))
    with store.get_conn() as conn:
        if mode == "replace":
            for table in ("energy_records", "service_records", "reminders", "vehicles"):
                conn.execute(f"DELETE FROM {table}")
        return _import_payload(conn, data, mode)


def _parse_multipart(content_type: str, body: bytes) -> dict:
    match = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not match:
        raise ApiError(422, "缺少 multipart boundary")
    boundary = ("--" + match.group(1)).encode()
    parts: dict[str, bytes] = {}
    for chunk in body.split(boundary):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        if b"\r\n\r\n" not in chunk:
            continue
        head, data = chunk.split(b"\r\n\r\n", 1)
        disposition = ""
        for line in head.decode("utf-8", errors="replace").split("\r\n"):
            if line.lower().startswith("content-disposition"):
                disposition = line
                break
        name_match = re.search(r'name="([^"]*)"', disposition)
        if not name_match:
            continue
        parts[name_match.group(1)] = data.rstrip(b"\r\n")
    return parts


@route("POST", "/api/import/csv")
def import_csv(req):
    require_admin(req)
    table = req.arg("table", "energy")
    if table not in ("energy", "service"):
        raise ApiError(422, "CSV 导入仅支持 energy / service 两类明细")
    parts = _parse_multipart(req.handler.headers.get("Content-Type", ""), req.body)
    raw = parts.get("file") or next((v for v in parts.values() if v), None)
    if not raw:
        raise ApiError(422, "未收到 CSV 文件")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("gbk", errors="replace")
    try:
        rows = backup.parse_csv(text, table)
    except ValueError as exc:
        raise ApiError(422, str(exc))
    with store.get_conn() as conn:
        vehicles = [dict(r) for r in conn.execute("SELECT * FROM vehicles ORDER BY id")]
        by_name = {v["name"]: v["id"] for v in vehicles}
        valid_ids = {v["id"] for v in vehicles}
        imported, skipped = 0, 0
        for row in rows:
            vid = row.get("vehicle_id")
            if not vid:
                vid = by_name.get(str(row.get("vehicle_name") or "").strip())
            if not vid or int(vid) not in valid_ids:
                skipped += 1
                continue
            data = {k: v for k, v in row.items() if k != "vehicle_name"}
            data["vehicle_id"] = int(vid)
            try:
                if table == "energy":
                    save_energy(conn, data, "import")
                else:
                    save_service(conn, data, "import")
                imported += 1
            except ApiError:
                skipped += 1
    return {"ok": True, "imported": imported, "skipped": skipped}


def _import_payload(conn, data, mode):
    id_map: dict[int, int] = {}
    created_vehicles = 0
    existing = [dict(r) for r in conn.execute("SELECT id, name, plate FROM vehicles")]
    now = store.now_iso()

    for v in data.get("vehicles") or []:
        if not isinstance(v, dict) or not v.get("name"):
            continue
        try:
            old_id = int(v.get("id") or 0)
        except (TypeError, ValueError):
            old_id = 0
        match = None
        for e in existing:
            if v.get("plate") and e.get("plate") == v.get("plate"):
                match = e
                break
            if not v.get("plate") and e.get("name") == v.get("name"):
                match = e
                break
        if mode == "merge" and match:
            id_map[old_id] = match["id"]
            continue
        cur = conn.execute(
            "INSERT INTO vehicles(name, plate, vtype, brand, model, year, color, vin, init_odometer,"
            " tank_capacity, battery_capacity, insurer, policy_no, insurance_due, inspect_due, tax_due,"
            " register_date, tire_spec, note, archived, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                v["name"], v.get("plate"), v.get("vtype") or "ice", v.get("brand"), v.get("model"),
                v.get("year"), v.get("color"), v.get("vin"), v.get("init_odometer") or 0,
                v.get("tank_capacity"), v.get("battery_capacity"), v.get("insurer"), v.get("policy_no"),
                v.get("insurance_due"), v.get("inspect_due"), v.get("tax_due"), v.get("register_date"),
                v.get("tire_spec"), v.get("note"), v.get("archived") or 0, v.get("created_at") or now, now,
            ),
        )
        new_id = int(cur.lastrowid)
        if old_id:
            id_map[old_id] = new_id
        created_vehicles += 1

    def resolve(old_vid):
        try:
            key = int(old_vid)
        except (TypeError, ValueError):
            return None
        if key in id_map:
            return id_map[key]
        return key if any(r["id"] == key for r in existing) else None

    energy_count = service_count = skipped = 0
    for r in data.get("energy_records") or []:
        vid = resolve(r.get("vehicle_id"))
        if not vid:
            skipped += 1
            continue
        if mode == "merge":
            dup = conn.execute(
                "SELECT 1 FROM energy_records WHERE vehicle_id=? AND date=? AND quantity=? AND COALESCE(cost,0)=COALESCE(?,0)",
                (vid, r.get("date"), r.get("quantity"), r.get("cost")),
            ).fetchone()
            if dup:
                skipped += 1
                continue
        conn.execute(
            "INSERT INTO energy_records(vehicle_id, kind, date, odometer, quantity, unit_price, cost, station,"
            " is_full, range_delta, soc_start, soc_end, note, source, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                vid, r.get("kind") or "fuel", r.get("date"), r.get("odometer"), r.get("quantity"),
                r.get("unit_price"), r.get("cost"), r.get("station"), r.get("is_full", 1),
                r.get("range_delta"), r.get("soc_start"), r.get("soc_end"), r.get("note"),
                r.get("source") or "import", r.get("created_at") or now,
            ),
        )
        energy_count += 1

    for r in data.get("service_records") or []:
        vid = resolve(r.get("vehicle_id"))
        if not vid:
            skipped += 1
            continue
        if mode == "merge":
            dup = conn.execute(
                "SELECT 1 FROM service_records WHERE vehicle_id=? AND date=? AND items=? AND COALESCE(cost,0)=COALESCE(?,0)",
                (vid, r.get("date"), r.get("items"), r.get("cost")),
            ).fetchone()
            if dup:
                skipped += 1
                continue
        conn.execute(
            "INSERT INTO service_records(vehicle_id, rtype, date, odometer, items, cost, shop, note,"
            " next_date, next_odometer, source, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                vid, r.get("rtype") or "maintenance", r.get("date"), r.get("odometer"), r.get("items"),
                r.get("cost"), r.get("shop"), r.get("note"), r.get("next_date"), r.get("next_odometer"),
                r.get("source") or "import", r.get("created_at") or now,
            ),
        )
        service_count += 1

    reminders = 0
    for r in data.get("reminders") or []:
        vid = resolve(r.get("vehicle_id"))
        if not vid:
            continue
        conn.execute(
            "INSERT INTO reminders(vehicle_id, title, due_date, due_odometer, note, status, done_at, created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (vid, r.get("title") or "提醒", r.get("due_date"), r.get("due_odometer"), r.get("note"),
             r.get("status") or "open", r.get("done_at"), r.get("created_at") or now),
        )
        reminders += 1

    return {
        "ok": True,
        "mode": mode,
        "imported": {
            "vehicles": created_vehicles,
            "energy": energy_count,
            "service": service_count,
            "reminders": reminders,
        },
        "skipped": skipped,
    }


# ------------------------------------------------------------------ 维护
@route("POST", "/api/demo-seed")
def demo_seed(req):
    require_admin(req)
    with store.get_conn() as conn:
        if conn.execute("SELECT COUNT(*) c FROM vehicles").fetchone()["c"] > 0:
            raise ApiError(409, "已存在车辆档案，示例数据仅在空库时载入")
        result = _seed(conn)
    return {"ok": True, **result}


@route("DELETE", "/api/data")
def clear_data(req):
    require_admin(req)
    if req.arg("confirm") != "DELETE":
        raise ApiError(422, "需提供 confirm=DELETE")
    with store.get_conn() as conn:
        for table in ("energy_records", "service_records", "reminders", "vehicles"):
            conn.execute(f"DELETE FROM {table}")
    return {"ok": True}


def _seed(conn):
    today = date.today()
    now = store.now_iso()

    def d(days_ago):
        return (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")

    cur = conn.execute(
        "INSERT INTO vehicles(name, plate, vtype, brand, model, year, color, vin, init_odometer, tank_capacity,"
        " battery_capacity, insurer, policy_no, insurance_due, inspect_due, tax_due, register_date, tire_spec,"
        " note, archived, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
        ("小鹏 G6", "京A·D8821", "ev", "小鹏", "G6 755 Max", 2024, "星阙灰",
         "L1NNSGHB1R0123456", 12600, None, 66.0, "中国人保", "PICC-2026-882134",
         (today + timedelta(days=68)).strftime("%Y-%m-%d"),
         (today + timedelta(days=24)).strftime("%Y-%m-%d"),
         (today + timedelta(days=140)).strftime("%Y-%m-%d"),
         "2024-05-18", "235/50 R19", "家充为主，偶尔使用超充", now, now),
    )
    ev_id = int(cur.lastrowid)

    cur = conn.execute(
        "INSERT INTO vehicles(name, plate, vtype, brand, model, year, color, vin, init_odometer, tank_capacity,"
        " battery_capacity, insurer, policy_no, insurance_due, inspect_due, tax_due, register_date, tire_spec,"
        " note, archived, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
        ("大众 途观 L", "京N·5F236", "ice", "上汽大众", "途观 L 330TSI", 2021, "曜石黑",
         "LSVUC60T8M2123456", 68200, 60.0, None, "平安车险", "PAIC-2026-556677",
         (today + timedelta(days=12)).strftime("%Y-%m-%d"),
         (today + timedelta(days=210)).strftime("%Y-%m-%d"),
         (today + timedelta(days=320)).strftime("%Y-%m-%d"),
         "2021-03-09", "235/55 R18", "通勤用车", now, now),
    )
    ice_id = int(cur.lastrowid)

    ev_rows = [
        (150, 12880, 41.2, 0.58, 22, 90, "小桔充电·望京 SOHO", 320),
        (132, 13240, 44.6, 0.62, 18, 92, "特来电·酒仙桥", 330),
        (118, 13610, 39.8, 0.55, 30, 95, "家充桩", 300),
        (101, 13980, 46.1, 0.68, 15, 90, "国家电网·朝阳大悦城", 340),
        (86, 14350, 42.5, 0.60, 20, 88, "小桔充电·三里屯", 310),
        (70, 14730, 45.3, 0.58, 25, 95, "家充桩", 330),
        (55, 15110, 40.7, 1.35, 12, 80, "特斯拉超充·蓝色港湾", 250),
        (41, 15480, 43.9, 0.57, 28, 93, "家充桩", 320),
        (27, 15860, 44.2, 0.59, 19, 91, "特来电·望京", 330),
        (13, 16230, 41.8, 0.61, 24, 90, "家充桩", 300),
        (4, 16590, 45.6, 0.58, 16, 94, "小桔充电·国贸", 340),
    ]
    for days, odo, kwh, price, soc_start, soc_end, station, rng in ev_rows:
        conn.execute(
            "INSERT INTO energy_records(vehicle_id, kind, date, odometer, quantity, unit_price, cost, station,"
            " is_full, range_delta, soc_start, soc_end, note, source, created_at) VALUES(?,?,?,?,?,?,?,?,1,?,?,?,?,?,?)",
            (ev_id, "charge", d(days), odo, kwh, price,
             round(kwh * price, 2), station, rng, soc_start, soc_end, None, "seed", now),
        )

    ice_rows = [
        (144, 68760, 46.8, 7.86, 368, "中石化·望京加油站"),
        (126, 69340, 51.2, 7.92, 405, "中石油·京密路"),
        (110, 69980, 48.5, 8.05, 390, "中石化·酒仙桥"),
        (95, 70610, 44.2, 7.78, 344, "壳牌·大山子"),
        (78, 71250, 52.6, 8.11, 427, "中石化·望京加油站"),
        (62, 71900, 47.3, 7.95, 376, "中石油·京密路"),
        (47, 72540, 50.1, 8.22, 412, "中石化·酒仙桥"),
        (31, 73120, 45.9, 7.88, 362, "壳牌·大山子"),
        (17, 73680, 49.4, 8.02, 396, "中石化·望京加油站"),
        (5, 74210, 47.7, 8.15, 389, "中石油·京密路"),
    ]
    for days, odo, liters, price, cost, station in ice_rows:
        conn.execute(
            "INSERT INTO energy_records(vehicle_id, kind, date, odometer, quantity, unit_price, cost, station,"
            " is_full, range_delta, soc_start, soc_end, note, source, created_at) VALUES(?,?,?,?,?,?,?,?,1,NULL,NULL,NULL,?,?,?)",
            (ice_id, "fuel", d(days), odo, liters, price, cost, station, "95 号", "seed", now),
        )

    conn.execute(
        "INSERT INTO service_records(vehicle_id, rtype, date, odometer, items, cost, shop, note, next_date,"
        " next_odometer, source, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (ev_id, "maintenance", d(120), 13520, "更换空调滤芯 · 四轮换位", 320, "小鹏汽车望京服务中心",
         "首保后第二次常规检查", (today + timedelta(days=110)).strftime("%Y-%m-%d"), 26000, "seed", now),
    )
    conn.execute(
        "INSERT INTO service_records(vehicle_id, rtype, date, odometer, items, cost, shop, note, next_date,"
        " next_odometer, source, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (ice_id, "maintenance", d(78), 71250, "更换机油机滤（全合成 5W-30）", 680, "上汽大众 4S 店",
         "同时检查刹车片厚度，余量充足", (today + timedelta(days=100)).strftime("%Y-%m-%d"), 81000, "seed", now),
    )
    conn.execute(
        "INSERT INTO service_records(vehicle_id, rtype, date, odometer, items, cost, shop, note, next_date,"
        " next_odometer, source, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (ice_id, "repair", d(35), 72980, "更换前刹车片 + 刹车盘光盘", 1450, "博世汽车服务·酒仙桥",
         "高速制动抖动，光盘后消除", None, None, "seed", now),
    )
    conn.execute(
        "INSERT INTO service_records(vehicle_id, rtype, date, odometer, items, cost, shop, note, next_date,"
        " next_odometer, source, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (ev_id, "expense", d(20), 16230, "洗车 + 内饰清洁", 88, "车享家·望京店",
         "月度精洗", None, None, "seed", now),
    )
    conn.execute(
        "INSERT INTO reminders(vehicle_id, title, due_date, due_odometer, note, status, created_at)"
        " VALUES(?,?,?,?,?, 'open', ?)",
        (ice_id, "轮胎换位", (today + timedelta(days=20)).strftime("%Y-%m-%d"), 78000,
         "每 10000 km 交叉换位，可延长轮胎寿命", now),
    )
    return {"vehicles": 2, "energy": len(ev_rows) + len(ice_rows), "service": 4}


# ------------------------------------------------------------------ HTTP 服务
class Handler(BaseHTTPRequestHandler):
    server_version = "GarageKeeper/" + APP_VERSION
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # 静默默认访问日志，仅记录异常
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("HEAD", head_only=True)

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _handle(self, method, head_only=False):
        self.user = None
        self._set_cookies: list[str] = []
        try:
            parsed = urllib.parse.urlsplit(self.path)
            path = urllib.parse.unquote(parsed.path)
            try:
                query = {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}
            except ValueError:
                query = {}
            body = self._read_body() if method in ("POST", "PUT", "PATCH") else b""

            if path.startswith("/api"):
                self.user = authenticate(self)
                if not self.user and path not in PUBLIC_API:
                    self._send_json(401, {"detail": "未登录或登录已过期"}, head_only)
                    return

            if method in ("GET", "HEAD") and not path.startswith("/api"):
                if self._serve_static(path, head_only):
                    return

            lookup = "GET" if method == "HEAD" else method
            for allowed_method, regex, fn in ROUTES:
                if allowed_method != lookup:
                    continue
                match = regex.match(path)
                if not match:
                    continue
                request = Request(self, method, path, query, body, self.user)
                try:
                    result = fn(request, **match.groupdict())
                except ApiError as exc:
                    self._send_json(exc.status, {"detail": exc.detail}, head_only)
                    return
                if isinstance(result, Raw):
                    self._send_raw(result, head_only)
                else:
                    self._send_json(200, result, head_only)
                return

            if path.startswith("/api"):
                self._send_json(404, {"detail": "接口不存在"}, head_only)
            else:
                self._send_json(404, {"detail": "页面不存在"}, head_only)

        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            traceback.print_exc(file=LOG)
            try:
                self._send_json(500, {"detail": f"服务器内部错误：{type(exc).__name__}"}, head_only)
            except Exception:
                pass

    def set_cookie(self, value, max_age):
        header = f"{SESSION_COOKIE}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={int(max_age)}"
        if max_age <= 0:
            header += "; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
        self._set_cookies.append(header)

    def _serve_static(self, path, head_only=False):
        if path in ("/", "/index.html"):
            target = UI_DIR / "index.html"
        elif path.startswith("/static/"):
            target = UI_DIR / path[len("/static/"):]
        elif path == "/favicon.ico":
            target = UI_DIR / "favicon.svg"
        elif path == "/favicon.svg":
            target = UI_DIR / "favicon.svg"
        else:
            return False

        try:
            resolved = target.resolve()
            if UI_DIR.resolve() not in resolved.parents and resolved != UI_DIR.resolve():
                self._send_json(403, {"detail": "禁止访问"}, head_only)
                return True
            data = resolved.read_bytes()
        except (FileNotFoundError, IsADirectoryError, OSError):
            return False

        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "image/svg+xml"):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if not head_only:
            self.wfile.write(data)
        return True

    def _send_json(self, status, payload, head_only=False):
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for cookie in getattr(self, "_set_cookies", []):
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _send_raw(self, raw, head_only=False):
        self.send_response(raw.status)
        self.send_header("Content-Type", raw.content_type)
        self.send_header("Content-Length", str(len(raw.body)))
        for key, value in raw.headers.items():
            self.send_header(key, value)
        for cookie in getattr(self, "_set_cookies", []):
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if not head_only:
            self.wfile.write(raw.body)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return
        traceback.print_exc(file=LOG)


def serve(host="0.0.0.0", port=8787, bootstrap=None):
    store.init_db(bootstrap)
    httpd = Server((host, port), Handler)
    LOG.write(f"[garage-keeper] {APP_VERSION} listening on http://{host}:{port} · data={store.DATA_DIR}\n")
    LOG.flush()
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
