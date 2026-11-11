import pytest
from fastapi.testclient import TestClient

import dealfinder.claude_connector as cc
import dealfinder.config as config
from dealfinder.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(cc, "load_config", lambda: cfg)
    monkeypatch.setattr(cc, "claude_desktop_status", lambda home_dir=None: {"installed": True, "connected": True})
    opened = []
    monkeypatch.setattr(cc, "open_claude_desktop", lambda: opened.append(1) or True)
    import dealfinder.web.photo_pages as pp
    monkeypatch.setattr(pp, "claude_desktop_status", lambda home_dir=None: {"installed": True, "connected": True})
    monkeypatch.setattr(pp, "open_claude_desktop", lambda: opened.append(1) or True)
    from tests.test_pipeline import scanner
    scanner(cfg, 125000).run()
    return TestClient(create_app(cfg)), opened


def test_photo_check_tab_and_start(client):
    c, opened = client
    home = c.get("/").text
    assert 'href="/photos">📷 Photo check' in home
    page = c.get("/photos").text
    assert "📷 Photo check" in page and "Analyse photos" in page and "No reports yet" in page
    r = c.post("/photos/start", json={"property": "https://www.rightmove.co.uk/properties/92563998#/?channel=RES_BUY"})
    d = r.json()
    assert r.status_code == 200 and d["prompt"] == "Analyse the photos of https://www.rightmove.co.uk/properties/92563998"
    assert d["key"] == "rightmove:92563998" and d["opened"] is True and opened == [1]
    assert c.post("/photos/start", json={"property": "rightmove:1"}).json()["url"].endswith("/properties/1")
    bad = c.post("/photos/start", json={"property": "hello"})
    assert bad.status_code == 400 and "Rightmove property link" in bad.json()["error"]


def test_results_have_analyse_button_then_report_ready(client):
    c, _ = client
    from tests.test_pipeline import FakePostcodes
    c.app.state.settings["postcodes"] = FakePostcodes()
    page = c.get("/", params={"area": "BS5 6AA", "radius": 1}).text
    assert "📷 Analyse photos" in page and "analysePhotos('https://www.rightmove.co.uk/properties/1')" in page
    assert "📷 Report ready" not in page
    assert c.get("/photos/status").json()["count"] == 0
    cc.save_report("https://www.rightmove.co.uk/properties/1", "## Kitchen\nPoor (photo 3).", 9000, 16000)
    page = c.get("/", params={"area": "BS5 6AA", "radius": 1}).text
    assert "📷 Report ready" in page and "📷 Analyse again" in page
    assert c.get("/photos/status").json() == {"count": 1, "latest": "rightmove:1"}
    lst = c.get("/photos").text
    assert "£9,000–£16,000" in lst and "/report/rightmove:1" in lst
    rep = c.get("/report/rightmove:1").text
    assert "Refurb estimate: £9,000–£16,000" in rep and "Use in deal post" in rep and "Poor (photo 3)." in rep


def test_report_for_property_not_searched_yet(client):
    c, _ = client
    cc.save_report("https://www.rightmove.co.uk/properties/92563998", "Endborne Road report", 3100, 8200)
    rep = c.get("/report/rightmove:92563998").text
    assert "Endborne Road report" in rep and "isn't in your Deal Finder searches yet" in rep
    assert "https://www.rightmove.co.uk/properties/92563998" in rep
    assert c.get("/report/rightmove:404").status_code == 404


def test_connector_save_message_links_to_report():
    import inspect
    assert "/report/{key}" in inspect.getsource(cc.build_server)
