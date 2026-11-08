"""Flags which investment strategies a listing fits, with the reason for each."""
from __future__ import annotations

import re

from ..models import Analysis, Listing, StrategyMatch

KEYWORDS = {
    "repossession": ["repossess", "mortgagee", "lpa receiver", "receivers", "by order of the"],
    "cash_only": ["cash buyers only", "cash buyer only", "non-mortgageable", "unmortgageable",
                  "not mortgageable", "cash purchase only"],
    "refurb": ["in need of modernisation", "requires modernisation", "in need of updating",
               "requires updating", "renovation", "refurbishment", "project", "doer upper",
               "doer-upper", "fixer upper", "needs work", "in need of improvement"],
    "problem": ["subsidence", "japanese knotweed", "fire damaged", "fire damage", "structural",
                "non-standard construction", "concrete construction", "spray foam", "flying freehold",
                "sitting tenant", "tenant in situ", "no access"],
    "motivated": ["no chain", "chain free", "chain-free", "quick sale", "must sell", "reduced",
                  "priced to sell", "offers invited", "motivated seller", "relocation", "probate",
                  "executor", "deceased estate", "vacant possession"],
    "probate": ["probate", "executor", "deceased estate", "estate of the late"],
    "auction": ["auction", "modern method of auction", "guide price"],
    "hmo": ["hmo", "house in multiple occupation", "licensed hmo"],
    "title_split": ["block of flats", "freehold block", "pair of flats", "two flats", "converted into flats",
                    "freehold building comprising"],
    "conversion": ["mixed use", "mixed-use", "commercial premises", "shop with flat", "planning permission",
                   "planning granted", "development opportunity", "permitted development"],
    "sa": ["holiday let", "airbnb", "serviced accommodation", "short let"],
}


def _has(text: str, group: str) -> str | None:
    for kw in KEYWORDS[group]:
        if kw in text:
            return kw
    return None


def lease_years_from_text(text: str) -> int | None:
    m = re.search(r"(\d{2,3})\s*(?:years?|yrs?)\s*(?:remaining|left|unexpired)", text)
    if not m:
        m = re.search(r"(?:remaining|unexpired)\s*(?:lease|term)?\s*(?:of)?\s*(\d{2,3})\s*years", text)
    return int(m.group(1)) if m else None


def match_strategies(listing: Listing, a: Analysis, thresholds: dict) -> list[StrategyMatch]:
    text = f"{listing.description} {listing.address or ''}".lower()
    out: list[StrategyMatch] = []

    def add(name: str, reason: str) -> None:
        out.append(StrategyMatch(name, reason))

    if a.bmv_pct is not None and a.bmv_pct >= thresholds["bmv_pct"]:
        add("BMV", f"{a.bmv_pct:.0f}% below the median of {a.valuation_comps} nearby sales")

    if a.gross_yield_pct is not None and a.monthly_cashflow is not None:
        if (a.gross_yield_pct >= thresholds["strong_btl_yield_pct"]
                and a.monthly_cashflow >= thresholds["strong_btl_cashflow"]):
            add("Strong BTL", f"{a.gross_yield_pct:.1f}% gross yield, £{a.monthly_cashflow}/month cashflow")

    if kw := _has(text, "cash_only"):
        add("Cash only", f'listing says "{kw}"')

    refurb_kw = _has(text, "refurb")
    if refurb_kw:
        reason = f'listing says "{refurb_kw}"'
        if a.brrr_cash_left_in is not None:
            reason += f"; est. £{a.brrr_cash_left_in:,} left in after refinance"
        add("Refurb / BRRR", reason)
        if a.flip_profit is not None and a.flip_profit > 0:
            add("Flip", f"est. £{a.flip_profit:,} profit after costs")

    if kw := _has(text, "problem"):
        add("Problem property", f'listing mentions "{kw}"')

    beds = listing.bedrooms or 0
    hmo_kw = _has(text, "hmo")
    if hmo_kw or (beds >= 4 and listing.property_type != "flat") or (
            listing.floor_area_sqm and listing.floor_area_sqm >= 110):
        add("HMO potential", f'listing says "{hmo_kw}"' if hmo_kw else
            f"{beds} bedrooms" + (f", {listing.floor_area_sqm:.0f} m²" if listing.floor_area_sqm else "")
            + " — check Article 4 and licensing")

    motivated = _has(text, "motivated")
    reductions = listing.raw.get("_price_reductions", 0)
    if motivated or reductions:
        bits = []
        if motivated:
            bits.append(f'"{motivated}"')
        if reductions:
            bits.append(f"{reductions} price reduction(s) seen")
        add("Motivated seller", ", ".join(bits))

    if kw := _has(text, "probate"):
        add("Probate", f'listing says "{kw}"')

    if kw := _has(text, "repossession"):
        add("Repossession", f'listing says "{kw}"')

    if listing.is_auction or _has(text, "auction"):
        add("Auction", "sold by auction — check the legal pack and completion deadline")

    lease = listing.lease_years or lease_years_from_text(text)
    if lease is not None and lease < 85:
        add("Short lease", f"{lease} years left — lease extension needed; most lenders want 85+")

    if a.negative_equity:
        add("Negative equity", "last recorded sale price is at or above the asking price")

    if a.negative_equity or (a.bmv_pct is not None and a.bmv_pct < 5 and (motivated or reductions)):
        add("Lease option candidate", "little or no equity and a seller who may want out")

    if kw := _has(text, "title_split"):
        add("Title split", f'listing says "{kw}"')
    if kw := _has(text, "conversion"):
        add("Conversion / development", f'listing says "{kw}"')

    if kw := _has(text, "sa"):
        add("Serviced accommodation", f'listing says "{kw}"')

    return out
