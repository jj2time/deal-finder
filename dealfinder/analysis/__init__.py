"""Runs every calculation for one listing."""
from __future__ import annotations

import re
from datetime import date

from ..models import Analysis, Comparable, Listing
from . import finance
from .score import deal_score
from .strategies import unlike_for_like
from .sdlt import stamp_duty
from .strategies import match_strategies
from .valuation import value_from_comps


def _house_number(address: str | None) -> str | None:
    if not address:
        return None
    m = re.match(r"\s*(?:flat\s+\w+,?\s*)?(\d+[a-z]?)\b", address.lower())
    return m.group(1) if m else None


def sales_history(listing: Listing, comps: list[Comparable]) -> list[dict]:
    """Earlier sales of this exact address (same postcode and house number)."""
    if not listing.postcode:
        return []
    num = _house_number(listing.address)
    if not num:
        return []
    pc = listing.postcode.replace(" ", "").upper()
    hits = [c for c in comps
            if c.postcode.replace(" ", "").upper() == pc and _house_number(c.address) == num]
    return [{"date": c.date, "price": c.price, "address": c.address}
            for c in sorted(hits, key=lambda c: c.date, reverse=True)]


def analyse(listing: Listing, comps: list[Comparable], cfg: dict,
            rent_pcm: int | None = None, rent_source: str | None = None,
            area_price_per_sqm: float | None = None, today: date | None = None) -> Analysis:
    a = Analysis(key=listing.key)
    f, th = cfg["finance"], cfg["thresholds"]
    vcfg = cfg["valuation"]

    val = value_from_comps(comps, listing.property_type, vcfg["radii_m"], vcfg["min_comparables"],
                           vcfg["months_back"], today=today)
    a.market_value, a.done_up_value = val.value, val.done_up_value
    a.valuation_comps, a.valuation_radius_m, a.valuation_confidence = val.count, val.radius_m, val.confidence
    a.comparables = [c.__dict__ for c in val.comps[:30]]
    if val.count and val.count < vcfg["min_comparables"]:
        a.notes.append(f"Only {val.count} comparable sales found within {val.radius_m} m — treat value with caution.")
    if not val.count:
        a.notes.append("No comparable sales found — no market value.")

    price = listing.price
    if not price:
        a.notes.append("No asking price.")
        a.strategies = match_strategies(listing, a, th)
        a.score = deal_score(a)
        return a

    a.stamp_duty = stamp_duty(price, cfg["stamp_duty"], additional=True)

    if a.market_value:
        a.bmv_amount = a.market_value - price
        a.bmv_pct = round(a.bmv_amount / a.market_value * 100, 1)
    a.is_auction = listing.is_auction
    kind = unlike_for_like(f"{listing.description} {listing.address or ''}".lower())
    if kind:
        a.comparison_warning = (f"Looks like {kind}, which sells for much less than ordinary homes nearby — "
                                "the BMV figure isn't meaningful.")
        a.notes.append(a.comparison_warning)
    elif listing.is_auction and a.bmv_pct is not None:
        a.notes.append("Auction: the asking price is a guide price, set low to attract bidders. "
                       "Lots usually sell above guide, so the real discount is smaller.")
    if (listing.tenure or "") == "leasehold" and not listing.lease_years:
        a.notes.append("Leasehold, but the lease length isn't stated — ask the agent before going further.")

    if listing.floor_area_sqm:
        a.price_per_sqm = round(price / listing.floor_area_sqm)
        a.area_price_per_sqm = area_price_per_sqm

    rent = listing.rent_pcm or rent_pcm
    if rent:
        a.rent_pcm = int(rent)
        a.rent_source = "listing" if listing.rent_pcm else rent_source
        a.gross_yield_pct = round(finance.gross_yield_pct(price, rent), 1)
        nums = finance.btl_numbers(price, rent, a.stamp_duty, f)
        a.monthly_mortgage = nums["monthly_mortgage"]
        a.monthly_cashflow = nums["monthly_cashflow"]
        a.cash_in = nums["cash_in"]
        a.roi_pct = nums["roi_pct"]
    else:
        a.notes.append("No rent figure — yield and cashflow not calculated. Add a PropertyData key or enter a rent.")

    a.refurb_cost = finance.refurb_estimate(listing.floor_area_sqm, f)
    end_value = a.done_up_value or a.market_value
    if end_value:
        a.flip_profit = finance.flip_profit(price, end_value, a.stamp_duty, a.refurb_cost, f)
        a.brrr_cash_left_in = finance.brrr_cash_left_in(price, end_value, a.stamp_duty, a.refurb_cost, f)

    a.sales_history = sales_history(listing, comps)
    if a.sales_history and a.sales_history[0]["price"] >= price:
        a.negative_equity = True

    a.strategies = match_strategies(listing, a, th)
    a.score = deal_score(a)
    return a
