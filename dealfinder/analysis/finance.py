"""Mortgage, yield, cashflow, ROI, flip and BRRR maths."""
from __future__ import annotations


def monthly_mortgage(loan: float, rate_pct: float, interest_only: bool = True, years: int = 25) -> float:
    if loan <= 0:
        return 0.0
    r = rate_pct / 100 / 12
    if interest_only or r == 0:
        return loan * r if r else loan / (years * 12)
    n = years * 12
    return loan * r / (1 - (1 + r) ** -n)


def gross_yield_pct(price: float, rent_pcm: float) -> float:
    return rent_pcm * 12 / price * 100 if price else 0.0


def btl_numbers(price: float, rent_pcm: float, sdlt: float, f: dict) -> dict:
    loan = price * f["loan_to_value_pct"] / 100
    mortgage = monthly_mortgage(loan, f["mortgage_rate_pct"], f.get("interest_only", True))
    costs = rent_pcm * f["running_costs_pct"] / 100
    cashflow = rent_pcm - mortgage - costs
    cash_in = price - loan + sdlt + f["legal_and_survey"]
    roi = cashflow * 12 / cash_in * 100 if cash_in > 0 else 0.0
    return {
        "monthly_mortgage": round(mortgage),
        "monthly_cashflow": round(cashflow),
        "cash_in": round(cash_in),
        "roi_pct": round(roi, 1),
    }


def refurb_estimate(floor_area_sqm: float | None, f: dict) -> int:
    if floor_area_sqm:
        return int(round(floor_area_sqm * f["refurb_per_sqm"]))
    return int(f["refurb_default"])


def flip_profit(price: float, end_value: float, sdlt: float, refurb: float, f: dict) -> int:
    selling = end_value * f["flip_selling_costs_pct"] / 100
    finance = price * f["mortgage_rate_pct"] / 100 * f["flip_months"] / 12
    return int(round(end_value - price - sdlt - f["legal_and_survey"] - refurb - selling - finance))


def brrr_cash_left_in(price: float, end_value: float, sdlt: float, refurb: float, f: dict) -> int:
    """Cash still tied up after buying (cash/bridge), refurbishing and refinancing at end value."""
    total_in = price + sdlt + f["legal_and_survey"] + refurb
    new_loan = end_value * f["refinance_ltv_pct"] / 100
    return int(round(total_in - new_loan))
