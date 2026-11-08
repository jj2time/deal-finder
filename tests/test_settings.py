import os

import pytest
import yaml
from fastapi.testclient import TestClient

import dealfinder.config as config
from dealfinder.web.app import create_app


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    for k in config.ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def test_settings_save_and_keep_secrets(home):
    client = TestClient(create_app(config.load_config()))
    assert "Welcome" in client.get("/").text
    page = client.get("/settings")
    assert page.status_code == 200 and "Apify API token" in page.text

    form = {"env_APIFY_TOKEN": "apify_api_secret123",
            "rightmove_actor_id": "someone/rightmove-scraper", "zoopla_actor_id": "other/zoopla",
            "apify_max_items": "50", "apify_extra": '{"proxy": {"useApifyProxy": true}}', "districts": "bs5, m14", "min_price": "50000", "max_price": "200000",
            "min_bedrooms": "2", "type_terraced": "on", "type_flat": "on", "mortgage_rate_pct": "6",
            "daily_at": "08:15", "env_ALERTS_IMAP_HOST": "imap.gmail.com"}
    r = client.post("/settings", data=form, follow_redirects=False)
    assert r.status_code == 303 and "saved=1" in r.headers["location"]

    cfg = yaml.safe_load((home / "config.yaml").read_text())
    assert cfg["areas"]["postcode_districts"] == ["BS5", "M14"]
    assert cfg["filters"]["property_types"] == ["terraced", "flat"]
    ap = cfg["sources"]["apify"]
    assert ap["rightmove_actor_id"] == "someone/rightmove-scraper" and ap["zoopla_actor_id"] == "other/zoopla"
    assert ap["max_items"] == 50 and ap["extra_input"] == {"proxy": {"useApifyProxy": True}}
    assert cfg["finance"]["mortgage_rate_pct"] == 6
    assert cfg["schedule"]["daily_at"] == "08:15" and cfg["database"] == "data/dealfinder.sqlite3"
    assert os.environ["APIFY_TOKEN"] == "apify_api_secret123"

    # The token is never sent back to the browser; saving with it blank keeps it.
    page = client.get("/settings").text
    assert "apify_api_secret123" not in page and "saved ✓" in page
    client.post("/settings", data={**form, "env_APIFY_TOKEN": ""})
    assert config.read_env()["APIFY_TOKEN"] == "apify_api_secret123"


def test_bad_settings_are_reported(home):
    client = TestClient(create_app(config.load_config()))
    r = client.post("/settings", data={"daily_at": "soon", "apify_extra": "not json"}, follow_redirects=True)
    assert "Daily scan time" in r.text and "JSON" in r.text


def test_csv_upload(home):
    client = TestClient(create_app(config.load_config()))
    r = client.post("/upload", files={"file": ("auction.csv", b"address,price\n1 A St,50000\n", "text/csv")})
    assert r.status_code == 200 and "Imported auction.csv" in r.text
    assert (home / "imports" / "auction.csv").exists()
    r = client.post("/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert "Only CSV" in r.text
