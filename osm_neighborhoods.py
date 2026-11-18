#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Automatic OSM reverse geocoding for Dezful listings, with a persistent cache."""
import json
import sqlite3
import time
from typing import Any, Dict, Optional

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "AmlakDivarDezful/1.0 (property research; contact: repository owner)"
MIN_INTERVAL = 1.1
_LAST_REQUEST = 0.0


def _text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item)
    return str(value or "").strip()


def normalize_address(payload: Dict[str, Any]) -> Dict[str, str]:
    address = payload.get("address") or {}
    neighborhood = (
        address.get("neighbourhood") or address.get("suburb")
        or address.get("quarter") or address.get("city_district")
        or address.get("residential") or ""
    )
    road = address.get("road") or address.get("pedestrian") or address.get("footway") or ""
    district = address.get("city_district") or address.get("suburb") or ""
    return {
        "neighborhood": _text(neighborhood),
        "road": _text(road),
        "district": _text(district),
        "display_name": _text(payload.get("display_name")),
        "osm_type": _text(payload.get("osm_type")),
        "osm_id": _text(payload.get("osm_id")),
    }


def reverse_lookup(latitude: Any, longitude: Any, conn: sqlite3.Connection,
                   session: Optional[requests.Session] = None) -> Dict[str, str]:
    """Return cached or Nominatim-derived address fields; never invent a neighborhood."""
    global _LAST_REQUEST
    try:
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return {}
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return {}
    # Four decimals are roughly 11 m at Dezful latitude; cache avoids repeat calls.
    key = (round(lat, 4), round(lon, 4))
    cached = conn.execute(
        "SELECT payload FROM osm_geocode_cache WHERE lat=? AND lon=?", key
    ).fetchone()
    if cached:
        try:
            return json.loads(cached[0])
        except (TypeError, ValueError):
            pass

    client = session or requests.Session()
    wait = MIN_INTERVAL - (time.monotonic() - _LAST_REQUEST)
    if wait > 0:
        time.sleep(wait)
    _LAST_REQUEST = time.monotonic()
    response = client.get(
        NOMINATIM_URL,
        params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 18,
                "addressdetails": 1, "accept-language": "fa"},
        headers={"User-Agent": USER_AGENT},
        timeout=(8, 20),
    )
    response.raise_for_status()
    data = response.json()
    result = normalize_address(data if isinstance(data, dict) else {})
    conn.execute(
        "INSERT OR REPLACE INTO osm_geocode_cache(lat,lon,payload,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP)",
        (key[0], key[1], json.dumps(result, ensure_ascii=False)),
    )
    conn.commit()
    return result
