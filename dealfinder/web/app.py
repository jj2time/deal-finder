"""Local dashboard: python -m dealfinder serve, then open http://127.0.0.1:8000"""
from __future__ import annotations

import csv
import io
import threading
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from ..config import load_config
from ..db import DB
from .dealpack import build_pdf

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters["money"] = lambda v: f"£{v:,.0f}" if isinstance(v, (int, float)) else "—"


def _filter(items, strategy, min_bmv, min_yield, q):
    out = []
    for it in items:
        a, l = it["analysis"], it["listing"]
        if strategy and strategy not in {s["name"] for s in a["strategies"]}:
            continue
        if min_bmv is not None and (a.get("bmv_pct") is None or a["bmv_pct"] < min_bmv):
            continue
        if min_yield is not None and (a.get("gross_yield_pct") is None or a["gross_yield_pct"] < min_yield):
            continue
        if q and q.lower() not in f"{l.get('address')} {l.get('postcode')} {l.get('outcode')}".lower():
            continue
        out.append(it)
    return out


def create_app(cfg: dict | None = None) -> FastAPI:
    cfg = cfg or load_config()
    db = DB(cfg["database"])
    app = FastAPI(title="Deal Finder")
    scan_state = {"running": False, "last": None}

    def _num(v):
        try:
            return float(v) if v not in (None, "") else None
        except ValueError:
            return None

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, strategy: str = "", min_bmv: str = "", min_yield: str = "", q: str = ""):
        items = db.results()
        all_strategies = sorted({s["name"] for it in items for s in it["analysis"]["strategies"]})
        shown = _filter(items, strategy, _num(min_bmv), _num(min_yield), q)
        points = [{"lat": it["listing"]["lat"], "lon": it["listing"]["lon"], "key": it["listing"]["key"],
                   "label": f"{it['listing'].get('address')} — {it['analysis']['score']}"}
                  for it in shown if it["listing"].get("lat") and it["listing"].get("lon")]
        return TEMPLATES.TemplateResponse(request, "index.html", {
            "items": shown, "total": len(items), "strategies": all_strategies, "strategy": strategy,
            "min_bmv": min_bmv, "min_yield": min_yield, "q": q, "points": points,
            "scan": scan_state, "year": date.today().year})

    @app.get("/deal/{key:path}/pack.pdf")
    def pack(key: str):
        item = db.result(key)
        if not item:
            raise HTTPException(404)
        return Response(build_pdf(item), media_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="deal-pack.pdf"'})

    @app.get("/deal/{key:path}", response_class=HTMLResponse)
    def detail(request: Request, key: str):
        item = db.result(key)
        if not item:
            raise HTTPException(404)
        return TEMPLATES.TemplateResponse(request, "detail.html", {"it": item, "year": date.today().year})

    @app.get("/export.csv")
    def export(strategy: str = "", min_bmv: str = "", min_yield: str = "", q: str = ""):
        items = _filter(db.results(), strategy, _num(min_bmv), _num(min_yield), q)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["score", "address", "postcode", "price", "market_value", "bmv_pct", "rent_pcm",
                    "gross_yield_pct", "monthly_cashflow", "roi_pct", "flip_profit", "brrr_cash_left_in",
                    "strategies", "url"])
        for it in items:
            l, a = it["listing"], it["analysis"]
            w.writerow([a["score"], l.get("address"), l.get("postcode") or l.get("outcode"), l.get("price"),
                        a.get("market_value"), a.get("bmv_pct"), a.get("rent_pcm"), a.get("gross_yield_pct"),
                        a.get("monthly_cashflow"), a.get("roi_pct"), a.get("flip_profit"),
                        a.get("brrr_cash_left_in"), "; ".join(s["name"] for s in a["strategies"]), l.get("url")])
        buf.seek(0)
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": 'attachment; filename="deals.csv"'})

    @app.post("/scan")
    def scan():
        if not scan_state["running"]:
            def work():
                from ..pipeline import Scanner
                scan_state["running"] = True
                try:
                    scan_state["last"] = Scanner(cfg, db=db).run()
                finally:
                    scan_state["running"] = False
            threading.Thread(target=work, daemon=True).start()
        return RedirectResponse("/", status_code=303)

    return app
