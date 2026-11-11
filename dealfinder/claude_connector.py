"""Deal Finder's connector for the Claude Desktop app (an MCP server, run by Claude Desktop on this Mac).

It lets Claude, under your own Claude plan, look at a listing's photos and save a condition report back into
Deal Finder: no Anthropic API key and no per-use charge. Set it up from Settings → Claude Desktop.

    python -m dealfinder.claude_connector      (Claude Desktop starts this itself)
"""
from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone

import httpx

from .config import load_config
from .db import DB
from .sources.rightmove import BASE, USER_AGENT, parse_property_page

MAX_SIDE = 1024          # photos are shrunk to this size, plenty for judging condition
DEFAULT_PHOTOS = 20

CHECKLIST = """You are helping a UK property investor judge a property's condition from its listing photos.
Look carefully at every photo and the floorplan, then report on:

1. Damp and mould: dark patches, black spots, tide marks, peeling or bubbling paint, condensation, especially
   in corners, around windows, ceilings, behind furniture and in bathrooms.
2. Walls and ceilings: cracks (note direction and width if visible), stains, uneven plaster, artex, sagging.
3. Kitchen: age and style of units, worktops, appliances, signs of water damage; keep, refresh or replace.
4. Bathroom(s): suite age and colour, tiling, shower, ventilation, signs of leaks or mould.
5. Floors: carpets, laminate, boards, tiles; condition and level.
6. Windows and doors: single or double glazing, frame material and condition, condensation between panes.
7. Heating and electrics where visible: boiler type and age, radiators, storage heaters, consumer unit, sockets.
8. Exterior and roof where visible: roof covering, missing or slipped tiles, chimney, gutters, pointing,
   render, damp-proof course line, garden and boundaries.
9. Anything else: signs of subsidence, Japanese knotweed, fire damage, structural alterations, hoarding,
   or rooms that seem deliberately not photographed.

For each area give: a rating (Good / Fair / Poor / Can't tell), what you saw and in which photo numbers, and
the work it likely needs. Then give a rough refurb estimate at typical 2026 UK trade prices as a low–high
range for each item and a total, and say whether this looks like a light refresh, a medium refurb or a full
renovation.

Be honest about what photos can't show: say "can't tell" rather than guess, point out what's missing, and end
with what to check at a viewing or in a survey. This is an estimate from photos only, not a survey.

When you're done, call save_condition_report with the property, your full report (markdown is fine) and the
total refurb range in pounds."""


def _db() -> DB:
    return DB(load_config()["database"])


def _ensure_reports_table(db: DB) -> None:
    db.conn.execute("CREATE TABLE IF NOT EXISTS condition_reports (key TEXT PRIMARY KEY, report TEXT, "
                    "refurb_low INTEGER, refurb_high INTEGER, saved_at TEXT)")
    db.conn.commit()


def resolve(prop: str) -> tuple[str, str]:
    """A Deal Finder key, a Rightmove link or a Rightmove property number -> (key, Rightmove page URL)."""
    prop = (prop or "").strip()
    m = re.search(r"rightmove\.co\.uk/properties/(\d+)", prop) or re.fullmatch(r"(?:rightmove:)?(\d{5,})", prop)
    if m:
        return f"rightmove:{m.group(1)}", f"{BASE}/properties/{m.group(1)}"
    db = _db()
    row = db.conn.execute("SELECT key, url FROM listings WHERE key=? OR lower(address) LIKE ? ORDER BY last_seen DESC",
                          (prop, f"%{prop.lower()}%")).fetchone()
    if row and row["url"] and "rightmove.co.uk/properties/" in row["url"]:
        return row["key"], row["url"].split("#")[0].split("?")[0]
    if row:
        raise ValueError(f"{row['key']} isn't a Rightmove listing, so there are no photos to fetch.")
    raise ValueError(f"Couldn't find “{prop}”. Paste the Rightmove link, or use find_properties first.")


def shrink(data: bytes) -> bytes:
    from PIL import Image as PILImage
    img = PILImage.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=80)
    return out.getvalue()


def fetch_listing(url: str, client: httpx.Client | None = None) -> dict:
    c = client or httpx.Client(timeout=30, follow_redirects=True,
                               headers={"User-Agent": USER_AGENT, "Accept-Language": "en-GB"})
    r = c.get(url)
    if r.status_code in (403, 429):
        raise ValueError("Rightmove refused the request (it may be limiting automated visits). Try again later.")
    if r.status_code == 404:
        raise ValueError("That Rightmove listing no longer exists.")
    r.raise_for_status()
    details = parse_property_page(r.text)
    if not details.get("images"):
        raise ValueError("Couldn't find any photos on that Rightmove page.")
    return details


def deal_summary(key: str) -> str:
    item = _db().result(key)
    if not item:
        return "Not yet analysed in Deal Finder (search its area there to get sold-price figures)."
    a, l = item["analysis"], item["listing"]
    bits = [f"Deal Finder: asking {_m(l.get('price'))}, area value {_m(a.get('market_value'))} "
            f"from {a.get('valuation_comps')} sold prices"]
    if a.get("bmv_pct") is not None:
        bits.append(f"{a['bmv_pct']}% below market value")
    bits.append(f"score {a.get('score')}/100")
    if a.get("strategies"):
        bits.append("flags: " + ", ".join(s["name"] for s in a["strategies"]))
    return "; ".join(bits) + "."


def _m(v) -> str:
    return f"£{v:,.0f}" if isinstance(v, (int, float)) else "unknown"


def save_report(prop: str, report: str, refurb_low: int | None = None, refurb_high: int | None = None) -> str:
    key, _ = resolve(prop)
    db = _db()
    _ensure_reports_table(db)
    db.conn.execute("INSERT OR REPLACE INTO condition_reports VALUES (?,?,?,?,?)",
                    (key, report.strip(), refurb_low, refurb_high,
                     datetime.now(timezone.utc).isoformat(timespec="seconds")))
    db.conn.commit()
    return key


def get_report(db: DB, key: str) -> dict | None:
    _ensure_reports_table(db)
    r = db.conn.execute("SELECT * FROM condition_reports WHERE key=?", (key,)).fetchone()
    return dict(r) if r else None


def build_server():
    import functools

    from mcp.server.mcpserver import Image, MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

    def friendly(fn):
        """Problems reach Claude as a plain sentence it can pass on, not a crash report."""
        @functools.wraps(fn)
        def wrapper(*a, **k):
            try:
                return fn(*a, **k)
            except ValueError as e:
                raise ToolError(str(e)) from e
            except httpx.HTTPError as e:
                raise ToolError(f"Couldn't reach Rightmove ({e.__class__.__name__}). Check the internet "
                                "connection and try again.") from e
        return wrapper

    server = MCPServer(
        name="Deal Finder",
        instructions=("Deal Finder is the user's UK property deal app on this Mac. Use get_property_photos to look "
                      "at a listing's photos (pass a Rightmove link or a property from find_properties), judge its "
                      "condition with the analyse_property_photos checklist, then save_condition_report."),
    )

    @server.tool(description="Find properties already in Deal Finder by address, street, town or postcode.")
    @friendly
    def find_properties(query: str = "", limit: int = 15) -> str:
        db = _db()
        rows = db.conn.execute(
            "SELECT l.key, l.address, l.price, l.url, a.score FROM listings l LEFT JOIN analyses a ON a.key=l.key "
            "WHERE lower(l.address) LIKE ? OR lower(coalesce(l.postcode,'')) LIKE ? OR lower(coalesce(l.outcode,'')) = ? "
            "ORDER BY coalesce(a.score,0) DESC LIMIT ?",
            (f"%{query.lower()}%", f"%{query.lower()}%", query.lower().strip(), max(1, min(limit, 50)))).fetchall()
        if not rows:
            return "No matching properties in Deal Finder. You can pass a Rightmove link to get_property_photos instead."
        return "\n".join(f"- {r['address']} | {_m(r['price'])} | score {r['score']} | id {r['key']} | {r['url'] or ''}"
                         for r in rows)

    @server.tool(description=("Get a property's listing photos and floorplan (as images) plus its details and Deal "
                              "Finder's numbers. `property` is a Rightmove link, a Rightmove property number, or an "
                              "id/address from find_properties."))
    @friendly
    def get_property_photos(property: str, max_photos: int = DEFAULT_PHOTOS) -> list:
        key, url = resolve(property)
        details = fetch_listing(url)
        photos = details["images"][: max(1, min(max_photos, 40))]
        client = httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        out: list = []
        header = [f"Property: {details.get('address') or key} ({details.get('postcode') or 'postcode not shown'})",
                  f"Asking price: {details.get('price_text') or 'unknown'}",
                  f"Tenure: {details.get('tenure') or 'not stated'}"
                  + (f", {details['lease_years']} years left on the lease" if details.get("lease_years") else ""),
                  f"Rightmove: {url}", f"Deal Finder id: {key}", deal_summary(key),
                  f"Showing {len(photos)} of {len(details['images'])} photos"
                  + (" plus the floorplan" if details.get("floorplans") else "") + ", numbered in order.",
                  "", "Description: " + (details.get("description") or "")[:1500]]
        out.append("\n".join(header))
        for n, ph in enumerate(photos, 1):
            try:
                img = shrink(client.get(ph["url"]).content)
            except Exception:
                out.append(f"Photo {n}: couldn't be downloaded.")
                continue
            out.append(f"Photo {n}" + (f" ({ph['caption']})" if ph.get("caption") and not
                                       re.match(r"(?i)^(img|dsc|photo)[_ -]?\d", ph["caption"]) else ""))
            out.append(Image(data=img, format="jpeg"))
        for fp in details.get("floorplans", [])[:1]:
            try:
                out.append("Floorplan")
                out.append(Image(data=shrink(client.get(fp).content), format="jpeg"))
            except Exception:
                pass
        return out

    @server.tool(description=("Save your condition report for a property into Deal Finder, with the total refurb "
                              "estimate range in pounds. It appears on the property's page there."))
    @friendly
    def save_condition_report(property: str, report: str, refurb_low: int | None = None,
                              refurb_high: int | None = None) -> str:
        key = save_report(property, report, refurb_low, refurb_high)
        return (f"Saved to Deal Finder. It's on the Photo check tab: http://127.0.0.1:8765/report/{key}"
                + (f" (refurb estimate £{refurb_low:,}–£{refurb_high:,})." if refurb_low and refurb_high else "."))

    @server.prompt(title="Analyse property photos",
                   description="Look at a listing's photos and report on its condition and likely refurb cost.")
    def analyse_property_photos(property: str) -> str:
        return (f"Use get_property_photos for this property: {property}\n\n" + CHECKLIST)

    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()


# ---- connecting Claude Desktop (run from Settings) -----------------------------------------------

CLAUDE_CONFIG = "Library/Application Support/Claude/claude_desktop_config.json"
SERVER_NAME = "deal-finder"


def connector_script(support: "Path", bundle_app: "Path", python: str) -> str:
    """A small launcher Claude Desktop runs; it always picks the newest installed copy of Deal Finder."""
    return f"""#!/bin/bash
# Started by Claude Desktop to connect to Deal Finder. Written by Deal Finder (Settings → Claude Desktop).
SUPPORT="{support}"
APP="{bundle_app}"
if [ -f "$SUPPORT/app-current/VERSION" ]; then
  bt="$(cut -d- -f2 "$APP/VERSION" 2>/dev/null)"; ut="$(cut -d- -f2 "$SUPPORT/app-current/VERSION" 2>/dev/null)"
  if [ -n "$ut" ] && [[ "$ut" > "$bt" ]]; then APP="$SUPPORT/app-current"; fi
fi
export DEALFINDER_HOME="$SUPPORT" PYTHONPATH="$APP" PYTHONDONTWRITEBYTECODE=1
exec "{python}" -m dealfinder.claude_connector
"""


def connect_claude_desktop(home_dir: "Path | None" = None) -> dict:
    """Adds Deal Finder to Claude Desktop's connectors, keeping everything else in its settings file."""
    import os
    import shutil
    import sys
    from pathlib import Path

    from .config import HOME, ROOT
    home_dir = Path(home_dir or Path.home())
    launcher = os.environ.get("DEALFINDER_LAUNCHER")
    bundle_app = (Path(launcher).resolve().parent.parent / "Resources" / "app") if launcher else ROOT
    script = HOME / "claude-connector.sh"
    script.write_text(connector_script(HOME, bundle_app, sys.executable))
    script.chmod(0o755)
    cfg_path = home_dir / CLAUDE_CONFIG
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text() or "{}")
        except ValueError as e:
            raise ValueError("Claude Desktop's settings file isn't valid JSON, so it wasn't changed. "
                             f"It's at ~/{CLAUDE_CONFIG}.") from e
        backup = cfg_path.with_suffix(".json.before-deal-finder")
        if not backup.exists():
            shutil.copy(cfg_path, backup)
    data.setdefault("mcpServers", {})[SERVER_NAME] = {"command": "/bin/bash", "args": [str(script)]}
    tmp = cfg_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(cfg_path)
    return {"config": str(cfg_path), "script": str(script)}


def claude_desktop_status(home_dir: "Path | None" = None) -> dict:
    from pathlib import Path
    home_dir = Path(home_dir or Path.home())
    cfg = home_dir / CLAUDE_CONFIG
    try:
        connected = SERVER_NAME in (json.loads(cfg.read_text()).get("mcpServers") or {})
    except (OSError, ValueError):
        connected = False
    return {"installed": cfg.parent.exists(), "connected": connected}


def list_reports(db: DB) -> list[dict]:
    _ensure_reports_table(db)
    out = []
    for r in db.conn.execute("SELECT r.*, l.address, l.price, l.url FROM condition_reports r "
                             "LEFT JOIN listings l ON l.key = r.key ORDER BY r.saved_at DESC"):
        d = dict(r)
        first = (d.get("report") or "").strip().splitlines()
        d["title"] = d.get("address") or next((ln.strip("# *") for ln in first if ln.strip()), d["key"])
        out.append(d)
    return out


def report_keys(db: DB) -> set[str]:
    _ensure_reports_table(db)
    return {r[0] for r in db.conn.execute("SELECT key FROM condition_reports")}


def prompt_for(url: str) -> str:
    return f"Analyse the photos of {url}"


def open_claude_desktop() -> bool:
    """Brings Claude Desktop to the front on a Mac. False anywhere else."""
    import subprocess
    import sys
    if sys.platform != "darwin":
        return False
    try:
        return subprocess.run(["open", "-a", "Claude"], timeout=15, capture_output=True).returncode == 0
    except Exception:
        return False
