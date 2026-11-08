"""Reads Rightmove / Zoopla / OnTheMarket alert emails from a mailbox you own (IMAP)."""
from __future__ import annotations

import email
import html
import imaplib
import logging
import re
from datetime import date, timedelta
from email.message import Message
from typing import Iterable

from ..config import env
from ..data.postcodes import find_outcode, find_postcode
from ..models import Listing
from .base import normalise_type, parse_int, parse_price

log = logging.getLogger(__name__)

LINK_PATTERNS = [
    ("rightmove", re.compile(r"https?://(?:www\.)?rightmove\.co\.uk/properties/(\d+)")),
    ("zoopla", re.compile(r"https?://(?:www\.)?zoopla\.co\.uk/for-sale/details/(\d+)")),
    ("onthemarket", re.compile(r"https?://(?:www\.)?onthemarket\.com/details/(\d+)")),
]
SENDERS = ("rightmove", "zoopla", "onthemarket")


def _body(msg: Message) -> str:
    parts = []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        ctype = part.get_content_type()
        if ctype in ("text/html", "text/plain"):
            payload = part.get_payload(decode=True) or b""
            parts.append(payload.decode(part.get_content_charset() or "utf-8", "replace"))
    return "\n".join(parts)


def _text(fragment: str) -> str:
    fragment = re.sub(r"<(script|style).*?</\1>", " ", fragment, flags=re.S | re.I)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(fragment)).strip()


def parse_alert_email(raw_html: str) -> list[Listing]:
    """Each listing link plus the text around it (price, beds, address)."""
    found: dict[str, Listing] = {}
    # First occurrence of each listing link, in document order. A listing's details are the text
    # from its link up to the next listing's link.
    firsts: list[tuple[int, str, str, str]] = []
    seen: set[str] = set()
    for source, pattern in LINK_PATTERNS:
        for m in pattern.finditer(raw_html):
            k = f"{source}:{m.group(1)}"
            if k not in seen:
                seen.add(k)
                firsts.append((m.start(), source, m.group(1), m.group(0)))
    firsts.sort()
    for i, (start, source, sid, url) in enumerate(firsts):
        end = firsts[i + 1][0] if i + 1 < len(firsts) else start + 3000
        chunk = _text(raw_html[start:end])
        price = parse_price(chunk)
        beds = re.search(r"(\d+)\s*(?:bed|bedroom)", chunk, re.I)
        addr = None
        am = re.search(r"([A-Za-z0-9][0-9A-Za-z '\-]*,\s*[A-Za-z ]+,\s*[A-Z]{1,2}\d[A-Z\d]?(?:\s*\d[A-Z]{2})?)\b", chunk)
        if am:
            addr = am.group(1).strip(" ,")
        found[f"{source}:{sid}"] = Listing(
            source=source, source_id=sid, url=url, address=addr,
            postcode=find_postcode(addr or ""), outcode=find_outcode(addr or "") if addr else None,
            price=price, bedrooms=parse_int(beds.group(1)) if beds else None,
            property_type=normalise_type(None, chunk), description=chunk[:600],
            is_auction="auction" in chunk.lower(),
        )
    return list(found.values())


class EmailAlertSource:
    name = "email_alerts"

    def __init__(self, cfg: dict, http=None):
        self.folder = cfg.get("folder", "INBOX")
        self.days_back = int(cfg.get("days_back", 3))

    def fetch(self) -> Iterable[Listing]:
        host, user, pw = env("ALERTS_IMAP_HOST"), env("ALERTS_IMAP_USER"), env("ALERTS_IMAP_PASSWORD")
        if not (host and user and pw):
            log.warning("ALERTS_IMAP_* not set in .env — skipping email alerts.")
            return []
        since = (date.today() - timedelta(days=self.days_back)).strftime("%d-%b-%Y")
        out: list[Listing] = []
        with imaplib.IMAP4_SSL(host) as imap:
            imap.login(user, pw)
            imap.select(self.folder, readonly=True)
            for sender in SENDERS:
                _, data = imap.search(None, f'(SINCE {since} FROM "{sender}")')
                for num in (data[0] or b"").split():
                    _, msg_data = imap.fetch(num, "(RFC822)")
                    msg = email.message_from_bytes(msg_data[0][1])
                    out.extend(parse_alert_email(_body(msg)))
        log.info("Email alerts: %d listings", len(out))
        return out
