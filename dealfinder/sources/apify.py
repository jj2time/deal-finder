"""Runs Apify actors (e.g. community Rightmove/Zoopla scrapers) and maps their output to Listings.

Actor output formats differ, so the mapper looks for the common field names. Check one run's
output in the Apify console and add a field name to FIELD_NAMES if something isn't picked up.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Iterable

from ..config import env
from ..data.postcodes import find_outcode, find_postcode
from ..models import Listing
from .base import normalise_type, parse_int, parse_price

log = logging.getLogger(__name__)
API = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"

FIELD_NAMES = {
    "id": ["id", "propertyId", "listingId", "listing_id", "property_id"],
    "url": ["url", "propertyUrl", "listingUrl", "link", "detailUrl"],
    "address": ["displayAddress", "address", "fullAddress", "title", "addressLine"],
    "price": ["price", "displayPrice", "priceAmount", "amount", "askingPrice"],
    "type": ["propertySubType", "propertyType", "type", "property_type"],
    "beds": ["bedrooms", "beds", "numBedrooms", "num_bedrooms"],
    "desc": ["description", "summary", "text", "fullDescription", "propertyDescription"],
    "postcode": ["postcode", "postCode", "postalCode"],
    "tenure": ["tenure", "tenureType"],
    "image": ["image", "mainImage", "propertyImage", "thumbnail"],
    "date": ["addedOn", "listingDate", "firstListedDate", "listedDate", "firstVisibleDate"],
}


def _get(item: dict, field: str) -> Any:
    for name in FIELD_NAMES[field]:
        if name in item and item[name] not in (None, ""):
            v = item[name]
            if isinstance(v, dict):
                v = v.get("amount") or v.get("value") or v.get("displayAddress") or v.get("url") or v
            if isinstance(v, list):
                v = v[0] if v else None
                if isinstance(v, dict):
                    v = v.get("url") or v.get("srcUrl") or v.get("src")
            return v
    return None


def _latlon(item: dict) -> tuple[float | None, float | None]:
    for key in ("location", "coordinates", "geo"):
        loc = item.get(key)
        if isinstance(loc, dict):
            lat = loc.get("latitude") or loc.get("lat")
            lon = loc.get("longitude") or loc.get("lng") or loc.get("lon")
            if lat and lon:
                return float(lat), float(lon)
    lat, lon = item.get("latitude") or item.get("lat"), item.get("longitude") or item.get("lng")
    return (float(lat), float(lon)) if lat and lon else (None, None)


def map_item(item: dict, source: str = "apify") -> Listing | None:
    url = _get(item, "url")
    if isinstance(url, str) and url.startswith("/"):
        url = "https://www.rightmove.co.uk" + url
    sid = _get(item, "id") or (hashlib.sha1(url.encode()).hexdigest()[:16] if url else None)
    if not sid:
        return None
    address = _get(item, "address")
    address = str(address) if address else None
    desc = " ".join(str(x) for x in [_get(item, "desc"), item.get("keyFeatures") or item.get("features")] if x)
    postcode = _get(item, "postcode") or find_postcode(address or "")
    lat, lon = _latlon(item)
    tenure = _get(item, "tenure")
    if isinstance(tenure, dict):
        tenure = tenure.get("tenureType")
    if "rightmove" in str(url):
        source = "rightmove"
    elif "zoopla" in str(url):
        source = "zoopla"
    return Listing(
        source=source,
        source_id=str(sid),
        url=url,
        address=address,
        postcode=find_postcode(postcode) if postcode else None,
        outcode=find_outcode(postcode or address or ""),
        price=parse_price(_get(item, "price")),
        property_type=normalise_type(_get(item, "type"), address or ""),
        bedrooms=parse_int(_get(item, "beds")),
        description=desc,
        tenure=str(tenure).lower() if tenure else None,
        lat=lat, lon=lon,
        listed_date=str(_get(item, "date"))[:10] if _get(item, "date") else None,
        image=_get(item, "image"),
        is_auction="auction" in desc.lower(),
        raw={k: item[k] for k in list(item)[:40]},
    )


class ApifySource:
    name = "apify"

    def __init__(self, cfg: dict, http=None):
        self.runs = cfg.get("runs", [])
        self.http = http

    def fetch(self) -> Iterable[Listing]:
        token = env("APIFY_TOKEN")
        if not token:
            log.warning("APIFY_TOKEN not set in .env — skipping Apify.")
            return []
        out: list[Listing] = []
        for run in self.runs:
            actor = str(run["actor_id"]).replace("/", "~")
            if actor.startswith("REPLACE"):
                log.warning("Apify run %r has no actor_id set — skipping.", run.get("name"))
                continue
            if "startUrls" in (run.get("input") or {}) and not run["input"]["startUrls"]:
                log.warning("Apify run %r has no search pages set — skipping.", run.get("name"))
                continue
            log.info("Running Apify actor %s (%s)…", actor, run.get("name"))
            try:
                items = self.http.request_json(
                    "POST", API.format(actor=actor), json_body=run.get("input", {}),
                    headers={"Authorization": f"Bearer {token}"}, cache=False, timeout=300)
            except Exception as e:  # one broken actor shouldn't stop the scan
                log.error("Apify run %r failed: %s", run.get("name"), e)
                continue
            for item in items or []:
                listing = map_item(item)
                if listing:
                    out.append(listing)
            log.info("  %d listings", len(items or []))
        return out
