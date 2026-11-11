"""National area scanner: every council area in the UK ranked by price, rent, yield and growth, for each
property type, from two free official sources:

- UK House Price Index (HM Land Registry and partners): average prices, growth and sales volumes,
  monthly since 1995, by property type.
- Price Index of Private Rents (ONS): average monthly rents by property type.

Both are published under the Open Government Licence v3.0.

"Projected growth" is not a forecast. It's each area's own long-run growth rate (the average of its yearly
growth over the last 10 and 20 years) carried forward: what happens *if the long-run trend continues*.
"""
from __future__ import annotations

import csv
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import httpx

log = logging.getLogger(__name__)

HPI_URL = ("https://publicdata.landregistry.gov.uk/market-trend-data/house-price-index-data/"
           "UK-HPI-full-file-{month}.csv")
PIPR_PAGE = ("https://www.ons.gov.uk/economy/inflationandpriceindices/datasets/"
             "priceindexofprivaterentsukmonthlypricestatistics")
UK_CODE = "K02000001"
LA_PREFIXES = ("E06", "E07", "E08", "E09", "W06", "S12", "N09")   # unitary, district, metropolitan, London, Wales, Scotland, NI
TYPES = {   # our name: (HPI price column, HPI index column, HPI 12m change column, ONS rent column)
    "all": ("AveragePrice", "Index", "12m%Change", 7),
    "detached": ("DetachedPrice", "DetachedIndex", "Detached12m%Change", 27),
    "semi-detached": ("SemiDetachedPrice", "SemiDetachedIndex", "SemiDetached12m%Change", 31),
    "terraced": ("TerracedPrice", "TerracedIndex", "Terraced12m%Change", 35),
    "flat": ("FlatPrice", "FlatIndex", "Flat12m%Change", 39),
}
TYPE_LABELS = {"all": "All property types", "detached": "Detached", "semi-detached": "Semi-detached",
               "terraced": "Terraced", "flat": "Flats"}
USER_AGENT = "dealfinder/1.0 (personal property research tool)"


def _f(v) -> float | None:
    try:
        return float(v) if v not in (None, "", "[x]", "[z]", "[c]", "[u]") else None
    except (TypeError, ValueError):
        return None


# ---- downloading --------------------------------------------------------------------------------

def download_hpi(dest: Path, client: httpx.Client, today: date | None = None) -> str:
    """The newest monthly file (it appears about two months after the month it covers). Returns its month."""
    today = today or date.today()
    y, m = today.year, today.month
    for _ in range(6):
        month = f"{y}-{m:02d}"
        url = HPI_URL.format(month=month)
        with client.stream("GET", url) as r:
            if r.status_code == 200:
                tmp = dest.with_suffix(".part")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
                tmp.replace(dest)
                return month
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    raise RuntimeError("Couldn't find a recent UK House Price Index file on the Land Registry site.")


def download_rents(dest: Path, client: httpx.Client) -> str:
    page = client.get(PIPR_PAGE)
    page.raise_for_status()
    links = re.findall(r'href="(/file\?uri=[^"]+\.xlsx)"', page.text)
    if not links:
        raise RuntimeError("Couldn't find the ONS private rents spreadsheet.")
    with client.stream("GET", "https://www.ons.gov.uk" + links[0]) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
        tmp.replace(dest)
    m = re.search(r"/(\d{1,2}[a-z]+\d{4})/", links[0])
    return m.group(1) if m else ""


# ---- reading ------------------------------------------------------------------------------------

def read_hpi(path: Path) -> dict[str, dict[str, Any]]:
    """{area code: {"name", "rows": [(date, row)...]}} for council areas."""
    out: dict[str, dict[str, Any]] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            code = r.get("AreaCode") or ""
            if not (code.startswith(LA_PREFIXES) or code == UK_CODE):
                continue
            d = datetime.strptime(r["Date"], "%d/%m/%Y").date()
            a = out.setdefault(code, {"name": r["RegionName"], "rows": []})
            a["rows"].append((d, r))
    for a in out.values():
        a["rows"].sort(key=lambda x: x[0])
    return out


def read_rents(path: Path) -> tuple[dict[str, dict[str, Any]], str]:
    """{area code: {"region", "rents": {type: £pcm}}}, and the month the rents are for."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = next((w for w in wb.worksheets if w.title.lower().startswith("table 1")), wb.worksheets[-1])
    rows = ws.iter_rows(values_only=True)
    header_seen = False
    latest: dict[str, tuple] = {}
    for r in rows:
        if not header_seen:
            header_seen = bool(r and r[1] == "Area code")
            continue
        if not r or not isinstance(r[0], datetime) or not r[1]:
            continue
        if r[1] not in latest or r[0] > latest[r[1]][0]:
            latest[r[1]] = r
    out, month = {}, ""
    for code, r in latest.items():
        month = max(month, r[0].strftime("%Y-%m"))
        out[code] = {"region": r[3] if r[3] not in (None, "[z]") else "",
                     "rents": {t: _f(r[col]) if len(r) > col else None for t, (_, _, _, col) in TYPES.items()}}
    return out, month


# ---- working out the numbers --------------------------------------------------------------------

def _value_months_back(rows, col: str, months: int):
    """The column's value `months` before the latest month that has one."""
    have = [(d, _f(r.get(col))) for d, r in rows if _f(r.get(col))]
    if not have:
        return None, None
    last_d, last_v = have[-1]
    target = (last_d.year * 12 + last_d.month - 1) - months
    for d, v in reversed(have):
        if d.year * 12 + d.month - 1 <= target:
            return last_v, v
    return last_v, None


def area_stats(code: str, hpi: dict, rent: dict | None) -> dict[str, Any]:
    rows = hpi["rows"]
    last_d = rows[-1][0]
    volumes = [_f(r.get("SalesVolume")) for _, r in rows]
    recent = [v for v in volumes if v is not None][-12:]
    out = {"code": code, "name": hpi["name"], "region": (rent or {}).get("region", ""),
           "month": last_d.isoformat()[:7], "sales_12m": int(sum(recent)) if len(recent) >= 6 else None,
           "types": {}}
    for t, (pcol, icol, ccol, _) in TYPES.items():
        price = _f(rows[-1][1].get(pcol))
        if not price:
            continue
        now5, then5 = _value_months_back(rows, icol, 60)
        now10, then10 = _value_months_back(rows, icol, 120)
        now20, then20 = _value_months_back(rows, icol, 240)
        g5 = (now5 / then5 - 1) * 100 if then5 else None
        g10 = (now10 / then10 - 1) * 100 if then10 else None
        cagr10_ = ((now10 / then10) ** (1 / 10) - 1) * 100 if then10 else None
        cagr20 = ((now20 / then20) ** (1 / 20) - 1) * 100 if then20 else None
        # Trend = average of the 10- and 20-year yearly growth. The 20 years include the 2008 crash, which
        # makes it more cautious than simply repeating the last decade.
        rates = [r for r in (cagr10_, cagr20) if r is not None]
        cagr10 = sum(rates) / len(rates) if rates else None
        rent_pcm = ((rent or {}).get("rents") or {}).get(t)
        out["types"][t] = {
            "price": int(round(price)),
            "growth_1y": _f(rows[-1][1].get(ccol)),
            "growth_5y": round(g5, 1) if g5 is not None else None,
            "growth_10y": round(g10, 1) if g10 is not None else None,
            "trend_per_year": round(cagr10, 2) if cagr10 is not None else None,
            "projected_5y": round(((1 + cagr10 / 100) ** 5 - 1) * 100, 1) if cagr10 is not None else None,
            "projected_10y": round(((1 + cagr10 / 100) ** 10 - 1) * 100, 1) if cagr10 is not None else None,
            "rent": int(rent_pcm) if rent_pcm else None,
            "yield": round(rent_pcm * 12 / price * 100, 2) if rent_pcm else None,
        }
    return out


def _percentile_ranks(values: dict[str, float]) -> dict[str, float]:
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    return {k: (i / (n - 1) if n > 1 else 0.5) for i, (k, _) in enumerate(items)}


def add_scores(areas: list[dict]) -> None:
    """0-100 per property type: yield 40, 5-year growth 25, 1-year momentum 15, trend 10, sales volume 10.
    Each part is the area's rank among all areas (100 = best in the country)."""
    for t in TYPES:
        have = [a for a in areas if t in a["types"]]
        parts = {
            "yield": (40, {a["code"]: a["types"][t]["yield"] for a in have if a["types"][t]["yield"] is not None}),
            "growth_5y": (25, {a["code"]: a["types"][t]["growth_5y"] for a in have
                               if a["types"][t]["growth_5y"] is not None}),
            "growth_1y": (15, {a["code"]: a["types"][t]["growth_1y"] for a in have
                               if a["types"][t]["growth_1y"] is not None}),
            "trend": (10, {a["code"]: a["types"][t]["trend_per_year"] for a in have
                           if a["types"][t]["trend_per_year"] is not None}),
            "sales": (10, {a["code"]: a["sales_12m"] for a in have if a["sales_12m"]}),
        }
        ranks = {k: (w, _percentile_ranks(v)) for k, (w, v) in parts.items()}
        for a in have:
            total = weight = 0.0
            pct = {}
            for k, (w, rk) in ranks.items():
                if a["code"] in rk:
                    total += w * rk[a["code"]]
                    weight += w
                    pct[k] = round(rk[a["code"]] * 100)
            # Without a rent figure there's no yield, so no fair overall score.
            a["types"][t]["score"] = int(round(total / weight * 100)) if weight and "yield" in pct else None
            a["types"][t]["percentiles"] = pct


def build(hpi_path: Path, rents_path: Path) -> tuple[list[dict], dict]:
    hpi = read_hpi(hpi_path)
    rents, rent_month = read_rents(rents_path)
    national = area_stats(UK_CODE, hpi[UK_CODE], rents.get(UK_CODE)) if UK_CODE in hpi else None
    areas = [area_stats(code, h, rents.get(code)) for code, h in hpi.items() if h["rows"] and code != UK_CODE]
    areas = [a for a in areas if a["types"]]
    add_scores(areas)
    medians = {}
    for t in TYPES:
        medians[t] = {}
        for k in ("yield", "growth_1y", "growth_5y", "growth_10y", "trend_per_year", "price", "rent"):
            vals = sorted(a["types"][t][k] for a in areas if t in a["types"] and a["types"][t].get(k) is not None)
            if vals:
                mid = len(vals) // 2
                medians[t][k] = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
    meta = {"medians": medians, "national": national,"price_month": max((a["month"] for a in areas), default=""), "rent_month": rent_month,
            "areas": len(areas), "built": date.today().isoformat()}
    return areas, meta


# ---- storage ------------------------------------------------------------------------------------

class AreaStore:
    def __init__(self, db):
        self.conn = db.conn
        self.conn.execute("CREATE TABLE IF NOT EXISTS area_stats (code TEXT PRIMARY KEY, name TEXT, data TEXT)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
        self.conn.commit()

    def replace_all(self, areas: list[dict], meta: dict) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM area_stats")
            self.conn.executemany("INSERT INTO area_stats VALUES (?,?,?)",
                                  [(a["code"], a["name"], json.dumps(a)) for a in areas])
            self.conn.execute("INSERT OR REPLACE INTO meta VALUES ('areas_meta', ?)", (json.dumps(meta),))

    def meta(self) -> dict | None:
        r = self.conn.execute("SELECT v FROM meta WHERE k='areas_meta'").fetchone()
        return json.loads(r[0]) if r else None

    def all(self) -> list[dict]:
        return [json.loads(r[0]) for r in self.conn.execute("SELECT data FROM area_stats")]

    def get(self, code: str) -> dict | None:
        r = self.conn.execute("SELECT data FROM area_stats WHERE code=?", (code,)).fetchone()
        return json.loads(r[0]) if r else None

    def find(self, name: str) -> dict | None:
        r = self.conn.execute("SELECT data FROM area_stats WHERE lower(name)=lower(?)", (name.strip(),)).fetchone()
        return json.loads(r[0]) if r else None


def update_area_data(store: AreaStore, data_dir: Path, progress: Callable[[str], None] = lambda m: None,
                     client: httpx.Client | None = None) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True)
    client = client or httpx.Client(timeout=300, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    progress("Downloading the UK House Price Index from HM Land Registry (about 35 MB)…")
    download_hpi(data_dir / "uk-hpi.csv", client)
    progress("Downloading private rents from the ONS (about 19 MB)…")
    download_rents(data_dir / "ons-rents.xlsx", client)
    progress("Working out yields and growth for every area…")
    areas, meta = build(data_dir / "uk-hpi.csv", data_dir / "ons-rents.xlsx")
    store.replace_all(areas, meta)
    return {"areas": meta["areas"], "price_month": meta["price_month"], "rent_month": meta["rent_month"]}


# ---- explaining an area -------------------------------------------------------------------------

def _ord(p: int) -> str:
    return f"top {100 - p}%" if p >= 50 else f"bottom {p + 1}%"


def explain(area: dict, t: str, medians: dict | None) -> list[str]:
    """Plain-English reasons an area does or doesn't stand out, for one property type, compared with
    the typical (median) UK area."""
    s = area["types"].get(t)
    if not s:
        return []
    n = (medians or {}).get(t, {})
    pct = s.get("percentiles", {})
    out = []
    if s.get("yield") is None:
        out.append("No council-level rent figures from the ONS for this area (common in Scotland and Northern "
                   "Ireland), so there's no yield or overall score.")
    if s.get("yield") is not None:
        line = f"Gross yield {s['yield']:.1f}% (£{s['rent']:,} rent on a £{s['price']:,} average price)"
        if n.get("yield"):
            line += f", against {n['yield']:.1f}% in the typical UK area"
        if "yield" in pct:
            line += f" — {_ord(pct['yield'])} of UK areas"
        out.append(line + ".")
    if s.get("growth_5y") is not None:
        line = f"Prices up {s['growth_5y']:.0f}% over 5 years"
        if n.get("growth_5y") is not None:
            line += f" (typical UK area {n['growth_5y']:.0f}%)"
        if s.get("growth_1y") is not None:
            line += f" and {s['growth_1y']:+.1f}% in the last year"
        out.append(line + ".")
    if s.get("trend_per_year") is not None:
        out.append(f"Long-run trend {s['trend_per_year']:.1f}% a year (average of the last 10 and 20 years); "
                   f"if that continued, prices "
                   f"would rise about {s['projected_5y']:.0f}% in 5 years and {s['projected_10y']:.0f}% in 10. "
                   "This is a trend, not a forecast.")
    if n.get("price") and s.get("price"):
        ratio = s["price"] / n["price"]
        out.append(f"Average {TYPE_LABELS[t].lower()} price £{s['price']:,}, "
                   f"{'about ' + str(round((1 - ratio) * 100)) + '% cheaper than' if ratio < 0.97 else 'about ' + str(round((ratio - 1) * 100)) + '% dearer than' if ratio > 1.03 else 'close to'} "
                   "the typical UK area.")
    if area.get("sales_12m"):
        out.append(f"About {area['sales_12m']:,} sales in the last 12 months recorded — "
                   f"{'a liquid market' if pct.get('sales', 0) >= 60 else 'a smaller market' if pct.get('sales', 100) < 30 else 'an average-sized market'}.")
    return out
