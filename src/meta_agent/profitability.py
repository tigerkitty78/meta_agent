"""Profitability layer: contribution margin & breakeven ROAS from config.

The doc's central point: Meta ROAS alone is insufficient. We derive a
contribution margin ratio from Nutrisulin economics and use it to (a) compute a
breakeven ROAS and (b) turn Meta-attributed revenue into a contribution
estimate. Everything here degrades gracefully when economics are UNSPECIFIED.
"""

from __future__ import annotations

from typing import Any

from .config import get_targets, get_unit_economics


def contribution_margin_ratio() -> tuple[float | None, str]:
    """Resolve the contribution margin ratio (0-1) from config.

    Priority: explicit contribution_margin_ratio, else derive from
    retail/sale price and per-unit variable costs. Returns (ratio, explanation).
    """
    ue = get_unit_economics()
    explicit = ue.get("contribution_margin_ratio")
    if explicit is not None:
        return float(explicit), "from unit_economics.contribution_margin_ratio"

    # Try to derive from price and costs.
    from .config import load_economics
    price = None
    product = load_economics().get("product", {}) or {}
    for key in ("sale_price", "retail_price"):
        if product.get(key) is not None:
            price = float(product[key])
            break
    if price is None or price == 0:
        return None, "unspecified — set unit_economics.contribution_margin_ratio or a product price"

    cogs = ue.get("cogs")
    fulfillment = ue.get("fulfillment_cost")
    shipping = ue.get("shipping_subsidy")
    fee_rate = ue.get("payment_fee_rate") or 0.0
    aff_rate = ue.get("affiliate_fee_rate") or 0.0

    if cogs is None:
        return None, "unspecified — need unit_economics.cogs (or set contribution_margin_ratio directly)"

    variable = float(cogs) + float(fulfillment or 0) + float(shipping or 0)
    variable += price * (float(fee_rate) + float(aff_rate))
    ratio = (price - variable) / price
    ratio = max(0.0, min(1.0, ratio))
    return ratio, (f"derived: (price {price} - variable {round(variable, 2)}) / price")


def breakeven_roas() -> tuple[float | None, str]:
    ratio, note = contribution_margin_ratio()
    if ratio is None or ratio == 0:
        return None, note
    return round(1.0 / ratio, 3), f"1 / contribution_margin_ratio ({round(ratio, 3)})"


def profitability_summary() -> dict[str, Any]:
    """Snapshot of the configured economics envelope for reporting."""
    ratio, ratio_note = contribution_margin_ratio()
    be, be_note = breakeven_roas()
    targets = get_targets()
    return {
        "contribution_margin_ratio": ratio,
        "contribution_margin_ratio_basis": ratio_note,
        "breakeven_roas": be,
        "breakeven_roas_basis": be_note,
        "configured_targets": {
            "cpa_target": targets.get("cpa_target"),
            "cac_target": targets.get("cac_target"),
            "roas_floor": targets.get("roas_floor"),
            "contribution_target": targets.get("contribution_target"),
            "max_payback_days": targets.get("max_payback_days"),
        },
        "note": "Contribution figures are Meta-ATTRIBUTED estimates, not realized "
                "finance. Realized revenue/refunds/LTV require the store backend "
                "(not yet integrated).",
    }
