"""Rolling-average SCALE / HOLD / FIX / STOP verdict engine.

The "which direction" layer the user asked for: compare an entity's RECENT
rolling window against its own PRIOR baseline window, then combine that trend
with target checks, evidence sufficiency and safety gates to produce a verdict.
Each verdict is paired with the matching fixes from the playbook (fixes.py).

Doc alignment:
  - SCALE mirrors the doc's controlled-scaling rule (evidence + profitability +
    favourable trend + tracking healthy).
  - STOP mirrors the stop-loss rule (materially over CPA target with enough
    spend/evidence).
  - Measurement is a GATE: if tracking looks broken, scaling is frozen and the
    verdict is FIX(measurement) regardless of apparent performance.
  - Never invents benchmarks; trend is entity-vs-own-baseline only.
"""

from __future__ import annotations

from typing import Any

from .baselines import compare_to_baseline
from .config import get_diagnostics_cfg, get_guardrails, get_targets
from .diagnostics import (evaluate_targets, evidence_sufficient,
                          root_cause_tree)
from .fixes import fixes_by_ids, get_fixes
from .kpis import aggregate_rows, compute_kpis

# Primary metric that defines "doing better long-term" at each level.
_PRIMARY = {
    "campaign": ["contribution_roas", "meta_roas", "cpa_meta"],
    "adset": ["cpa_meta", "meta_roas", "cvr_lpv_to_purchase"],
    "ad": ["ctr_link", "cpa_meta"],
}

_TREND_METRICS = ["cpm", "ctr_link", "cvr_lpv_to_purchase", "cpc_link",
                  "frequency", "cpa_meta", "meta_roas", "contribution_roas"]


def _profitability(kpis: dict[str, Any]) -> tuple[bool | None, str]:
    """Is this entity profitable by the best available configured yardstick?

    Returns (True/False/None, basis). None = cannot be confirmed (no targets,
    no margin) -> the engine will refuse to SCALE on trend alone.
    """
    targets = get_targets()
    contrib = kpis.get("contribution_after_ads")
    if contrib is not None:
        ctarget = targets.get("contribution_target")
        if ctarget is not None:
            return contrib >= ctarget, f"contribution_after_ads >= contribution_target ({ctarget})"
        return contrib > 0, "contribution_after_ads > 0"
    floor = targets.get("roas_floor")
    if floor and kpis.get("meta_roas") is not None:
        return kpis["meta_roas"] >= floor, f"meta_roas >= roas_floor ({floor})"
    cpa_t = targets.get("cpa_target")
    if cpa_t and kpis.get("cpa_meta") is not None:
        return kpis["cpa_meta"] <= cpa_t, f"cpa_meta <= cpa_target ({cpa_t})"
    return None, "no margin ratio or targets configured — profitability unconfirmed"


def _condition_tags(kpis: dict[str, Any], comparisons: dict[str, dict],
                    root: dict[str, Any]) -> list[str]:
    tags: set[str] = set()
    def adverse(m): return comparisons.get(m, {}).get("verdict") == "material_adverse"

    if root.get("primary_driver") == "tracking":
        tags.add("measurement_gate")
    if adverse("ctr_link"):
        tags.update(["ctr_down", "creative_fatigue"])
    if adverse("cpm") and comparisons.get("ctr_link", {}).get("verdict") != "material_adverse":
        tags.add("cpm_pressure")
    if adverse("cvr_lpv_to_purchase"):
        tags.update(["cvr_down", "offer_issue"])
    freq = kpis.get("frequency")
    if freq is not None and freq > 3.0:
        tags.add("frequency_high")
    if (kpis.get("meta_purchases") or 0) < 50:
        tags.add("learning_limited")
    return sorted(tags)


def _select_fix_ids(level: str, verdict: str, tags: list[str]) -> list[str]:
    ids: list[str] = []
    tagset = set(tags)
    if verdict == "SCALE":
        ids += [f["id"] for f in get_fixes("campaign", ["scale_ready"])]
    if "measurement_gate" in tagset:
        ids += [f["id"] for f in get_fixes("measurement")]
    if "learning_limited" in tagset:
        ids += [f["id"] for f in get_fixes("campaign", ["learning_limited"])]
        ids += [f["id"] for f in get_fixes("adset", ["learning_limited"])]
    if tagset & {"ctr_down", "creative_fatigue"}:
        ids += [f["id"] for f in get_fixes("ad", ["ctr_down", "creative_fatigue"])]
    if "cpm_pressure" in tagset:
        ids += [f["id"] for f in get_fixes("adset", ["cpm_pressure"])]
        ids += [f["id"] for f in get_fixes("ad", ["cpm_pressure"])]
    if tagset & {"cvr_down", "offer_issue"}:
        ids += [f["id"] for f in get_fixes("adset", ["cvr_down"])]
    if "frequency_high" in tagset:
        ids += [f["id"] for f in get_fixes("ad", ["frequency_high"])]
        ids += [f["id"] for f in get_fixes("adset", ["frequency_high"])]
    if verdict in ("FIX", "STOP") and "over_target" in tagset:
        ids += [f["id"] for f in get_fixes("adset", ["over_target"])]
        ids += [f["id"] for f in get_fixes("campaign", ["structure"])]
    # de-dupe, keep order, cap
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            out.append(i); seen.add(i)
    return out[:6]


def rolling_verdict(level: str, daily_rows: list[dict[str, Any]],
                    margin: float | None, recent_days: int = 7,
                    hours_since_last_edit: float | None = None) -> dict[str, Any]:
    """Produce a verdict for one entity from its daily insight rows.

    `hours_since_last_edit` (from the change log) enables the doc's cooldown
    rule: a fresh manual edit resets the learning phase, so we don't SCALE on
    top of it — we downgrade to recommendation-only until the cooldown passes.
    """
    rows = sorted(daily_rows, key=lambda r: r.get("date_start", ""))
    if len(rows) <= recent_days:
        return {"verdict": "HOLD", "reason": f"Only {len(rows)} days of data — need more than "
                f"recent_days={recent_days} to form a baseline.", "fixes": []}

    recent_rows, baseline_rows = rows[-recent_days:], rows[:-recent_days]
    recent = compute_kpis(aggregate_rows(recent_rows), margin)

    diag = get_diagnostics_cfg()
    guard = get_guardrails()
    targets = get_targets()
    thresh = {
        "cpm": diag.get("cpm_material_rise_pct", 0.20),
        "ctr_link": diag.get("ctr_material_drop_pct", 0.20),
        "cvr_lpv_to_purchase": diag.get("cvr_material_drop_pct", 0.20),
        "cpc_link": diag.get("ctr_material_drop_pct", 0.20),
        "frequency": 0.20,
        "cpa_meta": diag.get("cpa_over_target_pct", 0.15),
        "meta_roas": 0.15,
        "contribution_roas": 0.15,
    }
    comparisons = {m: compare_to_baseline(recent.get(m), baseline_rows, m,
                                          thresh.get(m, 0.20), margin)
                   for m in _TREND_METRICS}

    root = root_cause_tree(recent, comparisons)
    tags = _condition_tags(recent, comparisons, root)

    # overall long-term trend from the first available primary metric
    trend, trend_metric = "flat", None
    for m in _PRIMARY[level]:
        v = comparisons.get(m, {}).get("verdict")
        if v in ("material_favorable", "material_adverse"):
            trend = "improving" if v == "material_favorable" else "declining"
            trend_metric = m
            break

    evidence = evidence_sufficient(recent)
    target_eval = evaluate_targets(recent)
    profitable, prof_basis = _profitability(recent)

    over_target = any(c.get("status") == "over_target" for c in target_eval["checks"])
    if over_target:
        tags = sorted(set(tags) | {"over_target"})

    # stop-loss condition
    cpa = recent.get("cpa_meta")
    cpa_t = targets.get("cpa_target")
    min_mult = guard.get("min_spend_multiple", 3.0) or 3.0
    over_pct = diag.get("cpa_over_target_pct", 0.15)
    stop_loss = bool(
        cpa is not None and cpa_t and cpa > cpa_t * (1 + over_pct)
        and (recent.get("spend") or 0) >= cpa_t * min_mult
    )

    tracking_suspect = root.get("primary_driver") == "tracking"
    adverse = tracking_suspect or bool(set(tags) & {"ctr_down", "cvr_down", "cpm_pressure"}) \
        or trend == "declining"

    # ---- decision ordering -------------------------------------------------
    if tracking_suspect:
        verdict, reason = "FIX", ("Measurement gate: clicks present but no landing-page views. "
                                  "Fix tracking before any scaling.")
    elif not evidence["sufficient"]:
        verdict, reason = "HOLD", ("Below MIN_EVIDENCE — observe / recommend only. "
                                   f"{evidence['note'] or ''}").strip()
    elif stop_loss:
        verdict, reason = "STOP", (f"Stop-loss: CPA {cpa} is materially above target {cpa_t} with "
                                   f"spend past {min_mult}x the target. Reduce/pause per guardrail.")
    elif profitable is False or over_target:
        verdict, reason = "FIX", (f"Unprofitable vs configured target ({prof_basis}). "
                                  "Diagnose and correct before spending more.")
    elif adverse:
        driver = root["primary_driver"]
        driver_txt = ("overall efficiency down vs baseline; no single CPM/CTR/CVR driver isolated"
                      if driver == "no_material_driver" else f"driver: {driver}")
        verdict, reason = "FIX", f"Declining vs own baseline ({driver_txt}). Apply the matched fixes."
    elif trend == "improving" and profitable is True:
        verdict, reason = "SCALE", (f"Improving long-term ({trend_metric} favourable vs baseline) "
                                    f"and profitable ({prof_basis}). Scale within guardrails.")
    elif trend == "improving" and profitable is None:
        verdict, reason = "HOLD", ("Improving vs baseline but profitability is unconfirmed — set "
                                   "cpa_target/roas_floor or a contribution_margin_ratio to unlock SCALE.")
    else:
        verdict, reason = "HOLD", "Within normal range vs baseline; no material change to act on."

    # cooldown gate: a recent manual edit resets learning — don't stack a SCALE.
    cooldown_hours = guard.get("cooldown_hours", 24) or 24
    cooldown = {"hours_since_last_edit": hours_since_last_edit,
                "cooldown_hours": cooldown_hours, "applied": False}
    if (verdict == "SCALE" and hours_since_last_edit is not None
            and hours_since_last_edit < cooldown_hours):
        verdict = "HOLD"
        reason = (f"Would SCALE, but a manual edit {round(hours_since_last_edit, 1)}h ago is inside "
                  f"the {cooldown_hours}h cooldown (learning likely re-set). Recommendation-only until it clears.")
        cooldown["applied"] = True

    fix_ids = _select_fix_ids(level, verdict, tags)

    return {
        "verdict": verdict,
        "reason": reason,
        "cooldown": cooldown,
        "long_term_trend": trend,
        "trend_metric": trend_metric,
        "recent_window_days": recent_days,
        "baseline_days": len(baseline_rows),
        "condition_tags": tags,
        "primary_driver": root["primary_driver"],
        "profitability": {"profitable": profitable, "basis": prof_basis},
        "evidence": evidence,
        "target_evaluation": target_eval,
        "recent_kpis": recent,
        "creative_matrix": root["creative_matrix"],
        "fixes": fixes_by_ids(fix_ids),
        "gates_note": "Cooldown/inventory gates not enforced (no edit-time or inventory feed). "
                      "Measurement gate is heuristic until CAPI/backend reconciliation is wired.",
    }
