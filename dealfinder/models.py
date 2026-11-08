"""Plain data types shared by sources, analysis, storage and the dashboard."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

PROPERTY_TYPES = ("detached", "semi-detached", "terraced", "flat", "other")


@dataclass
class Listing:
    source: str
    source_id: str
    url: str | None = None
    address: str | None = None
    postcode: str | None = None        # full postcode if known
    outcode: str | None = None         # e.g. BS5
    price: int | None = None
    property_type: str = "other"
    bedrooms: int | None = None
    description: str = ""
    tenure: str | None = None          # freehold / leasehold
    lease_years: int | None = None
    floor_area_sqm: float | None = None
    rent_pcm: int | None = None        # entered or supplied by the source; never guessed
    lat: float | None = None
    lon: float | None = None
    listed_date: str | None = None
    image: str | None = None
    is_auction: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["key"] = self.key
        return d


@dataclass
class Comparable:
    price: int
    date: str            # YYYY-MM-DD
    address: str
    postcode: str
    property_type: str
    distance_m: float | None = None
    category: str | None = None   # Land Registry: standard / additional (incl. repossessions, BTL)


@dataclass
class StrategyMatch:
    name: str
    reason: str


@dataclass
class Analysis:
    key: str
    market_value: int | None = None
    done_up_value: int | None = None
    valuation_comps: int = 0
    valuation_radius_m: int | None = None
    valuation_confidence: float = 0.0
    price_per_sqm: float | None = None
    area_price_per_sqm: float | None = None
    bmv_pct: float | None = None
    bmv_amount: int | None = None
    stamp_duty: int | None = None
    rent_pcm: int | None = None
    rent_source: str | None = None
    gross_yield_pct: float | None = None
    monthly_mortgage: int | None = None
    monthly_cashflow: int | None = None
    cash_in: int | None = None
    roi_pct: float | None = None
    refurb_cost: int | None = None
    flip_profit: int | None = None
    brrr_cash_left_in: int | None = None
    sales_history: list[dict[str, Any]] = field(default_factory=list)
    negative_equity: bool = False
    strategies: list[StrategyMatch] = field(default_factory=list)
    score: int = 0
    comparables: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
