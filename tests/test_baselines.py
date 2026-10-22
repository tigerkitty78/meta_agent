import pytest

from meta_agent.baselines import baseline_stats, compare_to_baseline, daily_series
from ._util import mkdays, mkrow


def test_baseline_stats():
    s = baseline_stats([1.0, 2.0, 3.0])
    assert s["n"] == 3
    assert s["mean"] == pytest.approx(2.0)
    assert s["min"] == 1.0 and s["max"] == 3.0


def test_daily_series_drops_undefined():
    rows = [mkrow(impressions=10000, link_clicks=200),   # ctr 2.0
            mkrow(impressions=0, link_clicks=0)]          # ctr undefined -> dropped
    series = daily_series(rows, "ctr_link")
    assert series == [2.0]


def test_ctr_drop_is_material_adverse():
    base = mkdays(20, link_clicks=200, impressions=10000)      # ctr 2.0
    move = compare_to_baseline(1.0, base, "ctr_link", 0.20)    # current 1.0 = -50%
    assert move["verdict"] == "material_adverse"
    assert move["delta_pct"] == pytest.approx(-0.5)


def test_ctr_rise_is_material_favorable():
    base = mkdays(20, link_clicks=200, impressions=10000)      # ctr 2.0
    move = compare_to_baseline(3.0, base, "ctr_link", 0.20)    # +50%
    assert move["verdict"] == "material_favorable"


def test_cpm_rise_is_adverse_direction_aware():
    base = mkdays(20, spend=100, impressions=10000)            # cpm 10.0
    move = compare_to_baseline(14.0, base, "cpm", 0.20)        # +40%, up is bad
    assert move["verdict"] == "material_adverse"


def test_within_threshold_is_normal():
    base = mkdays(20, link_clicks=200, impressions=10000)      # ctr 2.0
    move = compare_to_baseline(2.1, base, "ctr_link", 0.20)    # +5% < 20%
    assert move["verdict"] == "within_normal_range"


def test_insufficient_data():
    move = compare_to_baseline(2.0, [], "ctr_link", 0.20)
    assert move["verdict"] == "insufficient_data"
