#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Point-in-polygon matching for user-drawn Dezful neighborhood GeoJSON areas."""
import json
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

GEOJSON_FILE = Path("data/neighborhoods_dezful.geojson")


def _number(value: Any) -> Optional[float]:
    try:
        return float(str(value).replace("،", "."))
    except (TypeError, ValueError):
        return None


def _on_segment(x: float, y: float, a: Sequence[float], b: Sequence[float]) -> bool:
    ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
    cross = (x-ax)*(by-ay) - (y-ay)*(bx-ax)
    return abs(cross) <= 1e-10 and min(ax,bx)-1e-10 <= x <= max(ax,bx)+1e-10 and min(ay,by)-1e-10 <= y <= max(ay,by)+1e-10


def _in_ring(lon: float, lat: float, ring: Sequence[Sequence[float]]) -> bool:
    if len(ring) < 3:
        return False
    inside = False
    previous = ring[-1]
    for current in ring:
        if _on_segment(lon, lat, previous, current):
            return True
        x1,y1 = float(previous[0]),float(previous[1])
        x2,y2 = float(current[0]),float(current[1])
        if (y1 > lat) != (y2 > lat):
            cross_x = (x2-x1)*(lat-y1)/(y2-y1)+x1
            if lon < cross_x:
                inside = not inside
        previous = current
    return inside


def _in_polygon(lon: float, lat: float, rings: Sequence[Sequence[Sequence[float]]]) -> bool:
    return bool(rings and _in_ring(lon,lat,rings[0]) and not any(_in_ring(lon,lat,hole) for hole in rings[1:]))


def _contains(geometry: Dict[str, Any], lon: float, lat: float) -> bool:
    kind, coords = geometry.get("type"), geometry.get("coordinates") or []
    if kind == "Polygon":
        return _in_polygon(lon,lat,coords)
    if kind == "MultiPolygon":
        return any(_in_polygon(lon,lat,poly) for poly in coords)
    return False


def load_areas(path: Path = GEOJSON_FILE):
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    if data.get("type") == "FeatureCollection":
        features = data.get("features") or []
    elif data.get("type") == "Feature":
        features = [data]
    else:
        features = []
    return [f for f in features if isinstance(f,dict) and isinstance(f.get("geometry"),dict) and f["geometry"].get("type") in ("Polygon","MultiPolygon")]


def classify_point(latitude: Any, longitude: Any, path: Path = GEOJSON_FILE) -> Optional[Dict[str, str]]:
    lat, lon = _number(latitude), _number(longitude)
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    for feature in load_areas(path):
        if _contains(feature["geometry"], lon, lat):
            props = feature.get("properties") or {}
            neighborhood = str(props.get("neighborhood") or props.get("name") or "").strip()
            subarea = str(props.get("subarea") or props.get("label") or "").strip()
            if neighborhood or subarea:
                return {"neighborhood": neighborhood, "subarea": subarea}
    return None
