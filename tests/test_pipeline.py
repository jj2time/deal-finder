from fastapi.testclient import TestClient

from dealfinder.models import Listing
from dealfinder.pipeline import Scanner
from dealfinder.web.app import create_app
from tests.helpers import comps


class FakeSource:
    name = "fake"

    def __init__(self, price):
        self.price = price

    def fetch(self):
        return [Listing(source="rightmove", source_id="1", url="https://www.rightmove.co.uk/properties/1",
                        address="12 Test Street, Bristol, BS5 6AA", postcode="BS5 6AA", outcode="BS5",
                        price=self.price, property_type="terraced", bedrooms=3,
                        description="In need of modernisation, no chain"),
                Listing(source="rightmove", source_id="2", address="Somewhere, London, SW1A 1AA",
                        postcode="SW1A 1AA", outcode="SW1A", price=2_000_000)]


class FakePostcodes:
    def locate(self, postcode=None, outcode=None):
        return (51.46, -2.56)

    def nearby(self, lat, lon, radius):
        return [("BS5 6AA", 100.0)]

    def ring(self, lat, lon, distance):
        return []


class FakeLR:
    def sold_prices(self, nearby, months_back):
        from datetime import date
        return comps(10, 160000, date=date.today().replace(day=1).isoformat())


class FakePD:
    def rent_estimate(self, postcode, beds):
        return 900


def scanner(cfg, price):
    return Scanner(cfg, http=object(), land_registry=FakeLR(), postcodes=FakePostcodes(),
                   propertydata=FakePD(), sources=[FakeSource(price)])


def test_scan_stores_ranks_and_tracks_price_drops(cfg):
    stats = scanner(cfg, 125000).run()
    assert stats == {"fetched": 2, "kept": 1, "new": 1, "alerts": 0}   # £2m listing filtered out
    s2 = scanner(cfg, 115000)
    s2.run()
    [item] = s2.db.results()
    a = item["analysis"]
    assert a["market_value"] == 164500 and a["rent_pcm"] == 900 and a["rent_source"] == "PropertyData"
    assert any(s["name"] == "Motivated seller" and "1 price reduction" in s["reason"] for s in a["strategies"])
    assert [p["price"] for p in s2.db.price_history("rightmove:1")] == [125000, 115000]


def test_dashboard(cfg):
    scanner(cfg, 125000).run()
    client = TestClient(create_app(cfg))
    client.app.state.settings["postcodes"] = FakePostcodes()
    r = client.get("/", params={"area": "BS5 6AA", "radius": 1})
    assert r.status_code == 200 and "12 Test Street" in r.text and "Open Government Licence" in r.text
    assert "12 Test Street" in client.get("/", params={"area": "BS5", "deal": "Refurb / BRRR"}).text
    assert "12 Test Street" not in client.get("/", params={"area": "BS5", "deal": "HMO potential"}).text
    assert "12 Test Street" in client.get("/", params={"area": "BS5", "deal": ["HMO potential", "BMV"]}).text
    d = client.get("/deal/rightmove:1")
    assert d.status_code == 200 and "Sold-price evidence" in d.text
    csv = client.get("/export.csv", params={"area": "BS5"})
    assert csv.status_code == 200 and "12 Test Street" in csv.text
    pdf = client.get("/deal/rightmove:1/pack.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
