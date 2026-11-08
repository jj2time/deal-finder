import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import dealfinder.config as config
from dealfinder.models import Listing
from dealfinder.pipeline import Scanner, SearchError
from dealfinder.search import Search, matches, rightmove_location_id, rightmove_url, zoopla_url
from dealfinder.web.app import create_app
from tests.test_pipeline import FakeLR, FakePD, FakePostcodes


def params(d):
    return Search.from_params(lambda k: d.get(k) if not isinstance(d.get(k), list) else d[k][0],
                              lambda k: d.get(k, []) if isinstance(d.get(k), list) else ([d[k]] if k in d else []))


def test_search_from_params():
    s = params({"area": " bs5 6hn ", "radius": "2", "max_price": "£150,000", "min_beds": "2",
                "type": ["terraced", "flat", "castle"], "deal": ["BMV", "Short lease", "nonsense"]})
    assert s.area == "BS5 6HN" and s.is_full_postcode and s.outcode == "BS5"
    assert s.radius_miles == 3          # nearest radius the portals offer
    assert s.max_price == 150000 and s.min_beds == 2
    assert s.types == ["terraced", "flat"] and s.deals == ["BMV", "Short lease"]
    assert params({"area": "m14"}).area == "M14" and not params({"area": "m14"}).is_full_postcode
    # deal ticks don't change what needs fetching
    assert s.fetch_key == params({**{"area": "BS5 6HN", "radius": "3", "max_price": "150000", "min_beds": "2",
                                    "type": ["terraced", "flat"]}}).fetch_key


def test_portal_urls():
    s = Search(area="BS5 6HN", radius_miles=1, min_price=50000, max_price=150000, min_beds=2,
               types=["terraced", "flat"])
    q = parse_qs(urlparse(rightmove_url("POSTCODE^103621", s)).query)
    assert q["locationIdentifier"] == ["POSTCODE^103621"] and q["radius"] == ["1"]
    assert q["minPrice"] == ["50000"] and q["maxPrice"] == ["150000"] and q["minBedrooms"] == ["2"]
    assert q["propertyTypes"] == ["terraced,flat"]
    z = urlparse(zoopla_url(s))
    assert z.path == "/for-sale/property/bs5/" and parse_qs(z.query)["q"] == ["BS5 6HN"]


class FakeHTTP:
    def __init__(self, body):
        self.body = body

    def request_json(self, *a, **k):
        return self.body


def test_rightmove_location_lookup():
    body = {"matches": [{"id": "291", "type": "OUTCODE", "displayName": "BS5"},
                        {"id": "x", "type": "STREET", "displayName": "Park Crescent, Bristol, BS5"}]}
    assert rightmove_location_id(FakeHTTP(body), "BS5") == "OUTCODE^291"
    body = {"matches": [{"id": "103621", "type": "POSTCODE", "displayName": "BS5 6HN"}]}
    assert rightmove_location_id(FakeHTTP(body), "BS5 6HN") == "POSTCODE^103621"
    assert rightmove_location_id(FakeHTTP({"matches": []}), "ZZ9") is None


def item(listing, **analysis):
    a = {"strategies": [], "bmv_pct": None, "gross_yield_pct": None, "score": 50}
    a.update(analysis)
    return {"listing": listing, "analysis": a}


def test_matches_radius_filters_and_ticks():
    s = Search(area="BS5 6HN", radius_miles=1, max_price=150000, deals=["Short lease", "Repossession"])
    near = {"lat": 51.4676, "lon": -2.5551, "price": 120000, "property_type": "flat", "bedrooms": 2}
    far = {**near, "lat": 51.50}   # ~3.6 km north
    short = [{"name": "Short lease"}]
    centre = (51.467638, -2.555134)
    assert matches(item(near, strategies=short), s, centre)
    assert not matches(item(far, strategies=short), s, centre)
    assert not matches(item(near, strategies=[{"name": "BMV"}]), s, centre)        # not ticked
    assert matches(item(near, strategies=[{"name": "BMV"}]), Search(area="BS5 6HN"), centre)  # nothing ticked
    assert not matches(item({**near, "price": 200000}, strategies=short), s, centre)
    nolatlon = {"outcode": "BS5", "price": 100000, "property_type": "terraced"}
    assert matches(item(nolatlon), Search(area="BS5"), None)
    assert not matches(item({**nolatlon, "outcode": "BS6"}), Search(area="BS5"), None)


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")


def fake_listings(n=3, outcode="BS5"):
    return [Listing(source="rightmove", source_id=str(i), url=f"https://www.rightmove.co.uk/properties/{i}",
                    address=f"{i} Test Street, Bristol, BS5 6AA", postcode="BS5 6AA", outcode=outcode,
                    price=100000 + i * 10000, property_type="terraced", bedrooms=3,
                    description="Short lease, 60 years remaining" if i == 0 else "Cash buyers only")
            for i in range(n)]


class NoNetworkReader:
    def search(self, url, progress=None):
        raise AssertionError("tests must not reach Rightmove")


def make_scanner(cfg, calls, listings=None, rm_id="POSTCODE^1"):
    cfg["sources"]["apify"]["rightmove_actor_id"] = "someone/rightmove-scraper"
    s = Scanner(cfg, http=FakeHTTP({"matches": [{"id": "1", "type": "POSTCODE", "displayName": "BS5 6AA"}]}),
                land_registry=FakeLR(), postcodes=FakePostcodes(), propertydata=FakePD(), sources=[],
                apify_runner=lambda actor, inp: calls.append((actor, inp)) or (listings or fake_listings()),
                rightmove_reader=NoNetworkReader())
    return s


def test_run_search_end_to_end(cfg, token):
    calls = []
    sc = make_scanner(cfg, calls)
    s = Search(area="BS5 6AA", radius_miles=1, max_price=115000)
    stats = sc.run_search(s)
    actor, inp = calls[0]
    assert actor == "someone/rightmove-scraper" and inp["maxItems"] == 100
    assert "locationIdentifier=POSTCODE%5E1" in inp["startUrls"][0]["url"]
    assert stats["fetched"] == 3 and stats["kept"] == 2          # the £120k one is over max price
    names = {m["name"] for it in sc.db.results() for m in it["analysis"]["strategies"]}
    assert {"Short lease", "Cash only"} <= names
    assert not sc.needs_fetch(s)                                 # fetched just now


def test_run_search_errors(cfg, token, monkeypatch):
    sc = make_scanner(cfg, [])
    with pytest.raises(SearchError, match="Type a postcode"):
        sc.run_search(Search(area=""))

    class NoPostcodes(FakePostcodes):
        def locate(self, postcode=None, outcode=None):
            return None
    sc.pc = NoPostcodes()
    with pytest.raises(SearchError, match="isn't a UK postcode"):
        sc.run_search(Search(area="ZZ99 9ZZ"))
    sc.pc = FakePostcodes()
    monkeypatch.delenv("APIFY_TOKEN")
    with pytest.raises(SearchError, match="Apify token"):
        sc.run_search(Search(area="BS5"))
    cfg["sources"]["apify"]["rightmove_actor_id"] = ""
    cfg["sources"]["rightmove"]["enabled"] = False
    with pytest.raises(SearchError, match="free Rightmove reader"):
        sc.run_search(Search(area="BS5"))


def test_scraper_failure_is_reported(cfg, token):
    sc = make_scanner(cfg, [])
    sc.apify_runner = lambda a, i: (_ for _ in ()).throw(RuntimeError("api.apify.com answered 402: no credit"))
    with pytest.raises(SearchError, match="no credit"):
        sc.run_search(Search(area="BS5"))


def test_saved_searches_run_in_daily_scan(cfg, token):
    calls = []
    sc = make_scanner(cfg, calls)
    s = Search(area="BS5 6AA", radius_miles=1)
    sc.db.set_saved(s.fetch_key, s.to_dict(), True)
    stats = sc.run()
    assert len(calls) == 1 and stats["kept"] == 3


def test_search_page_flow(tmp_path, monkeypatch, cfg, token):
    monkeypatch.setattr(config, "HOME", tmp_path)
    cfg["sources"]["apify"]["rightmove_actor_id"] = "someone/rightmove-scraper"
    app = create_app(cfg)
    client = TestClient(app)
    app.state.settings["postcodes"] = FakePostcodes()

    import dealfinder.pipeline as pipeline
    real_init = pipeline.Scanner.__init__

    def init(self, cfg, db=None, **kw):
        real_init(self, cfg, db=db, http=FakeHTTP({"matches": [{"id": "1", "type": "POSTCODE",
                                                                "displayName": "BS5 6AA"}]}),
                  land_registry=FakeLR(), postcodes=FakePostcodes(), propertydata=FakePD(), sources=[],
                  apify_runner=lambda a, i: fake_listings(), rightmove_reader=NoNetworkReader())
    monkeypatch.setattr(pipeline.Scanner, "__init__", init)

    page = client.get("/")
    for name in ("Short lease", "Repossession", "Probate", "BMV", "HMO potential", "Auction"):
        assert f'value="{name}"' in page.text
    r = client.post("/search", data={"area": "bs5 6aa", "radius": "1", "deal": "Short lease"},
                    follow_redirects=False)
    assert r.status_code == 303 and "area=BS5+6AA" in r.headers["location"]
    for _ in range(50):
        if not client.get("/scan/status").json()["running"]:
            break
        time.sleep(0.1)
    assert client.get("/scan/status").json()["error"] is None
    html = client.get(r.headers["location"]).text
    assert "1 property" in html and "0 Test Street" in html and "1 Test Street" not in html
    html = client.get("/", params={"area": "BS5 6AA", "radius": 1}).text      # no ticks = everything
    assert "3 properties" in html
    # searching again within 12 hours is instant (no new fetch)
    r = client.post("/search", data={"area": "BS5 6AA", "radius": "1"}, follow_redirects=False)
    assert client.get("/scan/status").json()["running"] is False
    # save it
    client.post("/search/save", data={"area": "BS5 6AA", "radius": "1", "saved": "1"})
    assert "Saved — scans daily" in client.get("/", params={"area": "BS5 6AA", "radius": 1}).text


def test_friendly_apify_errors():
    from dealfinder.sources.apify import friendly_error
    assert "token isn't valid" in friendly_error("api.apify.com answered 401: {...}", "a/b")
    assert "can't find the scraper “a/b”" in friendly_error("api.apify.com answered 404: {}", "a/b")
    assert "out of credit" in friendly_error("api.apify.com answered 402: {}", "a/b")
    assert "5 minutes" in friendly_error("api.apify.com timed out", "a/b")
