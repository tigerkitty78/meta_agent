from meta_agent.verdict import rolling_verdict
from ._util import mkdays


MARGIN = 0.55   # matches test_config.yaml


def _series(baseline_kw, recent_kw, base_days=21, recent_days=7):
    base = mkdays(base_days, start=1, **baseline_kw)
    recent = mkdays(recent_days, start=1 + base_days, **recent_kw)
    return base + recent


def test_scale_when_improving_and_profitable():
    rows = _series(
        baseline_kw=dict(spend=100, impressions=10000, link_clicks=200, purchases=5, value=250),
        recent_kw=dict(spend=100, impressions=10000, link_clicks=200, purchases=10, value=500),
    )
    v = rolling_verdict("campaign", rows, MARGIN, recent_days=7)
    assert v["verdict"] == "SCALE"
    assert v["long_term_trend"] == "improving"
    assert v["profitability"]["profitable"] is True


def test_cooldown_downgrades_scale_to_hold():
    rows = _series(
        baseline_kw=dict(spend=100, impressions=10000, link_clicks=200, purchases=5, value=250),
        recent_kw=dict(spend=100, impressions=10000, link_clicks=200, purchases=10, value=500),
    )
    v = rolling_verdict("campaign", rows, MARGIN, recent_days=7, hours_since_last_edit=2)
    assert v["verdict"] == "HOLD"
    assert v["cooldown"]["applied"] is True


def test_fix_when_creative_ctr_declines():
    # ad level: CTR halves recently, CPM and CVR stable -> creative attention FIX
    rows = _series(
        baseline_kw=dict(spend=100, impressions=10000, link_clicks=200, purchases=5, value=250),
        recent_kw=dict(spend=100, impressions=10000, link_clicks=100, purchases=5, value=250),
    )
    v = rolling_verdict("ad", rows, MARGIN, recent_days=7)
    assert v["verdict"] == "FIX"
    assert "ctr_down" in v["condition_tags"]
    assert v["fixes"]                      # matched playbook fixes attached


def test_economics_gate_blocks_scale_without_margin():
    # improving + ROAS clears the floor, but no contribution margin is set:
    # breakeven is unknown, so SCALE must be withheld (audit G1).
    rows = _series(
        baseline_kw=dict(spend=100, impressions=10000, link_clicks=200, purchases=5, value=120),
        recent_kw=dict(spend=100, impressions=10000, link_clicks=200, purchases=10, value=300),
    )
    v = rolling_verdict("campaign", rows, margin=None, recent_days=7)
    assert v["verdict"] == "HOLD"
    assert "economics gate" in v["reason"].lower()


def test_hold_when_too_few_days():
    rows = mkdays(3)
    v = rolling_verdict("campaign", rows, MARGIN, recent_days=7)
    assert v["verdict"] == "HOLD"


def test_stop_loss_over_target_with_spend():
    # cpa far above target (60) with spend past 3x target, healthy tracking
    rows = _series(
        baseline_kw=dict(spend=300, impressions=10000, link_clicks=200, purchases=1, value=50),
        recent_kw=dict(spend=300, impressions=10000, link_clicks=200, purchases=1, value=50),
    )
    v = rolling_verdict("campaign", rows, MARGIN, recent_days=7)
    assert v["verdict"] in ("STOP", "FIX")   # unprofitable; STOP once stop-loss conditions hold


def test_driver_fixes_rank_ahead_of_learning_limited():
    # learning_limited fires on nearly every small account; weekly_report keeps
    # only the top 2 fixes, so the driver's (cvr/offer) fixes must come first
    from meta_agent.fixes import get_fixes
    from meta_agent.verdict import _select_fix_ids
    ids = _select_fix_ids("campaign", "FIX", ["cvr_down", "learning_limited", "offer_issue"])
    cvr_ids = [f["id"] for f in get_fixes("adset", ["cvr_down"])]
    assert cvr_ids and ids[:len(cvr_ids)] == cvr_ids[:len(ids)]
