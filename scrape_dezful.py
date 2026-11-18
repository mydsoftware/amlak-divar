#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Amlak Divar scraper - Dezful. Console messages are Finglish; Excel data stays Persian."""

import json
import re
import time
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import jdatetime
import pandas as pd
import requests
from tqdm import tqdm

BASE_URL = "https://api.divar.ir/v8"
SEARCH_URL = f"{BASE_URL}/postlist/w/search"
POST_URL = f"{BASE_URL}/posts-v2/web"
DEZFUL_CITY_ID = "23"
DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")
STATE_FILE = DATA_DIR / "progress.json"
EXCEL_FILE = OUTPUT_DIR / "dezful_amlak.xlsx"
CATEGORIES = {
    "apartment-sell": "آپارتمان",
    "house-villa-sell": "ویلایی",
    "plot-old": "زمین",
}
COLUMNS = [
    "ردیف", "تاریخ انتشار", "عنوان", "دسته", "متراژ", "قیمت_کل",
    "قیمت_هر_متر", "سال_ساخت", "تعداد_اتاق", "محله",
    "نوع_آگهی_دهنده", "توضیحات", "لینک", "توکن",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://divar.ir",
    "Referer": "https://divar.ir/",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def say(message: str) -> None:
    print(message, flush=True)


def load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            say("HOSHdar: file progress kharabi bood; vazeyat jadid sakhte mishavad.")
    return {"version": 2, "next_id": 1, "seen": [], "categories": {}, "settings": {}}


def save_state(state: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(STATE_FILE)


def digits_to_ascii(value: str) -> str:
    return str(value).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))


def persian_to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9]", "", digits_to_ascii(str(value)))
    return int(cleaned) if cleaned else None


def jalali_input(value: str) -> date:
    value = digits_to_ascii(value.strip()).replace("-", "/")
    match = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", value)
    if not match:
        raise ValueError("Tarikh ra be shekle 1405/08/01 vared konid.")
    y, m, d = map(int, match.groups())
    return jdatetime.date(y, m, d).togregorian()


def find_publish_date(obj: Any, depth: int = 0) -> Optional[datetime]:
    """Find explicit publication timestamp/date fields in Divar JSON, without guessing."""
    if depth > 9 or not isinstance(obj, (dict, list)):
        return None
    keys = {"created_at", "published_at", "publish_time", "creation_time",
            "created_time", "date_created", "post_date", "timestamp"}
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.lower() in keys and value not in (None, ""):
                try:
                    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
                        number = float(value)
                        if number > 10**12:
                            number /= 1000
                        if number > 10**8:
                            return datetime.fromtimestamp(number, tz=timezone.utc).replace(tzinfo=None)
                    if isinstance(value, str):
                        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                        return parsed.replace(tzinfo=None)
                except (ValueError, TypeError, OverflowError, OSError):
                    pass
        for value in obj.values():
            found = find_publish_date(value, depth + 1)
            if found:
                return found
    else:
        for value in obj:
            found = find_publish_date(value, depth + 1)
            if found:
                return found
    return None


def extract_price_per_meter(total: Optional[int], area: Optional[int]) -> Optional[int]:
    if total and area and area > 0:
        return int(total / area)
    return None


def search_page(category: str, cursor: Optional[str], city_id: str,
                districts: Optional[List[str]]) -> Tuple[List[str], Optional[str], bool]:
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
    if districts:
        body["search_data"]["query"] = " ".join(districts)
    if cursor:
        body["pagination_data"] = {
            "@type": "type.googleapis.com/post_list.PaginationData",
            "last_post_date": cursor,
        }
    response = SESSION.post(SEARCH_URL, json=body, timeout=30)
    response.raise_for_status()
    payload = response.json()
    widgets = payload.get("list_widgets", [])
    tokens = [
        w.get("data", {}).get("token")
        for w in widgets
        if w.get("widget_type") == "POST_ROW" and w.get("data", {}).get("token")
    ]
    pagination = payload.get("pagination") or {}
    return tokens, pagination.get("last_post_date"), bool(pagination.get("has_next_page"))


def get_post_detail(token: str) -> Optional[Dict[str, Any]]:
    try:
        response = SESSION.get(f"{POST_URL}/{token}", timeout=25)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        say(f"Khata dar daryaft agahi {token}: {exc}")
        return None


def parse_post(data: Dict[str, Any], category_label: str) -> Dict[str, Any]:
    token = data.get("token") or data.get("data", {}).get("token", "")
    result: Dict[str, Any] = {
        "تاریخ انتشار": "",
        "عنوان": data.get("title", "") or data.get("data", {}).get("title", ""),
        "دسته": category_label, "متراژ": None, "قیمت_کل": None,
        "قیمت_هر_متر": None, "سال_ساخت": None, "تعداد_اتاق": None,
        "محله": "", "نوع_آگهی_دهنده": "", "توضیحات": "",
        "لینک": f"https://divar.ir/v/{token}", "توکن": token,
    }
    published = find_publish_date(data)
    if published:
        result["تاریخ انتشار"] = published.strftime("%Y-%m-%d %H:%M:%S")
    sections = data.get("sections", []) or data.get("widgets", [])
    for section in sections:
        if section.get("section_name") == "PRICE" or section.get("widget_type") == "PRICE_ROW":
            price_data = section.get("data", {}) or section
            price = price_data.get("price") or price_data.get("value") or price_data.get("title") or ""
            result["قیمت_کل"] = persian_to_int(price)
            break
    for section in sections:
        items = section.get("data", {}).get("items") or section.get("items") or []
        for item in items:
            title = (item.get("title") or item.get("name") or "").strip()
            value = (item.get("value") or item.get("subtitle") or "").strip()
            if "متراژ" in title or "مساحت" in title:
                result["متراژ"] = persian_to_int(value)
            elif "سال ساخت" in title or "ساخت" in title:
                result["سال_ساخت"] = persian_to_int(value)
            elif "اتاق" in title:
                result["تعداد_اتاق"] = value
            elif "قیمت هر متر" in title:
                result["قیمت_هر_متر"] = persian_to_int(value)
    district = data.get("district") or data.get("data", {}).get("district") or ""
    result["محله"] = str(district).strip()
    business = data.get("business") or data.get("data", {}).get("business") or {}
    result["نوع_آگهی_دهنده"] = "مشاور املاک" if (business.get("name") or business.get("type") == "agency") else "شخصی"
    description = data.get("description") or data.get("data", {}).get("description") or ""
    result["توضیحات"] = description[:1000] if description else ""
    if not result["قیمت_هر_متر"]:
        result["قیمت_هر_متر"] = extract_price_per_meter(result["قیمت_کل"], result["متراژ"])
    return result


def append_excel(row: Dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    new_df = pd.DataFrame([{column: row.get(column) for column in COLUMNS}])
    if EXCEL_FILE.exists():
        try:
            old_df = pd.read_excel(EXCEL_FILE, sheet_name="همه آگهی‌ها")
            combined = pd.concat([old_df, new_df], ignore_index=True)
        except Exception:
            combined = new_df
    else:
        combined = new_df
    if "قیمت_هر_متر" in combined:
        combined = combined.sort_values("ردیف", ascending=True, na_position="last")
    summary = (
        combined[combined["قیمت_هر_متر"].notna()]
        .groupby("محله", dropna=False)
        .agg(تعداد_آگهی=("عنوان", "count"),
             میانگین_قیمت_هر_متر=("قیمت_هر_متر", "mean"),
             حداقل_قیمت_هر_متر=("قیمت_هر_متر", "min"),
             حداکثر_قیمت_هر_متر=("قیمت_هر_متر", "max"))
        .reset_index()
    )
    if not summary.empty:
        summary["میانگین_قیمت_هر_متر"] = summary["میانگین_قیمت_هر_متر"].round(0).astype("Int64")
    temp_file = EXCEL_FILE.with_name("dezful_amlak.tmp.xlsx")
    with pd.ExcelWriter(temp_file, engine="openpyxl") as writer:
        combined.to_excel(writer, sheet_name="همه آگهی‌ها", index=False)
        summary.to_excel(writer, sheet_name="خلاصه قیمت مناطق", index=False)
    temp_file.replace(EXCEL_FILE)


def show_stats(state: Dict[str, Any]) -> None:
    say("\n========== AMAR ==========")
    say(f"Tedad agahi sabt shode: {len(state.get('seen', []))}")
    say(f"Shomare radif badi: {state.get('next_id', 1)}")
    say(f"File Excel: {EXCEL_FILE}")
    say("==========================\n")


def run_extraction(state: Dict[str, Any], target: int, start_date: date,
                   end_date: date, city_id: str, districts: Optional[List[str]]) -> None:
    seen = set(state.get("seen", []))
    added = 0
    unknown_dates = 0
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for category, label in CATEGORIES.items():
        if added >= target:
            break
        cat_state = state.setdefault("categories", {}).setdefault(
            category, {"cursor": None, "pending": [], "has_next": True}
        )
        say(f"\nDaste: {label}")
        while added < target:
            if not cat_state["pending"]:
                if not cat_state.get("has_next", True):
                    break
                try:
                    tokens, next_cursor, has_next = search_page(
                        category, cat_state.get("cursor"), city_id, districts
                    )
                except requests.RequestException as exc:
                    say(f"Khata dar daryaft list: {exc}")
                    save_state(state)
                    return
                if not tokens or (cat_state.get("cursor") and next_cursor == cat_state.get("cursor")):
                    cat_state["has_next"] = False
                    save_state(state)
                    break
                cat_state["pending"] = tokens
                cat_state["next_cursor"] = next_cursor
                cat_state["next_has_next"] = has_next
                save_state(state)

            token = cat_state["pending"][0]
            if token in seen:
                cat_state["pending"].pop(0)
                if not cat_state["pending"]:
                    cat_state["cursor"] = cat_state.pop("next_cursor", cat_state.get("cursor"))
                    cat_state["has_next"] = cat_state.pop("next_has_next", False)
                save_state(state)
                continue

            detail = get_post_detail(token)
            if detail is None:
                # Keep failed token at the head so the next run can retry it.
                save_state(state)
                say("Estekhraj be dalile khata motaghef shod; dobare ejra konid.")
                return
            parsed = parse_post(detail, label)
            published = find_publish_date(detail)
            if published is None:
                unknown_dates += 1
                # Strict date filtering: never include an ad whose date cannot be verified.
                cat_state["pending"].pop(0)
            elif published.date() > end_date:
                # Newer than requested window: skip, continue toward older posts.
                cat_state["pending"].pop(0)
            elif published.date() < start_date:
                # Search is newest-first; older-than-start means this category is complete.
                cat_state["pending"].clear()
                cat_state["has_next"] = False
                cat_state["next_has_next"] = False
            else:
                if districts:
                    searchable = f"{parsed.get('محله', '')} {parsed.get('عنوان', '')}"
                    if not any(d in searchable for d in districts):
                        cat_state["pending"].pop(0)
                        save_state(state)
                        continue
                parsed["ردیف"] = state.get("next_id", 1)
                append_excel(parsed)
                state["next_id"] = parsed["ردیف"] + 1
                state.setdefault("seen", []).append(token)
                seen.add(token)
                added += 1
                cat_state["pending"].pop(0)
                say(f"Agahi sabt shod: {parsed['ردیف']} | {parsed.get('عنوان', '')[:55]}")
            if not cat_state["pending"]:
                cat_state["cursor"] = cat_state.pop("next_cursor", cat_state.get("cursor"))
                cat_state["has_next"] = cat_state.pop("next_has_next", cat_state.get("has_next", False))
            save_state(state)
            time.sleep(0.8)

    say("\n========== NATIJE ==========")
    say(f"Tedad agahi jadid: {added}")
    say(f"Agahi ba tarikh gheire ghabele tashkhis: {unknown_dates}")
    say(f"Kol agahi haye unique: {len(state.get('seen', []))}")
    say(f"Excel: {EXCEL_FILE}")
    say("============================")


def ask_int(prompt: str, default: Optional[int] = None) -> int:
    while True:
        raw = input(prompt).strip()
        if not raw and default is not None:
            return default
        try:
            value = int(digits_to_ascii(raw))
            if value > 0:
                return value
        except ValueError:
            pass
        say("Lotfan yek adad bozorgtar az sefr vared konid.")


def ask_dates() -> Tuple[date, date]:
    while True:
        try:
            start = jalali_input(input("Tarikhe shoroo (Jalali YYYY/MM/DD): "))
            end = jalali_input(input("Tarikhe payan (Jalali YYYY/MM/DD): "))
            if start <= end:
                return start, end
            say("Tarikhe shoroo bayad ghabl az tarikhe payan bashad.")
        except ValueError as exc:
            say(str(exc))


def main() -> None:
    state = load_state()
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
            show_stats(state)
            continue
        if choice not in {"1", "2"}:
            say("Entekhab namotabar ast.")
            continue

        if choice == "1":
            start_date, end_date = ask_dates()
            target = ask_int("Tedade agahi morede nazar: ")
            districts_raw = input("Mahalleha (ba virgool, khali baraye hame): ").strip()
            districts = [x.strip() for x in districts_raw.split(",") if x.strip()] or None
            state["categories"] = {}
            state["settings"] = {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "districts": districts,
                "city_id": DEZFUL_CITY_ID,
            }
            save_state(state)
        else:
            settings = state.get("settings", {})
            if not settings.get("start_date") or not settings.get("end_date"):
                say("Estekhraj ghabli vojood nadarad. Aval gozine 1 ra entekhab konid.")
                continue
            start_date = date.fromisoformat(settings["start_date"])
            end_date = date.fromisoformat(settings["end_date"])
            districts = settings.get("districts")
            target = ask_int("Tedad agahi jadid baraye ezafe shodan: ")
            say(f"Bazeye sabt shode: {jdatetime.date.fromgregorian(date=start_date)} ta {jdatetime.date.fromgregorian(date=end_date)}")

        run_extraction(state, target, start_date, end_date,
                       state.get("settings", {}).get("city_id", DEZFUL_CITY_ID), districts)
        state = load_state()


if __name__ == "__main__":
    main()
