"""HTTP client with a 24-hour SQLite cache and polite pacing."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx

CACHE_SECONDS = 24 * 3600
USER_AGENT = "dealfinder/1.0 (personal property research tool)"


class CachedClient:
    def __init__(self, cache_path: str, min_interval: float = 0.3):
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(cache_path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS http_cache (k TEXT PRIMARY KEY, body TEXT, ts REAL)")
        self.client = httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT})
        self.min_interval = min_interval
        self._last = 0.0

    def _key(self, method: str, url: str, params: Any, data: Any) -> str:
        raw = json.dumps([method, url, params, data], sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def request_json(self, method: str, url: str, *, params: dict | None = None, data: Any = None,
                     json_body: Any = None, headers: dict | None = None, cache: bool = True,
                     timeout: float | None = None) -> Any:
        k = self._key(method, url, params, data if data is not None else json_body)
        if cache:
            row = self.db.execute("SELECT body, ts FROM http_cache WHERE k=?", (k,)).fetchone()
            if row and time.time() - row[1] < CACHE_SECONDS:
                return json.loads(row[0])
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        resp = self.client.request(method, url, params=params, data=data, json=json_body,
                                   headers=headers, timeout=timeout or 60)
        self._last = time.time()
        resp.raise_for_status()
        body = resp.json()
        if cache:
            self.db.execute("INSERT OR REPLACE INTO http_cache VALUES (?,?,?)", (k, json.dumps(body), time.time()))
            self.db.commit()
        return body
