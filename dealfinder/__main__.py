"""Command line (the Mac app does all of this for you):
  python -m dealfinder scan          run every saved search once
  python -m dealfinder serve         dashboard at http://127.0.0.1:8000
  python -m dealfinder run           dashboard + daily scan at the time set in Settings
"""
from __future__ import annotations

import argparse
import logging
import threading
import webbrowser
from datetime import datetime

from .config import load_config


def start_daily_scans(app) -> None:
    """Checks once a minute; runs the scan when the clock reaches the time set in Settings."""
    from apscheduler.schedulers.background import BackgroundScheduler

    from .pipeline import Scanner
    last_run = {"date": None}

    def tick():
        cfg = app.state.settings["cfg"]
        target = str((cfg.get("schedule") or {}).get("daily_at", "07:30")).zfill(5)
        now = datetime.now()
        if now.strftime("%H:%M") == target and last_run["date"] != now.date():
            last_run["date"] = now.date()
            logging.info("Daily scan starting")
            try:
                Scanner(cfg).run()
            except Exception:
                logging.exception("Daily scan failed")

    sched = BackgroundScheduler()
    sched.add_job(tick, "interval", minutes=1, max_instances=1)
    sched.start()


def main() -> None:
    p = argparse.ArgumentParser(prog="dealfinder")
    p.add_argument("command", choices=["scan", "serve", "run"])
    p.add_argument("--config", default=None)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--open", action="store_true", help="open the dashboard in the browser")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(args.config)

    if args.command == "scan":
        from .pipeline import Scanner
        print(Scanner(cfg).run())
        return

    import uvicorn

    from .web.app import create_app
    app = create_app(cfg)
    if args.command == "run":
        start_daily_scans(app)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Dashboard: {url}")
    if args.open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
