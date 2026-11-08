"""Every listing source implements this, so new sources need no analysis changes."""
from __future__ import annotations

import re
from typing import Iterable, Protocol

from ..models import Listing


class ListingSource(Protocol):
    name: str

    def fetch(self) -> Iterable[Listing]: ...


def parse_price(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    m = re.search(r"£?\s*([\d,]{4,})", str(value))
    return int(m.group(1).replace(",", "")) if m else None


def parse_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    m = re.search(r"\d+", str(value))
    return int(m.group(0)) if m else None


def normalise_type(value: str | None, text: str = "") -> str:
    s = f"{value or ''} {text}".lower()
    if "semi" in s:
        return "semi-detached"
    if "detached" in s or "bungalow" in s and "terrace" not in s:
        return "detached"
    if "terrace" in s or "end of terrace" in s or "town house" in s or "townhouse" in s:
        return "terraced"
    if any(w in s for w in ("flat", "apartment", "maisonette", "studio", "penthouse")):
        return "flat"
    return "other"
