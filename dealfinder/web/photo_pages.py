"""📷 Photo check: Claude Desktop analyses a listing's photos; reports are listed and shown here."""
from __future__ import annotations

import re

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..claude_connector import (claude_desktop_status, get_report, list_reports, open_claude_desktop, prompt_for)
from ..sources.rightmove import BASE

RM = re.compile(r"rightmove\.co\.uk/properties/(\d+)")


def register(app, templates, ctx, db):
    def to_url(raw: str) -> tuple[str, str] | None:
        """A Rightmove link, property number or Deal Finder key -> (key, clean Rightmove URL)."""
        raw = (raw or "").strip()
        m = RM.search(raw) or re.fullmatch(r"(?:rightmove:)?(\d{5,})", raw)
        if m:
            return f"rightmove:{m.group(1)}", f"{BASE}/properties/{m.group(1)}"
        row = db.conn.execute("SELECT key, url FROM listings WHERE key=?", (raw,)).fetchone()
        if row and row["url"] and RM.search(row["url"]):
            return row["key"], f"{BASE}/properties/{RM.search(row['url']).group(1)}"
        return None

    @app.get("/photos", response_class=HTMLResponse)
    def photos(request: Request):
        return templates.TemplateResponse(request, "photos.html", ctx(
            request, reports=list_reports(db), claude=claude_desktop_status()))

    @app.post("/photos/start")
    async def photos_start(request: Request):
        body = await request.json()
        found = to_url(str(body.get("property", "")))
        if not found:
            return JSONResponse({"error": "That doesn't look like a Rightmove property link. Open the property on "
                                          "Rightmove and copy the address from the top of the browser."}, status_code=400)
        key, url = found
        status = claude_desktop_status()
        opened = open_claude_desktop() if status["connected"] else False
        return JSONResponse({"key": key, "url": url, "prompt": prompt_for(url), "opened": opened,
                             "connected": status["connected"], "installed": status["installed"],
                             "count": len(list_reports(db))})

    @app.get("/photos/status")
    def photos_status():
        reps = list_reports(db)
        return {"count": len(reps), "latest": reps[0]["key"] if reps else None}

    @app.get("/report/{key:path}", response_class=HTMLResponse)
    def report_page(request: Request, key: str):
        rep = get_report(db, key)
        if not rep:
            raise HTTPException(404)
        item = db.result(key)
        m = RM.search(key) or re.match(r"rightmove:(\d+)", key)
        rm_url = f"{BASE}/properties/{m.group(1)}" if m else None
        return templates.TemplateResponse(request, "report.html", ctx(request, rep=rep, item=item, rm_url=rm_url,
                                                                      key=key))
