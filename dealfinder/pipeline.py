"""One scan: fetch every source -> filter -> store -> value -> analyse -> alert."""
from __future__ import annotations

import logging
from pathlib import Path

from .analysis import analyse
from .data.http import CachedClient
from .data.landregistry import LandRegistry
from .data.postcodes import Postcodes
from .data.propertydata import PropertyData
from .db import DB
from .models import Listing
from .sources.apify import ApifySource
from .sources.csv_import import CsvImportSource
from .sources.email_alerts import EmailAlertSource

log = logging.getLogger(__name__)

SOURCE_TYPES = {"apify": ApifySource, "email_alerts": EmailAlertSource, "csv_import": CsvImportSource}


def passes_filters(l: Listing, cfg: dict) -> bool:
    f = cfg.get("filters", {})
    districts = [d.upper() for d in cfg.get("areas", {}).get("postcode_districts") or []]
    if districts and l.outcode and l.outcode.upper() not in districts:
        return False
    if l.price is not None:
        if f.get("min_price") and l.price < f["min_price"]:
            return False
        if f.get("max_price") and l.price > f["max_price"]:
            return False
    types = f.get("property_types")
    if types and l.property_type not in types and l.property_type != "other":
        return False
    if f.get("min_bedrooms") and l.bedrooms is not None and l.bedrooms < f["min_bedrooms"]:
        return False
    return True


class Scanner:
    def __init__(self, cfg: dict, db: DB | None = None, http=None, land_registry=None, postcodes=None,
                 propertydata=None, sources=None):
        self.cfg = cfg
        self.db = db or DB(cfg["database"])
        cache_path = str(Path(cfg["database"]).with_name("http_cache.sqlite3"))
        self.http = http or CachedClient(cache_path)
        self.lr = land_registry or LandRegistry(self.http)
        self.pc = postcodes or Postcodes(self.http)
        self.pd = propertydata or PropertyData(self.http)
        self.sources = sources if sources is not None else self._build_sources()

    def _build_sources(self):
        out = []
        for name, scfg in (self.cfg.get("sources") or {}).items():
            if scfg and scfg.get("enabled") and name in SOURCE_TYPES:
                out.append(SOURCE_TYPES[name](scfg, self.http))
        return out

    def comparables(self, l: Listing):
        loc = (l.lat, l.lon) if l.lat and l.lon else self.pc.locate(l.postcode, l.outcode)
        if not loc:
            return []
        if not (l.lat and l.lon):
            l.lat, l.lon = loc
        radius = max(self.cfg["valuation"]["radii_m"])
        nearby = self.pc.nearby(loc[0], loc[1], radius)
        return self.lr.sold_prices(nearby, self.cfg["valuation"]["months_back"])

    def analyse_listing(self, l: Listing):
        try:
            comps = self.comparables(l)
        except Exception as e:
            log.warning("Sold-price lookup failed for %s: %s", l.address, e)
            comps = []
        rent = None
        if not l.rent_pcm and l.postcode:
            rent = self.pd.rent_estimate(l.postcode, l.bedrooms)
        a = analyse(l, comps, self.cfg, rent_pcm=rent, rent_source="PropertyData" if rent else None)
        if not l.postcode and not l.outcode:
            a.notes.append("No postcode in the listing — sold-price comparison not possible.")
        elif not l.postcode:
            a.notes.append(f"Only the district ({l.outcode}) is known — comparables are from around its centre.")
        return a

    def run(self) -> dict:
        stats = {"fetched": 0, "kept": 0, "new": 0, "alerts": 0}
        for source in self.sources:
            try:
                listings = list(source.fetch())
            except Exception as e:
                log.error("Source %s failed: %s", source.name, e)
                continue
            stats["fetched"] += len(listings)
            for l in listings:
                if not passes_filters(l, self.cfg):
                    continue
                stats["kept"] += 1
                info = self.db.upsert_listing(l)
                stats["new"] += info["new"]
                l.raw["_price_reductions"] = info["reductions"]
                a = self.analyse_listing(l)
                self.db.upsert_listing(l)  # store lat/lon found during valuation
                self.db.save_analysis(a)
                if self._maybe_alert(l, a):
                    stats["alerts"] += 1
        log.info("Scan done: %s", stats)
        return stats

    def _maybe_alert(self, l: Listing, a) -> bool:
        acfg = self.cfg.get("alerts") or {}
        if not acfg.get("enabled") or a.score < acfg.get("min_score", 70):
            return False
        if not self.db.mark_alerted(l.key):
            return False
        from .alerts import send_deal_alert
        return send_deal_alert(acfg["to"], l, a)
