from __future__ import annotations

import math
import sqlite3

PLACE_MERGE_RADIUS_KM = 1.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def reverse_geocode_name(lat: float, lon: float) -> str:
    try:
        import reverse_geocoder as rg
    except ImportError:
        return f"{lat:.3f},{lon:.3f}"

    result = rg.search([(lat, lon)])[0]
    parts = [p for p in (result.get("name"), result.get("admin1"), result.get("cc")) if p]
    return ", ".join(parts)


def get_or_create_place(conn: sqlite3.Connection, lat: float | None, lon: float | None) -> int | None:
    """Return a place id for the given GPS coordinate, or None if lat/lon is missing.

    Files without GPS are left with a blank (NULL) place -- location is never
    guessed from image content, only read from GPS metadata.
    """
    if lat is None or lon is None:
        return None

    candidates = conn.execute("SELECT id, lat, lon FROM places").fetchall()
    for row in candidates:
        if haversine_km(lat, lon, row["lat"], row["lon"]) <= PLACE_MERGE_RADIUS_KM:
            return row["id"]

    name = reverse_geocode_name(lat, lon)
    cur = conn.execute(
        "INSERT INTO places (name, lat, lon) VALUES (?, ?, ?)", (name, lat, lon)
    )
    return cur.lastrowid
