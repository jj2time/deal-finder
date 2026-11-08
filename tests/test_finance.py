from dealfinder.analysis import finance


def test_interest_only_mortgage():
    assert round(finance.monthly_mortgage(75000, 6.0)) == 375


def test_repayment_mortgage():
    assert round(finance.monthly_mortgage(100000, 5.0, interest_only=False, years=25)) == 585


def test_btl_numbers(cfg):
    f = cfg["finance"]  # 5.5% IO, 75% LTV, 15% costs, 2500 legal
    n = finance.btl_numbers(100000, 800, 3500, f)
    assert n["monthly_mortgage"] == round(75000 * 0.055 / 12)        # 344
    assert n["monthly_cashflow"] == round(800 - 75000 * 0.055 / 12 - 120)
    assert n["cash_in"] == 25000 + 3500 + 2500
    assert finance.gross_yield_pct(100000, 800) == 9.6


def test_flip_and_brrr(cfg):
    f = cfg["finance"]
    profit = finance.flip_profit(100000, 160000, 3500, 20000, f)
    assert profit == round(160000 - 100000 - 3500 - 2500 - 20000 - 4800 - 100000 * 0.055 * 0.5)
    assert finance.brrr_cash_left_in(100000, 160000, 3500, 20000, f) == 126000 - 120000


def test_refurb_estimate(cfg):
    assert finance.refurb_estimate(80, cfg["finance"]) == 36000
    assert finance.refurb_estimate(None, cfg["finance"]) == 20000
