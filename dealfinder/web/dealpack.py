"""One-page PDF deal pack."""
from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _money(v):
    return f"£{v:,.0f}" if isinstance(v, (int, float)) else "—"


def build_pdf(item: dict) -> bytes:
    l, a = item["listing"], item["analysis"]
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm)
    ss = getSampleStyleSheet()
    story = [Paragraph(l.get("address") or "Property", ss["Title"]),
             Paragraph(f"Deal score {a['score']}/100 · {l.get('bedrooms') or '?'} bed {l.get('property_type')}",
                       ss["Normal"]), Spacer(1, 6)]
    rows = [
        ["Asking price", _money(l.get("price")), "Market value", _money(a.get("market_value"))],
        ["BMV", f"{a['bmv_pct']}%" if a.get("bmv_pct") is not None else "—", "Comparable sales",
         f"{a['valuation_comps']} within {a.get('valuation_radius_m') or '—'} m"],
        ["Stamp duty", _money(a.get("stamp_duty")), "Rent (pcm)", _money(a.get("rent_pcm"))],
        ["Gross yield", f"{a['gross_yield_pct']}%" if a.get("gross_yield_pct") is not None else "—",
         "Cashflow (pcm)", _money(a.get("monthly_cashflow"))],
        ["Cash in", _money(a.get("cash_in")), "ROI", f"{a['roi_pct']}%" if a.get("roi_pct") is not None else "—"],
        ["Refurb estimate", _money(a.get("refurb_cost")), "Flip profit", _money(a.get("flip_profit"))],
        ["BRRR cash left in", _money(a.get("brrr_cash_left_in")), "Done-up value", _money(a.get("done_up_value"))],
    ]
    t = Table(rows, colWidths=[38 * mm, 42 * mm, 38 * mm, 42 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                           ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                           ("BACKGROUND", (2, 0), (2, -1), colors.whitesmoke),
                           ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    story += [t, Spacer(1, 8), Paragraph("Strategies", ss["Heading2"])]
    for s in a.get("strategies", []) or [{"name": "None flagged", "reason": ""}]:
        story.append(Paragraph(f"<b>{s['name']}</b> — {s['reason']}", ss["Normal"]))
    story += [Spacer(1, 6), Paragraph("Comparable sales (HM Land Registry)", ss["Heading2"])]
    comp_rows = [["Date", "Address", "Type", "Price", "Distance"]] + [
        [c["date"], c["address"][:48], c["property_type"], _money(c["price"]),
         f"{c['distance_m']:.0f} m" if c.get("distance_m") is not None else "—"]
        for c in a.get("comparables", [])[:15]]
    ct = Table(comp_rows, colWidths=[22 * mm, 78 * mm, 24 * mm, 22 * mm, 18 * mm])
    ct.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7.5), ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black)]))
    story += [ct, Spacer(1, 8)]
    for n in a.get("notes", []):
        story.append(Paragraph(f"Note: {n}", ss["Italic"]))
    story += [Spacer(1, 6), Paragraph(f"Listing: {l.get('url') or '—'}", ss["Normal"]), Spacer(1, 10),
              Paragraph("Estimates only — not financial advice. Contains HM Land Registry data © Crown copyright "
                        "and database right. Licensed under the Open Government Licence v3.0.", ss["Italic"])]
    doc.build(story)
    return buf.getvalue()
