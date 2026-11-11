import io
import json
import zipfile

import httpx
import pytest

import dealfinder.updater as up


def repo_zip(sha, files=None, top=None):
    buf = io.BytesIO()
    top = top or f"jj2time-deal-finder-{sha[:7]}"
    files = files if files is not None else {"dealfinder/__init__.py": "", "dealfinder/web/app.py": "",
                                             "requirements.txt": "fastapi\n", "config.example.yaml": "{}\n"}
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(f"{top}/{name}" if not name.startswith("../") else name, text)
    return buf.getvalue()


def github(sha="abcdef1234567890", date="2026-11-12T10:00:00Z", status=200, zipdata=None):
    calls = []

    def handler(req):
        calls.append(str(req.url))
        assert req.headers["authorization"] == "Bearer tok"
        if status != 200:
            return httpx.Response(status)
        if req.url.path.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": sha, "commit": {"message": "Add update button\n\nmore",
                                                                    "committer": {"date": date}}})
        if "/compare/" in req.url.path:
            return httpx.Response(200, json={"commits": [{"commit": {"message": "First change"}},
                                                         {"commit": {"message": "Add update button"}}]})
        if "/zipball/" in req.url.path:
            return httpx.Response(200, content=zipdata if zipdata is not None else repo_zip(sha))
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer tok"}), calls


@pytest.fixture
def running(tmp_path, monkeypatch):
    root = tmp_path / "running"
    root.mkdir()
    (root / "VERSION").write_text("e0870e1-20261111150009\n")
    monkeypatch.setattr(up, "ROOT", root)
    return root


def test_check_finds_newer_version_and_changes(running):
    c, calls = github()
    info = up.check(token="tok", client=c)
    assert info["available"] and info["latest"] == "abcdef1-20261112100000"
    assert info["changes"] == ["Add update button", "First change"]          # newest first
    assert any("/compare/e0870e1...abcdef1234567890" in u for u in calls)


def test_check_up_to_date_and_older(running):
    c, _ = github(sha="e0870e1aaaa")
    assert not up.check(token="tok", client=c)["available"]                   # same version
    c, _ = github(date="2026-11-01T10:00:00Z")
    assert not up.check(token="tok", client=c)["available"]                   # older than what's running


def test_check_errors_are_plain_english(running):
    with pytest.raises(up.UpdateError, match="Add a GitHub access key"):
        up.check(token=None)
    for status, msg in ((401, "isn't valid"), (404, "Contents: Read-only"), (500, "error 500")):
        c, _ = github(status=status)
        with pytest.raises(up.UpdateError, match=msg):
            up.check(token="tok", client=c)


def test_install_switches_current_and_keeps_two(running, tmp_path):
    home = tmp_path / "home"
    for n, (sha, date) in enumerate([("aaaaaaa1", "2026-11-12T10:00:00Z"), ("bbbbbbb2", "2026-11-13T10:00:00Z"),
                                     ("ccccccc3", "2026-11-14T10:00:00Z")]):
        c, _ = github(sha=sha, date=date)
        info = up.check(token="tok", client=c)
        final = up.install(info, token="tok", client=c, home=home)
        assert (home / "app-current").resolve() == final.resolve()
        assert (home / "app-current" / "VERSION").read_text().strip() == info["latest"]
        assert (home / "app-current" / "dealfinder" / "__init__.py").exists()
    kept = sorted(p.name for p in (home / "app-updates").iterdir())
    assert kept == ["bbbbbbb-20261113100000", "ccccccc-20261114100000"]


def test_install_refuses_broken_or_unsafe_downloads(running, tmp_path):
    home = tmp_path / "home"
    c, _ = github()
    info = up.check(token="tok", client=c)
    for bad, msg in ((b"not a zip", "incomplete"), (repo_zip("x", {"README.md": "hi"}), "didn't contain"),
                     (repo_zip("x", {"../evil.txt": "x"}), "unsafe")):
        c, _ = github(zipdata=bad)
        with pytest.raises(up.UpdateError, match=msg):
            up.install(info, token="tok", client=c, home=home)
        assert not (home / "app-current").exists()                           # nothing switched
    assert not (tmp_path / "evil.txt").exists()


def test_settings_and_routes(tmp_path, monkeypatch, cfg):
    import dealfinder.config as config
    from fastapi.testclient import TestClient
    from dealfinder.web.app import create_app
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    app = create_app(cfg)
    client = TestClient(app)
    page = client.get("/settings").text
    assert "⬆️ Updates" in page and "Fine-grained tokens" in page and "Check for updates" not in page
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    info = {"available": True, "latest": "abcdef1-20261112100000", "sha": "abcdef1234", "current": "dev",
            "date": "12 Nov 2026 10:00", "changes": ["Add update button"]}
    monkeypatch.setattr(up, "check", lambda repo: info)
    client.post("/settings", data={"env_GITHUB_TOKEN": "tok", "daily_at": "07:30"})
    client.post("/updates/check")
    page = client.get("/settings").text
    assert "Update available: version abcdef1" in page and "Add update button" in page
    assert "⬆️ Update available" in client.get("/").text                      # badge in the top bar
    installed = []
    monkeypatch.setattr(up, "install", lambda i, repo: installed.append(i["latest"]))
    monkeypatch.setattr(up, "restart_into_new_version", lambda: False)
    r = client.post("/updates/install", follow_redirects=False)
    assert r.headers["location"] == "/updating"
    import time
    for _ in range(50):
        if not client.get("/scan/status").json()["running"]:
            break
        time.sleep(0.05)
    assert installed == ["abcdef1-20261112100000"]
    assert "Updating Deal Finder" in client.get("/updating").text
