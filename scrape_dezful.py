#!/usr/bin/env python3
"""
amlak-divar - استخراج آگهی‌های املاک دزفول از دیوار
"""

import argparse
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from tqdm import tqdm

BASE_URL = "https://api.divar.ir/v8"
SEARCH_URL = f"{BASE_URL}/postlist/w/search"
POST_URL = f"{BASE_URL}/posts-v2/web"

# شناسه شهر دزفول - حتماً با find_city_id.py یا Network tab مرورگر چک کنید
DEZFUL_CITY_ID = "25"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://divar.ir",
    "Referer": "https://divar.ir/",
}

def persian_to_int(text: str) -> Optional[int]:
    if not text:
        return None
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
    text = text.translate(trans)
    text = re.sub(r"[^\d]", "", text)
    try:
        return int(text) if text else None
    except ValueError:
        return None

def extract_price_per_meter(total_price: Optional[int], area: Optional[float]) -> Optional[int]:
    if total_price and area and area > 0:
        return int(total_price / area)
    return None

def search_ads(category: str, city_id: str = DEZFUL_CITY_ID, max_pages: int = 4, districts: Optional[List[str]] = None) -> List[str]:
    all_tokens = []
    last_post_date = None
    for page in range(1, max_pages + 1):
        body = {
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
        if last_post_date:
            body["pagination_data"] = {
                "@type": "type.googleapis.com/post_list.PaginationData",
                "last_post_date": last_post_date,
                "page": page,
                "layer_page": page,
            }
        try:
            resp = requests.post(SEARCH_URL, headers=HEADERS, json=body, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[خطا] صفحه {page} دسته {category}: {e}")
            break
        widgets = data.get("list_widgets", [])
        page_tokens = [w.get("data", {}).get("token") for w in widgets if w.get("widget_type") == "POST_ROW" and w.get("data", {}).get("token")]
        if not page_tokens:
            break
        all_tokens.extend(page_tokens)
        pagination = data.get("pagination") or {}
        last_post_date = pagination.get("last_post_date")
        if not pagination.get("has_next_page"):
            break
        time.sleep(1.2)
    return all_tokens

def get_post_detail(token: str) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(f"{POST_URL}/{token}", headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[خطا] دریافت آگهی {token}: {e}")
        return None

def parse_post(data: Dict[str, Any], category_label: str) -> Dict[str, Any]:
    result = {
        "عنوان": data.get("title", "") or data.get("data", {}).get("title", ""),
        "دسته": category_label,
        "متراژ": None,
        "قیمت_کل": None,
        "قیمت_هر_متر": None,
        "سال_ساخت": None,
        "تعداد_اتاق": None,
        "محله": "",
        "نوع_آگهی_دهنده": "",
        "توضیحات": "",
        "لینک": f"https://divar.ir/v/{data.get('token', '')}",
        "توکن": data.get("token", ""),
    }
    sections = data.get("sections", []) or data.get("widgets", [])
    for s in sections:
        if s.get("section_name") == "PRICE" or s.get("widget_type") == "PRICE_ROW":
            price_data = s.get("data", {}) or s
            price_str = price_data.get("price") or price_data.get("value") or price_data.get("title") or ""
            result["قیمت_کل"] = persian_to_int(str(price_str))
            break
    for s in sections:
        items = s.get("data", {}).get("items") or s.get("items") or []
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
    desc = data.get("description") or data.get("data", {}).get("description") or ""
    result["توضیحات"] = desc[:500] if desc else ""
    if not result["قیمت_هر_متر"] and result["قیمت_کل"] and result["متراژ"]:
        result["قیمت_هر_متر"] = extract_price_per_meter(result["قیمت_کل"], result["متراژ"])
    return result

def main():
    parser = argparse.ArgumentParser(description="استخراج آگهی‌های املاک دزفول از دیوار")
    parser.add_argument("--max-pages", type=int, default=4)
    parser.add_argument("--districts", type=str, default="", help="مثال: بهاران,فرهنگ شهر")
    parser.add_argument("--city-id", type=str, default=DEZFUL_CITY_ID)
    args = parser.parse_args()
    districts = [d.strip() for d in args.districts.split(",") if d.strip()] if args.districts else None

    print("=" * 60)
    print("شروع استخراج آگهی‌های املاک دزفول از دیوار")
    print(f"شناسه شهر: {args.city_id}")
    if districts:
        print(f"فیلتر محله: {districts}")
    print("=" * 60)

    all_ads = []
    target_cats = {"apartment-sell": "آپارتمان", "house-villa-sell": "ویلایی", "plot-old": "زمین"}

    for cat_slug, cat_label in target_cats.items():
        print(f"\n>>> دسته: {cat_label} ({cat_slug})")
        tokens = search_ads(category=cat_slug, city_id=args.city_id, max_pages=args.max_pages, districts=districts)
        print(f"تعداد توکن: {len(tokens)}")
        for token in tqdm(tokens, desc=f"جزئیات {cat_label}"):
            detail = get_post_detail(token)
            if detail:
                parsed = parse_post(detail, cat_label)
                if districts:
                    dist = parsed.get("محله", "") + " " + parsed.get("عنوان", "")
                    if not any(d in dist for d in districts):
                        continue
                all_ads.append(parsed)
            time.sleep(0.8)

    if not all_ads:
        print("\nهیچ آگهی‌ای پیدا نشد. شناسه شهر را با find_city_id.py چک کنید.")
        return

    df = pd.DataFrame(all_ads)
    if "قیمت_هر_متر" in df.columns:
        df = df.sort_values(by="قیمت_هر_متر", ascending=True, na_position="last")

    summary = None
    if "محله" in df.columns and "قیمت_هر_متر" in df.columns:
        summary = (
            df[df["قیمت_هر_متر"].notna()]
            .groupby("محله")
            .agg(تعداد_آگهی=("عنوان", "count"), میانگین_قیمت_هر_متر=("قیمت_هر_متر", "mean"),
                 حداقل_قیمت_هر_متر=("قیمت_هر_متر", "min"), حداکثر_قیمت_هر_متر=("قیمت_هر_متر", "max"))
            .reset_index()
        )
        summary["میانگین_قیمت_هر_متر"] = summary["میانگین_قیمت_هر_متر"].round(0).astype("Int64")
        summary = summary.sort_values("میانگین_قیمت_هر_متر")

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    excel_path = output_dir / f"dezful_amlak_{timestamp}.xlsx"

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="همه آگهی‌ها", index=False)
        if summary is not None and not summary.empty:
            summary.to_excel(writer, sheet_name="خلاصه قیمت مناطق", index=False)

    print("\n" + "=" * 60)
    print(f"تعداد کل آگهی‌ها: {len(df)}")
    print(f"فایل اکسل: {excel_path}")
    print("=" * 60)
    if summary is not None and not summary.empty:
        print("\nخلاصه قیمت مناطق:")
        print(summary.to_string(index=False))

if __name__ == "__main__":
    main()
