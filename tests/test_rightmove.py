"""The free Rightmove reader, tested against small made-up pages shaped like Rightmove's (no network)."""
import json

import httpx
from fastapi.testclient import TestClient

import dealfinder.config as config
from dealfinder.analysis import analyse
from dealfinder.models import Listing
from dealfinder.pipeline import Scanner
from dealfinder.search import Search
from dealfinder.sources.rightmove import (RightmoveError, RightmoveReader, map_property, parse_property_page,
                                          parse_search_page)
from dealfinder.web.app import create_app
from tests.test_pipeline import FakeLR, FakePD, FakePostcodes


def prop(i, **kw):
    p = {"id": 1000 + i, "displayAddress": f"Example Road, Bristol, BS5", "bedrooms": 2,
         "price": {"amount": 100000 + i * 1000, "displayPrices": [{"displayPrice": "£x"}]},
         "propertySubType": "Flat", "summary": "A flat.", "keyFeatures": [{"description": "Garden"}],
         "location": {"latitude": 51.4676, "longitude": -2.5551}, "propertyUrl": f"/properties/{1000 + i}#/?channel=RES_BUY",
         "tenure": {"tenureType": "LEASEHOLD"}, "displaySize": "538 sq. ft.", "auction": False,
         "addedOrReduced": "Added on 01/11/2026", "propertyImages": {"mainImageSrc": "https://img/1.jpg"}}
    p.update(kw)
    return p


def search_page(props, total):
    data = {"props": {"pageProps": {"searchResults": {"properties": props, "resultCount": str(total)}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def property_page(years, description="Spacious flat.<br />Cash buyers only."):
    arr = [{"propertyData": 1}, {"tenure": 2, "text": 5, "sizings": 7, "keyFeatures": 10},
           {"tenureType": 3, "yearsRemainingOnLease": 4}, "LEASEHOLD", years,
           {"description": 6}, description, [8], {"unit": 9, "minimumSize": 11}, "sqm", [12], 50, "LIFT"]
    return f'<script>window.__PAGE_MODEL = {json.dumps({"data": json.dumps(arr), "encoding": "x"})}</script>'


def test_map_property():
    l = map_property(prop(1, addedOrReduced="Reduced on 06/11/2026"))
    assert l.key == "rightmove:1001" and l.url == "https://www.rightmove.co.uk/properties/1001"
    assert l.price == 101000 and l.property_type == "flat" and l.bedrooms == 2 and l.outcode == "BS5"
    assert l.tenure == "leasehold" and l.floor_area_sqm == 50.0 and l.lat == 51.4676
    assert l.raw["_portal_reduced"] and l.image == "https://img/1.jpg" and "Garden" in l.description
    # the trimmed copy the browser button sends
    l2 = map_property({"id": 7, "displayAddress": "X, M14", "price": 90000, "propertySubType": "Terraced",
                       "keyFeatures": ["Auction"], "tenure": "FREEHOLD", "auction": True})
    assert l2.price == 90000 and l2.property_type == "terraced" and l2.is_auction and l2.tenure == "freehold"


def test_parse_pages():
    props, total = parse_search_page(search_page([prop(1), prop(2)], 30))
    assert len(props) == 2 and total == 30
    d = parse_property_page(property_page(72))
    assert {k: d[k] for k in ("tenure", "lease_years", "floor_area_sqm", "description", "key_features")} == {
        "tenure": "leasehold", "lease_years": 72, "floor_area_sqm": 50.0,
        "description": "Spacious flat.\nCash buyers only.", "key_features": ["LIFT"]}
    assert parse_property_page("<html>nothing</html>") == {}
    try:
        parse_search_page("<html>blocked</html>")
        assert False
    except RightmoveError as e:
        assert "didn't contain any listings" in str(e)


def fake_client(routes, calls):
    def handler(request: httpx.Request):
        calls.append(str(request.url))
        for key, resp in routes.items():
            if key in str(request.url):
                return resp() if callable(resp) else resp
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_reader_pages_details_and_pauses():
    calls, pauses = [], []
    page1 = search_page([prop(i) for i in range(24)], 30)
    page2 = search_page([prop(i) for i in range(24, 30)], 30)
    routes = {"index=24": httpx.Response(200, text=page2), "find.html": httpx.Response(200, text=page1),
              "/properties/1003": httpx.Response(200, text=property_page(65)),
              "/properties/": httpx.Response(200, text=property_page(120))}
    r = RightmoveReader(max_pages=3, details="leasehold", max_details=5, client=fake_client(routes, calls),
                        sleep=pauses.append)
    out = r.search("https://www.rightmove.co.uk/property-for-sale/find.html?locationIdentifier=X")
    assert len(out) == 30
    assert sum("find.html" in c for c in calls) == 2            # stopped after the last page
    assert sum("/properties/" in c for c in calls) == 5         # capped
    assert len(pauses) == len(calls) - 1 and all(2 <= p <= 4 for p in pauses)
    short = next(l for l in out if l.source_id == "1003")
    assert short.lease_years == 65 and "Cash buyers only" in short.description


def test_reader_stops_when_refused():
    calls = []
    r = RightmoveReader(client=fake_client({"find.html": httpx.Response(429)}, calls), sleep=lambda s: None)
    try:
        r.search("https://www.rightmove.co.uk/property-for-sale/find.html?x=1")
        assert False
    except RightmoveError as e:
        assert "refused" in str(e)
    assert len(calls) == 1                                       # no retrying


def test_short_lease_found_from_property_page(cfg):
    l = map_property(prop(1))
    l.lease_years = 65
    a = analyse(l, [], cfg)
    assert "Short lease" in {m.name for m in a.strategies}


class FakeReader:
    def __init__(self):
        self.urls = []

    def search(self, url, progress=lambda m: None):
        self.urls.append(url)
        return [map_property(prop(i)) for i in range(3)]


def test_free_search_needs_no_apify(cfg, monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    reader = FakeReader()

    class HTTP:
        def request_json(self, *a, **k):
            return {"matches": [{"id": "291", "type": "OUTCODE", "displayName": "BS5"}]}
    sc = Scanner(cfg, http=HTTP(), land_registry=FakeLR(), postcodes=FakePostcodes(), propertydata=FakePD(),
                 sources=[], rightmove_reader=reader)
    stats = sc.run_search(Search(area="BS5", radius_miles=1))
    assert stats["kept"] == 3 and "locationIdentifier=OUTCODE%5E291" in reader.urls[0]


def test_browser_button_import(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(config, "HOME", tmp_path)
    import dealfinder.pipeline as pipeline
    real_init = pipeline.Scanner.__init__

    def init(self, cfg, db=None, **kw):
        real_init(self, cfg, db=db, http=object(), land_registry=FakeLR(), postcodes=FakePostcodes(),
                  propertydata=FakePD(), sources=[])
    monkeypatch.setattr(pipeline.Scanner, "__init__", init)
    client = TestClient(create_app(cfg))
    page = client.get("/").text
    assert 'href="javascript:' in page and "__NEXT_DATA__" in page.replace("%22", '"')

    items = [{k: v for k, v in prop(i).items()} for i in range(4)]
    for it in items:
        it["price"] = it["price"]["amount"]
    r = client.post("/import/browser", json={"items": items})
    assert r.status_code == 200 and r.json()["redirect"].startswith("/?batch=")
    import time
    for _ in range(50):
        if not client.get("/scan/status").json()["running"]:
            break
        time.sleep(0.1)
    html = client.get(r.json()["redirect"]).text
    assert "4 listings from your browser" in html and "Example Road" in html
    assert client.post("/import/browser", json={"items": []}).status_code == 400
    assert "Sending the listings" in client.get("/import/browser").text
