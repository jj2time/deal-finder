import json
import time

import pytest
from fastapi.testclient import TestClient

import dealfinder.config as config
import dealfinder.updater as up
from dealfinder.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(config, "HOME", tmp_path)
    cfg.pop("schedule", None)
    app = create_app(cfg)
    return app, TestClient(app)


def wait(c):
    for _ in range(60):
        if not c.get("/scan/status").json()["running"]:
            return
        time.sleep(0.05)


def test_top_bar_update_buttons(client, monkeypatch):
    app, c = client
    monkeypatch.delenv("DEALFINDER_GITHUB_TOKEN", raising=False)
    page = c.get("/").text
    assert "⬆️ Set up updates · v" in page                    # no key yet -> one-time setup link
    monkeypatch.setenv("DEALFINDER_GITHUB_TOKEN", "tok")
    assert "⬆️ Check for updates · v" in c.get("/").text
    monkeypatch.setattr(up, "check", lambda repo: {"available": False, "latest": "x-1", "changes": []})
    r = c.post("/updates/check", data={"back": "/areas"}, follow_redirects=False)
    assert r.headers["location"] == "/areas"                  # stays on the page you were on
    assert "up to date" in c.get("/areas").text
    assert "up to date" not in c.get("/areas").text           # message shows once
    monkeypatch.setattr(up, "check", lambda repo: {"available": True, "latest": "abc1234-20300101000000",
                                                   "sha": "abc1234", "changes": ["x"], "date": "", "current": ""})
    page = c.post("/updates/check", data={"back": "/"}).text   # lands back on the main page
    assert "Version abc1234 is ready" in page and "⬆️ Update now" in page
    def boom(repo):
        raise up.UpdateError("GitHub says the access key isn't valid.")
    monkeypatch.setattr(up, "check", boom)
    assert "access key isn" in c.post("/updates/check", data={"back": "/"}).text


def test_daily_check_panel(client, monkeypatch):
    app, c = client
    page = c.get("/").text
    assert ">OFF<" in page and "Turn on" in page and "nothing is checked automatically" in page
    c.post("/daily/toggle")
    assert app.state.settings["cfg"]["schedule"]["enabled"] is True
    page = c.get("/").text
    assert ">ON<" in page and "Turn off" in page and "Every day at 07:30" in page
    import yaml
    assert yaml.safe_load((config.HOME / "config.yaml").read_text())["schedule"]["enabled"] is True   # saved
    c.post("/daily/toggle")
    assert app.state.settings["cfg"]["schedule"]["enabled"] is False
    ran = []
    import dealfinder.pipeline as pipeline
    monkeypatch.setattr(pipeline.Scanner, "__init__", lambda self, cfg, db=None, **kw: None)
    monkeypatch.setattr(pipeline.Scanner, "daily_check", lambda self: ran.append(1) or {"new_matches": 0})
    c.post("/daily/run")
    wait(c)
    assert ran == [1]


def test_stop_wording(client):
    _, c = client
    page = c.get("/").text
    assert "Daily scans pause" not in page and "stops running in the background" in page


def test_connect_claude_desktop_keeps_other_settings(tmp_path, monkeypatch, client):
    from dealfinder.claude_connector import claude_desktop_status, connect_claude_desktop
    home = tmp_path / "mac-home"
    cfgp = home / "Library/Application Support/Claude/claude_desktop_config.json"
    assert claude_desktop_status(home) == {"installed": False, "connected": False}
    cfgp.parent.mkdir(parents=True)
    cfgp.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
    out = connect_claude_desktop(home)
    data = json.loads(cfgp.read_text())
    assert data["theme"] == "dark" and data["mcpServers"]["other"] == {"command": "x"}
    assert data["mcpServers"]["deal-finder"]["command"] == "/bin/bash"
    script = open(data["mcpServers"]["deal-finder"]["args"][0]).read()
    assert "dealfinder.claude_connector" in script and "app-current" in script
    assert (cfgp.parent / "claude_desktop_config.json.before-deal-finder").exists()
    assert claude_desktop_status(home) == {"installed": True, "connected": True}
    connect_claude_desktop(home)                                 # reconnecting is harmless
    assert list(json.loads(cfgp.read_text())["mcpServers"]) == ["other", "deal-finder"]
    cfgp.write_text("{not json")
    with pytest.raises(ValueError, match="isn't valid JSON"):
        connect_claude_desktop(home)
    assert cfgp.read_text() == "{not json"                       # left untouched


def test_condition_report_on_property_page(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(config, "HOME", tmp_path)
    from tests.test_pipeline import scanner
    scanner(cfg, 125000).run()
    app = create_app(cfg)
    c = TestClient(app)
    page = c.get("/deal/rightmove:1").text
    assert "📷 Condition report" in page and "analysePhotos('https://www.rightmove.co.uk/properties/1')" in page
    from dealfinder.claude_connector import save_report
    monkeypatch.setattr("dealfinder.claude_connector.load_config", lambda: cfg)
    assert save_report("https://www.rightmove.co.uk/properties/1", "Kitchen: Poor (photo 3).", 9000, 16000) == "rightmove:1"
    page = c.get("/deal/rightmove:1").text
    assert "Refurb estimate: £9,000–£16,000" in page and "Kitchen: Poor (photo 3)." in page
    assert "/deal/rightmove:1/post?refurb=12500" in page


def test_settings_save_after_turning_daily_on_from_main_page(client):
    """Regression: turning the daily check on before ever saving a time left the time box empty and
    then 'Save settings' refused everything."""
    app, c = client
    c.post("/daily/toggle")
    page = c.get("/settings").text
    assert 'name="daily_at" value="07:30"' in page
    r = c.post("/settings", data={"marketing_contact": "Me", "daily_enabled": "on"}, follow_redirects=False)
    assert "saved=1" in r.headers["location"]                    # no daily_at sent at all: still saves
    r = c.post("/settings", data={"daily_at": "", "daily_enabled": "on"}, follow_redirects=False)
    assert "saved=1" in r.headers["location"]
    assert app.state.settings["cfg"]["schedule"]["daily_at"] == "07:30"
    r = c.post("/settings", data={"daily_at": "soon"}, follow_redirects=False)
    assert "errors=" in r.headers["location"]                     # a wrong time is still reported
