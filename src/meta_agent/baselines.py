"""Own-history baselines.

The doc forbids hard-coded CTR/CPM/CVR benchmarks. Instead each rate metric is
compared against the same entity's own recent history. Given daily insight rows
we compute a mean +/- std baseline and flag material deviations using the
sensitivity knobs in economics.yaml -> diagnostics.
"""

from __future__ import annotations

import statistics
from typing import Any

from .kpis import compute_kpis

# metric -> ("up_is_bad" | "down_is_bad"), used to decide which direction to flag
DIRECTION = {
    "ctr_link": "down_is_bad",
    "ctr_all": "down_is_bad",
    "cpc_link": "up_is_bad",
    "cpm": "up_is_bad",
    "cvr_lpv_to_purchase": "down_is_bad",
    "cvr_link_click_to_purchase": "down_is_bad",
    "frequency": "up_is_bad",
    "cpa_meta": "up_is_bad",
    "meta_roas": "down_is_bad",
}


def daily_series(rows: list[dict[str, Any]], metric: str,
                 contribution_margin_ratio: float | None = None) -> list[float]:
    """Compute one metric per daily row, dropping days where it is undefined."""
    out: list[float] = []
    for r in rows:
        kpis = compute_kpis(r, contribution_margin_ratio)
        val = kpis.get(metric)
        if val is not None:
            out.append(float(val))
    return out


def baseline_stats(series: list[float]) -> dict[str, Any]:
    if not series:
        return {"n": 0, "mean": None, "std": None}
    mean = statistics.fmean(series)
    std = statistics.pstdev(series) if len(series) > 1 else 0.0
    return {"n": len(series), "mean": round(mean, 4), "std": round(std, 4),
            "min": round(min(series), 4), "max": round(max(series), 4)}


def compare_to_baseline(
    current: float | None,
    baseline_rows: list[dict[str, Any]],
    metric: str,
    material_pct: float,
    contribution_margin_ratio: float | None = None,
) -> dict[str, Any]:
    """Compare a current value against the baseline built from baseline_rows.

    Returns direction-aware verdict: whether the move is material AND in the
    bad direction for that metric.
    """
    series = daily_series(baseline_rows, metric, contribution_margin_ratio)
    stats = baseline_stats(series)
    result: dict[str, Any] = {
        "metric": metric,
        "current": current,
        "baseline": stats,
        "material_threshold_pct": material_pct,
    }
    if current is None or stats["mean"] is None or stats["mean"] == 0:
        result["verdict"] = "insufficient_data"
        return result

    delta_pct = (current - stats["mean"]) / stats["mean"]
    result["delta_pct"] = round(delta_pct, 4)
    # z-score for extra context when std is meaningful
    if stats["std"]:
        result["z_score"] = round((current - stats["mean"]) / stats["std"], 2)

    direction = DIRECTION.get(metric, "down_is_bad")
    is_bad_direction = (delta_pct < 0) if direction == "down_is_bad" else (delta_pct > 0)
    is_material = abs(delta_pct) >= material_pct

    if is_material and is_bad_direction:
        result["verdict"] = "material_adverse"
    elif is_material and not is_bad_direction:
        result["verdict"] = "material_favorable"
    else:
        result["verdict"] = "within_normal_range"
    return result
