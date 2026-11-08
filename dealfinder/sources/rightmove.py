"""Free, built-in Rightmove reader.

Reads Rightmove's ordinary search results pages (the same pages you see in a browser) slowly and at low
volume, and — for leasehold properties — the property page, to get the years left on the lease and the full
description. It identifies itself honestly and does nothing to get round Rightmove's protections: if Rightmove
refuses, it stops and says so.

Using it is against Rightmove's terms of use; see the README. Keep searches modest.
"""
from __future__ import annotations

import html as htmllib
import json
import logging
import random
import re
import time
from typing import Any, Callable

import httpx

from ..data.postcodes import find_outcode, find_postcode
from ..models import Listing
from .base import normalise_type, parse_int, parse_price

log = logging.getLogger(__name__)

BASE = "https://www.rightmove.co.uk"
USER_AGENT = "dealfinder/1.0 (personal property research tool)"
PER_PAGE = 24
NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


class RightmoveError(Exception):
    pass


# ---- parsing ------------------------------------------------------------------------------------

def parse_search_page(html: str) -> tuple[list[dict], int]:
    """(property dicts, total results) from a search results page."""
    m = NEXT_DATA_RE.search(html)
    if not m:
        raise RightmoveError("Rightmove's page didn't contain any listings — it may have changed its layout.")
    data = json.loads(m.group(1))
    results = (((data.get("props") or {}).get("pageProps") or {}).get("searchResults")) or {}
    total = parse_int(results.get("resultCount")) or 0
    return list(results.get("properties") or []), total


def _strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", htmllib.unescape(text)).strip()


def parse_property_page(html: str) -> dict[str, Any]:
    """Lease years, tenure, floor area and full description from a property page."""
    i = html.find("window.__PAGE_MODEL =")
    if i < 0:
        return {}
    try:
        model, _ = json.JSONDecoder().raw_decode(html[i + len("window.__PAGE_MODEL ="):].lstrip())
        arr = model["data"]
        arr = json.loads(arr) if isinstance(arr, str) else arr
    except (ValueError, KeyError, TypeError):
        return {}
    if not isinstance(arr, list):
        return {}

    # The page model is "flattened": objects hold positions in one big array instead of values.
    def res(idx, depth=0):
        if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < len(arr) or depth > 30:
            return None
        v = arr[idx]
        if isinstance(v, dict):
            return {k: res(x, depth + 1) for k, x in v.items()}
        if isinstance(v, list):
            return [res(x, depth + 1) for x in v]
        return v

    root = res(0) or {}
    pd = root.get("propertyData") or {}
    tenure = pd.get("tenure") or {}
    sqm = None
    for s in pd.get("sizings") or []:
        if isinstance(s, dict) and s.get("unit") == "sqm":
            sqm = s.get("minimumSize") or s.get("maximumSize")
    text = pd.get("text") or {}
    return {
        "tenure": (tenure.get("tenureType") or "").lower() or None,
        "lease_years": parse_int(tenure.get("yearsRemainingOnLease")),
        "floor_area_sqm": float(sqm) if sqm else None,
        "description": _strip_html(text.get("description") or ""),
        "key_features": [f for f in (pd.get("keyFeatures") or []) if isinstance(f, str)],
    }


def _sqm(display_size: str | None) -> float | None:
    if not display_size:
        return None
    m = re.search(r"([\d,.]+)\s*sq\.?\s*(ft|m)", display_size, re.I)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    return round(n * 0.092903, 1) if m.group(2).lower() == "ft" else n


def map_property(p: dict) -> Listing | None:
    """A property from Rightmove's search data (or the trimmed copy the browser button sends)."""
    pid = p.get("id")
    if not pid:
        return None
    price = p.get("price")
    if isinstance(price, dict):
        price = price.get("amount")
    feats = [f.get("description") if isinstance(f, dict) else f for f in (p.get("keyFeatures") or [])]
    desc = " ".join(x for x in [p.get("summary") or "", ". ".join(f for f in feats if f)] if x)
    tenure = p.get("tenure")
    if isinstance(tenure, dict):
        tenure = tenure.get("tenureType")
    loc = p.get("location") or {}
    url = p.get("propertyUrl") or f"/properties/{pid}"
    url = (BASE + url if url.startswith("/") else url).split("#")[0]
    image = p.get("image")
    if not image and isinstance(p.get("propertyImages"), dict):
        image = p["propertyImages"].get("mainImageSrc")
        if not image and p["propertyImages"].get("images"):
            image = p["propertyImages"]["images"][0].get("srcUrl")
    address = p.get("displayAddress") or ""
    reduced = str(p.get("addedOrReduced") or "")
    listing = Listing(
        source="rightmove", source_id=str(pid), url=url, address=address or None,
        postcode=find_postcode(address), outcode=find_outcode(address),
        price=parse_price(price),
        property_type=normalise_type(p.get("propertySubType"), f"{address} {p.get('propertyTypeFullDescription') or ''}"),
        bedrooms=parse_int(p.get("bedrooms")), description=desc,
        tenure=str(tenure).lower() if tenure else None,
        floor_area_sqm=_sqm(p.get("displaySize")),
        lat=loc.get("latitude"), lon=loc.get("longitude"),
        listed_date=str(p.get("firstVisibleDate") or "")[:10] or None, image=image,
        is_auction=bool(p.get("auction")) or "auction" in desc.lower(),
        raw={"addedOrReduced": reduced, "_portal_reduced": reduced.lower().startswith("reduced")},
    )
    return listing


def add_details(listing: Listing, details: dict) -> None:
    if details.get("tenure"):
        listing.tenure = details["tenure"]
    if details.get("lease_years"):
        listing.lease_years = details["lease_years"]
    if details.get("floor_area_sqm") and not listing.floor_area_sqm:
        listing.floor_area_sqm = details["floor_area_sqm"]
    if details.get("description"):
        feats = ". ".join(details.get("key_features") or [])
        listing.description = f"{details['description']} {feats}".strip()


# ---- fetching -----------------------------------------------------------------------------------

class RightmoveReader:
    def __init__(self, max_pages: int = 3, details: str = "leasehold", max_details: int = 25,
                 pause: tuple[float, float] = (2.0, 4.0), client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.max_pages = max(1, int(max_pages))
        self.details = details            # "none" | "leasehold" | "all"
        self.max_details = max_details
        self.pause = pause
        self.client = client or httpx.Client(timeout=30, follow_redirects=True,
                                             headers={"User-Agent": USER_AGENT, "Accept-Language": "en-GB"})
        self.sleep = sleep
        self._first = True

    def _get(self, url: str) -> str:
        if not self._first:
            self.sleep(random.uniform(*self.pause))
        self._first = False
        try:
            r = self.client.get(url)
        except httpx.HTTPError as e:
            raise RightmoveError(f"Couldn't reach Rightmove ({e.__class__.__name__}).") from e
        if r.status_code in (403, 429):
            raise RightmoveError("Rightmove refused the request (it may be limiting automated visits). "
                                 "Wait a while before searching again, or use your Rightmove email alerts.")
        if r.status_code >= 400:
            raise RightmoveError(f"Rightmove answered with error {r.status_code}.")
        return r.text

    def search(self, search_url: str, progress: Callable[[str], None] = lambda m: None) -> list[Listing]:
        listings: dict[str, Listing] = {}
        total = None
        for page in range(self.max_pages):
            progress(f"Reading Rightmove results page {page + 1}…")
            url = search_url + (f"&index={page * PER_PAGE}" if page else "")
            props, total = parse_search_page(self._get(url))
            for p in props:
                l = map_property(p)
                if l:
                    listings.setdefault(l.key, l)
            if not props or (page + 1) * PER_PAGE >= (total or 0):
                break
        out = list(listings.values())
        log.info("Rightmove: %d listings (of %s in the area)", len(out), total)

        wanted = [l for l in out if self.details == "all" or
                  (self.details == "leasehold" and (l.tenure or "") != "freehold" and
                   (l.property_type == "flat" or (l.tenure or "") == "leasehold"))]
        for i, l in enumerate(wanted[: self.max_details], 1):
            progress(f"Checking lease details {i} of {min(len(wanted), self.max_details)}…")
            try:
                add_details(l, parse_property_page(self._get(l.url)))
            except RightmoveError as e:
                log.warning("Stopped reading property pages: %s", e)
                break
        return out
