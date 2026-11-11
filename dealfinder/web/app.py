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
from ..search import (RADII_MILES, SORTS, Search, area_searches, hot_areas, matches, page_query,
                      parse_hot_areas)
from .dealpack import build_pdf

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters["parse_qs"] = lambda q: __import__("urllib.parse", fromlist=["parse_qsl"]).parse_qsl(q)
TEMPLATES.env.filters["money"] = lambda v: f"£{v:,.0f}" if isinstance(v, (int, float)) else "—"
# Load every page layout into memory once, at startup. Replacing the app while it's running (installing an
# update) then can't mix new layouts into the old running program.
TEMPLATES.env.auto_reload = False
for _name in TEMPLATES.env.list_templates():
    TEMPLATES.env.get_template(_name)


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

    if "hot_areas_text" in form:
        from ..search import HOT_AREAS_VERSION
        areas, errs = parse_hot_areas(form.get("hot_areas_text", ""))
        cfg["hot_areas"] = areas
        cfg["hot_areas_version"] = HOT_AREAS_VERSION
        errors += errs

    mk = cfg.setdefault("marketing", {})
    mk["contact"] = form.get("marketing_contact", "").strip()
    mk["sourcing_fee"] = _num(form.get("marketing_sourcing_fee"), int) or 0
    mk["default_highlights"] = [k for k in form.getlist("marketing_highlights")] if hasattr(form, "getlist") else []

    al = cfg.setdefault("alerts", {})
    al["enabled"] = bool(form.get("alerts_enabled"))
    al["to"] = form.get("alerts_to", "").strip()
    al["min_score"] = _num(form.get("alerts_min_score"), int) or 70
    sch = cfg.setdefault("schedule", {})
    sch["enabled"] = bool(form.get("daily_enabled"))
    sch["min_score"] = _num(form.get("daily_min_score"), int) if form.get("daily_min_score") not in (None, "") else 50
    # An empty box keeps the current time rather than refusing to save everything else.
    t = (form.get("daily_at") or "").strip() or str(sch.get("daily_at") or "07:30")
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
    from ..search import upgrade_hot_areas
    if upgrade_hot_areas(state["cfg"]):
        save_config(state["cfg"])
    db = DB(state["cfg"]["database"])
    app = FastAPI(title="Deal Finder")
    imports: dict[str, set[str]] = {}
    job_lock = threading.Lock()
    job_queue: list = []
    scan_state = {"running": False, "last": None, "error": None, "query": None, "label": "", "progress": "",
                  "queued": [], "errors": {}}

    def ctx(request, **kw):
        us = getattr(app.state, "updates", None) or {}
        flash = us.pop("flash", None) if request.method == "GET" else None
        return {"request": request, "year": date.today().year, "scan": scan_state, "app_version": running_version,
                "has_update_key": bool(env("DEALFINDER_GITHUB_TOKEN")),
                "update_message": flash, "update_error": bool(us.get("error")) and bool(flash),
                "update_available": bool((getattr(app.state, "updates", None) or {}).get("info", {}) and
                                         app.state.updates["info"].get("available")), **kw}

    from ..config import ROOT

    def _version_file() -> str:
        v = ROOT / "VERSION"
        return v.read_text().strip() if v.exists() else "dev"

    running_version = _version_file()

    @app.exception_handler(Exception)
    async def friendly_error(request: Request, exc: Exception):
        import logging
        import traceback
        logging.getLogger("dealfinder").error("Page error on %s:\n%s", request.url.path,
                                              "".join(traceback.format_exception(exc)))
        updated = _version_file() != running_version
        if updated:
            what = ("Deal Finder was updated while it was running. <b>Open the Deal Finder app again</b> "
                    "(from Applications) and it will restart with the new version.")
        else:
            what = ("Something went wrong showing this page. Try going back or reloading. If it keeps happening, "
                    "send Claude a screenshot of this page.")
        detail = f"{type(exc).__name__}: {exc}"[:400]
        import html as _html
        return HTMLResponse(
            "<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Deal Finder</title><body style='font:16px/1.5 -apple-system,sans-serif;max-width:640px;"
            "margin:60px auto;padding:0 16px;color:#1d1d1b;background:#f7f7f5'>"
            f"<h2>Deal Finder</h2><p>{what}</p>"
            "<p><a href='/'>Back to the search page</a></p>"
            f"<p style='color:#6b6b66;font-size:13px'>Details: {_html.escape(detail)}<br>Running version "
            f"{_html.escape(running_version)}. The full error is in ~/Library/Application Support/Deal Finder/"
            "dealfinder.log</p></body>", status_code=500)

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

    def postcodes():
        if "postcodes" not in state:
            from ..data.http import CachedClient
            from ..data.postcodes import Postcodes
            state["postcodes"] = Postcodes(CachedClient(
                str(Path(state["cfg"]["database"]).with_name("http_cache.sqlite3"))))
        return state["postcodes"]

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
            hot = hot_areas(state["cfg"])
            names = [n for n in request.query_params.getlist("hot") if n]
            searches = area_searches(s, hot, names)
            centre = locate(s)
            located = [(x, locate(x)) for x in searches]
            shown = [it for it in items if any(matches(it, x, c) for x, c in located)]
        shown.sort(key=SORTS.get(s.sort, SORTS["score"])[1])
        counts = {name: sum(1 for it in shown if name in {m["name"] for m in it["analysis"]["strategies"]})
                  for name in STRATEGIES}
        def money(v):
            return f"£{v:,.0f}" if isinstance(v, (int, float)) else "—"
        points = [{"n": n, "lat": it["listing"]["lat"], "lon": it["listing"]["lon"], "key": it["listing"]["key"],
                   "address": it["listing"].get("address") or "Unknown address",
                   "price": money(it["listing"].get("price")), "value": money(it["analysis"].get("market_value")),
                   "bmv": it["analysis"].get("bmv_pct"), "score": it["analysis"]["score"],
                   "beds": it["listing"].get("bedrooms")}
                  for n, it in enumerate(shown, 1) if it["listing"].get("lat") and it["listing"].get("lon")]
        srcs = state["cfg"].get("sources", {})
        acfg = srcs.get("apify") or {}
        free_on = (srcs.get("rightmove") or {}).get("enabled", True)
        needs_setup = not free_on and not (env("APIFY_TOKEN") and (acfg.get("rightmove_actor_id") or acfg.get("zoopla_actor_id")))
        hot = hot_areas(state["cfg"])
        names = [n for n in request.query_params.getlist("hot") if n]
        searches = area_searches(s, hot, names) if batch_keys is None else []
        last = db.last_fetched(s.fetch_key) if s.area else None
        fetched = [(x.area, db.last_fetched(x.fetch_key)) for x in searches]
        heads_up, seen = [], set()
        for x in searches:
            lookup = getattr(postcodes(), "councils", None)
            councils = lookup(x.area if x.is_full_postcode else None,
                              None if x.is_full_postcode else x.outcode) if lookup else []
            for e in hot_for_council(councils):
                if e["id"] not in seen:
                    seen.add(e["id"])
                    heads_up.append((x.area, councils, e))
        return TEMPLATES.TemplateResponse(request, "index.html", ctx(
            request, s=s, items=shown, total=len(items), strategies=STRATEGIES, counts=counts,
            radii=RADII_MILES, sorts={k: v[0] for k, v in SORTS.items()}, types=PROPERTY_TYPES,
            points=points, msg=msg, needs_setup=needs_setup, last_fetched=last,
            searching=scan_state["running"] and scan_state.get("query") == page_query(s, names),
            hot=hot, hot_ticked=names, searches=searches, fetched=fetched, heads_up=heads_up,
            hotlist_entries=app.state.hotlist.all(), digest=db.digest() if not s.area and batch_keys is None else [],
            daily_on=bool((state["cfg"].get("schedule") or {}).get("enabled")),
            daily_at=str((state["cfg"].get("schedule") or {}).get("daily_at", "07:30")),
            saved=db.is_saved(s.fetch_key) if s.area else False, saved_searches=db.saved_searches(),
            recent=[{"q": Search.from_dict(d).query_string(), "label": Search.from_dict(d).describe(),
                     "deals": d.get("deals") or [], "saved": d["_saved"], "when": d["_last_fetched"],
                     "count": d["_count"], "form": Search.from_dict(d).query_string()}
                    for d in db.recent_searches()],
            query=page_query(s, names), batch=batch if batch_keys is not None else "",
            batch_count=len(batch_keys or []), bookmarklet=bookmarklet(str(request.base_url).rstrip("/"))))

    @app.post("/search")
    async def run_search(request: Request):
        form = await request.form()
        base = Search.from_params(form.get, form.getlist)
        hot = hot_areas(state["cfg"])
        only = form.get("only")
        if only:   # a one-click hot-area button: just that area
            from dataclasses import replace
            base = replace(base, area="")
            names = [only]
        else:
            names = [n for n in form.getlist("hot") if n]
        searches = area_searches(base, hot, names)
        q = page_query(base, names)
        if not searches:
            return RedirectResponse("/?msg=Type+a+postcode+or+tick+a+hot+area+first.", status_code=303)
        from ..pipeline import Scanner
        refresh = bool(form.get("refresh"))
        scanner = Scanner(state["cfg"], db=db)
        if not refresh and not any(scanner.needs_fetch(x) for x in searches):
            return RedirectResponse(f"/?{q}", status_code=303)
        label = ("Searching " + searches[0].describe() if len(searches) == 1 else
                 f"Searching {len(searches)} areas: " + ", ".join(x.area for x in searches))
        start_job(lambda sc: sc.run_searches(searches, refresh), q, label)
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
        back = form.get("back") if str(form.get("back", "")).startswith("/") else f"/?{s.query_string()}"
        return RedirectResponse(back, status_code=303)

    @app.get("/deal/{key:path}/post", response_class=HTMLResponse)
    def deal_post(request: Request, key: str):
        from ..dealpost import HIGHLIGHTS, STRATEGY_LABELS, breakdown, build_numbers, write_post
        item = db.result(key)
        if not item:
            raise HTTPException(404)
        qp = request.query_params
        form = {k: qp.get(k) for k in ("strategy", "location", "purchase", "refurb", "gdv", "rent", "legal",
                                       "other_costs", "contact") if k in qp}
        if "highlights" in qp:
            form["highlights"] = [h for h in qp.getlist("highlights") if h]
        d = build_numbers(item, state["cfg"], form)
        return TEMPLATES.TemplateResponse(request, "post.html", ctx(
            request, l=item["listing"], d=d, text=write_post(d), rows=breakdown(d),
            highlights=HIGHLIGHTS, titles=STRATEGY_LABELS))

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
        from ..claude_connector import get_report
        return TEMPLATES.TemplateResponse(request, "detail.html", ctx(request, it=item, report=get_report(db, key)))

    @app.get("/export.csv")
    def export(request: Request):
        s = current_search(request)
        names = [n for n in request.query_params.getlist("hot") if n]
        searches = area_searches(s, hot_areas(state["cfg"]), names)
        located = [(x, locate(x)) for x in searches]
        items = [it for it in db.results() if any(matches(it, x, c) for x, c in located)] if searches else db.results()
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
        """Runs a job in the background. If one is already running, this one waits its turn (never dropped)."""
        with job_lock:
            if scan_state["running"]:
                if scan_state.get("query") != query and all(q != query for _, q, _ in job_queue):
                    job_queue.append((work, query, label))
                scan_state["queued"] = [lbl for _, _, lbl in job_queue]
                return True
            # Marked as running before the page reloads, so the page always shows the progress box.
            scan_state.update(running=True, error=None, last=None, query=query, label=label,
                              progress=label + "…", queued=[])
            scan_state["errors"].pop(query, None)

        def run(work, query):
            from ..pipeline import Scanner, SearchError
            while True:
                try:
                    scanner = Scanner(state["cfg"], db=db)
                    scanner.progress = lambda m: scan_state.__setitem__("progress", m)
                    scan_state["last"] = work(scanner)
                except SearchError as e:
                    scan_state["error"] = scan_state["errors"][query] = str(e)
                except Exception as e:  # shown on the page
                    scan_state["error"] = scan_state["errors"][query] = f"Something went wrong: {e}"
                with job_lock:
                    if not job_queue:
                        scan_state["running"] = False
                        scan_state["queued"] = []
                        return
                    work, query, label = job_queue.pop(0)
                    scan_state.update(error=None, query=query, label=label, progress=label + "…",
                                      queued=[lbl for _, _, lbl in job_queue])
                    scan_state["errors"].pop(query, None)
        threading.Thread(target=run, args=(work, query), daemon=True).start()
        return True

    app.state.start_job = start_job

    @app.post("/daily/toggle")
    def daily_toggle():
        cfg = state["cfg"]
        sch = cfg.setdefault("schedule", {})
        sch["enabled"] = not bool(sch.get("enabled"))
        sch.setdefault("daily_at", "07:30")
        sch.setdefault("min_score", 50)
        save_config(cfg)
        return RedirectResponse("/#daily", status_code=303)

    @app.post("/daily/run")
    def daily_run():
        start_job(lambda sc: sc.daily_check(), "daily", "Daily check of your saved searches")
        return RedirectResponse("/#daily", status_code=303)

    @app.post("/digest/clear")
    def digest_clear():
        db.clear_digest()
        return RedirectResponse("/", status_code=303)

    from .area_pages import register as register_area_pages
    hot_for_council = register_area_pages(app, TEMPLATES, ctx, state, db, start_job, postcodes,
                                          lambda: scan_state["errors"])

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
        from ..dealpost import HIGHLIGHTS
        return TEMPLATES.TemplateResponse(request, "settings.html", ctx(
            request, cfg=cfg, post_highlights=HIGHLIGHTS, updates=update_state, running_version=running_version,
            claude=__import__("dealfinder.claude_connector", fromlist=["claude_desktop_status"]).claude_desktop_status(),
            hot_text="\n".join(f"{h['name']}, {h['area']}, {h['radius']:g}" for h in hot_areas(cfg)), mk=cfg.get("marketing") or {}, keys=keys, has_secret=has_secret, apify=_apify_form(cfg),
            types=PROPERTY_TYPES, saved=saved, errors=[e for e in errors.split("|") if e]))

    @app.post("/settings")
    async def save_settings(request: Request):
        raw = await request.form()
        form = dict(raw)
        cfg = state["cfg"]
        errors = apply_settings(cfg, form)
        cfg["marketing"]["default_highlights"] = [h for h in raw.getlist("marketing_highlights") if h]
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

    # ---- in-app updates ----
    update_state = {"info": None, "error": None, "checked": None}

    def check_updates():
        from ..updater import UpdateError, check
        try:
            update_state["info"] = check(state["cfg"].get("updates", {}).get("repo") or "jj2time/deal-finder")
            update_state["error"] = None
        except UpdateError as e:
            update_state["error"] = str(e)
        except Exception as e:
            update_state["error"] = f"Couldn't check for updates: {e}"
        from datetime import datetime
        update_state["checked"] = datetime.now().strftime("%H:%M")

    if env("DEALFINDER_GITHUB_TOKEN"):     # quietly look for an update when Deal Finder starts
        threading.Thread(target=check_updates, daemon=True).start()
    app.state.updates = update_state

    @app.post("/updates/check")
    async def updates_check(request: Request):
        form = await request.form()
        check_updates()
        info = update_state.get("info") or {}
        update_state["flash"] = (update_state["error"] if update_state.get("error") else
                                 f"Version {info.get('latest', '').split('-')[0]} is ready — click Update now"
                                 if info.get("available") else "✓ You're up to date")
        back = form.get("back") if str(form.get("back", "")).startswith("/") else "/settings#updates"
        return RedirectResponse(back, status_code=303)

    @app.post("/updates/install")
    def updates_install():
        from ..updater import install, restart_into_new_version
        info = update_state.get("info")
        if not info or not info.get("available"):
            return RedirectResponse("/settings#updates", status_code=303)

        def work(sc):
            sc.progress("Downloading the new version from GitHub…")
            install(info, state["cfg"].get("updates", {}).get("repo") or "jj2time/deal-finder")
            sc.progress("Installed. Restarting Deal Finder…")
            update_state["installed"] = info["latest"]
            update_state["restarting"] = restart_into_new_version()
            return {"installed": info["latest"]}
        start_job(work, "update", f"Updating Deal Finder to {info['latest'].split('-')[0]}")
        return RedirectResponse("/updating", status_code=303)

    @app.get("/updating", response_class=HTMLResponse)
    def updating(request: Request):
        return TEMPLATES.TemplateResponse(request, "updating.html", ctx(request, updates=update_state,
                                                                       running_version=running_version))

    # ---- Claude Desktop photo analysis ----
    @app.post("/claude/connect")
    def claude_connect():
        from ..claude_connector import connect_claude_desktop
        try:
            connect_claude_desktop()
            return RedirectResponse("/settings?claude=connected#claude", status_code=303)
        except Exception as e:
            from urllib.parse import quote
            return RedirectResponse(f"/settings?claude_error={quote(str(e)[:300])}#claude", status_code=303)

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
