"""Local dashboard. The Mac app opens it automatically; otherwise: python -m dealfinder run"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import threading
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from ..config import ENV_KEYS, SECRET_KEYS, env, home_path, load_config, read_env, save_config, save_env
from ..db import DB
from ..analysis.strategies import STRATEGIES
from ..models import PROPERTY_TYPES
from ..search import RADII_MILES, SORTS, Search, matches
from .dealpack import build_pdf

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters["money"] = lambda v: f"£{v:,.0f}" if isinstance(v, (int, float)) else "—"


def _num(v, cast=float):
    try:
        return cast(v) if v not in (None, "") else None
    except ValueError:
        return None


def _apify_form(cfg: dict) -> dict:
    a = cfg.get("sources", {}).get("apify") or {}
    extra = a.get("extra_input") or {}
    return {"rightmove_actor_id": a.get("rightmove_actor_id", ""), "zoopla_actor_id": a.get("zoopla_actor_id", ""),
            "max_items": a.get("max_items", 100), "url_field": a.get("url_field", "startUrls"),
            "extra": json.dumps(extra, indent=2) if extra else ""}


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
    apify["enabled"] = True
    apify["rightmove_actor_id"] = form.get("rightmove_actor_id", "").strip()
    apify["zoopla_actor_id"] = form.get("zoopla_actor_id", "").strip()
    apify["max_items"] = _num(form.get("apify_max_items"), int) or 100
    apify["url_field"] = form.get("apify_url_field", "").strip() or "startUrls"
    apify["extra_input"] = {}
    if form.get("apify_extra", "").strip():
        try:
            extra = json.loads(form["apify_extra"])
            if not isinstance(extra, dict):
                raise ValueError
            apify["extra_input"] = extra
        except ValueError:
            errors.append("Extra scraper options must be JSON like {\"key\": \"value\"}.")
    apify["runs"] = []   # replaced by area searches
    rm = src.setdefault("rightmove", {})
    rm["enabled"] = bool(form.get("rightmove_enabled"))
    rm["max_pages"] = min(max(_num(form.get("rightmove_max_pages"), int) or 3, 1), 10)
    rm["details"] = form.get("rightmove_details") if form.get("rightmove_details") in ("none", "leasehold", "all") else "leasehold"
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


BOOKMARKLET_JS = r"""(async()=>{const D='%s';let d;try{const t=await (await fetch(location.href,{credentials:'include'})).text();const m=t.match(/<script id="__NEXT_DATA__" type="application\/json">([\s\S]*?)<\/script>/);d=JSON.parse(m[1]).props.pageProps.searchResults.properties;}catch(e){}if(!d||!d.length){alert('Deal Finder: open a Rightmove search results page first, then click this again.');return;}const items=d.map(p=>({id:p.id,displayAddress:p.displayAddress,price:p.price&&p.price.amount,propertySubType:p.propertySubType,bedrooms:p.bedrooms,summary:p.summary,keyFeatures:(p.keyFeatures||[]).map(k=>k.description||k),location:p.location,propertyUrl:p.propertyUrl,propertyTypeFullDescription:p.propertyTypeFullDescription,firstVisibleDate:p.firstVisibleDate,addedOrReduced:p.addedOrReduced,tenure:p.tenure&&p.tenure.tenureType,displaySize:p.displaySize,auction:p.auction,image:p.propertyImages&&p.propertyImages.mainImageSrc}));window.open(D+'/import/browser#'+encodeURIComponent(JSON.stringify({items})),'_blank');})();"""


def bookmarklet(base_url: str) -> str:
    from urllib.parse import quote
    return "javascript:" + quote(BOOKMARKLET_JS % base_url, safe="(){}[];:,.=>!&|'+/?*-_")


def create_app(cfg: dict | None = None, on_quit=None) -> FastAPI:
    state = {"cfg": cfg or load_config()}
    db = DB(state["cfg"]["database"])
    app = FastAPI(title="Deal Finder")
    imports: dict[str, set[str]] = {}
    scan_state = {"running": False, "last": None, "error": None, "query": None, "label": "", "progress": ""}

    def ctx(request, **kw):
        return {"request": request, "year": date.today().year, "scan": scan_state, **kw}

    @app.get("/health")
    def health():
        from ..config import ROOT
        v = ROOT / "VERSION"
        return {"ok": True, "version": v.read_text().strip() if v.exists() else "dev"}

    def locate(s: Search):
        if not s.area:
            return None
        from ..data.http import CachedClient
        from ..data.postcodes import Postcodes
        if "postcodes" not in state:
            state["postcodes"] = Postcodes(CachedClient(
                str(Path(state["cfg"]["database"]).with_name("http_cache.sqlite3"))))
        return state["postcodes"].locate(s.area if s.is_full_postcode else None,
                                         None if s.is_full_postcode else s.area)

    def current_search(request: Request) -> Search:
        qp = request.query_params
        return Search.from_params(qp.get, qp.getlist)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, msg: str = "", batch: str = ""):
        s = current_search(request)
        items = db.results()
        batch_keys = imports.get(batch)
        if batch_keys is not None:
            centre = None
            shown = [it for it in items if it["listing"]["key"] in batch_keys and
                     (not s.deals or {m["name"] for m in it["analysis"]["strategies"]} & set(s.deals))]
        else:
            centre = locate(s)
            shown = [it for it in items if matches(it, s, centre)] if s.area else []
        shown.sort(key=SORTS.get(s.sort, SORTS["score"])[1])
        counts = {name: sum(1 for it in shown if name in {m["name"] for m in it["analysis"]["strategies"]})
                  for name in STRATEGIES}
        points = [{"lat": it["listing"]["lat"], "lon": it["listing"]["lon"], "key": it["listing"]["key"],
                   "label": f"{it['listing'].get('address')} — {it['analysis']['score']}"}
                  for it in shown if it["listing"].get("lat") and it["listing"].get("lon")]
        srcs = state["cfg"].get("sources", {})
        acfg = srcs.get("apify") or {}
        free_on = (srcs.get("rightmove") or {}).get("enabled", True)
        needs_setup = not free_on and not (env("APIFY_TOKEN") and (acfg.get("rightmove_actor_id") or acfg.get("zoopla_actor_id")))
        last = db.last_fetched(s.fetch_key) if s.area else None
        return TEMPLATES.TemplateResponse(request, "index.html", ctx(
            request, s=s, items=shown, total=len(items), strategies=STRATEGIES, counts=counts,
            radii=RADII_MILES, sorts={k: v[0] for k, v in SORTS.items()}, types=PROPERTY_TYPES,
            points=points, msg=msg, needs_setup=needs_setup, last_fetched=last,
            searching=scan_state["running"] and scan_state.get("query") == s.query_string(),
            saved=db.is_saved(s.fetch_key) if s.area else False, saved_searches=db.saved_searches(),
            query=s.query_string(), batch=batch if batch_keys is not None else "",
            batch_count=len(batch_keys or []), bookmarklet=bookmarklet(str(request.base_url).rstrip("/"))))

    @app.post("/search")
    async def run_search(request: Request):
        form = await request.form()
        s = Search.from_params(form.get, form.getlist)
        q = s.query_string()
        if not s.area:
            return RedirectResponse("/?msg=Type+a+postcode+first.", status_code=303)
        from ..pipeline import Scanner
        scanner = Scanner(state["cfg"], db=db)
        if not form.get("refresh") and not scanner.needs_fetch(s):
            return RedirectResponse(f"/?{q}", status_code=303)
        start_job(lambda sc: sc.run_search(s), q, f"Searching {s.describe()}")
        return RedirectResponse(f"/?{q}", status_code=303)

    @app.get("/import/browser", response_class=HTMLResponse)
    def import_browser_page(request: Request):
        return TEMPLATES.TemplateResponse(request, "import.html", ctx(request))

    @app.post("/import/browser")
    async def import_browser(request: Request):
        """Listings sent from the Rightmove page you're looking at (the Send to Deal Finder button)."""
        from ..sources.rightmove import map_property
        try:
            body = await request.json()
            items = body.get("items") or []
        except Exception:
            return JSONResponse({"error": "That didn't look like Rightmove listings."}, status_code=400)
        listings = [l for l in (map_property(i) for i in items if isinstance(i, dict)) if l]
        if not listings:
            return JSONResponse({"error": "No listings found on that page. Open a Rightmove search results page "
                                          "and try again."}, status_code=400)
        batch_id = secrets.token_hex(4)
        imports[batch_id] = {l.key for l in listings}
        started = start_job(lambda sc: sc.process(listings, lambda l: True), f"batch={batch_id}",
                            f"Analysing {len(listings)} listings from your browser")
        if not started:
            return JSONResponse({"error": "Deal Finder is busy with another search. Try again in a minute."},
                                status_code=409)
        return JSONResponse({"redirect": f"/?batch={batch_id}"})

    @app.post("/search/save")
    async def save_search(request: Request):
        form = await request.form()
        s = Search.from_params(form.get, form.getlist)
        db.set_saved(s.fetch_key, s.to_dict(), form.get("saved") == "1")
        return RedirectResponse(f"/?{s.query_string()}", status_code=303)

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
    def export(request: Request):
        s = current_search(request)
        items = [it for it in db.results() if matches(it, s, locate(s))] if s.area else db.results()
        items.sort(key=SORTS.get(s.sort, SORTS["score"])[1])
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

    def start_job(work, query: str = "", label: str = "Scanning"):
        if scan_state["running"]:
            return False

        def run():
            from ..pipeline import Scanner, SearchError
            scan_state.update(running=True, error=None, query=query, label=label, progress=label + "…")
            try:
                scanner = Scanner(state["cfg"], db=db)
                scanner.progress = lambda m: scan_state.__setitem__("progress", m)
                scan_state["last"] = work(scanner)
            except SearchError as e:
                scan_state["error"] = str(e)
            except Exception as e:  # shown on the page
                scan_state["error"] = f"Something went wrong: {e}"
            finally:
                scan_state["running"] = False
        threading.Thread(target=run, daemon=True).start()
        return True

    @app.post("/scan")
    def scan():
        start_job(lambda sc: sc.run(), "", "Running saved searches")
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
