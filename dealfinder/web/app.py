"""Local dashboard. The Mac app opens it automatically; otherwise: python -m dealfinder run"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from ..config import ENV_KEYS, SECRET_KEYS, home_path, load_config, read_env, save_config, save_env
from ..db import DB
from ..models import PROPERTY_TYPES
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


def _num(v, cast=float):
    try:
        return cast(v) if v not in (None, "") else None
    except ValueError:
        return None


def _apify_form(cfg: dict) -> dict:
    """The first Apify run, as the simple fields the Settings page shows."""
    runs = (cfg.get("sources", {}).get("apify") or {}).get("runs") or []
    run = runs[0] if runs else {}
    inp = dict(run.get("input") or {})
    urls = [u.get("url") if isinstance(u, dict) else u for u in inp.pop("startUrls", [])]
    max_items = inp.pop("maxItems", 100)
    actor = run.get("actor_id", "")
    return {"actor_id": "" if str(actor).startswith("REPLACE") else actor,
            "urls": "\n".join(u for u in urls if u), "max_items": max_items,
            "extra": json.dumps(inp, indent=2) if inp else ""}


def apply_settings(cfg: dict, form: dict) -> list[str]:
    """Updates cfg in place from the Settings form. Returns error messages (empty = OK)."""
    errors = []
    cfg.setdefault("areas", {})["postcode_districts"] = [
        d.strip().upper() for d in re.split(r"[,\s]+", form.get("districts", "")) if d.strip()]
    f = cfg.setdefault("filters", {})
    f["min_price"] = _num(form.get("min_price"), int) or 0
    f["max_price"] = _num(form.get("max_price"), int) or 0
    f["min_bedrooms"] = _num(form.get("min_bedrooms"), int) or 0
    f["property_types"] = [t for t in PROPERTY_TYPES if form.get(f"type_{t}")] or list(PROPERTY_TYPES)

    src = cfg.setdefault("sources", {})
    apify = src.setdefault("apify", {})
    apify["enabled"] = bool(form.get("apify_enabled"))
    urls = [u.strip() for u in form.get("apify_urls", "").splitlines() if u.strip()]
    inp: dict = {}
    if form.get("apify_extra", "").strip():
        try:
            inp = json.loads(form["apify_extra"])
            if not isinstance(inp, dict):
                raise ValueError
        except ValueError:
            errors.append("Extra Apify input must be JSON like {\"key\": \"value\"}.")
            inp = {}
    inp["startUrls"] = [{"url": u} for u in urls]
    inp["maxItems"] = _num(form.get("apify_max_items"), int) or 100
    apify["runs"] = [{"name": "My portal searches",
                      "actor_id": form.get("apify_actor_id", "").strip() or "REPLACE-WITH-ACTOR-ID",
                      "input": inp}]
    src.setdefault("email_alerts", {"folder": "INBOX", "days_back": 3})["enabled"] = bool(form.get("email_enabled"))
    src.setdefault("csv_import", {"folder": "imports"})["enabled"] = True

    fin = cfg.setdefault("finance", {})
    for key in ("mortgage_rate_pct", "loan_to_value_pct", "running_costs_pct", "refurb_default", "refurb_per_sqm"):
        v = _num(form.get(key))
        if v is not None:
            fin[key] = v
    th = cfg.setdefault("thresholds", {})
    for key in ("bmv_pct", "strong_btl_yield_pct", "strong_btl_cashflow"):
        v = _num(form.get(key))
        if v is not None:
            th[key] = v
    cfg.setdefault("stamp_duty", {})["buyer_is_non_resident"] = bool(form.get("non_resident"))

    al = cfg.setdefault("alerts", {})
    al["enabled"] = bool(form.get("alerts_enabled"))
    al["to"] = form.get("alerts_to", "").strip()
    al["min_score"] = _num(form.get("alerts_min_score"), int) or 70
    t = form.get("daily_at", "07:30").strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", t):
        cfg.setdefault("schedule", {})["daily_at"] = t
    else:
        errors.append("Daily scan time must look like 07:30.")
    return errors


def create_app(cfg: dict | None = None, on_quit=None) -> FastAPI:
    state = {"cfg": cfg or load_config()}
    db = DB(state["cfg"]["database"])
    app = FastAPI(title="Deal Finder")
    scan_state = {"running": False, "last": None, "error": None}

    def ctx(request, **kw):
        return {"request": request, "year": date.today().year, "scan": scan_state, **kw}

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, strategy: str = "", min_bmv: str = "", min_yield: str = "", q: str = "",
              msg: str = ""):
        items = db.results()
        all_strategies = sorted({s["name"] for it in items for s in it["analysis"]["strategies"]})
        shown = _filter(items, strategy, _num(min_bmv), _num(min_yield), q)
        points = [{"lat": it["listing"]["lat"], "lon": it["listing"]["lon"], "key": it["listing"]["key"],
                   "label": f"{it['listing'].get('address')} — {it['analysis']['score']}"}
                  for it in shown if it["listing"].get("lat") and it["listing"].get("lon")]
        needs_setup = not read_env().get("APIFY_TOKEN") and not items
        return TEMPLATES.TemplateResponse(request, "index.html", ctx(
            request, items=shown, total=len(items), strategies=all_strategies, strategy=strategy,
            min_bmv=min_bmv, min_yield=min_yield, q=q, points=points, msg=msg, needs_setup=needs_setup))

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
        return TEMPLATES.TemplateResponse(request, "detail.html", ctx(request, it=item))

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
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": 'attachment; filename="deals.csv"'})

    @app.post("/scan")
    def scan():
        if not scan_state["running"]:
            def work():
                from ..pipeline import Scanner
                scan_state.update(running=True, error=None)
                try:
                    scan_state["last"] = Scanner(state["cfg"], db=db).run()
                except Exception as e:  # shown on the dashboard
                    scan_state["error"] = str(e)
                finally:
                    scan_state["running"] = False
            threading.Thread(target=work, daemon=True).start()
        return RedirectResponse("/", status_code=303)

    @app.get("/scan/status")
    def scan_status():
        return JSONResponse(scan_state)

    @app.post("/upload")
    async def upload(file: UploadFile = File(...)):
        name = Path(file.filename or "upload.csv").name
        if not name.lower().endswith(".csv"):
            return RedirectResponse("/?msg=Only+CSV+files+can+be+imported.", status_code=303)
        folder = home_path((state["cfg"].get("sources", {}).get("csv_import") or {}).get("folder", "imports"))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(await file.read())
        return RedirectResponse(f"/?msg=Imported+{name}.+Press+Scan+now+to+analyse+it.", status_code=303)

    @app.get("/settings", response_class=HTMLResponse)
    def settings(request: Request, saved: str = "", errors: str = ""):
        cfg = state["cfg"]
        envv = read_env()
        keys = {k: ("" if k in SECRET_KEYS else envv.get(k, "")) for k in ENV_KEYS}
        has_secret = {k: bool(envv.get(k)) for k in SECRET_KEYS}
        return TEMPLATES.TemplateResponse(request, "settings.html", ctx(
            request, cfg=cfg, keys=keys, has_secret=has_secret, apify=_apify_form(cfg),
            types=PROPERTY_TYPES, saved=saved, errors=[e for e in errors.split("|") if e]))

    @app.post("/settings")
    async def save_settings(request: Request):
        form = dict(await request.form())
        cfg = state["cfg"]
        errors = apply_settings(cfg, form)
        save_config(cfg)
        env_values = {}
        for k in ENV_KEYS:
            v = str(form.get(f"env_{k}", ""))
            if k in SECRET_KEYS and not v:
                if form.get(f"clear_{k}"):
                    env_values[k] = ""
                continue  # blank secret = keep the saved one
            env_values[k] = v
        save_env(env_values)
        state["cfg"] = load_config()
        if errors:
            return RedirectResponse("/settings?errors=" + "|".join(errors), status_code=303)
        return RedirectResponse("/settings?saved=1", status_code=303)

    @app.post("/quit")
    def quit_app():
        def stop():
            import time
            time.sleep(0.5)
            if on_quit:
                on_quit()
            os._exit(0)
        threading.Thread(target=stop, daemon=True).start()
        return HTMLResponse("<p style='font-family:sans-serif;padding:40px'>Deal Finder has stopped. "
                            "Open the Deal Finder app again to start it.</p>")

    app.state.settings = state
    return app
