from meta_agent.diagnostics import (creative_diagnosis_matrix, evaluate_targets,
                                    evidence_sufficient)
from meta_agent.kpis import compute_kpis
from ._util import mkrow


def test_creative_matrix_fatigue():
    m = creative_diagnosis_matrix("stable", "down", "stable")
    assert "fatigue" in m["interpretation"].lower() or "creative" in m["interpretation"].lower()


def test_creative_matrix_strong_efficiency():
    m = creative_diagnosis_matrix("down", "up", "up")
    assert "efficiency" in m["interpretation"].lower()


def test_creative_matrix_auction_pressure():
    m = creative_diagnosis_matrix("up", "stable", "stable")
    assert "auction" in m["interpretation"].lower()


def test_targets_flag_over_cpa_and_below_floor():
    # cpa_target=60, roas_floor=1.0 in test config
    k = compute_kpis(mkrow(spend=100, purchases=1, value=50))   # cpa 100, roas 0.5
    checks = {c["kpi"]: c for c in evaluate_targets(k)["checks"]}
    assert checks["cpa_meta"]["status"] == "over_target"
    assert checks["meta_roas"]["status"] == "below_floor"


def test_targets_pass_when_good():
    k = compute_kpis(mkrow(spend=100, purchases=5, value=250))  # cpa 20, roas 2.5
    checks = {c["kpi"]: c for c in evaluate_targets(k)["checks"]}
    assert checks["cpa_meta"]["status"] == "within_target"
    assert checks["meta_roas"]["status"] == "above_floor"


def test_evidence_gate():
    strong = evidence_sufficient(compute_kpis(
        mkrow(impressions=50000, link_clicks=500, purchases=10)))
    assert strong["sufficient"] is True

    weak = evidence_sufficient(compute_kpis(
        mkrow(impressions=200, link_clicks=5, purchases=1)))
    assert weak["sufficient"] is False
    assert weak["note"]
