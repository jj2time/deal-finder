"""Loads and saves settings (config.yaml) and keys (.env).

They live in DEALFINDER_HOME when set (the Mac app uses ~/Library/Application Support/Deal Finder),
otherwise in the project folder.
"""
from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("DEALFINDER_HOME") or ROOT)

ENV_KEYS = [
    "APIFY_TOKEN", "PROPERTYDATA_API_KEY",
    "ALERTS_IMAP_HOST", "ALERTS_IMAP_USER", "ALERTS_IMAP_PASSWORD",
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "DEALFINDER_GITHUB_TOKEN",
]
SECRET_KEYS = {"APIFY_TOKEN", "PROPERTYDATA_API_KEY", "ALERTS_IMAP_PASSWORD", "SMTP_PASSWORD", "DEALFINDER_GITHUB_TOKEN"}


def home_path(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else HOME / p


def config_path() -> Path:
    return HOME / "config.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    HOME.mkdir(parents=True, exist_ok=True)
    load_dotenv(HOME / ".env", override=True)
    path = Path(path) if path else config_path()
    if not path.exists():
        shutil.copy(ROOT / "config.example.yaml", path)
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    cfg["_database_setting"] = cfg.get("database", "data/dealfinder.sqlite3")
    cfg["database"] = str(home_path(cfg["_database_setting"]))
    return cfg


def save_config(cfg: dict[str, Any], path: str | Path | None = None) -> None:
    out = copy.deepcopy(cfg)
    out["database"] = out.pop("_database_setting", "data/dealfinder.sqlite3")
    path = Path(path) if path else config_path()
    with open(path, "w") as f:
        yaml.safe_dump(out, f, sort_keys=False, allow_unicode=True)


def read_env() -> dict[str, str]:
    path = HOME / ".env"
    return {k: v or "" for k, v in dotenv_values(path).items()} if path.exists() else {}


def save_env(values: dict[str, str]) -> None:
    """Writes .env and applies the values to this running process."""
    current = read_env()
    current.update({k: v.strip() for k, v in values.items()})
    lines = ["# Deal Finder keys. Edited from the Settings page; never share this file."]
    for k in ENV_KEYS + [k for k in current if k not in ENV_KEYS]:
        v = current.get(k, "")
        lines.append(f'{k}="{v}"' if v else f"{k}=")
        os.environ[k] = v
    path = HOME / ".env"
    path.write_text("\n".join(lines) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None
