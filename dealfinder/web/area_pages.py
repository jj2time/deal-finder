"""Area scanner, area reports and the hot list."""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..areas import TYPE_LABELS, TYPES, AreaStore, explain, update_area_data
from ..hotlist import CATEGORIES, HotList

SORTS = {"score": "Best overall score", "yield": "Highest yield", "growth_5y": "Biggest 5-year growth",
         "growth_1y": "Biggest 1-year growth", "projected_5y": "Highest 5-year trend projection",
         "price": "Cheapest"}


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("£", "")) if v not in (None, "") else None
    except ValueError:
        return None


def register(app, templates, ctx, state, db, start_job, postcodes):
    store = AreaStore(db)
    hotlist = HotList(db)
    app.state.hotlist = hotlist

    def hot_for_council(names):
        return hotlist.for_councils(set(names))

    # ---- area scanner ----
    @app.get("/areas", response_class=HTMLResponse)
    def area_scanner(request: Request):
        qp = request.query_params
        t = qp.get("type") if qp.get("type") in TYPES else "all"
        sort = qp.get("sort") if qp.get("sort") in SORTS else "score"
        region = qp.get("region") or ""
        max_price, min_yield = _num(qp.get("max_price")), _num(qp.get("min_yield"))
        q = (qp.get("q") or "").strip().lower()
        areas = store.all()
        regions = sorted({a["region"] for a in areas if a["region"]})
        rows = []
        for a in areas:
            s = a["types"].get(t)
            if not s or (region and a["region"] != region) or (q and q not in a["name"].lower()):
                continue
            if max_price and s["price"] > max_price:
                continue
            if min_yield and (s.get("yield") is None or s["yield"] < min_yield):
                continue
            rows.append((a, s, hot_for_council([a["name"]])))
        key = {"price": lambda r: r[1]["price"]}.get(sort, lambda r: -(r[1].get(sort) if r[1].get(sort) is not None else -1e9))
        rows.sort(key=key)
        return templates.TemplateResponse(request, "areas.html", ctx(
            request, rows=rows, meta=store.meta(), types=TYPE_LABELS, t=t, sorts=SORTS, sort=sort,
            regions=regions, region=region, max_price=qp.get("max_price") or "", min_yield=qp.get("min_yield") or "",
            q=qp.get("q") or ""))

    @app.post("/areas/update")
    def area_update():
        data_dir = Path(state["cfg"]["database"]).parent / "area-data"
        start_job(lambda sc: update_area_data(store, data_dir, sc.progress), "areas",
                  "Updating area data from the Land Registry and ONS")
        return RedirectResponse("/areas", status_code=303)

    @app.get("/areas/{code}", response_class=HTMLResponse)
    def area_report(request: Request, code: str):
        a = store.get(code)
        if not a:
            raise HTTPException(404)
        meta = store.meta() or {}
        t = request.query_params.get("type") if request.query_params.get("type") in a["types"] else "all"
        outcode = postcodes().town_outcode(a["name"])
        return templates.TemplateResponse(request, "area.html", ctx(
            request, a=a, t=t, types=TYPE_LABELS, reasons=explain(a, t, meta.get("medians")),
            medians=(meta.get("medians") or {}), meta=meta, hot=hot_for_council([a["name"]]), outcode=outcode))

    # ---- hot list ----
    @app.get("/hotlist", response_class=HTMLResponse)
    def hot_list(request: Request, edit: str = "", new: str = ""):
        entries = hotlist.all()
        editing = hotlist.get(edit) if edit else ({} if new else None)
        area_codes = {a["name"].lower(): a["code"] for a in store.all()}
        return templates.TemplateResponse(request, "hotlist.html", ctx(
            request, entries=entries, categories=CATEGORIES, editing=editing, area_codes=area_codes))

    @app.post("/hotlist")
    async def hot_save(request: Request):
        form = await request.form()
        if form.get("delete"):
            hotlist.delete(form["delete"])
            return RedirectResponse("/hotlist", status_code=303)
        e = hotlist.save({k: form.get(k) for k in ("id", "title", "category", "councils", "postcodes", "status",
                                                   "key_date", "summary", "impact", "sources", "checked")})
        return RedirectResponse(f"/hotlist#e-{e['id']}", status_code=303)

    return hot_for_council
