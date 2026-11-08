"""postcodes.io lookups (free, no key)."""
from __future__ import annotations

import math
import re

BASE = "https://api.postcodes.io"
POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)
OUTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\b")


def normalise(pc: str) -> str:
    m = POSTCODE_RE.search(pc or "")
    return f"{m.group(1).upper()} {m.group(2).upper()}" if m else ""


def find_postcode(text: str) -> str | None:
    m = POSTCODE_RE.search(text or "")
    return f"{m.group(1).upper()} {m.group(2).upper()}" if m else None


def find_outcode(text: str) -> str | None:
    """Outcode at the end of an address like '12 High St, Bristol BS5'."""
    pc = find_postcode(text)
    if pc:
        return pc.split()[0]
    tail = (text or "").strip().split(",")[-1].strip()
    m = OUTCODE_RE.search(tail.upper())
    return m.group(1) if m and any(ch.isdigit() for ch in m.group(1)) else None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Postcodes:
    def __init__(self, http):
        self.http = http

    def locate(self, postcode: str | None = None, outcode: str | None = None) -> tuple[float, float] | None:
        try:
            if postcode:
                r = self.http.request_json("GET", f"{BASE}/postcodes/{postcode.replace(' ', '')}")
            elif outcode:
                r = self.http.request_json("GET", f"{BASE}/outcodes/{outcode}")
            else:
                return None
        except Exception:
            return None
        res = r.get("result") or {}
        if res.get("latitude") is None:
            return None
        return res["latitude"], res["longitude"]

    def nearby(self, lat: float, lon: float, radius_m: int = 2000) -> list[tuple[str, float]]:
        """Postcodes within radius (postcodes.io caps radius at 2000 m and 100 results)."""
        r = self.http.request_json("GET", f"{BASE}/postcodes",
                                   params={"lat": lat, "lon": lon, "radius": min(radius_m, 2000), "limit": 100})
        out = []
        for p in r.get("result") or []:
            d = haversine_m(lat, lon, p["latitude"], p["longitude"])
            out.append((p["postcode"], d))
        return out
