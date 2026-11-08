from dealfinder.data.landregistry import parse_results
from dealfinder.sources.apify import map_item
from dealfinder.sources.csv_import import read_csv
from dealfinder.sources.email_alerts import parse_alert_email


def test_apify_rightmove_style_item():
    item = {"id": 1234567, "url": "https://www.rightmove.co.uk/properties/1234567",
            "displayAddress": "Rose Street, Bristol, BS5 6AA", "price": {"amount": 135000},
            "propertySubType": "Terraced", "bedrooms": 3, "summary": "Cash buyers only",
            "location": {"latitude": 51.46, "longitude": -2.56}}
    l = map_item(item)
    assert l.source == "rightmove" and l.source_id == "1234567"
    assert l.price == 135000 and l.property_type == "terraced" and l.bedrooms == 3
    assert l.postcode == "BS5 6AA" and l.outcode == "BS5" and l.lat == 51.46


def test_apify_zoopla_style_item():
    item = {"listingId": "998", "listingUrl": "https://www.zoopla.co.uk/for-sale/details/998/",
            "address": "Flat 2, High Road, Manchester M14", "price": "£95,000", "propertyType": "Flat",
            "numBedrooms": "2", "description": "Leasehold, 70 years remaining"}
    l = map_item(item)
    assert l.source == "zoopla" and l.price == 95000 and l.property_type == "flat" and l.bedrooms == 2
    assert l.postcode is None and l.outcode == "M14"


def test_alert_email_parsing():
    html = """
    <table><tr><td><a href="https://www.rightmove.co.uk/properties/111?utm=x">View</a></td>
    <td>£120,000</td><td>3 bedroom terraced house</td><td>Park Road, Bristol, BS5 7XY</td></tr>
    <tr><td><a href="https://www.rightmove.co.uk/properties/222">View</a></td>
    <td>£89,950</td><td>2 bed flat</td><td>Queens Road, Liverpool, L4</td></tr></table>"""
    ls = {l.source_id: l for l in parse_alert_email(html)}
    assert set(ls) == {"111", "222"}
    assert ls["111"].price == 120000 and ls["111"].bedrooms == 3 and ls["111"].postcode == "BS5 7XY"
    assert ls["222"].price == 89950 and ls["222"].property_type == "flat"


def test_csv_import(tmp_path):
    p = tmp_path / "auction.csv"
    p.write_text("Address,Postcode,Price,Bedrooms,Property_Type,Description,Auction\n"
                 "1 Mill Lane,L4 1AB,\"55,000\",2,Terraced,Repossession,yes\n")
    [l] = read_csv(p)
    assert l.price == 55000 and l.postcode == "L4 1AB" and l.is_auction and l.property_type == "terraced"


def test_land_registry_parse():
    body = {"results": {"bindings": [{
        "postcode": {"value": "BS5 6AA"}, "paon": {"value": "12"}, "street": {"value": "TEST STREET"},
        "town": {"value": "BRISTOL"}, "amount": {"value": "150000"}, "date": {"value": "2025-04-01"},
        "ptype": {"value": "http://landregistry.data.gov.uk/def/common/terraced"},
        "category": {"value": "http://landregistry.data.gov.uk/def/ppi/additionalPricePaidTransaction"}}]}}
    [c] = parse_results(body, {"BS5 6AA": 120.0})
    assert c.price == 150000 and c.property_type == "terraced" and c.address == "12, Test Street, Bristol"
    assert c.distance_m == 120.0 and c.category == "additional"
