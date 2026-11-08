"""Imports any CSV dropped in the imports folder (auction catalogues, agent lists, your own finds).

Columns (header names, case-insensitive; only address and price are required):
address, postcode, price, property_type, bedrooms, url, description, tenure, lease_years,
floor_area_sqm, rent_pcm, auction (yes/no)
"""
from __future__ import annotations

import csv
import hashlib
import logging
from pathlib import Path
from typing import Iterable

from ..config import ROOT
from ..data.postcodes import find_outcode, find_postcode
from ..models import Listing
from .base import normalise_type, parse_int, parse_price

log = logging.getLogger(__name__)


def _float(v) -> float | None:
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else None
    except ValueError:
        return None


def read_csv(path: Path) -> list[Listing]:
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            r = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            address = r.get("address")
            if not address:
                continue
            pc = find_postcode(r.get("postcode") or address)
            sid = hashlib.sha1(f"{address}|{pc}".lower().encode()).hexdigest()[:16]
            desc = r.get("description", "")
            out.append(Listing(
                source=f"csv:{path.stem}", source_id=sid, url=r.get("url") or None, address=address,
                postcode=pc, outcode=find_outcode(pc or address),
                price=parse_price(r.get("price")),
                property_type=normalise_type(r.get("property_type"), desc),
                bedrooms=parse_int(r.get("bedrooms")), description=desc,
                tenure=(r.get("tenure") or None), lease_years=parse_int(r.get("lease_years")),
                floor_area_sqm=_float(r.get("floor_area_sqm")), rent_pcm=parse_int(r.get("rent_pcm")),
                is_auction=r.get("auction", "").lower() in ("yes", "y", "true", "1") or "auction" in desc.lower(),
            ))
    return out


class CsvImportSource:
    name = "csv_import"

    def __init__(self, cfg: dict, http=None):
        folder = Path(cfg.get("folder", "imports"))
        self.folder = folder if folder.is_absolute() else ROOT / folder

    def fetch(self) -> Iterable[Listing]:
        if not self.folder.exists():
            return []
        out: list[Listing] = []
        for path in sorted(self.folder.glob("*.csv")):
            rows = read_csv(path)
            log.info("CSV %s: %d listings", path.name, len(rows))
            out.extend(rows)
        return out
