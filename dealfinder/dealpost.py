"""Investor deal posts: the BRRR / BMV / flip / buy-to-let numbers for one property, written up as a
short social-media post you can copy.

Every figure comes from Deal Finder's analysis or from what you type in. Selling points such as
"quote provided" or "fully hands off" only appear when you tick them, so a post never claims
something that isn't true.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .analysis.finance import monthly_mortgage
from .analysis.sdlt import stamp_duty

# Selling points you can tick. Each only appears in the post when ticked.
HIGHLIGHTS = {
    "quote": "Refurb quote provided",
    "build_team": "Full build team in place",
    "project_management": "Full project management included",
    "hands_off": "Fully hands-off investment",
    "lettings": "Full lettings team in place",
    "tenant": "Tenant ready to move in",
    "legal_pack": "Legal pack available",
}

STRATEGY_LABELS = {"brrr": "BRRR", "bmv": "Below market value", "flip": "Flip", "btl": "Buy-to-let"}

STRATEGY_TITLES = {
    "brrr": "BRRR DEAL",
    "bmv": "BELOW MARKET VALUE DEAL",
    "flip": "FLIP DEAL",
    "btl": "BUY-TO-LET DEAL",
}


def _int(v, default=None):
    try:
        return int(round(float(str(v).replace(",", "").replace("£", "")))) if v not in (None, "") else default
    except ValueError:
        return default


POSTCODE_ANYWHERE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?(?:\s*\d[A-Z]{2})?\b", re.I)
COUNTIES = {"merseyside", "greater manchester", "west midlands", "tyne and wear", "greater london",
            "south yorkshire", "west yorkshire", "north yorkshire", "east yorkshire", "east riding of yorkshire",
            "kent", "essex", "surrey", "east sussex", "west sussex", "norfolk", "suffolk", "devon", "cornwall",
            "dorset", "somerset", "cumbria", "durham", "county durham", "northumberland", "rutland",
            "isle of wight", "city of bristol", "bristol city", "south glamorgan", "west glamorgan", "gwent",
            "clwyd", "dyfed", "gwynedd", "powys", "mid glamorgan", "uk", "united kingdom", "england", "wales"}


def town_from_address(address: str | None) -> str:
    """'777 Ecclesall Road, Sheffield, South Yorkshire S11 8TH' -> 'Sheffield'."""
    parts = []
    for p in (address or "").split(","):
        p = POSTCODE_ANYWHERE.sub("", p).strip(" .")
        if not p or p.lower() in COUNTIES or p.lower().endswith("shire") or p.lower().startswith("county "):
            continue
        if re.match(r"^\d", p) or re.search(r"\b(road|street|lane|avenue|drive|close|way|court|place|crescent|"
                                            r"terrace|grove|gardens|house|flat|apartment)\b", p, re.I):
            continue   # street-level parts, not the town
        parts.append(p.title() if p.isupper() else p)
    return parts[-1] if parts else ""


@dataclass
class DealNumbers:
    strategy: str = "brrr"
    location: str = ""
    purchase: int = 0
    refurb: int = 0
    gdv: int = 0                      # end value after refurb
    rent: int | None = None
    stamp_duty: int = 0
    legal: int = 0
    other_costs: int = 0              # sourcing fee, bridging, project management…
    refinance_ltv_pct: float = 75
    mortgage_rate_pct: float = 5.5
    running_costs_pct: float = 15
    comps: int = 0                    # sold prices behind the GDV
    total_in: int = 0
    refinance_loan: int = 0
    money_left_in: int = 0
    equity: int = 0
    monthly_cashflow: int | None = None
    flip_profit: int = 0
    bmv_pct: float | None = None
    market_value: int | None = None
    highlights: list[str] = field(default_factory=list)
    contact: str = ""

    def to_dict(self):
        return asdict(self)


def build_numbers(item: dict, cfg: dict, form: dict | None = None) -> DealNumbers:
    """Defaults from the analysis; anything in `form` (what the person typed) overrides them."""
    form = form or {}
    l, a = item["listing"], item["analysis"]
    f = cfg["finance"]
    mk = cfg.get("marketing") or {}
    strategies = {m["name"] for m in a.get("strategies", [])}
    default_strategy = ("brrr" if "Refurb / BRRR" in strategies else
                        "bmv" if "BMV" in strategies else
                        "btl" if "Strong BTL" in strategies else "brrr")

    d = DealNumbers()
    d.strategy = form.get("strategy") if form.get("strategy") in STRATEGY_TITLES else default_strategy
    d.location = (form.get("location") or "").strip() or town_from_address(l.get("address"))
    d.purchase = _int(form.get("purchase"), l.get("price") or 0)
    d.refurb = _int(form.get("refurb"), a.get("refurb_cost") or 0)
    d.gdv = _int(form.get("gdv"), a.get("done_up_value") or a.get("market_value") or 0)
    d.rent = _int(form.get("rent"), a.get("rent_pcm"))
    d.legal = _int(form.get("legal"), f.get("legal_and_survey", 0))
    d.other_costs = _int(form.get("other_costs"), mk.get("sourcing_fee", 0))
    d.refinance_ltv_pct = f.get("refinance_ltv_pct", 75)
    d.mortgage_rate_pct = f.get("mortgage_rate_pct", 5.5)
    d.running_costs_pct = f.get("running_costs_pct", 15)
    d.comps = a.get("valuation_comps") or 0
    d.market_value = a.get("market_value")
    d.stamp_duty = stamp_duty(d.purchase, cfg["stamp_duty"]) if d.purchase else 0

    d.total_in = d.purchase + d.stamp_duty + d.legal + d.refurb + d.other_costs
    d.refinance_loan = int(round(d.gdv * d.refinance_ltv_pct / 100))
    d.money_left_in = d.total_in - d.refinance_loan
    d.equity = d.gdv - d.refinance_loan
    d.flip_profit = int(round(d.gdv * (1 - f.get("flip_selling_costs_pct", 3) / 100) - d.total_in))
    if d.market_value and d.purchase:
        d.bmv_pct = round((d.market_value - d.purchase) / d.market_value * 100, 1)
    if d.rent:
        mortgage = monthly_mortgage(d.refinance_loan, d.mortgage_rate_pct, f.get("interest_only", True))
        d.monthly_cashflow = int(round(d.rent - mortgage - d.rent * d.running_costs_pct / 100))

    ticked = form.get("highlights")
    if ticked is None:
        ticked = mk.get("default_highlights") or []
    d.highlights = [k for k in HIGHLIGHTS if k in ticked]
    d.contact = (form.get("contact") if form.get("contact") is not None else mk.get("contact", "")) or ""
    return d


def _m(v: int | None) -> str:
    if v is None:
        return "—"
    return f"-£{abs(v):,}" if v < 0 else f"£{v:,}"


def write_post(d: DealNumbers) -> str:
    title = STRATEGY_TITLES[d.strategy]
    where = f" {d.location.upper()}" if d.location else ""
    lines = [f"🚨{where} {title}🚨".replace("🚨 ", "🚨"), ""]
    if d.location:
        lines.append(f"📍 {d.location}")
    lines.append(f"💰 Purchase price: {_m(d.purchase)}")
    if d.strategy in ("brrr", "flip") or d.refurb:
        lines.append(f"👷 Refurb: {_m(d.refurb)}" + (" (quote provided)" if "quote" in d.highlights else " (estimate)"))
    if d.strategy == "bmv" and d.bmv_pct is not None:
        lines.append(f"📉 {d.bmv_pct:.0f}% below market value (£{d.market_value:,} median of {d.comps} local sales)")
    if d.gdv:
        evidence = f" (based on {d.comps} local sold prices)" if d.comps else ""
        lines.append(f"🔥 GDV: {_m(d.gdv)}{evidence}")
    if d.strategy == "brrr":
        lines.append(f"🏦 Money left in: {_m(max(d.money_left_in, 0))}"
                     + (" — all money out!" if d.money_left_in <= 0 else ""))
        lines.append(f"🏠 Equity: {_m(d.equity)}")
    if d.strategy == "flip":
        lines.append(f"📈 Estimated profit: {_m(d.flip_profit)}")
    if d.rent:
        lines.append(f"💸 Rent: {_m(d.rent)} pcm")
        if d.monthly_cashflow is not None and d.strategy in ("brrr", "btl"):
            lines.append(f"💷 Est. cashflow: {_m(d.monthly_cashflow)} pcm after mortgage and costs")
    if d.highlights:
        lines.append("")
        lines += [f"✅ {HIGHLIGHTS[h]}" for h in d.highlights if h != "quote"]
        if lines[-1] == "":
            lines.pop()
    lines += ["", "🏃 Don't miss out. For the full deal pack, get in touch:"]
    if d.contact.strip():
        lines.append(f"📲 {d.contact.strip()}")
    return "\n".join(lines).replace("\n\n\n", "\n\n")


def breakdown(d: DealNumbers) -> list[tuple[str, str]]:
    """How the post's numbers were worked out, shown under the post."""
    rows = [("Purchase price", _m(d.purchase)), ("Stamp duty (additional property)", _m(d.stamp_duty)),
            ("Legal and survey", _m(d.legal)), ("Refurb", _m(d.refurb)),
            ("Other costs (sourcing fee, bridging, etc.)", _m(d.other_costs)),
            ("Total cash in", _m(d.total_in)),
            (f"Refinance at {d.refinance_ltv_pct:g}% of GDV {_m(d.gdv)}", _m(d.refinance_loan)),
            ("Money left in (total in − refinance)", _m(d.money_left_in)),
            ("Equity (GDV − refinance)", _m(d.equity))]
    if d.monthly_cashflow is not None:
        rows.append((f"Cashflow (rent − mortgage at {d.mortgage_rate_pct:g}% − {d.running_costs_pct:g}% costs)",
                     _m(d.monthly_cashflow)))
    return rows
