from datetime import date

from dealfinder.analysis import analyse
from dealfinder.models import Comparable, Listing
from tests.helpers import comps

TODAY = date(2026, 11, 1)


def listing(**kw):
    base = dict(source="test", source_id="1", address="12 Test Street, Bristol", postcode="BS5 6AA",
                outcode="BS5", price=120000, property_type="terraced", bedrooms=3,
                description="Three bedroom terrace in need of modernisation. Cash buyers only. No chain.")
    base.update(kw)
    return Listing(**base)


def names(a):
    return {s.name for s in a.strategies}


def test_full_analysis(cfg):
    a = analyse(listing(), comps(10, 160000), cfg, rent_pcm=950, rent_source="PropertyData", today=TODAY)
    assert a.market_value == 164500
    assert a.bmv_pct == round((164500 - 120000) / 164500 * 100, 1)
    assert a.gross_yield_pct == 9.5
    assert a.monthly_cashflow is not None and a.flip_profit is not None
    assert {"BMV", "Cash only", "Refurb / BRRR", "Motivated seller"} <= names(a)
    assert 0 < a.score <= 100


def test_no_rent_means_no_yield(cfg):
    a = analyse(listing(), comps(10, 160000), cfg, today=TODAY)
    assert a.gross_yield_pct is None and a.monthly_cashflow is None
    assert any("No rent" in n for n in a.notes)


def test_negative_equity_and_history(cfg):
    history = [Comparable(price=130000, date="2025-06-01", address="12, Test Street, Bristol",
                          postcode="BS5 6AA", property_type="terraced", distance_m=0)]
    a = analyse(listing(description="Nice house"), comps(8, 160000, start=50) + history, cfg, today=TODAY)
    assert a.sales_history and a.sales_history[0]["price"] == 130000
    assert a.negative_equity and "Negative equity" in names(a)
    assert "Lease option candidate" in names(a)


def test_short_lease_hmo_and_auction(cfg):
    l = listing(property_type="flat", bedrooms=5, is_auction=True,
                description="Leasehold flat with 62 years remaining, sold by auction. Licensed HMO.")
    a = analyse(l, [], cfg, today=TODAY)
    n = names(a)
    assert {"Short lease", "HMO potential", "Auction"} <= n
    assert a.market_value is None and a.bmv_pct is None


def test_repossession_probate(cfg):
    a = analyse(listing(description="Repossession. Sold on behalf of the executor. Probate granted."), [],
                cfg, today=TODAY)
    assert {"Repossession", "Probate"} <= names(a)
