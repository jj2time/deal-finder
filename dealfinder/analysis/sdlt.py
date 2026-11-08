"""Stamp Duty Land Tax (England, residential) from configurable bands."""
from __future__ import annotations

from typing import Any


def stamp_duty(price: float, cfg: dict[str, Any], additional: bool = True,
               non_resident: bool | None = None) -> int:
    if price <= 0:
        return 0
    bands = cfg["bands"]
    if non_resident is None:
        non_resident = bool(cfg.get("buyer_is_non_resident", False))
    surcharge = 0.0
    if additional and price >= cfg.get("surcharge_min_price", 40000):
        surcharge += cfg.get("additional_property_surcharge_pct", 0)
    if non_resident:
        surcharge += cfg.get("non_resident_surcharge_pct", 0)

    tax = 0.0
    lower = 0.0
    for upper, rate in bands:
        top = price if upper is None else min(price, upper)
        if top > lower:
            tax += (top - lower) * (rate + surcharge) / 100
        if upper is None or price <= upper:
            break
        lower = upper
    return int(round(tax))
