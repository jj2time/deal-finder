"""PropertyData API — rent estimates (optional, paid). https://propertydata.co.uk/api"""
from __future__ import annotations

import logging

from ..config import env

log = logging.getLogger(__name__)
BASE = "https://api.propertydata.co.uk"


class PropertyData:
    def __init__(self, http):
        self.http = http
        self.key = env("PROPERTYDATA_API_KEY")

    def rent_estimate(self, postcode: str, bedrooms: int | None) -> int | None:
        if not self.key or not postcode:
            return None
        params = {"key": self.key, "postcode": postcode.replace(" ", "")}
        if bedrooms:
            params["bedrooms"] = min(bedrooms, 5)
        try:
            r = self.http.request_json("GET", f"{BASE}/rents", params=params)
        except Exception as e:
            log.warning("PropertyData rents failed for %s: %s", postcode, e)
            return None
        data = r.get("data") or {}
        long_let = data.get("long_let") or data
        avg = long_let.get("average")
        if avg is None:
            return None
        # PropertyData reports weekly rents; convert to monthly.
        unit = (long_let.get("unit") or r.get("unit") or "gbp_per_week").lower()
        return int(round(avg * 52 / 12)) if "week" in unit else int(round(avg))
