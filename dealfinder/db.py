"""SQLite storage: listings, price history (for drops and days on market) and analyses."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Analysis, Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
  key TEXT PRIMARY KEY, source TEXT, url TEXT, address TEXT, postcode TEXT, outcode TEXT,
  price INTEGER, property_type TEXT, bedrooms INTEGER, data TEXT,
  first_seen TEXT, last_seen TEXT, active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS price_history (key TEXT, price INTEGER, seen_at TEXT);
CREATE TABLE IF NOT EXISTS analyses (key TEXT PRIMARY KEY, score INTEGER, data TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS alerts_sent (key TEXT PRIMARY KEY, sent_at TEXT);
CREATE INDEX IF NOT EXISTS idx_ph_key ON price_history(key);
CREATE TABLE IF NOT EXISTS searches (
  fetch_key TEXT PRIMARY KEY, search TEXT, last_fetched TEXT, last_count INTEGER, saved INTEGER DEFAULT 0
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def upsert_listing(self, l: Listing) -> dict[str, Any]:
        """Returns {'new': bool, 'price_drop': int|None, 'reductions': int, 'first_seen': str}."""
        ts = now()
        row = self.conn.execute("SELECT price, first_seen FROM listings WHERE key=?", (l.key,)).fetchone()
        result = {"new": row is None, "price_drop": None, "first_seen": row["first_seen"] if row else ts}
        if row and row["price"] and l.price and l.price < row["price"]:
            result["price_drop"] = row["price"] - l.price
        if row is None:
            self.conn.execute(
                "INSERT INTO listings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)",
                (l.key, l.source, l.url, l.address, l.postcode, l.outcode, l.price, l.property_type,
                 l.bedrooms, json.dumps(l.to_dict(), default=str), ts, ts))
        else:
            self.conn.execute(
                "UPDATE listings SET url=?, address=?, postcode=?, outcode=?, price=?, property_type=?, "
                "bedrooms=?, data=?, last_seen=?, active=1 WHERE key=?",
                (l.url, l.address, l.postcode, l.outcode, l.price, l.property_type, l.bedrooms,
                 json.dumps(l.to_dict(), default=str), ts, l.key))
        last = self.conn.execute(
            "SELECT price FROM price_history WHERE key=? ORDER BY rowid DESC LIMIT 1", (l.key,)).fetchone()
        if l.price and (last is None or last["price"] != l.price):
            self.conn.execute("INSERT INTO price_history VALUES (?,?,?)", (l.key, l.price, ts))
        result["reductions"] = self.reductions(l.key)
        self.conn.commit()
        return result

    def reductions(self, key: str) -> int:
        prices = [r["price"] for r in self.conn.execute(
            "SELECT price FROM price_history WHERE key=? ORDER BY rowid", (key,))]
        return sum(1 for a, b in zip(prices, prices[1:]) if b < a)

    def price_history(self, key: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT price, seen_at FROM price_history WHERE key=? ORDER BY rowid", (key,))]

    def save_analysis(self, a: Analysis) -> None:
        self.conn.execute("INSERT OR REPLACE INTO analyses VALUES (?,?,?,?)",
                          (a.key, a.score, json.dumps(a.to_dict(), default=str), now()))
        self.conn.commit()

    def results(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT l.data AS ldata, l.first_seen, l.last_seen, a.data AS adata, a.score "
            "FROM listings l JOIN analyses a ON a.key = l.key WHERE l.active=1 ORDER BY a.score DESC").fetchall()
        out = []
        for r in rows:
            item = {"listing": json.loads(r["ldata"]), "analysis": json.loads(r["adata"]),
                    "first_seen": r["first_seen"], "last_seen": r["last_seen"]}
            out.append(item)
        return out

    def result(self, key: str) -> dict[str, Any] | None:
        r = self.conn.execute(
            "SELECT l.data AS ldata, l.first_seen, l.last_seen, a.data AS adata FROM listings l "
            "JOIN analyses a ON a.key = l.key WHERE l.key=?", (key,)).fetchone()
        if not r:
            return None
        return {"listing": json.loads(r["ldata"]), "analysis": json.loads(r["adata"]),
                "first_seen": r["first_seen"], "last_seen": r["last_seen"],
                "price_history": self.price_history(key)}

    def mark_alerted(self, key: str) -> bool:
        cur = self.conn.execute("INSERT OR IGNORE INTO alerts_sent VALUES (?,?)", (key, now()))
        self.conn.commit()
        return cur.rowcount == 1

    # ---- area searches ----
    def mark_fetched(self, fetch_key: str, search: dict, count: int) -> None:
        self.conn.execute(
            "INSERT INTO searches (fetch_key, search, last_fetched, last_count) VALUES (?,?,?,?) "
            "ON CONFLICT(fetch_key) DO UPDATE SET search=excluded.search, last_fetched=excluded.last_fetched, "
            "last_count=excluded.last_count", (fetch_key, json.dumps(search), now(), count))
        self.conn.commit()

    def last_fetched(self, fetch_key: str) -> str | None:
        row = self.conn.execute("SELECT last_fetched FROM searches WHERE fetch_key=?", (fetch_key,)).fetchone()
        return row["last_fetched"] if row else None

    def set_saved(self, fetch_key: str, search: dict, saved: bool) -> None:
        self.conn.execute(
            "INSERT INTO searches (fetch_key, search, saved) VALUES (?,?,?) "
            "ON CONFLICT(fetch_key) DO UPDATE SET search=excluded.search, saved=excluded.saved",
            (fetch_key, json.dumps(search), int(saved)))
        self.conn.commit()

    def saved_searches(self) -> list[dict]:
        return [{**json.loads(r["search"]), "_fetch_key": r["fetch_key"], "_last_fetched": r["last_fetched"]}
                for r in self.conn.execute("SELECT * FROM searches WHERE saved=1 ORDER BY fetch_key")]

    def recent_searches(self, limit: int = 12) -> list[dict]:
        """Saved searches first, then the most recently run ones."""
        rows = self.conn.execute(
            "SELECT * FROM searches WHERE saved=1 OR last_fetched IS NOT NULL "
            "ORDER BY saved DESC, last_fetched DESC LIMIT ?", (limit,)).fetchall()
        return [{**json.loads(r["search"]), "_saved": bool(r["saved"]), "_last_fetched": r["last_fetched"],
                 "_count": r["last_count"]} for r in rows]

    def is_saved(self, fetch_key: str) -> bool:
        row = self.conn.execute("SELECT saved FROM searches WHERE fetch_key=?", (fetch_key,)).fetchone()
        return bool(row and row["saved"])
