"""备份、CSV 导出与导入。备份为可读 JSON，CSV 用于 Excel / 修理厂对账。"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any

BACKUP_VERSION = 1

ENERGY_HEADERS = [
    ("id", "记录ID"), ("vehicle_id", "车辆ID"), ("vehicle_name", "车辆"), ("kind_label", "类型"),
    ("date", "日期"), ("odometer", "里程(km)"), ("quantity", "数量(L或kWh)"), ("unit_price", "单价(元)"),
    ("cost", "金额(元)"), ("station", "门店/站点"), ("is_full", "是否加满"), ("range_delta", "续航增加(km)"),
    ("soc_start", "起始电量(%)"), ("soc_end", "结束电量(%)"), ("note", "备注"),
]

SERVICE_HEADERS = [
    ("id", "记录ID"), ("vehicle_id", "车辆ID"), ("vehicle_name", "车辆"), ("rtype_label", "类型"),
    ("date", "日期"), ("odometer", "里程(km)"), ("items", "项目"), ("cost", "金额(元)"),
    ("shop", "门店"), ("note", "备注"), ("next_date", "下次日期"), ("next_odometer", "下次里程(km)"),
]

VEHICLE_HEADERS = [
    ("id", "记录ID"), ("name", "名称"), ("plate", "车牌"), ("vtype_label", "动力类型"), ("brand", "品牌"),
    ("model", "车型"), ("year", "年款"), ("vin", "车架号"), ("init_odometer", "初始里程(km)"),
    ("tank_capacity", "油箱容积(L)"), ("battery_capacity", "电池容量(kWh)"), ("insurer", "保险公司"),
    ("policy_no", "保单号"), ("insurance_due", "保险到期"), ("inspect_due", "年检到期"),
    ("tax_due", "车船税到期"), ("note", "备注"),
]

KIND_LABEL = {"fuel": "加油", "charge": "充电"}
RTYPE_LABEL = {"maintenance": "保养", "repair": "维修", "expense": "其他开销"}
VTYPE_LABEL = {"ice": "燃油车", "ev": "纯电动车", "phev": "插电混动"}


def _vehicle_names(conn) -> dict[int, str]:
    return {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM vehicles")}


def build_backup(conn, settings: dict[str, str]) -> dict[str, Any]:
    vehicles = [dict(r) for r in conn.execute("SELECT * FROM vehicles ORDER BY id")]
    energy = [dict(r) for r in conn.execute("SELECT * FROM energy_records ORDER BY id")]
    service = [dict(r) for r in conn.execute("SELECT * FROM service_records ORDER BY id")]
    reminders = [dict(r) for r in conn.execute("SELECT * FROM reminders ORDER BY id")]
    safe_settings = {k: v for k, v in settings.items() if not k.startswith("ai_api_key")}
    return {
        "app": "garage-keeper",
        "version": BACKUP_VERSION,
        "exported_at": datetime.now().replace(microsecond=0).isoformat(),
        "stats": {
            "vehicles": len(vehicles),
            "energy_records": len(energy),
            "service_records": len(service),
        },
        "settings": safe_settings,
        "vehicles": vehicles,
        "energy_records": energy,
        "service_records": service,
        "reminders": reminders,
    }


def export_filename(prefix: str, ext: str) -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M')}.{ext}"


def _csv_text(headers: list[tuple[str, str]], rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in headers])
    for row in rows:
        out = []
        for key, _ in headers:
            value = row.get(key)
            if key == "is_full":
                value = "是" if value else "否"
            out.append("" if value is None else value)
        writer.writerow(out)
    return "\ufeff" + buf.getvalue()


def to_csv(conn, table: str) -> tuple[str, str]:
    names = _vehicle_names(conn)
    if table == "vehicles":
        rows = [dict(r) for r in conn.execute("SELECT * FROM vehicles ORDER BY id")]
        for r in rows:
            r["vtype_label"] = VTYPE_LABEL.get(r["vtype"], r["vtype"])
        return _csv_text(VEHICLE_HEADERS, rows), export_filename("vehicles", "csv")
    if table == "service":
        rows = [dict(r) for r in conn.execute("SELECT * FROM service_records ORDER BY date, id")]
        for r in rows:
            r["vehicle_name"] = names.get(r["vehicle_id"], "")
            r["rtype_label"] = RTYPE_LABEL.get(r["rtype"], r["rtype"])
        return _csv_text(SERVICE_HEADERS, rows), export_filename("service-records", "csv")
    rows = [dict(r) for r in conn.execute("SELECT * FROM energy_records ORDER BY date, id")]
    for r in rows:
        r["vehicle_name"] = names.get(r["vehicle_id"], "")
        r["kind_label"] = KIND_LABEL.get(r["kind"], r["kind"])
    return _csv_text(ENERGY_HEADERS, rows), export_filename("energy-records", "csv")


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _pick(row: dict[str, str], *keys: str) -> Any:
    for k in keys:
        if k in row and str(row[k]).strip() != "":
            return row[k]
    return None


def parse_csv(text: str, table: str) -> list[dict[str, Any]]:
    """解析本应用导出的 CSV；表头同时兼容中文与英文字段名。"""
    text = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    out: list[dict[str, Any]] = []
    for raw in reader:
        row = {(k or "").strip(): (v if v is not None else "") for k, v in raw.items()}
        if table == "energy":
            kind_label = str(_pick(row, "类型", "kind_label", "kind") or "加油")
            kind = "charge" if "充" in kind_label else "fuel"
            out.append({
                "vehicle_id": _num(_pick(row, "车辆ID", "vehicle_id")),
                "vehicle_name": _pick(row, "车辆", "vehicle_name"),
                "kind": kind,
                "date": _pick(row, "日期", "date"),
                "odometer": _num(_pick(row, "里程(km)", "里程", "odometer")),
                "quantity": _num(_pick(row, "数量(L或kWh)", "数量", "quantity")),
                "unit_price": _num(_pick(row, "单价(元)", "单价", "unit_price")),
                "cost": _num(_pick(row, "金额(元)", "金额", "cost")),
                "station": _pick(row, "门店/站点", "站点", "station"),
                "is_full": 1 if str(_pick(row, "是否加满", "is_full") or "是") in ("是", "1", "True", "true") else 0,
                "range_delta": _num(_pick(row, "续航增加(km)", "range_delta")),
                "soc_start": _num(_pick(row, "起始电量(%)", "soc_start")),
                "soc_end": _num(_pick(row, "结束电量(%)", "soc_end")),
                "note": _pick(row, "备注", "note"),
            })
        elif table == "service":
            label = str(_pick(row, "类型", "rtype_label", "rtype") or "保养")
            rtype = "repair" if "维修" in label else ("expense" if "开销" in label else "maintenance")
            out.append({
                "vehicle_id": _num(_pick(row, "车辆ID", "vehicle_id")),
                "vehicle_name": _pick(row, "车辆", "vehicle_name"),
                "rtype": rtype,
                "date": _pick(row, "日期", "date"),
                "odometer": _num(_pick(row, "里程(km)", "里程", "odometer")),
                "items": _pick(row, "项目", "items") or "未命名项目",
                "cost": _num(_pick(row, "金额(元)", "金额", "cost")),
                "shop": _pick(row, "门店", "shop"),
                "note": _pick(row, "备注", "note"),
                "next_date": _pick(row, "下次日期", "next_date"),
                "next_odometer": _num(_pick(row, "下次里程(km)", "next_odometer")),
            })
        else:
            raise ValueError("CSV 导入仅支持 energy / service 两类明细")
    return [r for r in out if r.get("date")]


def load_backup_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, str):
        payload = json.loads(payload)
    if isinstance(payload, list):
        payload = {"vehicles": payload}
    if not isinstance(payload, dict):
        raise ValueError("备份文件格式不正确")
    if "vehicles" not in payload and "energy_records" not in payload:
        raise ValueError("未找到 vehicles / energy_records 字段，可能不是本应用的备份文件")
    return payload
