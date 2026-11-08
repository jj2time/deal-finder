"""Market value from Land Registry sold prices, widening the radius until there is enough evidence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from ..models import Comparable


@dataclass
class Valuation:
    value: int | None
    done_up_value: int | None
    count: int
    radius_m: int | None
    confidence: float
    comps: list[Comparable]


def _percentile(values: list[int], pct: float) -> float:
    s = sorted(values)
    k = (len(s) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def value_from_comps(comps: list[Comparable], property_type: str, radii_m: list[int],
                     min_count: int, months_back: int, today: date | None = None) -> Valuation:
    today = today or date.today()
    cutoff = (today - timedelta(days=int(months_back * 30.44))).isoformat()
    pool = [c for c in comps if c.date >= cutoff and c.price > 0]
    if property_type in ("detached", "semi-detached", "terraced", "flat"):
        pool = [c for c in pool if c.property_type == property_type]

    chosen: list[Comparable] = []
    used_radius = None
    for r in radii_m:
        within = [c for c in pool if c.distance_m is None or c.distance_m <= r]
        chosen, used_radius = within, r
        if len(within) >= min_count:
            break
    if not chosen:
        return Valuation(None, None, 0, None, 0.0, [])

    prices = [c.price for c in chosen]
    # Confidence: more sales and a tighter radius = more confident.
    count_part = min(len(chosen) / min_count, 1.0)
    radius_part = 1.0 - (radii_m.index(used_radius) / max(len(radii_m), 1)) * 0.5
    confidence = round(count_part * radius_part, 2)
    return Valuation(
        value=int(median(prices)),
        done_up_value=int(_percentile(prices, 0.75)) if len(prices) >= 4 else None,
        count=len(chosen),
        radius_m=used_radius,
        confidence=confidence,
        comps=sorted(chosen, key=lambda c: c.date, reverse=True),
    )
