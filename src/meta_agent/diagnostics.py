"""Diagnosis: targets, creative-diagnosis matrix, and root-cause reasoning.

Implements the doc's two decision aids:
  1. Creative diagnosis matrix (CPM x CTR x CVR movement -> interpretation).
  2. The causal diagnostic tree (is it tracking / CPM / CTR / CVR / offer?).

Nothing here executes changes. It produces evidence-labelled recommendations
for a human (or a later, guarded write stage).
"""

from __future__ import annotations

from typing import Any

from .config import get_diagnostics_cfg, get_guardrails, get_targets

STATE_UP = "up"
STATE_DOWN = "down"
STATE_STABLE = "stable"


def _state_from_compare(compare: dict[str, Any]) -> str:
    """Reduce a baseline-compare result to up / down / stable."""
    verdict = compare.get("verdict")
    if verdict in (None, "insufficient_data"):
        return STATE_STABLE
    delta = compare.get("delta_pct")
    material = compare.get("material_threshold_pct", 0.2)
    if delta is None or abs(delta) < material:
        return STATE_STABLE
    return STATE_UP if delta > 0 else STATE_DOWN


# The doc's creative-diagnosis matrix, as (cpm, ctr, cvr) -> verdict.
_MATRIX = {
    (STATE_STABLE, STATE_DOWN, STATE_STABLE): (
        "Creative / hook weakness or fatigue",
        "Test a new hook / creative. Landing page unlikely to be the cause."),
    (STATE_UP, STATE_STABLE, STATE_STABLE): (
        "Auction / audience / placement pressure",
        "Review delivery mix. Do NOT blame creative — this is a CPM cost issue."),
    (STATE_STABLE, STATE_STABLE, STATE_DOWN): (
        "Landing page, offer, checkout or traffic-quality issue",
        "Run site/offer diagnosis. Freeze aggressive scaling."),
    (STATE_STABLE, STATE_DOWN, STATE_DOWN): (
        "Creative-audience mismatch or broader quality problem",
        "New creative + audience diagnostic."),
    (STATE_DOWN, STATE_UP, STATE_UP): (
        "Strong efficiency",
        "Candidate for controlled scale (subject to evidence + guardrails)."),
    (STATE_STABLE, STATE_UP, STATE_DOWN): (
        "Clickier creative but lower-intent traffic",
        "Inspect message / landing-page congruence."),
}


def creative_diagnosis_matrix(cpm_state: str, ctr_state: str, cvr_state: str) -> dict[str, Any]:
    key = (cpm_state, ctr_state, cvr_state)
    if key in _MATRIX:
        interp, step = _MATRIX[key]
    else:
        interp, step = _compose_generic(cpm_state, ctr_state, cvr_state)
    return {
        "cpm_state": cpm_state, "ctr_state": ctr_state, "cvr_state": cvr_state,
        "interpretation": interp, "recommended_next_step": step,
    }


def _compose_generic(cpm: str, ctr: str, cvr: str) -> tuple[str, str]:
    parts = []
    if cpm == STATE_UP:
        parts.append("auction cost rising")
    if ctr == STATE_DOWN:
        parts.append("creative attention weakening")
    if cvr == STATE_DOWN:
        parts.append("conversion effectiveness weakening")
    if not parts:
        return ("No material movement vs baseline", "Continue monitoring; insufficient signal to act.")
    return (" + ".join(parts).capitalize(),
            "Diagnose the weakest link first; gather more evidence before acting.")


def evaluate_targets(kpis: dict[str, Any]) -> dict[str, Any]:
    """Compare financial KPIs against configured business targets."""
    targets = get_targets()
    diag = get_diagnostics_cfg()
    over_pct = diag.get("cpa_over_target_pct", 0.15)
    checks: list[dict[str, Any]] = []

    cpa = kpis.get("cpa_meta")
    cpa_target = targets.get("cpa_target")
    if cpa is not None and cpa_target:
        over = (cpa - cpa_target) / cpa_target
        checks.append({
            "kpi": "cpa_meta", "value": cpa, "target": cpa_target, "rule": "<=",
            "status": "over_target" if over > over_pct else "within_target",
            "delta_pct_vs_target": round(over, 3),
        })
    elif cpa is not None:
        checks.append({"kpi": "cpa_meta", "value": cpa, "target": None,
                       "status": "no_target_configured"})

    roas = kpis.get("meta_roas")
    floor = targets.get("roas_floor")
    if roas is not None and floor:
        checks.append({
            "kpi": "meta_roas", "value": roas, "target": floor, "rule": ">=",
            "status": "below_floor" if roas < floor else "above_floor",
        })
    elif roas is not None:
        checks.append({"kpi": "meta_roas", "value": roas, "target": None,
                       "status": "no_target_configured"})

    contrib = kpis.get("contribution_after_ads")
    ctarget = targets.get("contribution_target")
    if contrib is not None:
        status = "positive" if contrib > 0 else "negative"
        if ctarget is not None:
            status = "above_target" if contrib >= ctarget else "below_target"
        checks.append({"kpi": "contribution_after_ads", "value": contrib,
                       "target": ctarget, "rule": ">", "status": status})

    return {"checks": checks}


def evidence_sufficient(kpis: dict[str, Any]) -> dict[str, Any]:
    """Is there enough volume to trust a performance judgement? (MIN_EVIDENCE)."""
    g = get_guardrails()
    need_impr = g.get("min_impressions", 0) or 0
    need_clicks = g.get("min_clicks", 0) or 0
    need_purch = g.get("min_purchases", 0) or 0
    impr = kpis.get("impressions", 0) or 0
    clicks = kpis.get("link_clicks", 0) or 0
    purch = kpis.get("meta_purchases", 0) or 0
    met = impr >= need_impr and clicks >= need_clicks and purch >= need_purch
    return {
        "sufficient": met,
        "have": {"impressions": impr, "link_clicks": clicks, "purchases": purch},
        "need": {"impressions": need_impr, "link_clicks": need_clicks, "purchases": need_purch},
        "note": None if met else "Below MIN_EVIDENCE — observe / recommend only, do not act aggressively.",
    }


def root_cause_tree(kpis: dict[str, Any],
                    comparisons: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Walk the causal diagnostic tree from the doc.

    `comparisons` maps metric -> baseline-compare result for cpm, ctr_link,
    cvr_lpv_to_purchase (and optionally cpc_link, frequency).
    """
    cpm_state = _state_from_compare(comparisons.get("cpm", {}))
    ctr_state = _state_from_compare(comparisons.get("ctr_link", {}))
    cvr_state = _state_from_compare(comparisons.get("cvr_lpv_to_purchase", {}))

    steps: list[dict[str, Any]] = []

    # 1. Tracking — cheapest thing to rule out. Backend not wired, so we flag
    #    a suspicious pattern rather than assert it's broken.
    lpv = kpis.get("landing_page_views") or 0
    clicks = kpis.get("link_clicks") or 0
    tracking_flag = clicks > 50 and lpv == 0
    steps.append({
        "check": "tracking",
        "finding": "Possible measurement gap: clicks present but zero landing-page views."
                   if tracking_flag else "No obvious Meta-side tracking gap (LPV present).",
        "action": "Escalate to data/engineering; freeze scale actions." if tracking_flag
                  else "Proceed. (Full pixel/CAPI/backend reconciliation not yet integrated.)",
        "severity": "high" if tracking_flag else "ok",
    })

    # 2-4. CPM / CTR / CVR movements.
    steps.append({"check": "cpm", "state": cpm_state,
                  "finding": comparisons.get("cpm", {}).get("verdict")})
    steps.append({"check": "ctr_link", "state": ctr_state,
                  "finding": comparisons.get("ctr_link", {}).get("verdict")})
    steps.append({"check": "cvr_lpv_to_purchase", "state": cvr_state,
                  "finding": comparisons.get("cvr_lpv_to_purchase", {}).get("verdict")})

    matrix = creative_diagnosis_matrix(cpm_state, ctr_state, cvr_state)

    # Primary driver: pick the first adverse link in the funnel order.
    if tracking_flag:
        primary = "tracking"
    elif cpm_state == STATE_UP:
        primary = "cpm_auction_pressure"
    elif ctr_state == STATE_DOWN:
        primary = "creative_attention"
    elif cvr_state == STATE_DOWN:
        primary = "landing_page_or_offer"
    else:
        primary = "no_material_driver"

    return {
        "primary_driver": primary,
        "creative_matrix": matrix,
        "tree": steps,
    }
