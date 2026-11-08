"""Loads config.yaml and .env."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    path = Path(path) if path else ROOT / "config.yaml"
    if not path.exists():
        path = ROOT / "config.example.yaml"
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    db = Path(cfg.get("database", "data/dealfinder.sqlite3"))
    cfg["database"] = str(db if db.is_absolute() else ROOT / db)
    return cfg


def env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None
