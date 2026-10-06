"""Funnel-gate KPIs with full atomic-value + formula transparency.

Mirrors the Amazon agent's gate framework (Visibility -> Click -> Conversion ->
Paid Efficiency -> Ad Dependency -> Profit), translated to Meta. Each gate
returns not just a value but the exact atomic fields used and the formula with
the real numbers substituted, so a reader can audit every figure.

Honest limits:
  - ACoS = spend / purchase_value * 100 (the inverse of ROAS) is Meta-attributed.
  - TACoS needs TOTAL store revenue (organic + paid), which the Meta API does
    not have — it requires the ecommerce backend, or a manually supplied number.
  - Profit needs the contribution margin ratio from economics.yaml.
"""

from __future__ import annotations

from typing import Any

from .kpis import LPV_TYPES, PURCHASE_TYPES, _action_value, _f


def _r(v: float | None, nd: int = 2) -> float | None:
    return None if v is None else round(v, nd)


def compute_gates(raw: dict[str, Any], margin: float | None = None,
                  total_store_revenue: float | None = None) -> dict[str, Any]:
    """Compute the six funnel gates from one (aggregated) insights row.

    Returns {gates: [...], blocked: [...]} where each gate carries its atomic
    inputs, the formula, the substituted computation and the value.
    """
    impressions = _f(raw.get("impressions"))
    link_clicks = _f(raw.get("inline_link_clicks"))
    spend = _f(raw.get("spend"))
    purchases = _action_value(raw.get("actions"), PURCHASE_TYPES)
    lpv = _action_value(raw.get("actions"), LPV_TYPES)
    revenue = _action_value(raw.get("action_values"), PURCHASE_TYPES)

    gates: list[dict[str, Any]] = []

    # 1. Visibility -------------------------------------------------------
    gates.append({
        "gate": "Visibility (Impressions)", "metric": "impressions",
        "formula": "raw field: impressions",
        "atomic_values": {"impressions": int(impressions)},
        "computation": f"impressions = {int(impressions)}",
        "value": int(impressions), "unit": "count", "better": "higher",
    })

    # 2. Click (CTR link) -------------------------------------------------
    ctr = (link_clicks / impressions * 100) if impressions else None
    gates.append({
        "gate": "Click (CTR)", "metric": "ctr_link",
        "formula": "link_clicks / impressions * 100",
        "atomic_values": {"inline_link_clicks": int(link_clicks), "impressions": int(impressions)},
        "computation": (f"{int(link_clicks)} / {int(impressions)} * 100 = {_r(ctr)}"
                        if impressions else "impressions = 0 -> undefined"),
        "value": _r(ctr), "unit": "%", "better": "higher",
    })

    # 3. Conversion (CVR, LPV -> purchase) --------------------------------
    cvr = (purchases / lpv * 100) if lpv else None
    gates.append({
        "gate": "Conversion (CVR)", "metric": "cvr_lpv_to_purchase",
        "formula": "purchases / landing_page_views * 100",
        "atomic_values": {"purchases": int(purchases), "landing_page_views": int(lpv)},
        "computation": (f"{int(purchases)} / {int(lpv)} * 100 = {_r(cvr)}"
                        if lpv else "landing_page_views = 0 -> undefined"),
        "value": _r(cvr), "unit": "%", "better": "higher",
    })

    # 4. Paid Efficiency (ACoS = inverse ROAS) ----------------------------
    acos = (spend / revenue * 100) if revenue else None
    gates.append({
        "gate": "Paid Efficiency (ACoS)", "metric": "acos_meta",
        "formula": "spend / purchase_value * 100",
        "atomic_values": {"spend": round(spend, 2), "meta_purchase_value": round(revenue, 2)},
        "computation": (f"{round(spend, 2)} / {round(revenue, 2)} * 100 = {_r(acos)}"
                        if revenue else "purchase_value = 0 -> undefined (no attributed revenue)"),
        "value": _r(acos), "unit": "%", "better": "lower",
        "note": "Meta-attributed. ACoS = 100 / ROAS. Lower is better.",
    })

    # 5. Ad Dependency (TACoS) -- needs TOTAL store revenue ---------------
    if total_store_revenue:
        tacos = spend / total_store_revenue * 100
        gates.append({
            "gate": "Ad Dependency (TACoS)", "metric": "tacos",
            "formula": "spend / total_store_revenue * 100",
            "atomic_values": {"spend": round(spend, 2),
                              "total_store_revenue": round(total_store_revenue, 2)},
            "computation": f"{round(spend, 2)} / {round(total_store_revenue, 2)} * 100 = {_r(tacos)}",
            "value": _r(tacos), "unit": "%", "better": "lower",
            "note": "total_store_revenue was supplied manually (not from the Meta API).",
        })
    else:
        gates.append({
            "gate": "Ad Dependency (TACoS)", "metric": "tacos",
            "formula": "spend / total_store_revenue * 100",
            "atomic_values": {"spend": round(spend, 2), "total_store_revenue": None},
            "computation": "BLOCKED - total_store_revenue unavailable",
            "value": None, "unit": "%", "better": "lower",
            "note": "Needs TOTAL store revenue (organic + paid). Meta only knows ad-attributed "
                    "sales, so wire the ecommerce backend (Shopify) or pass total_store_revenue.",
        })

    # 6. Profit (contribution after ads) -- needs margin ------------------
    if margin is not None:
        contrib = revenue * margin - spend
        gates.append({
            "gate": "Profit", "metric": "contribution_after_ads",
            "formula": "purchase_value * contribution_margin_ratio - spend",
            "atomic_values": {"meta_purchase_value": round(revenue, 2),
                              "contribution_margin_ratio": margin, "spend": round(spend, 2)},
            "computation": f"{round(revenue, 2)} * {margin} - {round(spend, 2)} = {_r(contrib)}",
            "value": _r(contrib), "unit": "currency", "better": "higher",
            "note": "Meta-ATTRIBUTED contribution estimate (not realized finance).",
        })
    else:
        gates.append({
            "gate": "Profit", "metric": "contribution_after_ads",
            "formula": "purchase_value * contribution_margin_ratio - spend",
            "atomic_values": {"meta_purchase_value": round(revenue, 2),
                              "contribution_margin_ratio": None, "spend": round(spend, 2)},
            "computation": "BLOCKED - contribution_margin_ratio not configured",
            "value": None, "unit": "currency", "better": "higher",
            "note": "Set unit_economics.contribution_margin_ratio in economics.yaml to enable.",
        })

    blocked = [g["gate"] for g in gates if g["value"] is None]
    return {"gates": gates, "blocked": blocked,
            "atomic_source": "Meta Insights API (one aggregated row for the period)"}
