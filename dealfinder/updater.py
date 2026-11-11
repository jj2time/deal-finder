"""In-app updates from the GitHub repository.

Downloads the newest version of the code with a read-only GitHub token, unpacks it next to the person's
data (DEALFINDER_HOME/app-updates) and points DEALFINDER_HOME/app-current at it. The Mac launcher runs
that copy when it's newer than the one inside the app, then restarts. Files the app downloads itself
aren't marked by macOS as "downloaded from the internet", so there's no security prompt.
"""
from __future__ import annotations

import io
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from .config import HOME, ROOT, env

# The address can be overridden only for testing the update flow end to end.
API = os.environ.get("DEALFINDER_UPDATE_API", "https://api.github.com/repos/{repo}")
DEFAULT_REPO = "jj2time/deal-finder"


class UpdateError(Exception):
    pass


def current_version() -> str:
    v = ROOT / "VERSION"
    return v.read_text().strip() if v.exists() else "dev"


def version_parts(version: str) -> tuple[str, str]:
    """'e0870e1-20261111150009' -> ('e0870e1', '20261111150009')."""
    sha, _, stamp = version.partition("-")
    return sha, stamp


def _client(token: str, client: httpx.Client | None) -> httpx.Client:
    return client or httpx.Client(timeout=120, follow_redirects=True, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "dealfinder-updater"})


def _get(c: httpx.Client, url: str) -> httpx.Response:
    try:
        r = c.get(url)
    except httpx.HTTPError as e:
        raise UpdateError(f"Couldn't reach GitHub ({e.__class__.__name__}). Check your internet connection.") from e
    if r.status_code == 401:
        raise UpdateError("GitHub says the access key isn't valid. Create a new one and paste it in Settings.")
    if r.status_code in (403, 404):
        raise UpdateError("GitHub won't let this key read the repository. Make sure the key has access to "
                          "deal-finder with Contents: Read-only.")
    if r.status_code >= 400:
        raise UpdateError(f"GitHub answered with error {r.status_code}.")
    return r


def check(repo: str = DEFAULT_REPO, token: str | None = None, client: httpx.Client | None = None) -> dict[str, Any]:
    """What's on GitHub compared with what's running."""
    token = token or env("GITHUB_TOKEN")
    if not token:
        raise UpdateError("Add a GitHub access key in Settings first.")
    c = _client(token, client)
    head = _get(c, API.format(repo=repo) + "/commits/main").json()
    sha = head["sha"]
    when = datetime.strptime(head["commit"]["committer"]["date"], "%Y-%m-%dT%H:%M:%SZ")
    latest = f"{sha[:7]}-{when:%Y%m%d%H%M%S}"
    cur_sha, cur_stamp = version_parts(current_version())
    available = not sha.startswith(cur_sha) and when.strftime("%Y%m%d%H%M%S") > cur_stamp[:14]
    changes: list[str] = []
    if available and cur_sha and cur_sha != "dev":
        try:
            cmp = _get(c, API.format(repo=repo) + f"/compare/{cur_sha}...{sha}").json()
            changes = [cm["commit"]["message"].split("\n")[0] for cm in cmp.get("commits", [])][::-1][:15]
        except UpdateError:
            changes = []
    if available and not changes:
        changes = [head["commit"]["message"].split("\n")[0]]
    return {"available": available, "latest": latest, "sha": sha, "current": current_version(),
            "date": when.strftime("%d %b %Y %H:%M"), "changes": changes}


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> Path:
    dest = dest.resolve()
    for name in zf.namelist():
        target = (dest / name).resolve()
        if not str(target).startswith(str(dest) + os.sep) and target != dest:
            raise UpdateError("The download looked wrong (unsafe file paths); nothing was installed.")
    zf.extractall(dest)
    tops = {n.split("/")[0] for n in zf.namelist() if n.strip("/")}
    if len(tops) != 1:
        raise UpdateError("The download looked wrong; nothing was installed.")
    return dest / tops.pop()


def install(info: dict, repo: str = DEFAULT_REPO, token: str | None = None, client: httpx.Client | None = None,
            home: Path | None = None) -> Path:
    """Downloads info['sha'] and makes it the current copy. Returns its folder."""
    token = token or env("GITHUB_TOKEN")
    if not token:
        raise UpdateError("Add a GitHub access key in Settings first.")
    home = home or HOME
    c = _client(token, client)
    data = _get(c, API.format(repo=repo) + f"/zipball/{info['sha']}").content
    updates = home / "app-updates"
    updates.mkdir(parents=True, exist_ok=True)
    work = updates / f".download-{info['sha'][:7]}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            top = _safe_extract(zf, work)
    except zipfile.BadZipFile as e:
        shutil.rmtree(work, ignore_errors=True)
        raise UpdateError("The download from GitHub was incomplete; nothing was installed. Try again.") from e
    for needed in ("dealfinder/__init__.py", "dealfinder/web/app.py", "requirements.txt", "config.example.yaml"):
        if not (top / needed).exists():
            shutil.rmtree(work, ignore_errors=True)
            raise UpdateError("The download didn't contain the app; nothing was installed.")
    (top / "VERSION").write_text(info["latest"] + "\n")
    final = updates / info["latest"]
    shutil.rmtree(final, ignore_errors=True)
    top.rename(final)
    shutil.rmtree(work, ignore_errors=True)
    # Point app-current at the new copy in one step, so a half-finished update is never used.
    link, tmp = home / "app-current", home / ".app-current-new"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(final, target_is_directory=True)
    os.replace(tmp, link)
    # Keep the newest two copies, so going back is possible.
    copies = sorted((p for p in updates.iterdir() if p.is_dir() and not p.name.startswith(".")),
                    key=lambda p: version_parts(p.name)[1], reverse=True)
    for old in copies[2:]:
        shutil.rmtree(old, ignore_errors=True)
    return final


def restart_into_new_version() -> bool:
    """Starts the Mac launcher again (it picks the newest copy) and stops this process. False if not on the
    Mac app, in which case the person restarts it themselves."""
    launcher = os.environ.get("DEALFINDER_LAUNCHER")
    if not launcher or not Path(launcher).exists():
        return False
    import subprocess
    import threading
    import time

    def go():
        time.sleep(1.0)
        envv = {**os.environ, "DEALFINDER_NO_OPEN": "1"}
        subprocess.Popen(["/bin/bash", "-c", f'sleep 1; exec "{launcher}"'], env=envv,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        os._exit(0)
    threading.Thread(target=go, daemon=True).start()
    return True
