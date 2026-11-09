from fastapi.testclient import TestClient

import dealfinder.config as config
from dealfinder.dealpost import breakdown, build_numbers, town_from_address, write_post
from tests.test_pipeline import scanner


def item(**analysis):
    a = {"strategies": [{"name": "Refurb / BRRR"}], "refurb_cost": 20000, "done_up_value": 150000,
         "market_value": 140000, "rent_pcm": None, "valuation_comps": 42}
    a.update(analysis)
    return {"listing": {"address": "Abbeydale Road, Nether Edge, Sheffield, S7", "price": 95000}, "analysis": a}


def test_sheffield_example_numbers(cfg):
    # The worked example: £95k purchase, £17,720 refurb, £155k GDV, £850 rent, refinance at 75%.
    form = {"purchase": "95,000", "refurb": "17720", "gdv": "£155,000", "rent": "850", "other_costs": "9780",
            "highlights": ["quote", "build_team", "hands_off"], "contact": "Sam on 07000 000000"}
    d = build_numbers(item(), cfg, form)
    assert d.stamp_duty == 4750                                  # £95k additional property
    assert d.total_in == 95000 + 4750 + 2500 + 17720 + 9780
    assert d.refinance_loan == 116250 and d.equity == 38750
    assert d.money_left_in == 13500                              # matches the example post
    assert d.monthly_cashflow == round(850 - 116250 * 0.055 / 12 - 850 * 0.15)
    post = write_post(d)
    assert post.startswith("🚨SHEFFIELD BRRR DEAL🚨")
    for line in ("📍 Sheffield", "💰 Purchase price: £95,000", "👷 Refurb: £17,720 (quote provided)",
                 "🔥 GDV: £155,000 (based on 42 local sold prices)", "🏦 Money left in: £13,500",
                 "🏠 Equity: £38,750", "💸 Rent: £850 pcm", "✅ Full build team in place",
                 "✅ Fully hands-off investment", "📲 Sam on 07000 000000"):
        assert line in post, line
    assert "Full lettings team" not in post                      # not ticked, so not claimed
    assert ("Money left in (total in − refinance)", "£13,500") in breakdown(d)


def test_defaults_come_from_analysis_and_claim_nothing(cfg):
    d = build_numbers(item(), cfg)
    assert (d.purchase, d.refurb, d.gdv, d.strategy, d.location) == (95000, 20000, 150000, "brrr", "Sheffield")
    post = write_post(d)
    assert "(estimate)" in post and "quote provided" not in post and "✅" not in post
    assert "Rent" not in post                                    # no rent known, none invented


def test_all_money_out_and_other_types(cfg):
    d = build_numbers(item(), cfg, {"gdv": "200000"})
    assert d.money_left_in < 0 and "all money out!" in write_post(d)
    bmv = write_post(build_numbers(item(strategies=[{"name": "BMV"}]), cfg))
    assert bmv.startswith("🚨SHEFFIELD BELOW MARKET VALUE DEAL🚨") and "32% below market value" in bmv
    assert "Estimated profit" in write_post(build_numbers(item(), cfg, {"strategy": "flip"}))


def test_town_from_address():
    assert town_from_address("Carsons Road, Greenbank, Bristol, BS5") == "Bristol"
    assert town_from_address("Strathcona Road, Liverpool, Merseyside, L15") == "Liverpool"
    assert town_from_address("") == ""


def test_post_page_and_settings(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(config, "HOME", tmp_path)
    scanner(cfg, 125000).run()
    from dealfinder.web.app import create_app
    client = TestClient(create_app(cfg))
    client.post("/settings", data={"marketing_contact": "Sam on 07000 000000", "marketing_sourcing_fee": "3000",
                                   "marketing_highlights": ["lettings"], "daily_at": "07:30"})
    assert "Create deal post" in client.get("/deal/rightmove:1").text
    page = client.get("/deal/rightmove:1/post").text
    assert "BRRR DEAL" in page and "Sam on 07000 000000" in page and "Full lettings team in place" in page
    assert "£3,000" in page                                      # sourcing fee in the costs
    page = client.get("/deal/rightmove:1/post", params={"refurb": "30000", "highlights": ""}).text
    assert "Refurb: £30,000" in page and "✅" not in page.split("How the numbers work")[0].split("<textarea")[1]
