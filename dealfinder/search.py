"""Area searches: a postcode + radius + filters + the deal types you tick.

Running a search builds Rightmove / Zoopla results-page links for the area, hands them to your Apify
scrapers, and analyses every listing that comes back. Results are stored, so showing a search again is
instant; it only fetches fresh listings when the area hasn't been fetched recently (or you ask it to).
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import quote, urlencode

from .analysis.strategies import STRATEGY_NAMES
from .data.postcodes import POSTCODE_RE, haversine_m, normalise
from .models import PROPERTY_TYPES

log = logging.getLogger(__name__)

RADII_MILES = [0.25, 0.5, 1, 3, 5, 10, 15, 20, 30, 40]
METRES_PER_MILE = 1609.34
RIGHTMOVE_TYPES = {"detached": "detached", "semi-detached": "semi-detached", "terraced": "terraced",
                   "flat": "flat", "other": "bungalow"}


def _int(v) -> int | None:
    try:
        return int(float(str(v).replace(",", "").replace("£", ""))) if v not in (None, "") else None
    except ValueError:
        return None


def _float(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def clean_area(text: str) -> str:
    """'bs5 6hn' -> 'BS5 6HN'; 'm14' -> 'M14'."""
    text = (text or "").strip().upper()
    full = normalise(text)
    return full or " ".join(text.split())


@dataclass
class Search:
    area: str = ""                     # full postcode or district, e.g. "BS5 6HN" or "BS5"
    radius_miles: float = 1
    min_price: int | None = None
    max_price: int | None = None
    min_beds: int | None = None
    types: list[str] = field(default_factory=lambda: list(PROPERTY_TYPES))
    deals: list[str] = field(default_factory=list)   # ticked deal types; empty = all deals
    min_bmv: float | None = None
    min_yield: float | None = None
    sort: str = "score"

    @classmethod
    def from_params(cls, get_one, get_list) -> "Search":
        radius = _float(get_one("radius")) or 1
        types = [t for t in get_list("type") if t in PROPERTY_TYPES]
        return cls(
            area=clean_area(get_one("area") or ""),
            radius_miles=next((r for r in RADII_MILES if r >= radius - 1e-9), RADII_MILES[-1]),
            min_price=_int(get_one("min_price")), max_price=_int(get_one("max_price")),
            min_beds=_int(get_one("min_beds")),
            types=types or list(PROPERTY_TYPES),
            deals=[d for d in get_list("deal") if d in STRATEGY_NAMES],
            min_bmv=_float(get_one("min_bmv")), min_yield=_float(get_one("min_yield")),
            sort=get_one("sort") or "score",
        )

    @classmethod
    def from_dict(cls, d: dict) -> "Search":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_full_postcode(self) -> bool:
        return bool(POSTCODE_RE.fullmatch(self.area))

    @property
    def outcode(self) -> str:
        return self.area.split()[0] if self.area else ""

    @property
    def fetch_key(self) -> str:
        """Searches that would fetch the same listings share a key."""
        return "|".join(str(x) for x in (self.area, self.radius_miles, self.min_price, self.max_price,
                                         self.min_beds, ",".join(sorted(self.types))))

    def query_string(self) -> str:
        pairs: list[tuple[str, Any]] = [("area", self.area), ("radius", self.radius_miles)]
        for k in ("min_price", "max_price", "min_beds", "min_bmv", "min_yield"):
            if getattr(self, k) is not None:
                pairs.append((k, getattr(self, k)))
        pairs += [("type", t) for t in self.types] + [("deal", d) for d in self.deals]
        if self.sort != "score":
            pairs.append(("sort", self.sort))
        return urlencode(pairs)

    def describe(self) -> str:
        bits = [f"within {self.radius_miles:g} mile{'s' if self.radius_miles != 1 else ''} of {self.area}"]
        if self.min_price and self.max_price:
            bits.append(f"£{self.min_price:,}–£{self.max_price:,}")
        elif self.max_price:
            bits.append(f"up to £{self.max_price:,}")
        elif self.min_price:
            bits.append(f"from £{self.min_price:,}")
        if self.min_beds:
            bits.append(f"{self.min_beds}+ beds")
        return ", ".join(bits)


# ---- portal links -------------------------------------------------------------------------------

def rightmove_location_id(http, area: str) -> str | None:
    """Rightmove's own location code for a postcode/district (e.g. 'OUTCODE^291')."""
    try:
        r = http.request_json("GET", "https://los.rightmove.co.uk/typeahead",
                              params={"query": area, "limit": 10})
    except Exception as e:
        log.warning("Rightmove location lookup failed for %s: %s", area, e)
        return None
    want = "POSTCODE" if POSTCODE_RE.fullmatch(area) else "OUTCODE"
    matches = r.get("matches") or []
    for m in matches:
        if m.get("type") == want and m.get("displayName", "").upper().replace(" ", "") == area.replace(" ", ""):
            return f"{want}^{m['id']}"
    for m in matches:
        if m.get("type") in ("POSTCODE", "OUTCODE", "REGION"):
            return f"{m['type']}^{m['id']}"
    return None


def rightmove_url(location_id: str, s: Search) -> str:
    params: list[tuple[str, Any]] = [("locationIdentifier", location_id), ("radius", s.radius_miles)]
    if s.min_price:
        params.append(("minPrice", s.min_price))
    if s.max_price:
        params.append(("maxPrice", s.max_price))
    if s.min_beds:
        params.append(("minBedrooms", s.min_beds))
    if set(s.types) != set(PROPERTY_TYPES):
        params.append(("propertyTypes", ",".join(RIGHTMOVE_TYPES[t] for t in s.types)))
    params += [("sortType", 6), ("includeSSTC", "false")]
    return "https://www.rightmove.co.uk/property-for-sale/find.html?" + urlencode(params)


def zoopla_url(s: Search) -> str:
    params: list[tuple[str, Any]] = [("q", s.area), ("radius", s.radius_miles), ("search_source", "for-sale")]
    if s.min_price:
        params.append(("price_min", s.min_price))
    if s.max_price:
        params.append(("price_max", s.max_price))
    if s.min_beds:
        params.append(("beds_min", s.min_beds))
    return f"https://www.zoopla.co.uk/for-sale/property/{quote(s.outcode.lower())}/?" + urlencode(params)


# ---- matching stored results against a search ---------------------------------------------------

def matches(item: dict, s: Search, centre: tuple[float, float] | None) -> bool:
    l, a = item["listing"], item["analysis"]
    if centre and l.get("lat") and l.get("lon"):
        if haversine_m(centre[0], centre[1], l["lat"], l["lon"]) > s.radius_miles * METRES_PER_MILE * 1.05:
            return False
    elif s.area:
        if (l.get("outcode") or "").upper() != s.outcode:
            return False
    price = l.get("price")
    if price is not None:
        if s.min_price and price < s.min_price:
            return False
        if s.max_price and price > s.max_price:
            return False
    if s.min_beds and l.get("bedrooms") is not None and l["bedrooms"] < s.min_beds:
        return False
    if l.get("property_type") not in s.types and l.get("property_type") != "other":
        return False
    if s.deals and not ({m["name"] for m in a["strategies"]} & set(s.deals)):
        return False
    if s.min_bmv is not None and (a.get("bmv_pct") is None or a["bmv_pct"] < s.min_bmv):
        return False
    if s.min_yield is not None and (a.get("gross_yield_pct") is None or a["gross_yield_pct"] < s.min_yield):
        return False
    return True


SORTS = {
    "score": ("Best deal score", lambda it: -it["analysis"]["score"]),
    "bmv": ("Biggest BMV", lambda it: -(it["analysis"].get("bmv_pct") or -999)),
    "yield": ("Highest yield", lambda it: -(it["analysis"].get("gross_yield_pct") or -999)),
    "cashflow": ("Best cashflow", lambda it: -(it["analysis"].get("monthly_cashflow") or -99999)),
    "price_low": ("Lowest price", lambda it: it["listing"].get("price") or 10**12),
    "newest": ("Newest first", lambda it: "~" if not it.get("first_seen") else
               "".join(chr(255 - ord(c)) for c in it["first_seen"])),
}
