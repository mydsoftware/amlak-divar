"""Divar native map viewport client and geometry helpers."""
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import requests


MAP_URL = "https://api.divar.ir/v8/mapview/viewport"


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        digits = str(value).translate(str.maketrans(
            "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"
        ))
        return float(digits)
    except (TypeError, ValueError):
        return None


def parse_bbox(value: str) -> Dict[str, float]:
    """Read a Divar map URL (map_bbox) or four values: west,south,east,north."""
    raw = value.strip()
    if "://" in raw:
        query = parse_qs(urlparse(raw).query)
        values = query.get("map_bbox") or query.get("bbox") or []
        raw = values[0] if values else ""
    raw = raw.strip().strip("[]()")
    parts = [_number(part.strip()) for part in raw.split(",")]
    if len(parts) != 4 or any(part is None for part in parts):
        raise ValueError("Link map Divar ya 4 adad minLon,minLat,maxLon,maxLat ra vared konid.")
    west, south, east, north = parts
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("Mogheiyat map_bbox sahih nist.")
    return {
        "minLongitude": west, "minLatitude": south,
        "maxLongitude": east, "maxLatitude": north,
    }


def request_body(category: str, city_id: str, bbox: Dict[str, float], zoom: int = 15) -> Dict[str, Any]:
    return {
        "city_ids": [str(city_id)],
        "search_data": {
            "form_data": {"data": {"category": {"str": {"value": category}}}},
            "server_payload": {
                "@type": "type.googleapis.com/widgets.SearchData.ServerPayload",
                "additional_form_data": {"data": {"sort": {"str": {"value": "sort_date"}}}},
            },
        },
        "camera_info": {"bbox": bbox, "zoom": zoom},
    }


def extract_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows, seen = [], set()
    for post in payload.get("posts", []) or []:
        card = post.get("map_post_card") or post.get("card") or post
        pin = post.get("map_pin_feature") or post.get("pin") or {}
        token = _text(card.get("token") or post.get("token"))
        if not token or token in seen:
            continue
        seen.add(token)
        point = pin.get("point") if isinstance(pin.get("point"), dict) else {}
        lat = _number(pin.get("lat") if pin.get("lat") is not None else point.get("lat"))
        lon = _number(pin.get("lon") if pin.get("lon") is not None else point.get("lon"))
        prices = card.get("price_fields") or []
        price_text = " ".join(_text(item.get("value")) for item in prices if isinstance(item, dict))
        rows.append({
            "token": token,
            "title": _text(card.get("title") or post.get("title")),
            "district": "",
            "price_text": price_text,
            "relative_time": "",
            "latitude": lat,
            "longitude": lon,
            "approximate_location": bool(pin.get("approximate_location", True)),
        })
    return rows


def _split(bbox: Dict[str, float]) -> List[Dict[str, float]]:
    west, south = bbox["minLongitude"], bbox["minLatitude"]
    east, north = bbox["maxLongitude"], bbox["maxLatitude"]
    mid_lon, mid_lat = (west + east) / 2, (south + north) / 2
    return [
        {"minLongitude": west, "minLatitude": south, "maxLongitude": mid_lon, "maxLatitude": mid_lat},
        {"minLongitude": mid_lon, "minLatitude": south, "maxLongitude": east, "maxLatitude": mid_lat},
        {"minLongitude": west, "minLatitude": mid_lat, "maxLongitude": mid_lon, "maxLatitude": north},
        {"minLongitude": mid_lon, "minLatitude": mid_lat, "maxLongitude": east, "maxLatitude": north},
    ]


def search(category: str, city_id: str, bbox: Dict[str, float],
           session: requests.Session, depth: int = 0, max_depth: int = 7) -> List[Dict[str, Any]]:
    """Fetch all map pins, recursively subdividing viewports over Divar's 200-pin cap."""
    response = session.post(MAP_URL, json=request_body(category, city_id, bbox), timeout=(10, 35))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Divar map response is not a JSON object")
    rows = extract_rows(payload)
    try:
        count = int(payload.get("count") or len(rows))
    except (TypeError, ValueError):
        count = len(rows)
    if count <= 200 and len(rows) < 200:
        return rows
    if depth >= max_depth:
        raise RuntimeError("Map area is too dense. Choose a smaller map viewport.")
    merged, seen = [], set()
    for child in _split(bbox):
        for row in search(category, city_id, child, session, depth + 1, max_depth):
            if row["token"] not in seen:
                seen.add(row["token"])
                merged.append(row)
    return merged
