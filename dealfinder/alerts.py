"""Email alert for a high-scoring deal (SMTP details in .env)."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .config import env

log = logging.getLogger(__name__)


def send_deal_alert(to: str, listing, a) -> bool:
    host, user, pw = env("SMTP_HOST"), env("SMTP_USER"), env("SMTP_PASSWORD")
    if not (host and user and pw):
        log.warning("SMTP_* not set in .env — alert for %s not sent.", listing.address)
        return False
    msg = EmailMessage()
    msg["Subject"] = f"Deal {a.score}/100: {listing.address} £{listing.price:,}" if listing.price else \
        f"Deal {a.score}/100: {listing.address}"
    msg["From"], msg["To"] = user, to
    lines = [f"{listing.address}", f"Asking: £{listing.price:,}" if listing.price else "Asking: n/a"]
    if a.market_value:
        lines.append(f"Market value: £{a.market_value:,} ({a.bmv_pct}% BMV, {a.valuation_comps} sales)")
    if a.gross_yield_pct is not None:
        lines.append(f"Yield {a.gross_yield_pct}%, cashflow £{a.monthly_cashflow}/month")
    lines += [f"- {s.name}: {s.reason}" for s in a.strategies]
    lines.append(listing.url or "")
    msg.set_content("\n".join(lines))
    try:
        with smtplib.SMTP(host, int(env("SMTP_PORT") or 587)) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
        return True
    except Exception as e:
        log.error("Alert email failed: %s", e)
        return False
