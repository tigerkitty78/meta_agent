"""Deterministic KPI engine.

Turns a raw Meta insights row into the explicit, unambiguously-named KPI set
from the doc (ctr_link vs ctr_all; cvr_lpv_to_purchase vs
cvr_link_click_to_purchase). No LLM guesses numbers — this is pure arithmetic.
"""

from __future__ import annotations

from typing import Any

# action_type fallbacks: Meta reports purchases under several names depending on
# pixel/CAPI setup. We take the first present, in priority order.
PURCHASE_TYPES = [
    "purchase",
    "omni_purchase",
    "offsite_conversion.fb_pixel_purchase",
]
LPV_TYPES = ["landing_page_view", "omni_landing_page_view"]
ATC_TYPES = ["add_to_cart", "omni_add_to_cart", "offsite_conversion.fb_pixel_add_to_cart"]
IC_TYPES = ["initiate_checkout", "omni_initiated_checkout",
            "offsite_conversion.fb_pixel_initiate_checkout"]


def _f(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _action_value(actions: list[dict] | None, types: list[str]) -> float:
    """First matching action_type's value, following the fallback priority."""
    if not actions:
        return 0.0
    by_type = {a.get("action_type"): a for a in actions}
    for t in types:
        if t in by_type:
            return _f(by_type[t].get("value"))
    return 0.0


def _safe_div(num: float, den: float) -> float | None:
    return num / den if den else None


def compute_kpis(row: dict[str, Any], contribution_margin_ratio: float | None = None) -> dict[str, Any]:
    """Compute the full KPI set for one insights row.

    `contribution_margin_ratio` (0-1) enables the Meta-attributed contribution
    estimates. When None, those fields are returned as None with a note.
    """
    spend = _f(row.get("spend"))
    impressions = _f(row.get("impressions"))
    reach = _f(row.get("reach"))
    clicks = _f(row.get("clicks"))
    link_clicks = _f(row.get("inline_link_clicks"))

    actions = row.get("actions")
    action_values = row.get("action_values")

    purchases = _action_value(actions, PURCHASE_TYPES)
    purchase_value = _action_value(action_values, PURCHASE_TYPES)
    lpv = _action_value(actions, LPV_TYPES)
    atc = _action_value(actions, ATC_TYPES)
    ic = _action_value(actions, IC_TYPES)

    kpis: dict[str, Any] = {
        # delivery
        "spend": round(spend, 2),
        "impressions": int(impressions),
        "reach": int(reach),
        "frequency": round(impressions / reach, 3) if reach else _f(row.get("frequency")) or None,
        "cpm": _round(_safe_div(spend, impressions), mult=1000),
        # engagement
        "clicks": int(clicks),
        "link_clicks": int(link_clicks),
        "ctr_link": _round(_safe_div(link_clicks, impressions), mult=100),
        "ctr_all": _round(_safe_div(clicks, impressions), mult=100),
        "cpc_link": _round(_safe_div(spend, link_clicks)),
        # conversion funnel
        "landing_page_views": int(lpv),
        "add_to_cart": int(atc),
        "initiate_checkout": int(ic),
        "meta_purchases": int(purchases),
        "cvr_lpv_to_purchase": _round(_safe_div(purchases, lpv), mult=100),
        "cvr_link_click_to_purchase": _round(_safe_div(purchases, link_clicks), mult=100),
        # financial (Meta-attributed)
        "meta_purchase_value": round(purchase_value, 2),
        "cpa_meta": _round(_safe_div(spend, purchases)),
        "meta_roas": _round(_safe_div(purchase_value, spend)),
        # diagnostics (Meta-calculated)
        "quality_ranking": row.get("quality_ranking"),
        "engagement_rate_ranking": row.get("engagement_rate_ranking"),
        "conversion_rate_ranking": row.get("conversion_rate_ranking"),
    }

    # Contribution estimates require the margin ratio from config.
    if contribution_margin_ratio is not None:
        contribution_before_ads = purchase_value * contribution_margin_ratio
        kpis["contribution_after_ads"] = round(contribution_before_ads - spend, 2)
        kpis["contribution_roas"] = _round(_safe_div(contribution_before_ads, spend))
        kpis["_contribution_basis"] = "meta_attributed_estimate"
    else:
        kpis["contribution_after_ads"] = None
        kpis["contribution_roas"] = None
        kpis["_contribution_note"] = "requires unit_economics.contribution_margin_ratio in config"

    return kpis


def _round(value: float | None, mult: float = 1.0, ndigits: int = 3) -> float | None:
    if value is None:
        return None
    return round(value * mult, ndigits)


def aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum raw insight fields across rows into one synthetic row.

    Used to roll daily rows up to a period total before computing rates
    (rates must be computed on summed numerators/denominators, never averaged).
    """
    if not rows:
        return {}
    total: dict[str, Any] = {
        "spend": 0.0, "impressions": 0.0, "reach": 0.0,
        "clicks": 0.0, "inline_link_clicks": 0.0,
    }
    agg_actions: dict[str, float] = {}
    agg_values: dict[str, float] = {}
    for r in rows:
        for k in ("spend", "impressions", "reach", "clicks", "inline_link_clicks"):
            total[k] += _f(r.get(k))
        for a in r.get("actions") or []:
            agg_actions[a.get("action_type")] = agg_actions.get(a.get("action_type"), 0.0) + _f(a.get("value"))
        for a in r.get("action_values") or []:
            agg_values[a.get("action_type")] = agg_values.get(a.get("action_type"), 0.0) + _f(a.get("value"))
    total["actions"] = [{"action_type": k, "value": v} for k, v in agg_actions.items()]
    total["action_values"] = [{"action_type": k, "value": v} for k, v in agg_values.items()]
    # reach summed across days overstates uniqueness; keep it but flag.
    total["_reach_note"] = "reach summed across rows is an upper bound, not unique reach"
    return total
