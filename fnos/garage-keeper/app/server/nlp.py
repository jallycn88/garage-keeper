"""Hermes 自然语言解析：优先调用 OpenAI 兼容的 Hermes 推理服务，失败时降级为本地规则解析。"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any

import socket
import urllib.error
import urllib.request

from calc import VTYPE_LABEL

FIELD_ENERGY = ["vehicle_id", "kind", "date", "odometer", "quantity", "unit_price", "cost",
                "station", "is_full", "range_delta", "soc_start", "soc_end", "note"]
FIELD_SERVICE = ["vehicle_id", "rtype", "date", "odometer", "items", "cost", "shop", "note",
                 "next_date", "next_odometer"]

SYSTEM_PROMPT = """你是「车库管家」的记录解析引擎，职责是把车主的自然口语输入转换成严格的结构化 JSON。
今天是 {today}（星期{tweek}）。

【可用车辆】
{vehicles}

【输出要求】
1. 只输出一个 JSON 对象，不要 markdown 代码块、不要任何解释文字。
2. 结构固定为：{{"records": [ 记录对象, ... ]}}
3. 一段输入可能包含多条记录（例如既加油又保养），必须拆分为多个对象。
4. 无法确定的字段一律输出 null，绝不编造；数字必须是纯数字，不带单位。

【记录对象字段】
- target: "energy"（加油/充电）或 "service"（保养/维修/开销），必填。
- vehicle_id: 整数，从【可用车辆】中选择最匹配的一辆；无法判断时输出 null。
- date: 记录发生日期，格式 YYYY-MM-DD；"昨天""上周三"等相对时间以今天为基准换算。
- odometer: 仪表总里程，单位 km，整数或小数。
- 当 target="energy" 时：
  - kind: "fuel"（加油）或 "charge"（充电）。
  - quantity: 加油升数（L）或充电度数（kWh），必填。
  - unit_price: 单价（元/L 或 元/kWh）。
  - cost: 本次总金额（元）。
  - station: 加油站或充电站名称。
  - is_full: 是否加满/充满，布尔值，默认 true。
  - range_delta: 本次补能增加的续航里程（km），仅充电常见。
  - soc_start / soc_end: 充电前后电量百分比（0-100），仅充电。
- 当 target="service" 时：
  - rtype: "maintenance"（保养、更换、例检）、"repair"（故障维修、钣金喷漆）或 "expense"（洗车、停车、保险、罚款、装饰等）。
  - items: 项目名称，简洁中文（如"更换机油机滤"、"更换前刹车片"），必填。
  - cost: 本次费用（元）。
  - shop: 门店/修理厂/4S 店名称。
  - next_date / next_odometer: 用户明确提到的下次保养日期或里程。
- note: 备注原文要点；用户额外描述（如"用了全合成机油"）写在这里。

【硬性规则】
- 纯电车（ev）只能有 kind="charge"；燃油车（ice）只能有 kind="fuel"；插混（phev）两者皆可。
- "加满 45 升 95 号，花了 360 块" → quantity=45, cost=360, is_full=true, kind="fuel"。
- "充了 42 度电，从 20% 到 90%，花了 60 元" → quantity=42, soc_start=20, soc_end=90, cost=60, kind="charge"。
- 单价与总价只给其一时，不要臆造另一个。
- 门店名、项目名保持用户原文措辞。

【示例】
输入：昨天在壳牌加满 45 升 95 号，里程 45230，一共花了 342 元
输出：{{"records":[{{"target":"energy","vehicle_id":1,"kind":"fuel","date":"{yesterday}","odometer":45230,"quantity":45,"unit_price":null,"cost":342,"station":"壳牌","is_full":true,"range_delta":null,"soc_start":null,"soc_end":null,"note":"95 号汽油","items":null,"rtype":null,"shop":null,"next_date":null,"next_odometer":null}}]}}

输入：今天去 4S 店做保养，换了机油机滤，里程 46000，花了 680，师傅说一万公里后再来
输出：{{"records":[{{"target":"service","vehicle_id":1,"kind":null,"date":"{today}","odometer":46000,"quantity":null,"unit_price":null,"cost":680,"station":null,"is_full":null,"range_delta":null,"soc_start":null,"soc_end":null,"note":null,"items":"更换机油机滤","rtype":"maintenance","shop":"4S 店","next_date":null,"next_odometer":56000}}]}}
"""

CN_NUM = {"零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("，", "")
    text = re.sub(r"[^\d.\-]", "", text)
    if text in ("", "-", "."):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_date(value: Any, fallback: str | None = None) -> str:
    if not value:
        return fallback or date.today().strftime("%Y-%m-%d")
    text = str(value).strip()
    text = re.sub(r"[年月]", "-", text).replace("日", "").replace("/", "-").replace(".", "-")
    text = text[:10].strip("-")
    parts = [p for p in text.split("-") if p]
    try:
        if len(parts) == 1:
            d = datetime.strptime(parts[0], "%Y%m%d").date()
        elif len(parts) == 2:
            d = date(date.today().year, int(parts[0]), int(parts[1]))
        else:
            d = date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return fallback or date.today().strftime("%Y-%m-%d")
    if d > date.today() + timedelta(days=1):
        return fallback or date.today().strftime("%Y-%m-%d")
    return d.strftime("%Y-%m-%d")


def _allowed_kinds(vtype: str) -> tuple[str, ...]:
    if vtype == "ev":
        return ("charge",)
    if vtype == "phev":
        return ("fuel", "charge")
    return ("fuel",)


def _match_vehicle(text: str, vehicles: list[dict[str, Any]]) -> dict[str, Any] | None:
    hits = []
    for v in vehicles:
        for token in (v.get("plate"), v.get("name")):
            if token and len(str(token)) >= 1 and str(token) in text:
                hits.append((len(str(token)), v))
                break
    if not hits:
        return None
    hits.sort(key=lambda x: -x[0])
    return hits[0][1]


def normalize_record(raw: dict[str, Any], vehicles: list[dict[str, Any]], default_vehicle_id: int | None,
                     raw_text: str = "") -> dict[str, Any]:
    target = str(raw.get("target") or raw.get("record_type") or "").lower()
    warnings: list[str] = []

    vehicle = None
    vid = raw.get("vehicle_id")
    if vid not in (None, ""):
        vehicle = next((v for v in vehicles if v["id"] == int(vid)), None)
    if vehicle is None:
        vehicle = _match_vehicle(raw_text, vehicles)
    if vehicle is None and default_vehicle_id:
        vehicle = next((v for v in vehicles if v["id"] == default_vehicle_id), None)
    if vehicle is None and vehicles:
        vehicle = vehicles[0]
        warnings.append("未指定车辆，已默认第一辆，请核对")
    if vehicle is None:
        return {"record_type": target, "valid": False, "warnings": ["请先建立车辆档案"]}

    if not target:
        target = "energy" if raw.get("kind") in ("fuel", "charge") else "service"

    if target == "energy":
        kind = str(raw.get("kind") or "").lower()
        allowed = _allowed_kinds(vehicle["vtype"])
        if kind not in allowed:
            kind = allowed[0]
            if raw.get("kind"):
                warnings.append(f"{vehicle['name']} 不支持该补能类型，已按{VTYPE_LABEL[vehicle['vtype']]}处理")
        quantity = _to_float(raw.get("quantity"))
        unit_price = _to_float(raw.get("unit_price"))
        cost = _to_float(raw.get("cost"))
        if quantity is None:
            warnings.append("缺少加油量/充电量")
        if cost is None and quantity and unit_price:
            cost = round(quantity * unit_price, 2)
        if unit_price is None and quantity and cost:
            unit_price = round(cost / quantity, 3)
        odometer = _to_float(raw.get("odometer"))
        if odometer is None:
            warnings.append("未填写里程，油耗/电耗将无法计算")
        is_full = raw.get("is_full")
        if is_full is None:
            is_full = True
        record = {
            "record_type": "energy",
            "vehicle_id": vehicle["id"],
            "vehicle_name": vehicle["name"],
            "kind": kind,
            "date": _to_date(raw.get("date")),
            "odometer": odometer,
            "quantity": quantity,
            "unit_price": unit_price,
            "cost": cost,
            "station": (raw.get("station") or None),
            "is_full": 1 if is_full else 0,
            "range_delta": _to_float(raw.get("range_delta")),
            "soc_start": _to_float(raw.get("soc_start")),
            "soc_end": _to_float(raw.get("soc_end")),
            "note": (raw.get("note") or None),
        }
        record["valid"] = quantity is not None and quantity > 0
    else:
        rtype = str(raw.get("rtype") or "maintenance").lower()
        if rtype not in ("maintenance", "repair", "expense"):
            rtype = "maintenance"
        items = (raw.get("items") or "").strip()
        if not items:
            items = "未命名项目"
            warnings.append("缺少项目名称，已填入占位内容")
        record = {
            "record_type": "service",
            "vehicle_id": vehicle["id"],
            "vehicle_name": vehicle["name"],
            "rtype": rtype,
            "date": _to_date(raw.get("date")),
            "odometer": _to_float(raw.get("odometer")),
            "items": items,
            "cost": _to_float(raw.get("cost")),
            "shop": (raw.get("shop") or None),
            "note": (raw.get("note") or None),
            "next_date": raw.get("next_date") or None,
            "next_odometer": _to_float(raw.get("next_odometer")),
        }
        if record["next_date"]:
            record["next_date"] = _to_date(record["next_date"], fallback=None)
        record["valid"] = True

    record["warnings"] = warnings
    record["confidence"] = round(max(0.35, 0.92 - 0.12 * len(warnings)), 2)
    record["raw_text"] = raw_text
    return record


def extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?|```$", "", cleaned, flags=re.MULTILINE).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return None


def call_hermes(text, settings, vehicles, default_vehicle_id):
    """调用 OpenAI 兼容的 Hermes / Ollama 服务；返回 (记录列表, 错误信息)。"""
    base_url = (settings.get("ai_base_url") or "").rstrip("/")
    if not base_url:
        return None, "未配置 Hermes 服务地址"
    model = settings.get("ai_model") or "hermes3:8b"
    today = date.today()
    vehicle_lines = "\n".join(
        f"- id={v['id']} 名称={v['name']} 车牌={v.get('plate') or '未填'} 类型={VTYPE_LABEL.get(v['vtype'], v['vtype'])}"
        for v in vehicles
    ) or "- （暂无车辆）"
    system = SYSTEM_PROMPT.format(
        today=today.strftime("%Y-%m-%d"),
        tweek="一二三四五六日"[today.weekday()],
        yesterday=(today - timedelta(days=1)).strftime("%Y-%m-%d"),
        vehicles=vehicle_lines,
    )
    payload = {
        "model": model,
        "temperature": float(settings.get("ai_temperature") or 0.1),
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
    }
    headers = {"Content-Type": "application/json"}
    if settings.get("ai_api_key"):
        headers["Authorization"] = f"Bearer {settings['ai_api_key']}"
    timeout = float(settings.get("ai_timeout") or 60)
    url = f"{base_url}/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        return None, f"Hermes 返回 HTTP {exc.code}：{detail}"
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        return None, f"无法连接 Hermes：{getattr(exc, 'reason', exc)}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, "Hermes 返回内容不是合法 JSON"
    content = ""
    if isinstance(data, dict):
        choices = data.get("choices")
        if choices:
            content = (choices[0].get("message") or {}).get("content") or ""
        elif "message" in data:                       # Ollama 原生 /api/chat 兜底
            content = (data["message"] or {}).get("content") or ""
    parsed = extract_json(content)
    if not parsed:
        return None, "Hermes 返回内容无法解析为 JSON"
    records = parsed.get("records") if isinstance(parsed, dict) else None
    if not isinstance(records, list):
        return None, "Hermes 返回结构缺少 records 数组"
    return [normalize_record(r, vehicles, default_vehicle_id, text) for r in records], None


# ---------------------------------------------------------------- 规则降级解析

def _find(pattern: str, text: str, group: int = 1) -> re.Match[str] | None:
    return re.search(pattern, text, flags=re.IGNORECASE)


def rule_parse(text: str, vehicles: list[dict[str, Any]], default_vehicle_id: int | None) -> list[dict[str, Any]]:
    """Hermes 不可用时的兜底：覆盖「加油/充电/保养/维修」的高频表达。"""
    segments = [s.strip() for s in re.split(r"[\n;；。]+", text) if s.strip()]
    results: list[dict[str, Any]] = []
    today = date.today()

    for seg in segments:
        low = seg.lower()
        if re.search(r"保养|维修|换机油|机滤|空滤|刹车|轮胎|补胎|洗车|停车|保险|罚款|年检", seg):
            target = "service"
            if re.search(r"洗车|停车|保险|罚款|装饰|贴膜|脚垫", seg):
                rtype = "expense"
            elif re.search(r"维修|故障|补胎|钣金|喷漆|更换?刹车|异响|漏油|打不着", seg):
                rtype = "repair"
            else:
                rtype = "maintenance"
        elif re.search(r"加油|加满|加注|汽油|柴油|95|92|98", seg) or re.search(r"升", seg):
            target, rtype = "energy", None
        elif re.search(r"充|度电|kwh|千瓦时|电量", low):
            target, rtype = "energy", None
        else:
            continue

        raw: dict[str, Any] = {"target": target}
        if target == "energy":
            raw["kind"] = "charge" if re.search(r"充|度电|kwh|千瓦时|电量", low) else "fuel"

        # 日期
        d = today
        if "大前天" in seg:
            d = today - timedelta(days=3)
        elif "前天" in seg:
            d = today - timedelta(days=2)
        elif "昨天" in seg:
            d = today - timedelta(days=1)
        elif "今天" in seg or "刚刚" in seg:
            d = today
        m = _find(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", seg)
        if m:
            raw["date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        else:
            m = _find(r"(\d{1,2})[月/-](\d{1,2})[日号]?", seg)
            if m and not re.search(r"\d\s*[升度L]", m.group(0)):
                try:
                    raw["date"] = date(today.year, int(m.group(1)), int(m.group(2))).strftime("%Y-%m-%d")
                except ValueError:
                    raw["date"] = d.strftime("%Y-%m-%d")
            else:
                raw["date"] = d.strftime("%Y-%m-%d")

        # 里程
        m = _find(r"(?:里程|表显|公里数|ODO)[^\d]{0,4}(\d+(?:\.\d+)?)", seg) or \
            _find(r"(\d+(?:\.\d+)?)\s*(?:km|公里|千米)", seg)
        if m:
            raw["odometer"] = float(m.group(1))
        else:
            # 五位以上裸数字更可能是里程
            m = _find(r"(?<![\d.])(\d{4,7})(?![\d.])", seg.replace(",", ""))
            if m:
                raw["odometer"] = float(m.group(1))

        # 单价（元/升、元/度）
        price_match = _find(r"(\d+(?:\.\d+)?)\s*元?\s*/\s*(?:升|L|度|kwh|千瓦时)", seg)
        if price_match:
            raw["unit_price"] = float(price_match.group(1))
        m = _find(r"单价[^\d]{0,3}(\d+(?:\.\d+)?)", seg)
        if m and raw.get("unit_price") is None:
            raw["unit_price"] = float(m.group(1))

        # 数量
        m = _find(r"(\d+(?:\.\d+)?)\s*(?:升|L|度|kwh|千瓦时)", seg) or \
            _find(r"(?:加了|充了|充入|用电|用了)[^\d]{0,4}(\d+(?:\.\d+)?)", seg)
        if m:
            raw["quantity"] = float(m.group(1))

        # 金额：先去掉单价片段，避免把单价当总价
        stripped = seg
        if price_match:
            stripped = stripped.replace(price_match.group(0), " ")
        m = _find(r"(?:共|总价|总计|合计|花了|花费|消费|支付|付了|用了|金额)[^\d]{0,4}(\d+(?:\.\d+)?)", stripped) or \
            _find(r"(\d+(?:\.\d+)?)\s*(?:元|块|¥|RMB)", stripped)
        if m:
            raw["cost"] = float(m.group(1))

        # 电量百分比
        socs = re.findall(r"(\d{1,3})\s*%", seg)
        if len(socs) >= 2:
            raw["soc_start"], raw["soc_end"] = float(socs[0]), float(socs[1])
        elif len(socs) == 1:
            raw["soc_end"] = float(socs[0])

        if re.search(r"加满|充满|满箱|满了", seg):
            raw["is_full"] = True

        # 门店
        shop_match = _find(r"在([^，,。；;]{2,20}?)(?:加油|充电|加满|充满|保养|维修|做|换|洗车)", seg)
        shop = shop_match.group(1) if shop_match else None
        if shop:
            if target == "energy":
                raw["station"] = shop
            else:
                raw["shop"] = shop

        if target == "service":
            raw["rtype"] = rtype
            candidates = [
                m.group(1) for m in re.finditer(
                    r"(?:保养|维修|更换|换了|换|做了|补胎|洗车)([^，,。；;\d]{1,30})", seg)
            ]
            items = ""
            for cand in candidates:
                cand = re.sub(r"^(?:了|一下|一次|个|做|次|换)+", "", cand.strip())
                cand = re.sub(r"(?:了|吧|呢|的)$", "", cand.strip())
                cand = cand.strip(" ，,。")
                if len(cand) > len(items):
                    items = cand
            if not items:
                items = re.sub(r"\d+(?:\.\d+)?\s*(?:元|块|km|公里|升|度)", "", seg).strip(" ，,。")[:40]
            raw["items"] = items or "未命名项目"
            m = _find(r"(?:下次|再跑)[^\d]{0,4}(\d+(?:\.\d+)?)\s*(?:km|公里|千米)", seg)
            if m:
                raw["next_odometer"] = float(m.group(1))
            m = _find(r"(?:下次)[^\d]{0,4}(\d+)\s*个月", seg)
            if m:
                raw["next_date"] = (today + timedelta(days=int(m.group(1)) * 30)).strftime("%Y-%m-%d")

        m = _find(r"备注[:：]?\s*([^，,。；;]+)", seg)
        if m:
            raw["note"] = m.group(1).strip()

        results.append(normalize_record(raw, vehicles, default_vehicle_id, seg))

    if not results:
        results.append(normalize_record(
            {"target": "energy", "kind": "fuel"},
            vehicles, default_vehicle_id, text,
        ))
        results[-1]["valid"] = False
        results[-1]["warnings"] = ["未能识别记录类型，请补充「加油/充电/保养/维修」等关键词"]
    return results
