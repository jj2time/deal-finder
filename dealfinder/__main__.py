"""Command line:
  python -m dealfinder scan          run every saved search once
  python -m dealfinder serve         dashboard at http://127.0.0.1:8000
  python -m dealfinder run           dashboard + daily scan on the schedule in config.yaml
"""
from __future__ import annotations

import argparse
import logging

from .config import load_config


def main() -> None:
    p = argparse.ArgumentParser(prog="dealfinder")
    p.add_argument("command", choices=["scan", "serve", "run"])
    p.add_argument("--config", default=None)
    p.add_argument("--port", type=int, default=8000)
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
        from apscheduler.schedulers.background import BackgroundScheduler
        from .pipeline import Scanner
        hh, mm = str(cfg.get("schedule", {}).get("daily_at", "07:30")).split(":")
        sched = BackgroundScheduler()
        sched.add_job(lambda: Scanner(cfg).run(), "cron", hour=int(hh), minute=int(mm))
        sched.start()
        logging.info("Daily scan scheduled at %s:%s", hh, mm)
    print(f"Dashboard: http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
