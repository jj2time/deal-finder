from dealfinder.models import Comparable


def comps(n, price, ptype="terraced", distance=300, date="2026-03-01", postcode="BS5 6AA", start=1):
    return [Comparable(price=price + i * 1000, date=date, address=f"{start + i} Test Street, Bristol",
                       postcode=postcode, property_type=ptype, distance_m=distance) for i in range(n)]
