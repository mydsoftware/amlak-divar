#!/usr/bin/env python3
"""
پیدا کردن شناسه شهر دزفول در دیوار
"""

import requests
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

def find_dezful():
    # روش ۱: از endpoint شهرها
    urls = [
        "https://api.divar.ir/v8/places/cities",
        "https://api.divar.ir/v5/places/cities",
        "https://api.divar.ir/v8/web/places/cities",
    ]

    for url in urls:
        try:
            print(f"در حال امتحان: {url}")
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                # جستجوی دزفول
                cities = data if isinstance(data, list) else data.get("cities") or data.get("data") or []
                for city in cities:
                    name = str(city.get("name") or city.get("title") or "")
                    if "دزفول" in name or "dezful" in name.lower():
                        print("\n✅ پیدا شد:")
                        print(json.dumps(city, ensure_ascii=False, indent=2))
                        return city.get("id") or city.get("city_id")
                print("دزفول در لیست پیدا نشد.")
            else:
                print(f"وضعیت: {resp.status_code}")
        except Exception as e:
            print(f"خطا: {e}")

    print("\n--- راهنمای دستی ---")
    print("1. به https://divar.ir/s/dezful بروید")
    print("2. Developer Tools (F12) > Network را باز کنید")
    print("3. صفحه را رفرش کنید")
    print("4. درخواست‌های postlist یا search را پیدا کنید")
    print("5. در Payload یا Request، مقدار city_ids را ببینید")
    return None


if __name__ == "__main__":
    find_dezful()
