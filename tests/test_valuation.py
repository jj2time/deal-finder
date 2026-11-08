from datetime import date

from dealfinder.analysis.valuation import value_from_comps
from tests.helpers import comps

TODAY = date(2026, 11, 1)


def test_median_within_first_radius():
    v = value_from_comps(comps(9, 150000), "terraced", [400, 800, 2000], 8, 24, today=TODAY)
    assert v.value == 154000 and v.radius_m == 400 and v.count == 9 and v.confidence == 1.0


def test_widens_radius_until_enough_sales():
    pool = comps(3, 150000, distance=300) + comps(6, 170000, distance=1500)
    v = value_from_comps(pool, "terraced", [400, 800, 2000], 8, 24, today=TODAY)
    assert v.radius_m == 2000 and v.count == 9


def test_ignores_other_types_and_old_sales():
    pool = comps(8, 150000) + comps(8, 400000, ptype="detached") + comps(8, 10000, date="2020-01-01")
    v = value_from_comps(pool, "terraced", [400], 8, 24, today=TODAY)
    assert v.count == 8 and v.value == 153500


def test_no_comps():
    v = value_from_comps([], "flat", [400], 8, 24, today=TODAY)
    assert v.value is None and v.confidence == 0
