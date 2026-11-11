"""The hot list: areas with something going on — Article 4 directions coming in, big projects,
regeneration. Kept by hand (by you, or updated in a Claude session), because upcoming changes appear in
council papers and news, not in any data feed.

Each entry names the councils it applies to (as postcodes.io names them), so a search in an area that
falls in one of those councils shows a heads-up. Summaries are short and in our own words; follow the
source links and check with the council before relying on a date.
"""
from __future__ import annotations

import json
import secrets
from datetime import date
from typing import Any

CATEGORIES = ["Article 4 coming", "Article 4 in force", "Major project", "Regeneration", "Other"]

SEED_VERSION = 2
# Seed entries replaced in later versions (removed only if the person never edited them).
REPLACED_SEEDS = {2: ["Liverpool: HMO Article 4 spreading across the city"]}
SEED: list[dict[str, Any]] = [
    {
        "title": "Liverpool: HMO Article 4 in force since June 2021 (11 wards incl. Wavertree)",
        "category": "Article 4 in force",
        "councils": ["Liverpool"],
        "postcodes": ["L15", "L7", "L8", "L6"],
        "status": "In force since 17 June 2021",
        "key_date": "2021-06-17",
        "summary": ("Turning a family home into a small HMO (3+ unrelated people) needs planning permission in 11 of "
                    "Liverpool's former wards: Anfield, Central, Greenbank, Kensington and Fairfield, Picton, Princes "
                    "Park, Riverside, Tuebrook and Stoneycroft, Wavertree, and parts of Church and Kirkdale. An earlier "
                    "2018 direction covered the Dales area of Greenbank. Ward boundaries changed in 2023, so check the "
                    "council's map for a specific street."),
        "impact": ("New HMO conversions in these areas need planning permission. HMOs lawfully in use before "
                   "17 June 2021 aren't affected, which makes existing licensed HMOs here scarcer and more valuable."),
        "sources": [
            {"title": "Liverpool City Council: planning permission for HMOs",
             "url": "https://liverpool.gov.uk/planning-and-building-control/planning-permission/planning-permission-for-hmos/"},
            {"title": "Liverpool Express: Liverpool to limit rise of HMO conversions",
             "url": "https://liverpoolexpress.co.uk/liverpool-to-limit-rise-of-hmo-conversions/"},
        ],
        "checked": "2026-11-11",
    },
    {
        "title": "Liverpool: HMO Article 4 expansion (Oct 2026) and citywide plan (2027)",
        "category": "Article 4 coming",
        "councils": ["Liverpool"],
        "postcodes": ["L13", "L9 8BX", "L9 7AL", "L4", "L5"],
        "status": "Cabinet approved 13 Oct 2026; called in for scrutiny 29 Oct 2026, so not settled",
        "key_date": "Immediate areas now (if upheld); rest of the city about October 2027",
        "summary": ("Cabinet approved immediate Article 4 controls in more areas: Kirkdale, Everton, County, Walton, "
                    "Orrell Park and part of Fazakerley, part of Tuebrook Larkhill, Old Swan and part of Stoneycroft, "
                    "Penny Lane, and parts of Calderstones and St Michaels and Sefton Park. A separate direction for the "
                    "rest of the city is intended to start around October 2027. Opposition councillors called the "
                    "decision in, so details and timing may change."),
        "impact": ("If upheld, new small HMOs in Old Swan, Orrell Park and part of Fazakerley need planning "
                   "permission now, and everywhere else in Liverpool from about late 2027. Check the council's "
                   "decision record before buying for HMO use."),
        "sources": [
            {"title": "PlanningGeek: call-in delays new Article 4 controls",
             "url": "https://www.planninggeek.co.uk/2026/liverpool-hmo-call-in/"},
            {"title": "LandlordZone: Liverpool plans Article 4 expansion",
             "url": "https://www.landlordzone.co.uk/news/liverpool-plans-article-4-expansion-to-curb-hmo-growth"},
            {"title": "Birkenhead News: decision called in",
             "url": "https://www.birkenhead.news/liverpool-hmo-decision-called-in/"},
            {"title": "Brit Brief: Liverpool expands HMO controls",
             "url": "https://britbrief.co.uk/business/property/liverpool-expands-hmo-controls-to-five-more-areas.html"},
        ],
        "checked": "2026-11-11",
    },
    {
        "title": "Preston: HMO Article 4",
        "category": "Article 4 coming",
        "councils": ["Preston"],
        "postcodes": ["PR1", "PR2"],
        "status": "Made 29 Jan 2026; consultation closed 19 Mar 2026; needs confirming by the council",
        "key_date": "2027-02-15",
        "summary": "A non-immediate HMO Article 4 direction that would take effect on 15 February 2027 if confirmed.",
        "impact": "New small HMOs in the covered area would need planning permission from that date.",
        "sources": [{"title": "Preston City Council: Article 4 Direction on HMOs",
                     "url": "https://www.preston.gov.uk/article/12132/Article-4-Direction-on-HMOs"}],
        "checked": "2026-11-11",
    },
    {
        "title": "Hertsmere (Potters Bar): HMO Article 4",
        "category": "Article 4 coming",
        "councils": ["Hertsmere"],
        "postcodes": ["EN6"],
        "status": "Consultation ran to 17 Jun 2026; needs confirming",
        "key_date": "May 2027",
        "summary": "A proposed HMO Article 4 direction for Potters Bar, due to come into force in May 2027 if confirmed.",
        "impact": "New small HMOs in Potters Bar would need planning permission.",
        "sources": [{"title": "Hertsmere Borough Council: consultation",
                     "url": "https://www.hertsmere.gov.uk/news/residents-invited-to-comment-on-proposed-article-4-direction-in-relation-to-hmos-in-potters-bar"}],
        "checked": "2026-11-11",
    },
    {
        "title": "North Tyneside: HMO Article 4 in eight wards",
        "category": "Article 4 coming",
        "councils": ["North Tyneside"],
        "postcodes": ["NE28", "NE29", "NE30"],
        "status": "Made 6 Aug 2026; consultation closed 22 Oct 2026; needs confirming",
        "key_date": "2027-08-06",
        "summary": "A non-immediate HMO Article 4 direction covering eight wards, proposed to start 6 August 2027.",
        "impact": "New small HMOs in those wards would need planning permission from that date.",
        "sources": [{"title": "PlanningGeek: North Tyneside HMO Article 4",
                     "url": "https://www.planninggeek.co.uk/2026/north-tyneside-hmo-article-4/"}],
        "checked": "2026-11-11",
    },
    {
        "title": "Burnley: HMO Article 4 extending to six more wards",
        "category": "Article 4 coming",
        "councils": ["Burnley"],
        "postcodes": ["BB10", "BB11", "BB12"],
        "status": "Made 25 Sep 2026; consultation closed 6 Nov 2026; needs confirming",
        "key_date": "2027-09-27",
        "summary": "A further HMO Article 4 direction for six wards, scheduled to take effect on 27 September 2027 "
                   "if confirmed. An earlier Burnley direction is also due for a decision in spring 2027.",
        "impact": "New small HMOs in the covered wards would need planning permission.",
        "sources": [{"title": "PlanningGeek: Burnley HMO Article 4",
                     "url": "https://www.planninggeek.co.uk/2026/burnley-hmo-article-4-made/"},
                    {"title": "Burnley Council: Article 4 (HMOs)",
                     "url": "https://burnley.gov.uk/planning/planning-permission/do-i-need-planning-permission/article4/article-4-direction-houses-in-multiple-occupation/"}],
        "checked": "2026-11-11",
    },
    {
        "title": "Bury: borough-wide HMO Article 4",
        "category": "Article 4 in force",
        "councils": ["Bury"],
        "postcodes": ["BL9", "BL8"],
        "status": "Immediate direction in force since 16 Jul 2026; lapses unless confirmed within 6 months",
        "key_date": "2027-01-16 (confirmation deadline)",
        "summary": "An immediate, borough-wide HMO Article 4 direction. It must be confirmed within six months "
                   "of coming into force or it expires.",
        "impact": "New small HMOs across Bury need planning permission now.",
        "sources": [{"title": "Bury Council: Article 4 directions",
                     "url": "https://www.bury.gov.uk/planning-building-control/planning-permission/article-4-directions"}],
        "checked": "2026-11-11",
    },
    {
        "title": "Sizewell C nuclear power station (Suffolk)",
        "category": "Major project",
        "councils": ["East Suffolk"],
        "postcodes": ["IP16", "IP17"],
        "status": "Main construction phase; formal construction began January 2024",
        "key_date": "Construction ongoing through the 2030s",
        "summary": ("Almost 2,000 workers on site and nearly £1bn of contracts awarded to East of England "
                    "businesses by January 2026. Haul road, marine import facility, the Sizewell Link Road and "
                    "the Two Village Bypass were all under construction in 2026."),
        "impact": ("A large construction workforce drives demand for rooms, HMOs and short lets in towns like "
                   "Leiston (IP16) and Saxmundham (IP17), and further out to Ipswich. That demand tends to fall "
                   "as construction winds down, so check how long a tenant base will last."),
        "sources": [
            {"title": "New Civil Engineer: two-year construction milestone",
             "url": "https://www.newcivilengineer.com/latest/sizewell-c-has-awarded-almost-1bn-in-local-contracts-at-two-year-mark-of-construction-16-01-2026/"},
            {"title": "Aldeburgh Town Council: construction update (June 2026)",
             "url": "https://www.aldeburghtowncouncil.gov.uk/2026/06/sizewell-c-construction-update/"},
            {"title": "Sizewell C annual report FY25/26",
             "url": "https://www.sizewellc.com/wp-content/uploads/2026/07/Annual-Report-2025-26.pdf"},
        ],
        "checked": "2026-11-11",
    },
]


def council_key(name: str) -> str:
    """'Bristol, City of', 'City of Bristol' and 'Bristol City Council' all become 'bristol'."""
    n = name.lower().replace("&", "and")
    for junk in (", city of", ", county of", "city of ", "county of ", " city council", " borough council",
                 " district council", " county council", " council", " metropolitan borough", " (b)"):
        n = n.replace(junk, "")
    return " ".join(n.replace(",", " ").split())


def split_councils(v) -> list[str]:
    """Comma-separated councils, keeping names like 'Bristol, City of' in one piece."""
    if not isinstance(v, str):
        return [str(x).strip() for x in (v or []) if str(x).strip()]
    out: list[str] = []
    for part in [p.strip() for p in v.replace("\n", ",").replace(";", ",").split(",")]:
        if not part:
            continue
        if out and part.lower() in ("city of", "county of"):
            out[-1] = f"{out[-1]}, {part}"
        else:
            out.append(part)
    return out


def clean_entry(d: dict) -> dict:
    """Normalises an entry from the form or the seed."""
    def lst(v):
        if isinstance(v, str):
            return [x.strip() for x in v.replace("\n", ",").split(",") if x.strip()]
        return [str(x).strip() for x in (v or []) if str(x).strip()]

    sources = d.get("sources") or []
    if isinstance(sources, str):   # "Title | url" per line, or bare urls
        parsed = []
        for line in sources.splitlines():
            if not line.strip():
                continue
            title, _, url = line.rpartition("|") if "|" in line else ("", "", line)
            url = url.strip()
            if url.startswith(("http://", "https://")):
                parsed.append({"title": title.strip() or url, "url": url})
        sources = parsed
    return {
        "id": d.get("id") or secrets.token_hex(4),
        "title": str(d.get("title") or "").strip() or "Untitled",
        "category": d.get("category") if d.get("category") in CATEGORIES else "Other",
        "councils": split_councils(d.get("councils")),
        "postcodes": [p.upper() for p in lst(d.get("postcodes"))],
        "status": str(d.get("status") or "").strip(),
        "key_date": str(d.get("key_date") or "").strip(),
        "summary": str(d.get("summary") or "").strip(),
        "impact": str(d.get("impact") or "").strip(),
        "sources": [s for s in sources if isinstance(s, dict) and str(s.get("url", "")).startswith("http")],
        "checked": str(d.get("checked") or date.today().isoformat()),
    }


class HotList:
    """Stored in the app's SQLite database."""

    def __init__(self, db):
        self.conn = db.conn
        self.conn.execute("CREATE TABLE IF NOT EXISTS hotlist (id TEXT PRIMARY KEY, data TEXT, updated TEXT)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
        self.conn.commit()
        self._seed()

    def _seed(self) -> None:
        row = self.conn.execute("SELECT v FROM meta WHERE k='hotlist_seed'").fetchone()
        if row and int(row[0]) >= SEED_VERSION:
            return
        done = int(row[0]) if row else 0
        for v in range(done + 1, SEED_VERSION + 1):
            for title in REPLACED_SEEDS.get(v, []):
                for e in self.all():
                    if e["title"] == title and e.get("checked") == "2026-11-11":
                        self.delete(e["id"])
        existing = {e["title"] for e in self.all()}
        for d in SEED:
            if d["title"] not in existing:
                self.save(clean_entry(d))
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES ('hotlist_seed', ?)", (str(SEED_VERSION),))
        self.conn.commit()

    def all(self) -> list[dict]:
        out = [json.loads(r[0]) for r in self.conn.execute("SELECT data FROM hotlist")]
        order = {c: i for i, c in enumerate(CATEGORIES)}
        return sorted(out, key=lambda e: (order.get(e["category"], 99), e["title"].lower()))

    def get(self, entry_id: str) -> dict | None:
        r = self.conn.execute("SELECT data FROM hotlist WHERE id=?", (entry_id,)).fetchone()
        return json.loads(r[0]) if r else None

    def save(self, entry: dict) -> dict:
        entry = clean_entry(entry)
        self.conn.execute("INSERT OR REPLACE INTO hotlist VALUES (?,?,?)",
                          (entry["id"], json.dumps(entry), date.today().isoformat()))
        self.conn.commit()
        return entry

    def delete(self, entry_id: str) -> None:
        self.conn.execute("DELETE FROM hotlist WHERE id=?", (entry_id,))
        self.conn.commit()

    def for_councils(self, councils: set[str]) -> list[dict]:
        wanted = {council_key(c) for c in councils}
        return [e for e in self.all() if wanted & {council_key(c) for c in e["councils"]}]
