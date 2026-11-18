#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Amlak Divar scraper for Dezful. Console: Finglish. Exported data: Persian."""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import webbrowser
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import jdatetime
import pandas as pd
import requests
import divar_map
import neighborhoods
import osm_city_index

API_BASE = "https://api.divar.ir/v8"
SEARCH_URL = f"{API_BASE}/postlist/w/search"
DETAIL_URL = f"{API_BASE}/posts-v2/web"
DEZFUL_CITY_ID = "23"
DIVAR_MAP_PICKER_URL = "https://divar.ir/s/dezful/buy-apartment"
PAGE_SIZE = 24
REQUEST_INTERVAL = 0.9
DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")
DB_FILE = DATA_DIR / "amlak.sqlite3"
STATE_FILE = DATA_DIR / "progress.json"
EXCEL_FILE = OUTPUT_DIR / "dezful_amlak.xlsx"
CATEGORIES = {
    "apartment-sell": "آپارتمان",
    "house-villa-sell": "ویلایی",
    "plot-old": "زمین",
}
COLUMNS = [
    "ردیف", "تاریخ انتشار", "عنوان", "دسته", "متراژ", "قیمت_کل",
    "قیمت_هر_متر", "سال_ساخت", "تعداد_اتاق", "محله", "محله_خودکار", "خیابان_خودکار", "خیابان‌های_نزدیک", "محدوده_خودکار", "اطمینان_تشخیص", "محله_نقشه", "محدوده_نقشه", "منبع_محله",
    "نوع_آگهی_دهنده", "عرض_جغرافیایی", "طول_جغرافیایی", "موقعیت_تقریبی", "توضیحات", "لینک", "توکن",
]
MONTHS = {
    "فروردین": 1, "اردیبهشت": 2, "خرداد": 3, "تیر": 4,
    "مرداد": 5, "شهریور": 6, "مهر": 7, "آبان": 8,
    "آذر": 9, "دی": 10, "بهمن": 11, "اسفند": 12,
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://divar.ir",
    "Referer": "https://divar.ir/",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
LAST_REQUEST_AT = 0.0


def say(message: str) -> None:
    print(message, flush=True)


def ascii_digits(value: Any) -> str:
    return str(value).translate(str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"
    ))


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return ""
    return str(value).replace("\u200c", " ").strip()


def parse_number(value: Any) -> Optional[int]:
    if value is None:
        return None
    raw = ascii_digits(value).replace(",", "").replace("،", "").replace("٬", "").replace(" ", "")
    match = re.search(r"\d+(?:\.\d+)?", raw)
    if not match:
        return None
    try:
        return int(float(match.group()))
    except ValueError:
        return None


def parse_money(value: Any) -> Optional[int]:
    """Parse Divar's displayed Toman values, including million/billion wording."""
    if value is None:
        return None
    raw = ascii_digits(value).replace("٬", "").replace(",", "").replace("،", "")
    match = re.search(r"\d+(?:\.\d+)?", raw)
    if not match:
        return None
    number = float(match.group())
    if "میلیارد" in raw:
        number *= 1_000_000_000
    elif "میلیون" in raw:
        number *= 1_000_000
    elif "هزار" in raw:
        number *= 1_000
    return int(number)


def parse_jalali_datetime(value: Any) -> Optional[datetime]:
    """Parse exact date text shown in the post's 'انتشار آگهی' widget."""
    text = ascii_digits(clean_text(value))
    match = re.search(
        r"(\d{1,2})\s+(فروردین|اردیبهشت|خرداد|تیر|مرداد|شهریور|مهر|آبان|آذر|دی|بهمن|اسفند)\s+(\d{4})(?:[،, ]+(\d{1,2}):(\d{2}))?",
        text,
    )
    if not match:
        return None
    day, month_name, year = int(match.group(1)), match.group(2), int(match.group(3))
    hour, minute = int(match.group(4) or 0), int(match.group(5) or 0)
    try:
        gregorian = jdatetime.datetime(year, MONTHS[month_name], day, hour, minute).togregorian()
        return gregorian.replace(tzinfo=timezone(timedelta(hours=3, minutes=30)))
    except (ValueError, OverflowError):
        return None


def jalali_input(value: str) -> date:
    text = ascii_digits(value.strip()).replace("-", "/")
    match = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", text)
    if not match:
        raise ValueError("Tarikh ra be shekle 1405/08/01 vared konid.")
    year, month, day = map(int, match.groups())
    return jdatetime.date(year, month, day).togregorian()


def load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("invalid state")
            state.setdefault("categories", {})
            state.setdefault("settings", {})
            return state
        except (OSError, ValueError, json.JSONDecodeError):
            say("HOSHdar: file vazeyat ghabele khanesh nist; file ghabli ra negah darid va backup begirid.")
    return {"version": 3, "categories": {}, "settings": {}}


def save_state(state: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(STATE_FILE)


def db_connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL,
            saved_at TEXT NOT NULL
        )
    """)
    conn.commit()
    migrate_legacy_excel(conn)
    return conn


def migrate_legacy_excel(conn: sqlite3.Connection) -> None:
    """One-time import of the previous Excel database when SQLite is first created."""
    if conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] > 0 or not EXCEL_FILE.exists():
        return
    try:
        old = pd.read_excel(EXCEL_FILE, sheet_name="همه آگهی‌ها")
    except Exception as exc:
        say(f"HOSHdar: file Excel ghabli import nashod: {type(exc).__name__}")
        return
    imported = 0
    for _, series in old.iterrows():
        row = {key: (None if pd.isna(val) else val) for key, val in series.to_dict().items()}
        token = clean_text(row.get("توکن"))
        if not token:
            continue
        old_id = parse_number(row.get("ردیف"))
        payload = json.dumps(row, ensure_ascii=False, default=str)
        if old_id:
            conn.execute(
                "INSERT OR IGNORE INTO listings(id,token,payload,saved_at) VALUES(?,?,?,?)",
                (old_id, token, payload, datetime.now().isoformat()),
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO listings(token,payload,saved_at) VALUES(?,?,?)",
                (token, payload, datetime.now().isoformat()),
            )
        imported += conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    if imported:
        say(f"Data haye ghabli az Excel be database enteghal yaft: {imported}")


def export_excel(conn: sqlite3.Connection) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records = conn.execute("SELECT id,payload FROM listings ORDER BY id DESC").fetchall()
    rows = []
    for record in records:
        try:
            row = json.loads(record["payload"])
        except (TypeError, json.JSONDecodeError):
            continue
        row = apply_osm_neighborhood(row, conn, allow_network=False)
        row["ردیف"] = record["id"]
        rows.append({column: row.get(column) for column in COLUMNS})
    frame = pd.DataFrame(rows, columns=COLUMNS)
    if frame.empty:
        summary = pd.DataFrame(columns=[
            "محله", "تعداد_آگهی", "میانگین_قیمت_هر_متر",
            "حداقل_قیمت_هر_متر", "حداکثر_قیمت_هر_متر",
        ])
    else:
        priced = frame[frame["قیمت_هر_متر"].notna()].copy()
        summary = (
            priced.groupby("محله", dropna=False)
            .agg(تعداد_آگهی=("عنوان", "count"),
                 میانگین_قیمت_هر_متر=("قیمت_هر_متر", "mean"),
                 حداقل_قیمت_هر_متر=("قیمت_هر_متر", "min"),
                 حداکثر_قیمت_هر_متر=("قیمت_هر_متر", "max"))
            .reset_index()
        )
        if not summary.empty:
            summary["میانگین_قیمت_هر_متر"] = summary["میانگین_قیمت_هر_متر"].round().astype("Int64")
    temp = EXCEL_FILE.with_name("dezful_amlak.tmp.xlsx")
    try:
        with pd.ExcelWriter(temp, engine="openpyxl") as writer:
            frame.to_excel(writer, sheet_name="همه آگهی‌ها", index=False)
            summary.to_excel(writer, sheet_name="خلاصه قیمت مناطق", index=False)
        from openpyxl import load_workbook
        workbook = load_workbook(temp)
        sheet = workbook["همه آگهی‌ها"]
        link_column = COLUMNS.index("لینک") + 1
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for row_index in range(2, sheet.max_row + 1):
            cell = sheet.cell(row=row_index, column=link_column)
            url = clean_text(cell.value)
            if url.startswith("https://divar.ir/"):
                cell.value = "مشاهده آگهی"
                cell.hyperlink = url
                cell.style = "Hyperlink"
        workbook.save(temp)
        temp.replace(EXCEL_FILE)
    except PermissionError:
        say("HOSHdar: file Excel baz ast. Excel ra bebandid va dobare export konid.")
        if temp.exists():
            temp.unlink()
        raise


def insert_listing(conn: sqlite3.Connection, row: Dict[str, Any]) -> Tuple[bool, int]:
    token = clean_text(row.get("توکن"))
    if not token:
        return False, 0
    payload = json.dumps(row, ensure_ascii=False, default=str)
    cursor = conn.execute(
        "INSERT OR IGNORE INTO listings(token,payload,saved_at) VALUES(?,?,?)",
        (token, payload, datetime.now().isoformat()),
    )
    conn.commit()
    if cursor.rowcount == 0:
        found = conn.execute("SELECT id FROM listings WHERE token=?", (token,)).fetchone()
        return False, int(found["id"]) if found else 0
    found = conn.execute("SELECT id FROM listings WHERE token=?", (token,)).fetchone()
    return True, int(found["id"])


def search_body(category: str, city_id: str, districts: Optional[List[str]],
                cursor: Optional[Dict[str, Any]], page: int) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "city_ids": [str(city_id)],
        "source_view": "SEARCH",
        "disable_recommendation": True,
        "search_data": {
            "form_data": {"data": {"category": {"str": {"value": category}}}},
            "server_payload": {
                "@type": "type.googleapis.com/widgets.SearchData.ServerPayload",
                "additional_form_data": {"data": {"sort": {"str": {"value": "sort_date"}}}},
            },
        },
    }
    # District names are not valid numeric district IDs. Do not send them as
    # free-text query terms; filter against the returned Persian district locally.
    if cursor:
        pagination = dict(cursor)
        pagination.pop("@type", None)
        pagination.pop("search_uid", None)
        pagination.pop("viewed_tokens", None)
        pagination["page"] = page
        pagination["page_size"] = PAGE_SIZE
        body["pagination_data"] = {
            "@type": "type.googleapis.com/post_list.PaginationData",
            **pagination,
        }
    else:
        body["pagination_data"] = {
            "@type": "type.googleapis.com/post_list.PaginationData",
            "page": page,
            "page_size": PAGE_SIZE,
        }
    return body


def request_json(method: str, url: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    global LAST_REQUEST_AT
    last_error = None
    for attempt in range(4):
        wait = REQUEST_INTERVAL - (time.monotonic() - LAST_REQUEST_AT)
        if wait > 0:
            time.sleep(wait)
        LAST_REQUEST_AT = time.monotonic()
        try:
            response = SESSION.request(method, url, json=body, timeout=(10, 35))
            if response.status_code == 404:
                response.raise_for_status()
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 3:
                    time.sleep(min(12, 1.5 * (2 ** attempt)))
                    continue
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("API response is not a JSON object")
            return data
        except requests.HTTPError as exc:
            last_error = exc
            status = exc.response.status_code if exc.response is not None else 0
            if status and 400 <= status < 500 and status != 429:
                raise
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(min(8, 1.2 * (2 ** attempt)))
    raise RuntimeError(f"darkhast API pas az retry movafagh nashod: {type(last_error).__name__}")


def extract_token(row: Dict[str, Any]) -> str:
    data = row.get("data") or {}
    action_payload = ((data.get("action") or {}).get("payload") or {})
    return clean_text(data.get("token") or action_payload.get("token"))


def extract_search_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    for widget in payload.get("list_widgets", []) or []:
        if widget.get("widget_type") != "POST_ROW":
            continue
        data = widget.get("data") or {}
        token = extract_token({"data": data})
        if not token or token in seen:
            continue
        seen.add(token)
        action_payload = ((data.get("action") or {}).get("payload") or {})
        web_info = action_payload.get("web_info") or {}
        rows.append({
            "token": token,
            "title": clean_text(data.get("title")),
            "district": clean_text(web_info.get("district_persian")),
            "city": clean_text(web_info.get("city_persian")),
            "price_text": clean_text(data.get("middle_description_text")),
            "relative_time": clean_text(data.get("bottom_description_text")),
        })
    return rows


def get_search_page(category: str, city_id: str, districts: Optional[List[str]],
                    cursor: Optional[Dict[str, Any]], page: int) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], bool]:
    payload = request_json(
        "POST", SEARCH_URL,
        search_body(category, city_id, districts, cursor, page),
    )
    pagination = payload.get("pagination") or {}
    next_cursor = pagination.get("data")
    if not isinstance(next_cursor, dict):
        # Compatibility with older API responses.
        last_post_date = pagination.get("last_post_date")
        next_cursor = {"last_post_date": last_post_date} if last_post_date else None
    return extract_search_rows(payload), next_cursor, bool(pagination.get("has_next_page"))


def iter_widget_data(sections: List[Dict[str, Any]]):
    for section in sections:
        for widget in section.get("widgets", []) or []:
            yield section.get("section_name", ""), widget.get("widget_type", ""), widget.get("data") or {}


def extract_detail_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    sections = payload.get("sections") or []
    result: Dict[str, Any] = {
        "title": "", "description": "", "posted_at": None,
        "district": "", "price": None, "attributes": {},
        "business_type": "",
    }
    webengage = payload.get("webengage") or {}
    result["price"] = parse_money(webengage.get("price"))
    result["business_type"] = clean_text(webengage.get("business_type"))
    for section_name, widget_type, data in iter_widget_data(sections):
        if section_name == "TITLE":
            if widget_type == "LEGEND_TITLE_ROW" and not result["title"]:
                result["title"] = clean_text(data.get("title"))
            if widget_type == "EXPANDABLE_SECTION":
                title = clean_text(data.get("title"))
                if " در " in title and not result["district"]:
                    result["district"] = title.split(" در ", 1)[-1].strip()
                for sub in data.get("widget_list", []) or []:
                    subdata = sub.get("data") or {}
                    text = clean_text(subdata.get("text"))
                    if "انتشار آگهی" in text:
                        published_text = text.split("انتشار آگهی", 1)[-1].lstrip(" :：\n")
                        result["posted_at"] = parse_jalali_datetime(published_text)
        elif section_name == "DESCRIPTION" and widget_type == "DESCRIPTION_ROW":
            result["description"] = clean_text(data.get("text"))
        elif section_name == "PRICE":
            result["price"] = result["price"] or parse_money(
                data.get("price") or data.get("value") or data.get("title")
            )
        if section_name == "LIST_DATA":
            title = clean_text(data.get("title"))
            value = clean_text(data.get("value"))
            if title and value:
                result["attributes"][title] = value
            for item in data.get("items", []) or []:
                item_title = clean_text(item.get("title"))
                item_value = clean_text(item.get("value"))
                if item_title and item_value:
                    result["attributes"][item_title] = item_value
    if not result["title"]:
        result["title"] = clean_text(payload.get("title"))
    return result


def normalize_seller_type(value: Any) -> str:
    raw = clean_text(value).casefold().replace("-", "_").replace(" ", "_")
    if any(term in raw for term in ("business", "agency", "real_estate", "realestate", "broker", "مشاور", "املاک")):
        return "املاک"
    if any(term in raw for term in ("personal", "person", "private", "individual", "شخصی")):
        return "شخصی"
    return "نامشخص"


def apply_map_neighborhood(row: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich a listing from locally maintained Dezful GeoJSON polygons."""
    match = neighborhoods.classify_point(
        row.get("عرض_جغرافیایی"), row.get("طول_جغرافیایی")
    )
    if match:
        row["محله_نقشه"] = match.get("neighborhood", "")
        row["محدوده_نقشه"] = match.get("subarea", "")
        row["منبع_محله"] = (
            "نقشه - مختصات تقریبی"
            if row.get("موقعیت_تقریبی") == "بله"
            else "نقشه - محدوده ترسیم‌شده"
        )
        row["محله"] = row["محدوده_نقشه"] or row["محله_نقشه"] or row.get("محله", "")
    else:
        row.setdefault("محله_نقشه", "")
        row.setdefault("محدوده_نقشه", "")
        if not row.get("منبع_محله"):
            row["منبع_محله"] = "دیوار" if row.get("محله") else ""
    return row


def apply_osm_neighborhood(row: Dict[str, Any], conn: sqlite3.Connection,
                           allow_network: bool = True) -> Dict[str, Any]:
    """Classify coordinates against a locally cached bulk OSM street/area index."""
    lat, lon = row.get("عرض_جغرافیایی"), row.get("طول_جغرافیایی")
    if lat is None or lon is None:
        return apply_map_neighborhood(row)
    try:
        index = (osm_city_index.ensure_index() if allow_network
                 else osm_city_index.load_index())
        result = osm_city_index.classify_point(
            lat, lon, index=index, approximate=row.get("موقعیت_تقریبی") == "بله"
        )
    except Exception as exc:
        say(f"OSM city map dar dastres nist: {type(exc).__name__}; mahale Divar hefz shod.")
        return apply_map_neighborhood(row)

    row["محله_خودکار"] = result.get("neighborhood", "")
    row["خیابان_خودکار"] = result.get("street", "")
    row["خیابان‌های_نزدیک"] = "، ".join(result.get("nearby_streets", []))
    row["محدوده_خودکار"] = result.get("subarea", "")
    row["اطمینان_تشخیص"] = result.get("confidence", "")
    if result.get("neighborhood"):
        row["محله"] = result["neighborhood"]
    if result.get("source"):
        row["منبع_محله"] = result["source"]
    return apply_map_neighborhood(row)

def make_listing(search_row: Dict[str, Any], detail: Dict[str, Any],
                 category_label: str) -> Dict[str, Any]:
    token = search_row["token"]
    attrs = detail["attributes"]
    area = None
    build_year = None
    rooms = None
    for key, value in attrs.items():
        normalized = key.replace("‌", " ")
        if "متراژ" in normalized or "مساحت" in normalized:
            area = parse_number(value)
        elif "سال ساخت" in normalized:
            build_year = parse_number(value)
        elif "اتاق" in normalized:
            rooms = value
    price = detail["price"] or parse_money(search_row.get("price_text"))
    price_per_meter = int(price / area) if price and area and area > 0 else None
    seller = normalize_seller_type(detail.get("business_type", ""))
    published = detail.get("posted_at")
    return apply_map_neighborhood({
        "تاریخ انتشار": published.isoformat() if published else "",
        "عنوان": detail.get("title") or search_row.get("title", ""),
        "دسته": category_label,
        "متراژ": area,
        "قیمت_کل": price,
        "قیمت_هر_متر": price_per_meter,
        "سال_ساخت": build_year,
        "تعداد_اتاق": rooms,
        "محله": search_row.get("district") or detail.get("district", ""),
        "محله_خودکار": "", "خیابان_خودکار": "", "خیابان‌های_نزدیک": "", "محدوده_خودکار": "", "اطمینان_تشخیص": "",
        "محله_نقشه": "", "محدوده_نقشه": "", "منبع_محله": "",
        "نوع_آگهی_دهنده": seller,
        "عرض_جغرافیایی": search_row.get("latitude"),
        "طول_جغرافیایی": search_row.get("longitude"),
        "موقعیت_تقریبی": ("بله" if search_row.get("approximate_location", True) else "خیر") if search_row.get("latitude") is not None and search_row.get("longitude") is not None else "",
        "توضیحات": (detail.get("description") or "")[:1500],
        "لینک": f"https://divar.ir/v/{token}",
        "توکن": token,
    })


def district_matches(row: Dict[str, Any], districts: Optional[List[str]]) -> bool:
    if not districts:
        return True
    haystack = " ".join((row.get("محله") or "", row.get("عنوان") or "")).replace("ي", "ی").replace("ك", "ک").casefold()
    return any(d.replace("ي", "ی").replace("ك", "ک").casefold() in haystack for d in districts)


def category_state(state: Dict[str, Any], slug: str) -> Dict[str, Any]:
    categories = state.setdefault("categories", {})
    value = categories.setdefault(slug, {
        "cursor": None, "page": 1, "pending": [], "has_next": True,
    })
    value.setdefault("cursor", None)
    value.setdefault("page", 1)
    value.setdefault("pending", [])
    value.setdefault("has_next", True)
    # Migrate v2 checkpoints: old cursors were stored as a bare last_post_date string.
    if isinstance(value.get("cursor"), str):
        value["cursor"] = {"last_post_date": value["cursor"]}
    if isinstance(value.get("next_cursor"), str):
        value["next_cursor"] = {"last_post_date": value["next_cursor"]}
    # Migrate the previous version's pending token strings.
    value["pending"] = [
        item if isinstance(item, dict) else {"token": str(item)}
        for item in value["pending"]
    ]
    return value


def process_extraction(conn: sqlite3.Connection, state: Dict[str, Any], targets: Dict[str, int],
                       start_date: Optional[date], end_date: Optional[date], city_id: str,
                       districts: Optional[List[str]], bbox: Optional[Dict[str, float]] = None) -> None:
    added_by_category = {slug: 0 for slug in CATEGORIES}
    added = 0
    skipped_unknown_date = 0
    skipped_unavailable = 0
    export_counter = 0
    for slug, label in CATEGORIES.items():
        category_target = targets.get(slug, 0)
        if category_target <= 0:
            continue
        progress = category_state(state, slug)
        say(f"\nDaste: {label} | Hadaf: {category_target}")
        while added_by_category[slug] < category_target:
            if not progress["pending"]:
                if bbox is not None:
                    if progress.get("map_loaded"):
                        break
                    try:
                        rows = divar_map.search(slug, city_id, bbox, SESSION)
                    except Exception as exc:
                        save_state(state)
                        say(f"Khata dar map search: {type(exc).__name__}. Map link ya internet ra check konid.")
                        return
                    progress["pending"] = rows
                    progress["map_loaded"] = True
                    progress["has_next"] = False
                    save_state(state)
                    say(f"Agahi peyda shode dar map: {len(rows)}")
                    if not rows:
                        break
                else:
                    if not progress["has_next"]:
                        break
                    try:
                        rows, next_cursor, has_next = get_search_page(
                            slug, city_id, districts, progress.get("cursor"), progress["page"]
                        )
                    except Exception as exc:
                        save_state(state)
                        say(f"Khata dar search: {type(exc).__name__}. Check internet va dobare ejra konid.")
                        return
                    if not rows:
                        progress["has_next"] = False
                        save_state(state)
                        break
                    if progress.get("cursor") and next_cursor == progress.get("cursor"):
                        progress["has_next"] = False
                        save_state(state)
                        say("Pagination cursor taghir nakard; baraye jelogiri az loop motavaghef shod.")
                        break
                    progress["pending"] = rows
                    progress["next_cursor"] = next_cursor
                    progress["next_has_next"] = has_next
                    save_state(state)

            item = progress["pending"][0]
            token = item.get("token", "")
            if not token:
                progress["pending"].pop(0)
                save_state(state)
                continue

            exists = conn.execute("SELECT id FROM listings WHERE token=?", (token,)).fetchone()
            if exists:
                progress["pending"].pop(0)
                save_state(state)
                continue

            try:
                detail_payload = request_json("GET", f"{DETAIL_URL}/{token}")
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status == 404:
                    skipped_unavailable += 1
                    progress["pending"].pop(0)
                    save_state(state)
                    continue
                save_state(state)
                say(f"Khata dar daryaft jozeyat (HTTP {status}). Dar ejraye badi retry mishavad.")
                return
            except Exception as exc:
                save_state(state)
                say(f"Khata dar daryaft jozeyat: {type(exc).__name__}. Dar ejraye badi retry mishavad.")
                return

            detail = extract_detail_fields(detail_payload)
            row = make_listing(item, detail, label)
            row = apply_osm_neighborhood(row, conn, allow_network=True)
            published = detail.get("posted_at")
            if start_date is not None and end_date is not None and published is None:
                skipped_unknown_date += 1
                save_state(state)
                say("Tarikhe daghigh baraye filter peyda nashod; agahi dar queue mimanad.")
                return
            elif start_date is not None and end_date is not None and published.date() > end_date:
                progress["pending"].pop(0)
            elif start_date is not None and end_date is not None and published.date() < start_date and bbox is None:
                # Search endpoint is newest-first; map viewport order is not guaranteed.
                progress["pending"].clear()
                progress["has_next"] = False
                progress["next_has_next"] = False
            elif start_date is not None and end_date is not None and published.date() < start_date:
                progress["pending"].pop(0)
            elif not district_matches(row, districts):
                progress["pending"].pop(0)
            else:
                inserted, row_id = insert_listing(conn, row)
                progress["pending"].pop(0)
                if inserted:
                    added += 1
                    added_by_category[slug] += 1
                    export_counter += 1
                    say(f"Agahi sabt shod: {row_id} | {row['عنوان'][:60]}")
                if export_counter >= 10:
                    try:
                        export_excel(conn)
                    except Exception:
                        pass
                    export_counter = 0

            if not progress["pending"]:
                next_cursor = progress.pop("next_cursor", None)
                next_has_next = progress.pop("next_has_next", False)
                if bbox is None:
                    if next_cursor:
                        progress["cursor"] = next_cursor
                        progress["page"] += 1
                    progress["has_next"] = bool(next_has_next) and bool(next_cursor)
            save_state(state)

        save_state(state)

    try:
        export_excel(conn)
    except Exception:
        say("HOSHdar: database salem ast vali export Excel anjam nashod; file Excel ra bebandid va dobare ejra konid.")
    total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    say("\n========== NATIJE ==========")
    say(f"Agahi jadid ezafe shode: {added}")
    for slug, label in CATEGORIES.items():
        say(f"{label}: {added_by_category[slug]} / {targets.get(slug, 0)}")
    say(f"Tarikh namashkhas: {skipped_unknown_date}")
    say(f"Agahi hazf shode ya dar dastres nist: {skipped_unavailable}")
    say(f"Kol agahi haye unique: {total}")
    say(f"File Excel: {EXCEL_FILE}")
    say("============================")


def open_url_for_platform(url: str) -> bool:
    """Open a URL using the native launcher for Windows or Termux."""
    if sys.platform.startswith("win"):
        try:
            os.startfile(url)
            return True
        except (OSError, AttributeError):
            pass

    is_termux = bool(os.environ.get("TERMUX_VERSION")) or "com.termux" in os.environ.get("PREFIX", "")
    if is_termux:
        command = shutil.which("termux-open-url")
        if command:
            try:
                subprocess.run([command, url], check=True, timeout=10,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except (OSError, subprocess.SubprocessError):
                pass

    try:
        return bool(webbrowser.open_new_tab(url))
    except Exception:
        return False


def open_divar_map_picker() -> bool:
    """Open Divar Dezful residential property listings for map selection."""
    say("\nDar hale baz kardan map-e amlak-e Divar hastim...")
    say("Dar safheye baz shode, namayeshe map ra entekhab konid va mahdude mored nazar ra set konid.")
    say("Pas az entekhab mahdude, link ra copy karde va dar inja paste konid.")
    opened = open_url_for_platform(DIVAR_MAP_PICKER_URL)
    if not opened:
        say("Mororgar khodkar baz nashod. Link ra dasty baz konid:")
        say(DIVAR_MAP_PICKER_URL)
    return opened


def ask_map_bbox() -> Dict[str, float]:
    open_divar_map_picker()
    while True:
        raw = input("Link map Divar ya minLon,minLat,maxLon,maxLat ra paste konid: ").strip()
        try:
            return divar_map.parse_bbox(raw)
        except ValueError as exc:
            say(str(exc))
            say("Agar link map parametre map_bbox nadarad, 4 mokhtasat ro ba tartibe minLon,minLat,maxLon,maxLat vared konid.")


def ask_int(prompt: str) -> int:
    while True:
        try:
            value = int(ascii_digits(input(prompt).strip()))
            if value > 0:
                return value
        except ValueError:
            pass
        say("Lotfan yek adad bozorgtar az sefr vared konid.")


def ask_dates() -> Tuple[Optional[date], Optional[date]]:
    while True:
        start_raw = input("Tarikhe shoroo (khali = bedone filter): ").strip()
        end_raw = input("Tarikhe payan (khali = bedone filter): ").strip()
        if not start_raw and not end_raw:
            return None, None
        if not start_raw or not end_raw:
            say("Har do tarikh ra vared konid ya har do ra khali bezarid.")
            continue
        try:
            start = jalali_input(start_raw)
            end = jalali_input(end_raw)
            if start <= end:
                return start, end
            say("Tarikhe shoroo bayad ghabl az tarikhe payan bashad.")
        except ValueError as exc:
            say(str(exc))


def ask_category_targets() -> Dict[str, int]:
    say("\nTedad morede nazar baraye har daste ra vared konid (0 = skip):")
    targets = {}
    for slug, label in CATEGORIES.items():
        while True:
            raw = ascii_digits(input(f"Tedad {label}: ").strip() or "0")
            try:
                value = int(raw)
                if value >= 0:
                    targets[slug] = value
                    break
            except ValueError:
                pass
            say("Lotfan adad sefr ya bishtar vared konid.")
    return targets


def ask_keep_previous_data() -> bool:
    say("\nEtelaate estekhraj haye ghabli ham dar nazar gerefte shavad?")
    say("1. Bale - data haye ghabli hefz shavad va agahi haye tekrari dobare sabt nashavand")
    say("2. Na - shoroo az sefr (az database backup gerefte mishavad)")
    while True:
        choice = input("Entekhab konid (1/2): ").strip()
        if choice == "1":
            return True
        if choice == "2":
            return False
        say("Lotfan 1 ya 2 ra vared konid.")


def reset_collection(conn: sqlite3.Connection, state: Dict[str, Any]) -> None:
    """Back up the current SQLite database, then clear collected listings."""
    if conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]:
        backup_dir = DATA_DIR / "backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"amlak_{stamp}.sqlite3"
        backup_conn = sqlite3.connect(backup_path)
        try:
            conn.backup(backup_conn)
        finally:
            backup_conn.close()
        say(f"Backup data haye ghabli: {backup_path}")
    conn.execute("DELETE FROM listings")
    conn.commit()
    state["categories"] = {}
    state["settings"] = {}
    save_state(state)
    say("Database va vazeyat estekhraj az sefr shod.")


def show_stats(conn: sqlite3.Connection, state: Dict[str, Any]) -> None:
    total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM listings").fetchone()[0]
    say("\n========== AMAR ==========")
    say(f"Tedad agahi sabt shode: {total}")
    say(f"Shomare radif badi: {next_id}")
    say(f"File database: {DB_FILE}")
    say(f"File Excel: {EXCEL_FILE}")
    settings = state.get("settings", {})
    if settings.get("start_date"):
        say(f"Bazeye tarikh: {settings['start_date']} ta {settings['end_date']}")
    say("==========================\n")


def main() -> None:
    conn = db_connect()
    state = load_state()
    try:
        # Always rebuild Excel from the durable database at startup.
        try:
            export_excel(conn)
        except Exception:
            say("HOSHdar: Excel update nashod; database asli va salem ast.")
        while True:
            say("\n========================================")
            say("       DIVAR AMLAK SCRAPER - DEZFUL")
            say("========================================")
            say("1. Shorooe Estekhraj Jadid")
            say("2. Edameye Estekhraj Ghabli")
            say("3. Namayeshe Amar")
            say("4. Khorooj")
            choice = input("\nEntekhab konid: ").strip()
            if choice == "4":
                say("Khorooj az barname.")
                break
            if choice == "3":
                show_stats(conn, state)
                continue
            if choice not in {"1", "2"}:
                say("Entekhab namotabar ast.")
                continue

            bbox = None
            if choice == "1":
                keep_previous = ask_keep_previous_data()
                if not keep_previous:
                    reset_collection(conn, state)
                start_date, end_date = ask_dates()
                districts_raw = input("Mahalleha (ba virgool, khali baraye hame): ").strip()
                districts = [part.strip() for part in districts_raw.split(",") if part.strip()] or None
                map_mode = input("Estekhraj az map-e Divar? (y/n): ").strip().casefold() in {"y", "yes", "bale", "1"}
                bbox = None
                if map_mode:
                    bbox = ask_map_bbox()
                state["categories"] = {}
                state["settings"] = {
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                    "date_filter_enabled": start_date is not None and end_date is not None,
                    "districts": districts,
                    "map_bbox": bbox,
                    "city_id": DEZFUL_CITY_ID,
                }
                save_state(state)
            else:
                settings = state.get("settings", {})
                if not settings:
                    say("Estekhraj ghabli vojood nadarad. Aval gozine 1 ra entekhab konid.")
                    continue
                start_date = date.fromisoformat(settings["start_date"]) if settings.get("start_date") else None
                end_date = date.fromisoformat(settings["end_date"]) if settings.get("end_date") else None
                districts = settings.get("districts")
                bbox = settings.get("map_bbox")
                if start_date and end_date:
                    say(f"Bazeye sabt shode: {start_date} ta {end_date}")
                else:
                    say("Filter tarikh gheyr faal ast; jadidtarin agahiha aval sabt mishavand.")

            targets = ask_category_targets()
            process_extraction(
                conn, state, targets, start_date, end_date,
                settings.get("city_id", DEZFUL_CITY_ID) if choice == "2" else DEZFUL_CITY_ID,
                districts, bbox,
            )
            state = load_state()
    except KeyboardInterrupt:
        save_state(state)
        try:
            export_excel(conn)
        except Exception:
            pass
        say("\nBarname tavasote karbar motevaghef shod; vazeyat save shod.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()