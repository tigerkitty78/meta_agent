import math

import pytest

from meta_agent.kpis import aggregate_rows, compute_kpis
from ._util import mkrow


def test_basic_derivations():
    k = compute_kpis(mkrow(spend=100, impressions=10000, link_clicks=200,
                           purchases=5, value=250, lpv=150))
    assert k["cpm"] == 10.0                      # 100/10000*1000
    assert k["ctr_link"] == 2.0                  # 200/10000*100
    assert k["cpc_link"] == 0.5                  # 100/200
    assert k["cvr_lpv_to_purchase"] == pytest.approx(3.333, abs=0.01)   # 5/150*100
    assert k["cvr_link_click_to_purchase"] == 2.5                       # 5/200*100
    assert k["cpa_meta"] == 20.0                 # 100/5
    assert k["meta_roas"] == 2.5                 # 250/100


def test_contribution_requires_margin():
    no = compute_kpis(mkrow(value=250, spend=100))
    assert no["contribution_after_ads"] is None
    assert no["contribution_roas"] is None

    yes = compute_kpis(mkrow(value=250, spend=100), contribution_margin_ratio=0.55)
    assert yes["contribution_after_ads"] == pytest.approx(37.5)   # 250*0.55 - 100
    assert yes["contribution_roas"] == pytest.approx(1.375)       # 137.5/100


def test_zero_denominators_are_none_not_crash():
    k = compute_kpis(mkrow(spend=0, impressions=0, link_clicks=0, purchases=0,
                           value=0, lpv=0))
    assert k["cpm"] is None
    assert k["ctr_link"] is None
    assert k["cpc_link"] is None
    assert k["cpa_meta"] is None
    assert k["meta_roas"] is None        # value/spend both 0 -> undefined
    assert k["cvr_lpv_to_purchase"] is None


def test_roas_is_zero_when_spend_but_no_revenue():
    k = compute_kpis(mkrow(spend=100, value=0, purchases=0))
    assert k["meta_roas"] == 0.0         # spent, earned nothing -> ROAS 0, not None


def test_purchase_action_type_fallback():
    # only the pixel-prefixed purchase type present -> still counted
    k = compute_kpis(mkrow(purchases=4, value=200,
                           purchase_type="offsite_conversion.fb_pixel_purchase"))
    assert k["meta_purchases"] == 4
    assert k["meta_purchase_value"] == 200.0


def test_ctr_link_vs_ctr_all_are_distinct():
    k = compute_kpis(mkrow(impressions=10000, link_clicks=200, clicks=500))
    assert k["ctr_link"] == 2.0     # link clicks
    assert k["ctr_all"] == 5.0      # all clicks


def test_aggregate_rows_sums_counts_and_actions():
    rows = [mkrow(spend=100, impressions=1000, purchases=2, value=100),
            mkrow(spend=50, impressions=500, purchases=3, value=150)]
    agg = aggregate_rows(rows)
    k = compute_kpis(agg)
    assert k["spend"] == 150.0
    assert k["impressions"] == 1500
    assert k["meta_purchases"] == 5
    assert k["meta_purchase_value"] == 250.0
