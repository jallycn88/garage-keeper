"""统计与提醒计算：全部基于用户自身记录推导，不做任何估算填充。"""
from __future__ import annotations

import sqlite3
from collections import OrderedDict
from datetime import date, datetime, timedelta
from typing import Any

VTYPE_LABEL = {"ice": "燃油车", "ev": "纯电动车", "phev": "插电混动"}
RTYPE_LABEL = {"maintenance": "保养", "repair": "维修", "expense": "其他开销"}
KIND_LABEL = {"fuel": "加油", "charge": "充电"}
FUEL_UNIT = "L"
CHARGE_UNIT = "kWh"


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def month_key(value: str | None) -> str | None:
    d = parse_date(value)
    return d.strftime("%Y-%m") if d else None


def recent_months(count: int = 12) -> list[str]:
    today = date.today().replace(day=1)
    out: list[str] = []
    for i in range(count - 1, -1, -1):
        y = today.year
        m = today.month - i
        while m <= 0:
            m += 12
            y -= 1
        out.append(f"{y:04d}-{m:02d}")
    return out


def consumption_points(records: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """油箱/电池「满到满」法：两笔满充（满油）之间的补能量 ÷ 行驶里程。

    仅在存在连续两笔标记为「加满/充满」且里程递增的记录时给出数值，
    因此界面上呈现的是可验证的真实油耗，而非估算值。
    """
    items = [
        r for r in records
        if r.get("kind") == kind and r.get("odometer") not in (None, "") and r.get("is_full")
    ]
    items.sort(key=lambda r: (float(r["odometer"]), r.get("date") or ""))
    points: list[dict[str, Any]] = []
    for prev, cur in zip(items, items[1:]):
        odo_prev, odo_cur = float(prev["odometer"]), float(cur["odometer"])
        distance = odo_cur - odo_prev
        if distance <= 0:
            continue
        between = [
            float(r.get("quantity") or 0)
            for r in records
            if r.get("kind") == kind
            and r.get("odometer") not in (None, "")
            and odo_prev < float(r["odometer"]) <= odo_cur
        ]
        quantity = sum(between)
        if quantity <= 0:
            continue
        points.append({
            "date": cur.get("date"),
            "odometer": round(odo_cur, 1),
            "distance": round(distance, 1),
            "quantity": round(quantity, 2),
            "value": round(quantity / distance * 100, 2),
        })
    return points


def consumption_average(points: list[dict[str, Any]]) -> float | None:
    distance = sum(p["distance"] for p in points)
    quantity = sum(p["quantity"] for p in points)
    if distance <= 0 or quantity <= 0:
        return None
    return round(quantity / distance * 100, 2)


def monthly_costs(conn: sqlite3.Connection, vehicle_id: int | None = None, months: int = 12) -> list[dict[str, Any]]:
    keys = recent_months(months)
    bucket: dict[str, dict[str, float]] = {k: {"energy": 0.0, "service": 0.0} for k in keys}
    params: list[Any] = []
    where = ""
    if vehicle_id:
        where = " WHERE vehicle_id = ?"
        params = [vehicle_id]
    for table, field in (("energy_records", "energy"), ("service_records", "service")):
        sql = f"SELECT date, cost FROM {table}{where}"
        for row in conn.execute(sql, params):
            key = month_key(row["date"])
            if key and key in bucket:
                bucket[key][field] += float(row["cost"] or 0)
    return [
        {
            "month": k,
            "label": f"{int(k[5:7])}月",
            "energy": round(v["energy"], 2),
            "service": round(v["service"], 2),
            "total": round(v["energy"] + v["service"], 2),
        }
        for k, v in bucket.items()
    ]


def vehicle_summary(conn: sqlite3.Connection, vehicle: dict[str, Any]) -> dict[str, Any]:
    vid = vehicle["id"]
    energy = [dict(r) for r in conn.execute(
        "SELECT * FROM energy_records WHERE vehicle_id = ? ORDER BY date, id", (vid,)
    )]
    service = [dict(r) for r in conn.execute(
        "SELECT * FROM service_records WHERE vehicle_id = ? ORDER BY date, id", (vid,)
    )]

    odometers = [float(r["odometer"]) for r in energy + service if r.get("odometer") not in (None, "")]
    odometers.append(float(vehicle.get("init_odometer") or 0))
    current_odo = max(odometers)

    fuel_points = consumption_points(energy, "fuel")
    charge_points = consumption_points(energy, "charge")

    energy_cost = sum(float(r["cost"] or 0) for r in energy)
    service_cost = sum(float(r["cost"] or 0) for r in service if r.get("rtype") in ("maintenance", "repair"))
    expense_cost = sum(float(r["cost"] or 0) for r in service if r.get("rtype") == "expense")
    total_cost = energy_cost + service_cost + expense_cost

    distance = current_odo - float(vehicle.get("init_odometer") or 0)
    this_month = date.today().strftime("%Y-%m")
    month_cost = sum(
        float(r["cost"] or 0)
        for r in energy + service
        if month_key(r.get("date")) == this_month
    )

    last_energy = max(energy, key=lambda r: (r.get("date") or "", r["id"]), default=None)
    last_service = max(service, key=lambda r: (r.get("date") or "", r["id"]), default=None)

    def avg_price(kind: str) -> float | None:
        rows = [r for r in energy if r["kind"] == kind and r.get("unit_price")]
        if not rows:
            return None
        q = sum(float(r["quantity"] or 0) for r in rows)
        c = sum(float(r["cost"] or 0) for r in rows)
        return round(c / q, 3) if q else None

    return {
        "vehicle": vehicle,
        "current_odometer": round(current_odo, 1),
        "total_distance": round(distance, 1),
        "record_count": len(energy) + len(service),
        "energy_count": len(energy),
        "service_count": len(service),
        "energy_cost": round(energy_cost, 2),
        "service_cost": round(service_cost, 2),
        "expense_cost": round(expense_cost, 2),
        "total_cost": round(total_cost, 2),
        "month_cost": round(month_cost, 2),
        "cost_per_km": round(total_cost / distance, 3) if distance > 0 else None,
        "fuel_consumption": consumption_average(fuel_points),
        "fuel_points": fuel_points[-12:],
        "fuel_avg_price": avg_price("fuel"),
        "charge_consumption": consumption_average(charge_points),
        "charge_points": charge_points[-12:],
        "charge_avg_price": avg_price("charge"),
        "charge_total_kwh": round(sum(float(r["quantity"] or 0) for r in energy if r["kind"] == "charge"), 2),
        "fuel_total_l": round(sum(float(r["quantity"] or 0) for r in energy if r["kind"] == "fuel"), 2),
        "last_energy": last_energy,
        "last_service": last_service,
        "monthly": monthly_costs(conn, vid),
    }


def latest_maintenance(conn: sqlite3.Connection, vehicle_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM service_records WHERE vehicle_id = ? AND rtype IN ('maintenance','repair') "
        "AND (next_date IS NOT NULL AND next_date <> '' OR next_odometer IS NOT NULL) "
        "ORDER BY date DESC, id DESC LIMIT 1",
        (vehicle_id,),
    ).fetchone()
    return dict(row) if row else None


def build_reminders(conn: sqlite3.Connection, vehicles: list[dict[str, Any]], today: date | None = None) -> list[dict[str, Any]]:
    """合并三类提醒源：法定到期日、保养周期（日期+里程双条件）、自定义提醒。"""
    today = today or date.today()
    odo_map: dict[int, float] = {}
    for v in vehicles:
        vals = [float(v.get("init_odometer") or 0)]
        for r in conn.execute(
            "SELECT odometer FROM energy_records WHERE vehicle_id = ? AND odometer IS NOT NULL "
            "UNION ALL SELECT odometer FROM service_records WHERE vehicle_id = ? AND odometer IS NOT NULL",
            (v["id"], v["id"]),
        ):
            vals.append(float(r["odometer"]))
        odo_map[v["id"]] = max(vals)

    items: list[dict[str, Any]] = []

    def add(vehicle, title, due_date, due_odo, source, note="", rid=None, editable=False):
        days_left = (parse_date(due_date) - today).days if due_date else None
        km_left = round(due_odo - odo_map.get(vehicle["id"], 0), 1) if due_odo is not None else None
        levels = []
        if days_left is not None:
            levels.append("overdue" if days_left < 0 else ("soon" if days_left <= 30 else "ok"))
        if km_left is not None:
            levels.append("overdue" if km_left < 0 else ("soon" if km_left <= 1000 else "ok"))
        if "overdue" in levels:
            level = "overdue"
        elif "soon" in levels:
            level = "soon"
        else:
            level = "ok"
        items.append({
            "id": rid,
            "editable": editable,
            "source": source,
            "vehicle_id": vehicle["id"],
            "vehicle_name": vehicle["name"],
            "plate": vehicle.get("plate"),
            "title": title,
            "due_date": due_date,
            "due_odometer": due_odo,
            "current_odometer": odo_map.get(vehicle["id"], 0),
            "days_left": days_left,
            "km_left": km_left,
            "level": level,
            "note": note,
        })

    for v in vehicles:
        if v.get("insurance_due"):
            add(v, "保险到期", v["insurance_due"], None, "statutory", "交强险/商业险续保")
        if v.get("inspect_due"):
            add(v, "年检到期", v["inspect_due"], None, "statutory", "车辆安全技术检验")
        if v.get("tax_due"):
            add(v, "车船税缴纳", v["tax_due"], None, "statutory", "按登记地规定缴纳")
        m = latest_maintenance(conn, v["id"])
        if m and (m.get("next_date") or m.get("next_odometer")):
            add(
                v,
                f"下次保养：{m['items']}",
                m.get("next_date"),
                m.get("next_odometer"),
                "maintenance",
                f"上次 {m['date']} · {m['items']}",
            )

    for r in conn.execute("SELECT * FROM reminders WHERE status = 'open' ORDER BY created_at DESC"):
        row = dict(r)
        vehicle = next((v for v in vehicles if v["id"] == row["vehicle_id"]), None)
        if not vehicle:
            continue
        add(vehicle, row["title"], row.get("due_date"), row.get("due_odometer"), "custom", row.get("note") or "",
            rid=row["id"], editable=True)

    rank = {"overdue": 0, "soon": 1, "ok": 2}
    items.sort(key=lambda x: (rank[x["level"]], x["days_left"] if x["days_left"] is not None else 99999,
                              x["km_left"] if x["km_left"] is not None else 999999))
    return items


def overview(conn: sqlite3.Connection, vehicles: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = [vehicle_summary(conn, v) for v in vehicles]
    total_cost = round(sum(s["total_cost"] for s in summaries), 2)
    total_distance = round(sum(s["total_distance"] for s in summaries), 1)
    month_cost = round(sum(s["month_cost"] for s in summaries), 2)
    energy_cost = round(sum(s["energy_cost"] for s in summaries), 2)
    service_cost = round(sum(s["service_cost"] for s in summaries), 2)
    fuel_points: list[dict[str, Any]] = []
    charge_points: list[dict[str, Any]] = []
    for s in summaries:
        fuel_points.extend(s["fuel_points"])
        charge_points.extend(s["charge_points"])
    reminders = build_reminders(conn, vehicles)

    recent: list[dict[str, Any]] = []
    for v in vehicles:
        for r in conn.execute(
            "SELECT * FROM energy_records WHERE vehicle_id = ? ORDER BY date DESC, id DESC LIMIT 6", (v["id"],)
        ):
            row = dict(r)
            recent.append({
                "record_type": "energy", "id": row["id"], "vehicle_id": v["id"], "vehicle_name": v["name"],
                "date": row["date"], "title": KIND_LABEL.get(row["kind"], "补能"),
                "detail": f"{row['quantity']:g} {'kWh' if row['kind'] == 'charge' else 'L'}",
                "cost": row["cost"], "odometer": row["odometer"],
            })
        for r in conn.execute(
            "SELECT * FROM service_records WHERE vehicle_id = ? ORDER BY date DESC, id DESC LIMIT 6", (v["id"],)
        ):
            row = dict(r)
            recent.append({
                "record_type": "service", "id": row["id"], "vehicle_id": v["id"], "vehicle_name": v["name"],
                "date": row["date"], "title": RTYPE_LABEL.get(row["rtype"], "保养"),
                "detail": row["items"], "cost": row["cost"], "odometer": row["odometer"],
            })
    recent.sort(key=lambda x: (x["date"] or "", x["id"]), reverse=True)

    return {
        "vehicle_count": len(vehicles),
        "total_cost": total_cost,
        "month_cost": month_cost,
        "total_distance": total_distance,
        "energy_cost": energy_cost,
        "service_cost": service_cost,
        "monthly": monthly_costs(conn, None),
        "consumption": {
            "fuel": consumption_average(fuel_points),
            "charge": consumption_average(charge_points),
        },
        "next_reminder": reminders[0] if reminders else None,
        "reminder_count": len([r for r in reminders if r["level"] != "ok"]),
        "recent": recent[:10],
        "vehicles": summaries,
    }
