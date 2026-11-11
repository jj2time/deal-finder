"""Fetching and analysing listings: area searches, saved searches and the daily scan."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

from .analysis import analyse
from .analysis.valuation import value_from_comps
from .config import env
from .data.http import CachedClient
from .data.landregistry import LandRegistry
from .data.postcodes import Postcodes
from .data.propertydata import PropertyData
from .db import DB
from .models import Listing
from .search import Search, rightmove_location_id, rightmove_url, zoopla_url
from .sources.apify import ApifySource, run_actor
from .sources.csv_import import CsvImportSource
from .sources.rightmove import RightmoveError, RightmoveReader
from .sources.email_alerts import EmailAlertSource

log = logging.getLogger(__name__)

SOURCE_TYPES = {"apify": ApifySource, "email_alerts": EmailAlertSource, "csv_import": CsvImportSource}
REFETCH_AFTER = timedelta(hours=12)


class SearchError(Exception):
    """A problem the person needs to fix (shown on the page)."""


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


def search_filter(s: Search) -> Callable[[Listing], bool]:
    def keep(l: Listing) -> bool:
        if l.price is not None:
            if s.min_price and l.price < s.min_price:
                return False
            if s.max_price and l.price > s.max_price:
                return False
        if s.min_beds and l.bedrooms is not None and l.bedrooms < s.min_beds:
            return False
        return l.property_type in s.types or l.property_type == "other"
    return keep


class Scanner:
    def __init__(self, cfg: dict, db: DB | None = None, http=None, land_registry=None, postcodes=None,
                 propertydata=None, sources=None, apify_runner=None, rightmove_reader=None):
        self.cfg = cfg
        self.db = db or DB(cfg["database"])
        cache_path = str(Path(cfg["database"]).with_name("http_cache.sqlite3"))
        self.http = http or CachedClient(cache_path)
        self.lr = land_registry or LandRegistry(self.http)
        self.pc = postcodes or Postcodes(self.http)
        self.pd = propertydata or PropertyData(self.http)
        self.sources = sources if sources is not None else self._build_sources()
        self.apify_runner = apify_runner or (lambda actor, inp: run_actor(self.http, actor, inp))
        self._rightmove_reader = rightmove_reader
        self.progress: Callable[[str], None] = lambda msg: None

    def _build_sources(self):
        out = []
        for name, scfg in (self.cfg.get("sources") or {}).items():
            if scfg and scfg.get("enabled") and name in SOURCE_TYPES:
                out.append(SOURCE_TYPES[name](scfg, self.http))
        return out

    # ---- valuation evidence ----
    def comparables(self, l: Listing):
        loc = (l.lat, l.lon) if l.lat and l.lon else self.pc.locate(l.postcode, l.outcode)
        if not loc:
            return []
        if not (l.lat and l.lon):
            l.lat, l.lon = loc
        v = self.cfg["valuation"]
        max_r = max(v["radii_m"])
        known = dict(self.pc.nearby(loc[0], loc[1], max_r))
        if l.postcode and l.postcode not in known:
            known[l.postcode] = 0.0   # always include the property's own postcode (sales history)
        comps = self.lr.sold_prices(list(known.items()), v["months_back"])
        # Only look further out when the nearest postcodes don't hold enough sales.
        for ring_m in (max_r * 0.45, max_r * 0.8):
            if value_from_comps(comps, l.property_type, v["radii_m"], v["min_comparables"],
                                v["months_back"]).count >= v["min_comparables"]:
                break
            more = [(pc, d) for pc, d in self.pc.ring(loc[0], loc[1], ring_m) if pc not in known and d <= max_r]
            known.update(more)
            comps += self.lr.sold_prices(more, v["months_back"])
        return comps

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

    # ---- processing ----
    def process(self, listings: Iterable[Listing], keep: Callable[[Listing], bool]) -> dict:
        stats = {"fetched": 0, "kept": 0, "new": 0, "alerts": 0}
        listings = list(listings)
        stats["fetched"] = len(listings)
        wanted = [l for l in listings if keep(l)]
        for i, l in enumerate(wanted, 1):
            self.progress(f"Valuing property {i} of {len(wanted)}: {l.address or l.url}")
            stats["kept"] += 1
            info = self.db.upsert_listing(l)
            stats["new"] += info["new"]
            l.raw["_price_reductions"] = info["reductions"]
            a = self.analyse_listing(l)
            self.db.upsert_listing(l)  # store lat/lon found during valuation
            self.db.save_analysis(a)
            if self._maybe_alert(l, a):
                stats["alerts"] += 1
        return stats

    # ---- area search ----
    def portal_inputs(self, s: Search) -> list[tuple[str, str, dict]]:
        """(portal name, actor id, actor input) for each portal with a scraper set up."""
        acfg = (self.cfg.get("sources") or {}).get("apify") or {}
        field = acfg.get("url_field") or "startUrls"
        base = dict(acfg.get("extra_input") or {})
        max_items = int(acfg.get("max_items") or 100)
        out = []
        rm_actor = (acfg.get("rightmove_actor_id") or "").strip()
        if rm_actor:
            loc_id = rightmove_location_id(self.http, s.area)
            if not loc_id:
                raise SearchError(f"Rightmove doesn't recognise “{s.area}”. Check the postcode.")
            out.append(("Rightmove", rm_actor,
                        {**base, field: [{"url": rightmove_url(loc_id, s)}], "maxItems": max_items}))
        zp_actor = (acfg.get("zoopla_actor_id") or "").strip()
        if zp_actor:
            out.append(("Zoopla", zp_actor, {**base, field: [{"url": zoopla_url(s)}], "maxItems": max_items}))
        return out

    def needs_fetch(self, s: Search) -> bool:
        last = self.db.last_fetched(s.fetch_key)
        if not last:
            return True
        return datetime.now(timezone.utc) - datetime.fromisoformat(last) > REFETCH_AFTER

    def rightmove_reader(self) -> RightmoveReader:
        if self._rightmove_reader is None:
            rcfg = (self.cfg.get("sources") or {}).get("rightmove") or {}
            self._rightmove_reader = RightmoveReader(max_pages=rcfg.get("max_pages", 3),
                                                     details=rcfg.get("details", "leasehold"))
        return self._rightmove_reader

    def run_search(self, s: Search) -> dict:
        if not s.area:
            raise SearchError("Type a postcode or postcode district, e.g. BS5 6HN or M14.")
        if not self.pc.locate(s.area if s.is_full_postcode else None, None if s.is_full_postcode else s.area):
            raise SearchError(f"“{s.area}” isn't a UK postcode or postcode district we can find.")
        free_rm = ((self.cfg.get("sources") or {}).get("rightmove") or {}).get("enabled", True)
        acfg = (self.cfg.get("sources") or {}).get("apify") or {}
        use_apify = bool(acfg.get("rightmove_actor_id") or acfg.get("zoopla_actor_id"))
        if use_apify and not env("APIFY_TOKEN"):
            raise SearchError("Add your Apify token in Settings, or clear the Apify scraper IDs to use the free reader.")
        if not free_rm and not use_apify:
            raise SearchError("Turn on the free Rightmove reader in Settings, or add an Apify scraper.")

        listings: list[Listing] = []
        errors = []
        if free_rm and not acfg.get("rightmove_actor_id"):
            loc_id = rightmove_location_id(self.http, s.area)
            if not loc_id:
                raise SearchError(f"Rightmove doesn't recognise “{s.area}”. Check the postcode.")
            try:
                listings.extend(self.rightmove_reader().search(rightmove_url(loc_id, s), self.progress))
            except RightmoveError as e:
                errors.append(f"Rightmove: {e}")
        if use_apify:
            for portal, actor, inp in self.portal_inputs(s):
                self.progress(f"Fetching listings from {portal} via Apify (usually 1–3 minutes)…")
                try:
                    found = self.apify_runner(actor, inp)
                    log.info("%s: %d listings", portal, len(found))
                    listings.extend(found)
                except Exception as e:
                    log.error("%s scraper failed: %s", portal, e)
                    errors.append(f"{portal}: {e}")
        if errors and not listings:
            raise SearchError(" ".join(errors))
        stats = self.process(listings, search_filter(s))
        stats["errors"] = errors
        self.db.mark_fetched(s.fetch_key, s.to_dict(), stats["fetched"])
        return stats

    def run_searches(self, searches: list[Search], refresh: bool = False) -> dict:
        """Several area searches in one go; one failing area doesn't stop the others."""
        total = {"fetched": 0, "kept": 0, "new": 0, "alerts": 0, "errors": []}
        done = 0
        for i, s in enumerate(searches, 1):
            if not refresh and not self.needs_fetch(s):
                done += 1
                continue
            if len(searches) > 1:
                outer = self.progress
                self.progress = lambda m, outer=outer, s=s, i=i: outer(f"{s.area} ({i} of {len(searches)}): {m}")
            try:
                stats = self.run_search(s)
                done += 1
                for k in ("fetched", "kept", "new", "alerts"):
                    total[k] += stats.get(k, 0)
                total["errors"] += stats.get("errors", [])
            except SearchError as e:
                total["errors"].append(f"{s.area}: {e}")
            finally:
                if len(searches) > 1:
                    self.progress = outer
        if not done and total["errors"]:
            raise SearchError(" ".join(total["errors"]))
        return total

    # ---- daily scan ----
    def run(self) -> dict:
        total = {"fetched": 0, "kept": 0, "new": 0, "alerts": 0}

        def add(stats):
            for k in total:
                total[k] += stats.get(k, 0)

        for source in self.sources:
            try:
                add(self.process(source.fetch(), lambda l: passes_filters(l, self.cfg)))
            except Exception as e:
                log.error("Source %s failed: %s", source.name, e)
        for saved in self.db.saved_searches():
            try:
                add(self.run_search(Search.from_dict(saved)))
            except Exception as e:
                log.error("Saved search %s failed: %s", saved.get("area"), e)
        log.info("Scan done: %s", total)
        return total

    def _maybe_alert(self, l: Listing, a) -> bool:
        acfg = self.cfg.get("alerts") or {}
        if not acfg.get("enabled") or a.score < acfg.get("min_score", 70):
            return False
        if not self.db.mark_alerted(l.key):
            return False
        from .alerts import send_deal_alert
        return send_deal_alert(acfg["to"], l, a)
