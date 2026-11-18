#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bulk OSM street/area index and offline point classification for Dezful."""
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
# Dezful urban coverage with a small margin; coordinates are south,west,north,east.
DEZFUL_BBOX = (32.30, 48.30, 32.48, 48.50)
DATA_FILE = Path("data/dezful_osm_index.json")
TIMEOUT = (15, 180)
_INDEX: Optional[Dict[str, Any]] = None


def _name(tags: Dict[str, Any]) -> str:
    return str(tags.get("name:fa") or tags.get("name") or tags.get("official_name") or "").strip()


def _valid_geometry(geometry: Any) -> List[Tuple[float, float]]:
    points = []
    if not isinstance(geometry, list):
        return points
    for item in geometry:
        try:
            lat, lon = float(item["lat"]), float(item["lon"])
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                points.append((lat, lon))
        except (KeyError, TypeError, ValueError):
            continue
    return points


def build_query(bbox: Tuple[float, float, float, float] = DEZFUL_BBOX) -> str:
    south, west, north, east = bbox
    area = f"{south},{west},{north},{east}"
    return f"""[out:json][timeout:120];
(
  way["highway"]["name"]({area});
  way["place"~"neighbourhood|suburb|quarter|locality"]["name"]({area});
  way["landuse"="residential"]["name"]({area});
  relation["place"~"neighbourhood|suburb|quarter|locality"]["name"]({area});
);
out tags geom;"""


def _relation_outer_rings(members: Any) -> List[List[Tuple[float, float]]]:
    segments = []
    for member in members if isinstance(members, list) else []:
        if member.get("role") != "outer":
            continue
        geometry = _valid_geometry(member.get("geometry"))
        if len(geometry) >= 2:
            segments.append(geometry)
    rings = []
    while segments:
        ring = segments.pop(0)
        changed = True
        while changed and ring[0] != ring[-1]:
            changed = False
            for i, segment in enumerate(segments):
                if ring[-1] == segment[0]:
                    ring.extend(segment[1:])
                elif ring[-1] == segment[-1]:
                    ring.extend(reversed(segment[:-1]))
                elif ring[0] == segment[-1]:
                    ring = segment[:-1] + ring
                elif ring[0] == segment[0]:
                    ring = list(reversed(segment[1:])) + ring
                else:
                    continue
                segments.pop(i)
                changed = True
                break
        if len(ring) >= 4 and ring[0] == ring[-1]:
            rings.append(ring)
    return rings


def parse_overpass(payload: Dict[str, Any]) -> Dict[str, Any]:
    roads, areas = [], []
    seen = set()
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        name = _name(tags)
        if not name:
            continue
        geometry = _valid_geometry(element.get("geometry"))
        kind = str(tags.get("highway") or "")
        if kind and len(geometry) >= 2:
            key = (element.get("type"), element.get("id"), name)
            if key not in seen:
                roads.append({"name": name, "highway": kind, "geometry": geometry})
                seen.add(key)
        # Residential landuse polygons can cover the whole city, not a neighborhood.
        is_area = tags.get("place") in {"neighbourhood", "suburb", "quarter", "locality"}
        if not is_area:
            continue
        geometries = [geometry] if len(geometry) >= 4 and geometry[0] == geometry[-1] else []
        if not geometries and element.get("type") == "relation":
            geometries = _relation_outer_rings(element.get("members"))
        for ring in geometries:
            areas.append({"name": name, "geometry": ring})
    return {"version": 2, "source": "© OpenStreetMap contributors",
            "roads": roads, "areas": areas}


def download_index(path: Path = DATA_FILE, session: Optional[requests.Session] = None,
                   bbox: Tuple[float, float, float, float] = DEZFUL_BBOX) -> Dict[str, Any]:
    client = session or requests.Session()
    query = build_query(bbox)
    last_error = None
    for endpoint in OVERPASS_URLS:
        try:
            response = client.post(endpoint, data={"data": query}, timeout=TIMEOUT,
                                   headers={"User-Agent": "AmlakDivarDezful/2.0"})
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
                raise ValueError("Overpass response format is invalid")
            index = parse_overpass(payload)
            if not index["roads"] and not index["areas"]:
                raise ValueError("No named roads or areas found in the selected coverage")
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
            temp.replace(path)
            return index
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"OSM city index download failed: {type(last_error).__name__}: {last_error}")


def load_index(path: Path = DATA_FILE) -> Dict[str, Any]:
    global _INDEX
    if _INDEX is not None and path == DATA_FILE:
        return _INDEX
    if not path.exists():
        raise FileNotFoundError(f"OSM index not found: {path}")
    index = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(index, dict) or not isinstance(index.get("roads"), list):
        raise ValueError("OSM index file is invalid")
    if path == DATA_FILE:
        _INDEX = index
    return index


def ensure_index(path: Path = DATA_FILE, session: Optional[requests.Session] = None) -> Dict[str, Any]:
    if path.exists():
        try:
            cached = load_index(path)
            if int(cached.get("version", 0)) >= 2:
                return cached
        except (OSError, ValueError, TypeError):
            pass
    index = download_index(path, session=session)
    global _INDEX
    if path == DATA_FILE:
        _INDEX = index
    return index


def _point_in_polygon(lat: float, lon: float, polygon: List[Tuple[float, float]]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i, (yi, xi) in enumerate(polygon):
        yj, xj = polygon[j]
        if ((yi > lat) != (yj > lat)) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi:
            inside = not inside
        j = i
    return inside


def _segment_metrics(lat: float, lon: float, a: Tuple[float, float],
                     b: Tuple[float, float]) -> Tuple[float, float, float]:
    """Distance in metres, signed cross-track offset and segment bearing in local coordinates."""
    scale_x = 111320.0 * math.cos(math.radians(lat))
    scale_y = 110540.0
    ax, ay = (a[1] - lon) * scale_x, (a[0] - lat) * scale_y
    bx, by = (b[1] - lon) * scale_x, (b[0] - lat) * scale_y
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.hypot(ax, ay), 0.0, 0.0
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / length2))
    px, py = ax + t * dx, ay + t * dy
    cross = dx * (-ay) - dy * (-ax)
    signed = cross / math.sqrt(length2)
    return math.hypot(px, py), signed, math.atan2(dy, dx)


def _nearest_roads(lat: float, lon: float, roads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    best: Dict[str, Dict[str, Any]] = {}
    for road in roads:
        coords = road.get("geometry") or []
        for a, b in zip(coords, coords[1:]):
            distance, signed, angle = _segment_metrics(lat, lon, a, b)
            name = road["name"]
            current = best.get(name)
            if current is None or distance < current["distance"]:
                best[name] = {"name": name, "distance": distance,
                              "signed": signed, "angle": angle}
    return sorted(best.values(), key=lambda item: item["distance"])[:8]


def _polygon_area_m2(polygon: List[Tuple[float, float]]) -> float:
    if len(polygon) < 4:
        return float('inf')
    mean_lat = sum(point[0] for point in polygon) / len(polygon)
    sx, sy = 111320.0 * math.cos(math.radians(mean_lat)), 110540.0
    points = [(lon * sx, lat * sy) for lat, lon in polygon]
    return abs(sum(points[i][0] * points[(i + 1) % len(points)][1] - points[(i + 1) % len(points)][0] * points[i][1] for i in range(len(points)))) / 2.0

def _is_city_name(name: str) -> bool:
    normalized = ' '.join(str(name).replace('ي', 'ی').replace('ك', 'ک').casefold().split())
    return normalized in {'دزفول', 'dezful', 'dezfool'}

def classify_point(latitude: Any, longitude: Any, index: Optional[Dict[str, Any]] = None,
                   approximate: bool = False) -> Dict[str, Any]:
    try:
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return {}
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return {}
    data = index or load_index()
    matching_areas = []
    for area in data.get('areas', []):
        name, polygon = str(area.get('name') or '').strip(), area.get('geometry') or []
        if not name or _is_city_name(name) or len(polygon) < 4:
            continue
        if _point_in_polygon(lat, lon, polygon):
            matching_areas.append((_polygon_area_m2(polygon), name))
    neighborhood = min(matching_areas, default=(0.0, ''), key=lambda item: item[0])[1]
    # Always calculate roads; a matching polygon must not suppress street detection.
    roads = _nearest_roads(lat, lon, data.get('roads', []))
    street, subarea, nearby_streets, distance_m = '', '', [], None
    confidence = 0.0
    if roads and roads[0]['distance'] <= 120:
        first = roads[0]
        street, distance_m = first['name'], round(first['distance'], 1)
        nearby_streets = [item['name'] for item in roads[:3]]
        confidence = 0.88 if first['distance'] <= 25 else 0.76 if first['distance'] <= 60 else 0.58
        for second in roads[1:]:
            angle_delta = abs((first['angle'] - second['angle'] + math.pi / 2) % math.pi - math.pi / 2)
            if first['signed'] * second['signed'] < 0 and angle_delta <= math.radians(22) and second['distance'] <= 120:
                subarea = f"بین {first['name']} و {second['name']} (تخمینی)"
                confidence = min(confidence, 0.72)
                break
    if approximate and confidence:
        confidence = min(confidence, 0.55)
    if not neighborhood and not street:
        return {}
    source = 'OSM neighborhood polygon + road network' if neighborhood and street else 'OSM neighborhood polygon' if neighborhood else 'OSM road network'
    if approximate:
        source += ' / approximate coordinate'
    if neighborhood and not street and not approximate:
        confidence = max(confidence, 0.68)
    return {'neighborhood': neighborhood, 'street': street, 'subarea': subarea,
            'nearby_streets': nearby_streets, 'distance_m': distance_m,
            'confidence': round(confidence, 2), 'source': source}
