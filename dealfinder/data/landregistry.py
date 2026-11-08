"""HM Land Registry Price Paid Data via the public SPARQL endpoint (no key).

Contains HM Land Registry data © Crown copyright and database right. Licensed under the
Open Government Licence v3.0.
"""
from __future__ import annotations

from datetime import date, timedelta

from ..models import Comparable

ENDPOINT = "https://landregistry.data.gov.uk/landregistry/query"

TYPE_MAP = {
    "detached": "detached",
    "semi-detached": "semi-detached",
    "terraced": "terraced",
    "flat-maisonette": "flat",
    "otherPropertyType": "other",
}

QUERY = """
PREFIX lrppi: <http://landregistry.data.gov.uk/def/ppi/>
PREFIX lrcommon: <http://landregistry.data.gov.uk/def/common/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?postcode ?paon ?saon ?street ?town ?amount ?date ?ptype ?category WHERE {
  VALUES ?postcode { %s }
  ?addr lrcommon:postcode ?postcode .
  ?tx lrppi:propertyAddress ?addr ;
      lrppi:pricePaid ?amount ;
      lrppi:transactionDate ?date ;
      lrppi:propertyType ?ptype .
  OPTIONAL { ?tx lrppi:transactionCategory ?category }
  OPTIONAL { ?addr lrcommon:paon ?paon }
  OPTIONAL { ?addr lrcommon:saon ?saon }
  OPTIONAL { ?addr lrcommon:street ?street }
  OPTIONAL { ?addr lrcommon:town ?town }
  FILTER (?date >= "%s"^^xsd:date)
}
"""


def _last(uri: str) -> str:
    return uri.rstrip("/").rsplit("/", 1)[-1]


def parse_results(body: dict, distances: dict[str, float] | None = None) -> list[Comparable]:
    distances = distances or {}
    out = []
    for b in body.get("results", {}).get("bindings", []):
        v = {k: x["value"] for k, x in b.items()}
        parts = [v.get("saon"), v.get("paon"), v.get("street"), v.get("town")]
        pc = v.get("postcode", "")
        cat = _last(v["category"]) if v.get("category") else None
        out.append(Comparable(
            price=int(float(v["amount"])),
            date=v["date"][:10],
            address=", ".join(p.title() for p in parts if p),
            postcode=pc,
            property_type=TYPE_MAP.get(_last(v.get("ptype", "")), "other"),
            distance_m=distances.get(pc),
            category={"standardPricePaidTransaction": "standard",
                      "additionalPricePaidTransaction": "additional"}.get(cat, cat),
        ))
    return out


class LandRegistry:
    def __init__(self, http):
        self.http = http

    def sold_prices(self, postcodes_with_distance: list[tuple[str, float]], months_back: int = 24,
                    today: date | None = None) -> list[Comparable]:
        if not postcodes_with_distance:
            return []
        today = today or date.today()
        since = (today - timedelta(days=int(months_back * 30.44) + 400)).isoformat()  # extra year for sales history
        distances = {pc: d for pc, d in postcodes_with_distance}
        comps: list[Comparable] = []
        pcs = sorted(distances)
        for i in range(0, len(pcs), 50):
            chunk = pcs[i:i + 50]
            values = " ".join(f'"{pc}"^^xsd:string' for pc in chunk)
            body = self.http.request_json(
                "POST", ENDPOINT, data={"query": QUERY % (values, since)},
                headers={"Accept": "application/sparql-results+json"}, timeout=120)
            comps.extend(parse_results(body, distances))
        return comps
