from dealfinder.analysis.sdlt import stamp_duty


def test_main_residence_rates(cfg):
    assert stamp_duty(125000, cfg["stamp_duty"], additional=False) == 0
    assert stamp_duty(200000, cfg["stamp_duty"], additional=False) == 1500


def test_additional_property(cfg):
    # 125k @ 5% + 75k @ 7%
    assert stamp_duty(200000, cfg["stamp_duty"]) == 6250 + 5250
    # 125k @ 5% + 125k @ 7% + 50k @ 10%
    assert stamp_duty(300000, cfg["stamp_duty"]) == 20000


def test_non_resident(cfg):
    assert stamp_duty(300000, cfg["stamp_duty"], non_resident=True) == 8750 + 11250 + 6000


def test_surcharge_not_below_40k(cfg):
    assert stamp_duty(39000, cfg["stamp_duty"]) == 0
