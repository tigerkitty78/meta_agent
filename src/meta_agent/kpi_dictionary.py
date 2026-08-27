"""The Nutrisulin KPI dictionary.

Machine-readable encoding of the KPI operating model from the design doc.
Each entry records: how the metric is computed, how OFTEN it should drive
decisions, what its benchmark actually is (own baseline vs configured target
vs diagnostic-only), and how the agent should interpret it at each level of
the campaign -> ad set -> ad hierarchy.

Deliberately, NO generic industry benchmark numbers are stored here. The
"benchmark" field names the *source of truth*, not a magic number.
"""

from __future__ import annotations

# benchmark kinds
OWN_BASELINE = "own_rolling_baseline"     # compare to this account's own history
CONFIG_TARGET = "configured_target"       # compare to a value in economics.yaml
DIAGNOSTIC_ONLY = "diagnostic_only"       # Meta-calculated, never a business target / pause trigger
RAW_MONITOR = "raw_monitor"               # tracked for pacing/anomaly, no pass/fail benchmark

# The four-level KPI hierarchy from the doc.
HIERARCHY = ["delivery", "engagement", "conversion", "financial", "diagnostic"]

KPI_DICTIONARY: dict[str, dict] = {
    # ---- Delivery ----------------------------------------------------------
    "spend": {
        "layer": "delivery",
        "formula": "raw field: spend",
        "monitoring": "30-60 min (pacing)",
        "benchmark": RAW_MONITOR,
        "interpretation": "Budget consumption; watched for pacing / overspend anomalies.",
        "levels": ["campaign", "adset", "ad"],
    },
    "impressions": {
        "layer": "delivery",
        "formula": "raw field: impressions",
        "monitoring": "hourly",
        "benchmark": RAW_MONITOR,
        "interpretation": "Delivery volume.",
        "levels": ["campaign", "adset", "ad"],
    },
    "reach": {
        "layer": "delivery",
        "formula": "raw field: reach",
        "monitoring": "daily",
        "benchmark": RAW_MONITOR,
        "interpretation": "Unique people reached.",
        "levels": ["campaign", "adset", "ad"],
    },
    "frequency": {
        "layer": "delivery",
        "formula": "impressions / reach (or raw field frequency)",
        "monitoring": "daily",
        "benchmark": OWN_BASELINE,
        "interpretation": "Rising frequency vs baseline can signal fatigue / audience saturation.",
        "levels": ["campaign", "adset", "ad"],
    },
    "cpm": {
        "layer": "delivery",
        "formula": "(spend / impressions) * 1000",
        "monitoring": "hourly",
        "benchmark": OWN_BASELINE,
        "interpretation": "Auction / delivery cost. Compare INTERNALLY by audience/placement/time "
                          "against a long (28d) baseline. A rise here is auction pressure, not a "
                          "creative problem.",
        "levels": ["campaign", "adset", "ad"],
    },
    # ---- Engagement --------------------------------------------------------
    "link_clicks": {
        "layer": "engagement",
        "formula": "raw field: inline_link_clicks",
        "monitoring": "hourly",
        "benchmark": RAW_MONITOR,
        "interpretation": "Outbound interest volume.",
        "levels": ["campaign", "adset", "ad"],
    },
    "ctr_link": {
        "layer": "engagement",
        "formula": "(inline_link_clicks / impressions) * 100",
        "monitoring": "hourly monitor; daily decisions",
        "benchmark": OWN_BASELINE,
        "interpretation": "Creative's ability to generate clicks. Baseline by placement/objective/"
                          "creative (Reels vs Feed vs Stories are NOT directly comparable). Primary "
                          "signal at the AD level for creative fatigue.",
        "levels": ["campaign", "adset", "ad"],
    },
    "ctr_all": {
        "layer": "engagement",
        "formula": "(clicks / impressions) * 100",
        "monitoring": "hourly",
        "benchmark": OWN_BASELINE,
        "interpretation": "All-click CTR (includes non-link clicks). Kept separate from ctr_link on "
                          "purpose so denominators never get confused.",
        "levels": ["campaign", "adset", "ad"],
    },
    "cpc_link": {
        "layer": "engagement",
        "formula": "spend / inline_link_clicks",
        "monitoring": "hourly/daily",
        "benchmark": OWN_BASELINE,
        "interpretation": "Cost of traffic. Must fit CPA economics: a CPC ceiling can be derived as "
                          "cpa_target * cvr_link_click_to_purchase.",
        "levels": ["campaign", "adset", "ad"],
    },
    # ---- Conversion --------------------------------------------------------
    "landing_page_views": {
        "layer": "conversion",
        "formula": "actions[action_type='landing_page_view'].value",
        "monitoring": "hourly",
        "benchmark": RAW_MONITOR,
        "interpretation": "Meta-side landing-page arrivals. Gap vs link_clicks hints at page-load / "
                          "drop-off issues (full drop-off analysis needs GA4 — not yet wired).",
        "levels": ["campaign", "adset", "ad"],
    },
    "cvr_lpv_to_purchase": {
        "layer": "conversion",
        "formula": "(purchases / landing_page_views) * 100",
        "monitoring": "6-hour monitor; daily action",
        "benchmark": OWN_BASELINE,
        "interpretation": "Landing-page / checkout effectiveness. Baseline by page/device/offer. "
                          "Stable CVR while CTR falls => creative issue, not the page.",
        "levels": ["campaign", "adset", "ad"],
    },
    "cvr_link_click_to_purchase": {
        "layer": "conversion",
        "formula": "(purchases / inline_link_clicks) * 100",
        "monitoring": "daily",
        "benchmark": OWN_BASELINE,
        "interpretation": "End-to-end click efficiency.",
        "levels": ["campaign", "adset", "ad"],
    },
    "meta_purchases": {
        "layer": "conversion",
        "formula": "actions[action_type='purchase'].value",
        "monitoring": "hourly",
        "benchmark": RAW_MONITOR,
        "interpretation": "Meta-attributed purchases. Reconcile with backend orders before trusting "
                          "for scaling (backend not yet wired).",
        "levels": ["campaign", "adset", "ad"],
    },
    # ---- Financial ---------------------------------------------------------
    "cpa_meta": {
        "layer": "financial",
        "formula": "spend / meta_purchases",
        "monitoring": "hourly monitoring; daily decisions",
        "benchmark": CONFIG_TARGET,           # targets.cpa_target
        "interpretation": "Ad efficiency. Benchmark = configured cpa_target (<= is good).",
        "levels": ["campaign", "adset", "ad"],
    },
    "meta_roas": {
        "layer": "financial",
        "formula": "meta_purchase_value / spend",
        "monitoring": "daily",
        "benchmark": CONFIG_TARGET,           # targets.roas_floor
        "interpretation": "Meta-attributed revenue efficiency. Benchmark = configured roas_floor "
                          "(>= is good). NOT sufficient alone — see contribution_roas.",
        "levels": ["campaign", "adset", "ad"],
    },
    "meta_purchase_value": {
        "layer": "financial",
        "formula": "action_values[action_type='purchase'].value",
        "monitoring": "daily",
        "benchmark": RAW_MONITOR,
        "interpretation": "Meta-attributed revenue.",
        "levels": ["campaign", "adset", "ad"],
    },
    "contribution_after_ads": {
        "layer": "financial",
        "formula": "(meta_purchase_value * contribution_margin_ratio) - spend",
        "monitoring": "daily",
        "benchmark": CONFIG_TARGET,           # targets.contribution_target ; and > 0
        "interpretation": "Meta-ATTRIBUTED contribution estimate after ad spend, using the margin "
                          "ratio from economics.yaml. This is the real reward signal — a strong ROAS "
                          "with thin margin can still be unprofitable. Not a realized-finance number.",
        "levels": ["campaign", "adset", "ad"],
    },
    "contribution_roas": {
        "layer": "financial",
        "formula": "(meta_purchase_value * contribution_margin_ratio) / spend",
        "monitoring": "daily",
        "benchmark": CONFIG_TARGET,           # > 1 for positive post-ad contribution
        "interpretation": ">1 means positive post-ad contribution before fixed costs. Compare with "
                          "breakeven_roas = 1 / contribution_margin_ratio.",
        "levels": ["campaign", "adset", "ad"],
    },
    # ---- Diagnostic (Meta-calculated relevance rankings) -------------------
    "quality_ranking": {
        "layer": "diagnostic",
        "formula": "raw field: quality_ranking (below_average / average / above_average)",
        "monitoring": "daily",
        "benchmark": DIAGNOSTIC_ONLY,
        "interpretation": "Perceived quality vs competing ads. DIAGNOSTIC ONLY — a below-average "
                          "ranking must NEVER auto-pause a profitable ad.",
        "levels": ["ad"],
    },
    "engagement_rate_ranking": {
        "layer": "diagnostic",
        "formula": "raw field: engagement_rate_ranking",
        "monitoring": "daily",
        "benchmark": DIAGNOSTIC_ONLY,
        "interpretation": "Expected engagement vs competing ads. Diagnostic only.",
        "levels": ["ad"],
    },
    "conversion_rate_ranking": {
        "layer": "diagnostic",
        "formula": "raw field: conversion_rate_ranking",
        "monitoring": "daily",
        "benchmark": DIAGNOSTIC_ONLY,
        "interpretation": "Expected conversion vs competing ads. Diagnostic only.",
        "levels": ["ad"],
    },
}


# What each level of the hierarchy is primarily FOR (drives interpretation).
LEVEL_FOCUS = {
    "campaign": {
        "focus": "Overall efficiency, budget pacing, and profitability vs targets.",
        "primary_kpis": ["spend", "cpa_meta", "meta_roas", "contribution_after_ads",
                         "contribution_roas"],
    },
    "adset": {
        "focus": "Audience / placement / offer. Delivery cost (CPM) and conversion "
                 "effectiveness (CVR) live here.",
        "primary_kpis": ["cpm", "cvr_lpv_to_purchase", "cvr_link_click_to_purchase",
                         "cpa_meta", "frequency"],
    },
    "ad": {
        "focus": "Creative. Attention (CTR) and Meta's relevance diagnostics. "
                 "Creative fatigue is judged here.",
        "primary_kpis": ["ctr_link", "cpc_link", "quality_ranking",
                         "engagement_rate_ranking", "conversion_rate_ranking"],
    },
}


def kpis_for_level(level: str) -> list[str]:
    """All KPI keys applicable at a given hierarchy level."""
    return [k for k, v in KPI_DICTIONARY.items() if level in v["levels"]]
