import time

from fastapi.testclient import TestClient

import dealfinder.config as config
from dealfinder.models import Listing
from dealfinder.pipeline import Scanner, SearchError
from dealfinder.search import Search, area_searches, hot_areas, parse_hot_areas
from dealfinder.web.app import create_app
from tests.test_pipeline import FakeLR, FakePD

CENTRES = {"L15": (53.3960, -2.9200), "L13": (53.4140, -2.9150), "L7": (53.4050, -2.9480)}


class Postcodes:
    def councils(self, postcode=None, outcode=None):
        oc = (outcode or postcode or "").split()[0]
        return {"L15": ["Liverpool"], "L13": ["Liverpool"], "L9": ["Liverpool", "Sefton"],
                "BS5": ["Bristol, City of"]}.get(oc, [])

    def town_outcode(self, name):
        return {"Liverpool": "L3"}.get(name)

    def locate(self, postcode=None, outcode=None):
        return CENTRES.get((outcode or postcode or "").split()[0])

    def nearby(self, lat, lon, radius):
        return [("L15 1AA", 100.0)]

    def ring(self, *a):
        return []


def listing(i, outcode):
    lat, lon = CENTRES[outcode]
    return Listing(source="rightmove", source_id=f"{outcode}-{i}", address=f"{i} Test Road, Liverpool, {outcode}",
                   outcode=outcode, price=120000 + i, property_type="terraced", bedrooms=3, lat=lat, lon=lon,
                   description="No chain")


class Reader:
    def __init__(self, fail=()):
        self.urls, self.fail = [], fail

    def search(self, url, progress=lambda m: None):
        self.urls.append(url)
        oc = "L15" if "OUTCODE%5E15" in url else "L13" if "OUTCODE%5E13" in url else "L7"
        if oc in self.fail:
            from dealfinder.sources.rightmove import RightmoveError
            raise RightmoveError("Rightmove refused the request")
        return [listing(i, oc) for i in range(2)]


class HTTP:   # Rightmove's location lookup: L15 -> OUTCODE^15 etc.
    def request_json(self, method, url, params=None, **k):
        oc = params["query"]
        return {"matches": [{"id": oc[1:], "type": "OUTCODE", "displayName": oc}]}


def test_defaults_and_parsing(cfg):
    cfg.pop("hot_areas", None)
    assert [(h["name"], h["area"], h["radius"]) for h in hot_areas(cfg)] == [
        ("Wavertree", "L15", 1), ("Old Swan", "L13", 1), ("Aintree Hospital / Longmoor Lane", "L9 7AL", 0.5),
        ("Orrell Park", "L9 8BX", 0.5)]
    cfg["hot_areas"] = []
    assert hot_areas(cfg) == []                                   # removing them all is respected
    areas, errors = parse_hot_areas("Wavertree, l15, 1\nOld Swan, L13\nEdge Hill, l7 5ab, 0.5\nbad line")
    assert areas == [{"name": "Wavertree", "area": "L15", "radius": 1}, {"name": "Old Swan", "area": "L13", "radius": 1},
                     {"name": "Edge Hill", "area": "L7 5AB", "radius": 0.5}]
    assert errors and "bad line" in errors[0]


def test_area_searches_share_filters():
    base = Search(area="", max_price=150000, deals=["BMV"])
    hot = [{"name": "Wavertree", "area": "L15", "radius": 1}, {"name": "Old Swan", "area": "L13", "radius": 3}]
    ss = area_searches(base, hot, ["Wavertree", "Old Swan", "Nowhere"])
    assert [(x.area, x.radius_miles, x.max_price, x.deals) for x in ss] == [("L15", 1, 150000, ["BMV"]),
                                                                          ("L13", 3, 150000, ["BMV"])]
    assert len(area_searches(Search(area="L15"), hot, ["Wavertree"])) == 1   # no duplicate search


def test_one_failing_area_doesnt_stop_the_others(cfg):
    sc = Scanner(cfg, http=HTTP(), land_registry=FakeLR(), postcodes=Postcodes(), propertydata=FakePD(),
                 sources=[], rightmove_reader=Reader(fail=("L13",)))
    stats = sc.run_searches([Search(area="L15"), Search(area="L13")])
    assert stats["kept"] == 2 and "L13" in stats["errors"][0]
    sc2 = Scanner(cfg, http=HTTP(), land_registry=FakeLR(), postcodes=Postcodes(), propertydata=FakePD(),
                  sources=[], rightmove_reader=Reader(fail=("L15", "L13")))
    try:
        sc2.run_searches([Search(area="L15", max_price=1), Search(area="L13", max_price=1)])
        assert False
    except SearchError as e:
        assert "L15" in str(e) and "L13" in str(e)


def wait(client):
    for _ in range(60):
        if not client.get("/scan/status").json()["running"]:
            return
        time.sleep(0.05)


def test_hot_areas_on_the_search_page(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(config, "HOME", tmp_path)
    cfg.pop("hot_areas", None)
    import dealfinder.pipeline as pipeline
    reader = Reader()
    real_init = pipeline.Scanner.__init__
    monkeypatch.setattr(pipeline.Scanner, "__init__", lambda self, cfg, db=None, **kw: real_init(
        self, cfg, db=db, http=HTTP(), land_registry=FakeLR(), postcodes=Postcodes(), propertydata=FakePD(),
        sources=[], rightmove_reader=reader))
    app = create_app(cfg)
    app.state.settings["postcodes"] = Postcodes()
    client = TestClient(app)

    page = client.get("/").text
    assert "Hot areas" in page and 'value="Wavertree"' in page and 'value="Old Swan"' in page and "L13" in page

    # tick both, no postcode typed
    r = client.post("/search", data={"hot": ["Wavertree", "Old Swan"], "radius": "1", "max_price": "200000"},
                    follow_redirects=False)
    assert "hot=Wavertree" in r.headers["location"] and "hot=Old+Swan" in r.headers["location"]
    wait(client)
    assert client.get("/scan/status").json()["error"] is None
    assert len(reader.urls) == 2
    page = client.get(r.headers["location"]).text
    assert "4 properties" in page and "Wavertree (L15)" in page and "Old Swan (L13)" in page
    assert "L15-0" in page and "L13-1" in page

    # one-click button: only Old Swan, ignoring other ticks
    r = client.post("/search", data={"only": "Old Swan", "hot": ["Wavertree"], "refresh": "1"},
                    follow_redirects=False)
    wait(client)
    page = client.get(r.headers["location"]).text
    assert "2 properties" in page and "L13-0" in page and "L15-0" not in page

    # export follows the hot areas
    csv = client.get("/export.csv?" + r.headers["location"].split("?", 1)[1]).text
    assert "L13" in csv and "L15 " not in csv

    # nothing typed or ticked
    r = client.post("/search", data={"radius": "1"})
    assert "Type a postcode or tick a hot area" in r.text

    # edit them in Settings
    client.post("/settings", data={"hot_areas_text": "Wavertree, L15, 1\nEdge Hill, L7, 0.5", "daily_at": "07:30"})
    page = client.get("/").text
    assert 'value="Edge Hill"' in page and 'value="Old Swan"' not in page
    assert "Edge Hill, L7, 0.5" in client.get("/settings").text


def test_new_default_areas_added_once_to_a_saved_list(cfg):
    from dealfinder.search import upgrade_hot_areas
    cfg["hot_areas"] = [{"name": "Wavertree", "area": "L15", "radius": 3}, {"name": "Edge Hill", "area": "L7"}]
    cfg.pop("hot_areas_version", None)
    assert upgrade_hot_areas(cfg)
    assert [h["name"] for h in cfg["hot_areas"]] == ["Wavertree", "Edge Hill", "Aintree Hospital / Longmoor Lane",
                                                     "Orrell Park"]
    assert cfg["hot_areas"][0]["radius"] == 3                     # their own settings untouched
    cfg["hot_areas"] = cfg["hot_areas"][:2]                       # they delete the new ones later…
    assert not upgrade_hot_areas(cfg) and len(cfg["hot_areas"]) == 2   # …and they stay deleted
