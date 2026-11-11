import csv
from datetime import date, datetime

import openpyxl
from fastapi.testclient import TestClient

import dealfinder.config as config
from dealfinder.areas import AreaStore, build, explain
from dealfinder.db import DB
from dealfinder.hotlist import HotList, SEED
from dealfinder.web.app import create_app

HPI_COLS = ["Date", "RegionName", "AreaCode", "AveragePrice", "Index", "12m%Change", "SalesVolume",
            "DetachedPrice", "DetachedIndex", "Detached12m%Change", "SemiDetachedPrice", "SemiDetachedIndex",
            "SemiDetached12m%Change", "TerracedPrice", "TerracedIndex", "Terraced12m%Change", "FlatPrice",
            "FlatIndex", "Flat12m%Change"]
AREAS = {  # code: (name, price now, yearly growth %, rent pcm or None)
    "E08000012": ("Liverpool", 180000, 6.0, 900),
    "E09000001": ("City of London", 800000, 2.0, 2500),
    "E07000117": ("Burnley", 120000, 3.0, 650),
    "S12000049": ("Glasgow City", 200000, 5.0, None),
    "K02000001": ("United Kingdom", 270000, 3.0, 1400),
}


def make_files(tmp_path):
    hpi = tmp_path / "hpi.csv"
    with open(hpi, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HPI_COLS)
        for code, (name, price, g, _) in AREAS.items():
            for months_ago in range(252, -1, -1):
                y, m = divmod(2026 * 12 + 7 - months_ago, 12)
                p = price / (1 + g / 100) ** (months_ago / 12)
                idx = 100 * p / price
                vol = "" if months_ago < 2 else "300"
                row = [f"01/{m + 1:02d}/{y}", name, code, round(p), idx, g, vol]
                for factor in (1.5, 1.1, 0.95, 0.7):
                    row += [round(p * factor), idx, g]
                w.writerow(row)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Table 1"
    ws.append(["Price Index of Private Rents"])
    ws.append(["notes"])
    header = ["Time period", "Area code", "Area name", "Region or country name"] + [f"c{i}" for i in range(4, 40)]
    header[7] = "Rental price"
    ws.append(header)
    regions = {"E08000012": "North West", "E09000001": "London", "E07000117": "North West",
               "S12000049": "Scotland", "K02000001": "[z]"}
    for code, (name, _, _, rent) in AREAS.items():
        for month in (8, 9):
            row = [datetime(2026, month, 1), code, name, regions[code]] + [None] * 36
            if rent:
                row[7] = rent
                row[27], row[31], row[35], row[39] = rent * 1.4, rent * 1.15, rent, rent * 0.8
            else:
                for i in (7, 27, 31, 35, 39):
                    row[i] = "[x]"
            ws.append(row)
    rents = tmp_path / "rents.xlsx"
    wb.save(rents)
    return hpi, rents


def test_build_scores_and_projection(tmp_path):
    areas, meta = build(*make_files(tmp_path))
    by = {a["name"]: a for a in areas}
    assert set(by) == {"Liverpool", "City of London", "Burnley", "Glasgow City"}   # UK row kept separately
    assert meta["price_month"] == "2026-08" and meta["rent_month"] == "2026-09"
    liv = by["Liverpool"]["types"]["all"]
    assert liv["price"] == 180000 and liv["rent"] == 900 and liv["yield"] == 6.0
    assert abs(liv["growth_5y"] - ((1.06 ** 5 - 1) * 100)) < 0.3
    assert abs(liv["trend_per_year"] - 6.0) < 0.05
    assert abs(liv["projected_10y"] - ((1.06 ** 10 - 1) * 100)) < 0.5
    assert by["Liverpool"]["sales_12m"] == 3600
    flats = by["Liverpool"]["types"]["flat"]
    assert flats["price"] == 126000 and flats["rent"] == 720 and round(flats["yield"], 1) == 6.9
    # Glasgow has no ONS rents: no yield and no overall score, so it can't top the table on growth alone
    assert by["Glasgow City"]["types"]["all"]["yield"] is None and by["Glasgow City"]["types"]["all"]["score"] is None
    assert by["Liverpool"]["types"]["all"]["score"] > by["City of London"]["types"]["all"]["score"]
    reasons = " ".join(explain(by["Liverpool"], "all", meta["medians"]))
    assert "Gross yield 6.0%" in reasons and "not a forecast" in reasons
    assert "no yield" in " ".join(explain(by["Glasgow City"], "all", meta["medians"]))


def test_hotlist_seed_edit_and_lookup(tmp_path):
    db = DB(str(tmp_path / "x.sqlite3"))
    hl = HotList(db)
    assert len(hl.all()) == len(SEED)
    assert HotList(db) and len(hl.all()) == len(SEED)                    # seeding happens once
    liv = hl.for_councils({"Liverpool"})
    assert len(liv) == 2 and {e["category"] for e in liv} == {"Article 4 in force", "Article 4 coming"}
    assert any("17 June 2021" in e["status"] and "Wavertree" in e["summary"] for e in liv)
    assert any("Orrell Park" in e["summary"] and "called in" in e["status"] for e in liv)
    assert hl.for_councils({"sefton"}) == []
    e = hl.save({"title": "Leeds: Headingley", "category": "Article 4 coming", "councils": "Leeds",
                 "postcodes": "ls6, ls4", "sources": "Leeds council | https://www.leeds.gov.uk/x\nnot a link"})
    assert e["postcodes"] == ["LS6", "LS4"] and e["sources"] == [{"title": "Leeds council", "url": "https://www.leeds.gov.uk/x"}]
    hl.delete(e["id"])
    assert not hl.for_councils({"Leeds"})
    b = hl.save({"title": "Bristol thing", "councils": "Bristol, City of, Bath and North East Somerset"})
    assert b["councils"] == ["Bristol, City of", "Bath and North East Somerset"]
    assert hl.for_councils({"City of Bristol"}) and hl.for_councils({"Bristol City Council"})
    hl.delete(b["id"])
    hl.delete(liv[0]["id"])
    assert len(HotList(db).all()) == len(SEED) - 1                      # a deleted seed entry stays deleted


def test_pages(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(config, "HOME", tmp_path)
    from tests.test_pipeline import FakePostcodes, scanner
    scanner(cfg, 125000).run()
    app = create_app(cfg)
    app.state.settings["postcodes"] = FakePostcodes()
    client = TestClient(app)
    started = []
    import dealfinder.web.area_pages as ap
    monkeypatch.setattr(ap, "update_area_data", lambda store, d, progress: started.append(1) or {})
    page = client.get("/areas").text                                   # first visit starts the download itself
    assert "Updating area data" in page
    for _ in range(40):
        if not client.get("/scan/status").json()["running"]:
            break
        import time; time.sleep(0.05)
    assert started == [1]
    areas, meta = build(*make_files(tmp_path))
    AreaStore(DB(cfg["database"])).replace_all(areas, meta)

    page = client.get("/areas").text
    assert page.index("Liverpool") < page.index("City of London") and "Glasgow City" in page
    assert "🔥 Article 4 coming" in page                              # Liverpool is on the hot list
    flats = client.get("/areas", params={"type": "flat", "sort": "price", "max_price": "150000"}).text
    assert "Burnley" in flats and "City of London" not in flats
    assert flats.index("Burnley") < flats.index("Liverpool")           # cheapest first

    report = client.get("/areas/E08000012", params={"type": "terraced"}).text
    assert "Why Liverpool (terraced)" in report and "not a forecast" in report
    assert "Liverpool: HMO Article 4 in force since June 2021" in report and "Search within 3 miles of L3" in report

    home = client.get("/").text                                         # hot list is on the main page
    assert "🔥 Hot list" in home and "Sizewell C" in home and "Liverpool: HMO Article 4" in home
    assert 'href="/hotlist"' not in home.split("<main>")[0]              # no longer a menu tab
    hot = client.get("/hotlist").text
    assert "Sizewell C" in hot and "Liverpool area report" in hot and "Search L9 8BX" in hot
    r = client.post("/hotlist", data={"title": "Test regen", "category": "Regeneration", "councils": "Bristol, City of",
                                      "postcodes": "BS5", "status": "Planned", "checked": "2026-11-11"})
    assert r.status_code == 200 and "Test regen" in r.text

    # searching an area in a hot-list council shows a heads-up
    page = client.get("/", params={"area": "L15", "radius": 1}).text
    assert "Heads-up for L15" in page and "Liverpool: HMO Article 4" in page
    page = client.get("/", params={"area": "BS5", "radius": 1}).text
    assert "Heads-up for BS5" in page and "Test regen" in page


def test_old_liverpool_entry_replaced_on_upgrade(tmp_path):
    import json
    db = DB(str(tmp_path / "x.sqlite3"))
    db.conn.execute("CREATE TABLE IF NOT EXISTS hotlist (id TEXT PRIMARY KEY, data TEXT, updated TEXT)")
    db.conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    old = {"id": "old1", "title": "Liverpool: HMO Article 4 spreading across the city", "category": "Article 4 coming",
           "councils": ["Liverpool"], "postcodes": [], "status": "", "key_date": "", "summary": "", "impact": "",
           "sources": [], "checked": "2026-11-11"}
    mine = {**old, "id": "mine", "title": "My own Leeds note", "checked": "2026-11-12"}
    for e in (old, mine):
        db.conn.execute("INSERT INTO hotlist VALUES (?,?,?)", (e["id"], json.dumps(e), "x"))
    db.conn.execute("INSERT INTO meta VALUES ('hotlist_seed', '1')")
    db.conn.commit()
    titles = [e["title"] for e in HotList(db).all()]
    assert "Liverpool: HMO Article 4 spreading across the city" not in titles
    assert "My own Leeds note" in titles
    assert sum(t.startswith("Liverpool: HMO Article 4") for t in titles) == 2


def test_stage_where_and_link(tmp_path, monkeypatch, cfg):
    db = DB(str(tmp_path / "x.sqlite3"))
    hl = HotList(db)
    by = {e["title"]: e for e in hl.all()}
    exp = by["Liverpool: HMO Article 4 expansion (Oct 2026) and citywide plan (2027)"]
    assert exp["stage"] == "Expansion" and "Orrell Park" in exp["where"] and exp["link"].startswith("https://")
    assert by["Liverpool: HMO Article 4 in force since June 2021 (11 wards incl. Wavertree)"]["stage"] == "In force"
    assert by["Sizewell C nuclear power station (Suffolk)"]["stage"] == "Project underway"
    # an entry saved before these fields existed gets them filled in
    import json
    old = {**exp, "id": "x1"}
    for k in ("stage", "where", "link"):
        old.pop(k)
    db.conn.execute("UPDATE hotlist SET data=? WHERE id=?", (json.dumps(old), exp["id"]))
    db.conn.commit()
    again = next(e for e in HotList(db).all() if e["title"] == exp["title"])
    assert again["stage"] == "Expansion" and "Old Swan" in again["where"]
    mine = hl.save({"title": "Leeds note", "category": "Article 4 coming", "stage": "Proposed",
                    "where": "Headingley", "link": "https://example.com/leeds"})
    assert (mine["stage"], mine["where"], mine["link"]) == ("Proposed", "Headingley", "https://example.com/leeds")
    assert hl.save({"title": "Bad", "link": "javascript:alert(1)"})["link"] == ""

    monkeypatch.setattr(config, "HOME", tmp_path)
    cfg["database"] = str(tmp_path / "x.sqlite3")
    client = TestClient(create_app(cfg))
    page = client.get("/").text
    for col in ("<th>Stage</th>", "<th>Where</th>", "<th>Details</th>", "Read more ↗", "stage-expansion",
                "Orrell Park, part of Fazakerley"):
        assert col in page, col
    assert "Where:</b>" in client.get("/hotlist").text
