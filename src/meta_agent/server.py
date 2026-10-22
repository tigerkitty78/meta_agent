"""Nutrisulin Meta Ads agent — MCP server for Claude Desktop.

Read-only observation & diagnosis tools organised around the three measurement
phases from the design doc: campaign-level, ad-set-level and ad-level.

Run:  python -m meta_agent.server
(configured as an MCP server in claude_desktop_config.json — see README.)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import __version__
from .activity_log import normalize_many
from .baselines import baseline_stats, compare_to_baseline, daily_series
from .config import get_compliance, get_guardrails, load_economics
from .diagnostics import evaluate_targets, evidence_sufficient, root_cause_tree
from .fixes import DISCLAIMER, FIXES, get_fixes
from .gates import compute_gates, gates_audit_block
from .kpi_dictionary import KPI_DICTIONARY, LEVEL_FOCUS, kpis_for_level
from .kpis import aggregate_rows, compute_kpis
from .meta_client import (LEVEL_ID_FIELD, LEVEL_NAME_FIELD, MetaAPIError,
                          MetaClient)
from .profitability import contribution_margin_ratio, profitability_summary
from . import competitors, store
from .verdict import rolling_verdict

mcp = FastMCP("nutrisulin-meta-agent")
_client = MetaClient()

_VALID_LEVELS = ("campaign", "adset", "ad")


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)


def _err(msg: str) -> str:
    return _dump({"error": msg})


def _margin() -> float | None:
    ratio, _ = contribution_margin_ratio()
    return ratio


# ---------------------------------------------------------------------------
# Setup / configuration tools
# ---------------------------------------------------------------------------
@mcp.tool()
async def check_setup() -> str:
    """Verify Meta API access and report which config/data sources are wired.

    Call this first. Confirms the access token + ad account work, and lists
    what is still UNSPECIFIED (targets, economics) or not-yet-integrated
    (Shopify/GA4/CRM/inventory)."""
    econ = load_economics()
    report: dict[str, Any] = {"version": __version__}
    try:
        acct = await _client.verify_access()
        report["meta_access"] = "ok"
        report["account"] = {
            "id": _client.creds.ad_account_id,
            "name": acct.get("name"),
            "currency": acct.get("currency"),
            "timezone": acct.get("timezone_name"),
            "account_status": acct.get("account_status"),
        }
        report["attribution_windows"] = _client.creds.attribution_windows
    except MetaAPIError as exc:
        report["meta_access"] = "FAILED"
        report["meta_error"] = str(exc)

    targets = econ.get("targets", {}) or {}
    report["unspecified_targets"] = [k for k, v in targets.items() if v is None]
    ratio_val, ratio_note = contribution_margin_ratio()
    report["contribution_margin_ratio"] = ratio_val
    report["contribution_margin_note"] = ratio_note
    ext = econ.get("external_sources", {}) or {}
    report["not_yet_integrated"] = [k for k, v in ext.items() if v is None]
    report["reminder"] = ("Benchmarks are derived from your own baselines and configured "
                          "targets — no industry numbers are assumed.")
    return _dump(report)


@mcp.tool()
async def get_economics_config() -> str:
    """Show the configured targets, guardrails, contribution margin and
    breakeven ROAS (the agent's reward function and safety envelope)."""
    return _dump({
        "profitability": profitability_summary(),
        "decision_guardrails": get_guardrails(),
        "compliance": get_compliance(),
    })


@mcp.tool()
async def describe_kpis(level: str = "all") -> str:
    """Return the KPI dictionary: formula, monitoring cadence, benchmark source
    and interpretation for each metric. Optionally filter by 'campaign',
    'adset' or 'ad' to see that phase's focus and its KPIs."""
    if level != "all" and level not in _VALID_LEVELS:
        return _err(f"level must be one of all/{'/'.join(_VALID_LEVELS)}")
    if level == "all":
        return _dump({"levels": LEVEL_FOCUS, "kpis": KPI_DICTIONARY})
    keys = kpis_for_level(level)
    return _dump({
        "level": level,
        "focus": LEVEL_FOCUS[level],
        "kpis": {k: KPI_DICTIONARY[k] for k in keys},
    })


# ---------------------------------------------------------------------------
# Entity listing
# ---------------------------------------------------------------------------
@mcp.tool()
async def list_entities(level: str, active_only: bool = True, limit: int = 100) -> str:
    """List campaigns, ad sets, or ads with basic metadata (status, budget,
    objective). `level` is one of campaign / adset / ad."""
    if level not in _VALID_LEVELS:
        return _err(f"level must be one of {'/'.join(_VALID_LEVELS)}")
    try:
        status = ["ACTIVE"] if active_only else None
        rows = await _client.list_entities(level, limit=limit, effective_status=status)
    except MetaAPIError as exc:
        return _err(str(exc))
    return _dump({"level": level, "count": len(rows), "entities": rows})


# ---------------------------------------------------------------------------
# Core KPI tool — the three phases
# ---------------------------------------------------------------------------
@mcp.tool()
async def get_kpis(
    level: str,
    date_preset: str = "last_7d",
    entity_ids: list[str] | None = None,
    evaluate: bool = True,
) -> str:
    """Compute the full KPI set at a given phase (campaign / adset / ad).

    This is the main measurement tool. For each entity it returns the delivery,
    engagement, conversion and financial KPIs, plus (when evaluate=True) target
    checks against your configured CPA/ROAS/contribution and an evidence check.

    date_preset: Meta preset such as today, yesterday, last_7d, last_14d,
    last_28d, last_30d, last_90d, this_month, last_month, maximum.
    entity_ids: optionally restrict to specific campaign/adset/ad IDs.
    """
    if level not in _VALID_LEVELS:
        return _err(f"level must be one of {'/'.join(_VALID_LEVELS)}")
    try:
        rows = await _client.get_insights(level, date_preset=date_preset, entity_ids=entity_ids)
    except MetaAPIError as exc:
        return _err(str(exc))

    margin = _margin()
    id_field, name_field = LEVEL_ID_FIELD[level], LEVEL_NAME_FIELD[level]
    results = []
    for row in rows:
        kpis = compute_kpis(row, margin)
        entry: dict[str, Any] = {
            "id": row.get(id_field),
            "name": row.get(name_field),
            "date_range": {"since": row.get("date_start"), "until": row.get("date_stop")},
            "kpis": kpis,
        }
        if evaluate:
            entry["target_evaluation"] = evaluate_targets(kpis)
            entry["evidence"] = evidence_sufficient(kpis)
        results.append(entry)

    return _dump({
        "level": level,
        "phase_focus": LEVEL_FOCUS[level]["focus"],
        "date_preset": date_preset,
        "contribution_margin_ratio": margin,
        "count": len(results),
        "entities": results,
    })


# ---------------------------------------------------------------------------
# Diagnosis tool — baseline comparison + root cause
# ---------------------------------------------------------------------------
@mcp.tool()
async def diagnose_entity(
    level: str,
    entity_id: str,
    window_days: int = 28,
    recent_days: int = 3,
) -> str:
    """Diagnose ONE entity by comparing its recent performance to its OWN
    rolling baseline, then walking the root-cause tree and creative-diagnosis
    matrix from the design doc.

    Pulls daily insights over `window_days`; the last `recent_days` form the
    'current' reading and the earlier days form the baseline. Reports whether
    CPM / CTR / CVR moved materially and in a bad direction, the likely primary
    driver, and the recommended next step. Read-only — no changes are made.
    """
    if level not in _VALID_LEVELS:
        return _err(f"level must be one of {'/'.join(_VALID_LEVELS)}")
    try:
        daily = await _client.get_insights(
            level, date_preset=_preset_for_days(window_days),
            time_increment=1, entity_ids=[entity_id])
    except MetaAPIError as exc:
        return _err(str(exc))

    if not daily:
        return _err(f"No insights returned for {level} {entity_id} in the last {window_days} days.")

    # Meta returns daily rows in chronological order.
    daily.sort(key=lambda r: r.get("date_start", ""))
    if len(daily) <= recent_days:
        return _err(f"Only {len(daily)} days of data — need more than recent_days={recent_days} "
                    "to form a baseline. Reduce recent_days or wait for more data.")

    recent_rows = daily[-recent_days:]
    baseline_rows = daily[:-recent_days]
    margin = _margin()

    current_kpis = compute_kpis(aggregate_rows(recent_rows), margin)
    diag_cfg = load_economics().get("diagnostics", {}) or {}

    metrics_thresholds = {
        "cpm": diag_cfg.get("cpm_material_rise_pct", 0.20),
        "ctr_link": diag_cfg.get("ctr_material_drop_pct", 0.20),
        "cvr_lpv_to_purchase": diag_cfg.get("cvr_material_drop_pct", 0.20),
        "cpc_link": diag_cfg.get("ctr_material_drop_pct", 0.20),
        "frequency": 0.20,
    }
    comparisons: dict[str, Any] = {}
    for metric, thresh in metrics_thresholds.items():
        comparisons[metric] = compare_to_baseline(
            current_kpis.get(metric), baseline_rows, metric, thresh, margin)

    root = root_cause_tree(current_kpis, comparisons)
    name = recent_rows[-1].get(LEVEL_NAME_FIELD[level])

    return _dump({
        "level": level,
        "entity_id": entity_id,
        "name": name,
        "phase_focus": LEVEL_FOCUS[level]["focus"],
        "window_days": window_days,
        "recent_days": recent_days,
        "current_kpis": current_kpis,
        "target_evaluation": evaluate_targets(current_kpis),
        "evidence": evidence_sufficient(current_kpis),
        "baseline_comparisons": comparisons,
        "diagnosis": root,
        "note": "Rankings are diagnostic only and are never a stand-alone pause trigger.",
    })


# ---------------------------------------------------------------------------
# Account rollup
# ---------------------------------------------------------------------------
@mcp.tool()
async def account_summary(date_preset: str = "last_7d") -> str:
    """Account-wide KPI rollup for the period: totals + blended CPA/ROAS/
    contribution against configured targets. Good starting overview."""
    try:
        rows = await _client.get_insights("campaign", date_preset=date_preset)
    except MetaAPIError as exc:
        return _err(str(exc))
    margin = _margin()
    total_kpis = compute_kpis(aggregate_rows(rows), margin)
    return _dump({
        "date_preset": date_preset,
        "campaigns_included": len(rows),
        "blended_kpis": total_kpis,
        "target_evaluation": evaluate_targets(total_kpis),
        "profitability": profitability_summary(),
    })


@mcp.tool()
async def recommend_action(
    level: str,
    entity_id: str | None = None,
    window_days: int = 28,
    recent_days: int = 7,
    limit: int = 25,
) -> str:
    """Rolling-average SCALE / HOLD / FIX / STOP verdict + matched fixes.

    Compares each entity's RECENT `recent_days` window against its own prior
    baseline (the rest of `window_days`), then combines that trend with target
    checks, evidence and safety gates to recommend an action — and attaches the
    specific playbook fixes for the diagnosed condition.

    Pass `entity_id` for one campaign/adset/ad, or omit it to rank ALL active
    entities at that level (by spend, capped at `limit`). Read-only.
    """
    if level not in _VALID_LEVELS:
        return _err(f"level must be one of {'/'.join(_VALID_LEVELS)}")
    try:
        daily = await _client.get_insights(
            level, date_preset=_preset_for_days(window_days), time_increment=1,
            entity_ids=[entity_id] if entity_id else None)
    except MetaAPIError as exc:
        return _err(str(exc))
    if not daily:
        return _err(f"No insights for {level}"
                    + (f" {entity_id}" if entity_id else "") + f" in the last {window_days} days.")

    id_field, name_field = LEVEL_ID_FIELD[level], LEVEL_NAME_FIELD[level]
    groups: dict[str, list[dict]] = {}
    names: dict[str, str] = {}
    for row in daily:
        eid = row.get(id_field)
        if not eid:
            continue
        groups.setdefault(eid, []).append(row)
        names[eid] = row.get(name_field) or names.get(eid, "")

    margin = _margin()
    ranked = sorted(groups.items(),
                    key=lambda kv: sum(float(r.get("spend") or 0) for r in kv[1]),
                    reverse=True)[:limit]

    since_assoc, until_assoc = _period_dates(recent_days + 3)
    results = []
    for eid, rows in ranked:
        hrs = _hours_since(store.last_change_time(level, eid, manual_only=True))
        v = rolling_verdict(level, rows, margin, recent_days, hours_since_last_edit=hrs)
        # auto-attach the change-log association ONLY when there's an adverse
        # move to explain (FIX/STOP). SCALE/HOLD stay clean.
        if v.get("verdict") in ("FIX", "STOP"):
            v["change_association"] = _change_association(
                level, eid, since_assoc, until_assoc, metric=v.get("trend_metric"))
        results.append({"id": eid, "name": names.get(eid), **v})

    return _dump({
        "level": level,
        "phase_focus": LEVEL_FOCUS[level]["focus"],
        "window_days": window_days,
        "recent_days": recent_days,
        "contribution_margin_ratio": margin,
        "count": len(results),
        "verdict_legend": {
            "SCALE": "improving vs own baseline + profitable + enough evidence",
            "HOLD": "insufficient evidence, unconfirmed profitability, or no material change",
            "FIX": "declining vs baseline / unprofitable — apply matched fixes",
            "STOP": "materially over CPA target with enough spend (stop-loss)",
        },
        "entities": results,
    })


@mcp.tool()
async def get_fix_playbook(level: str = "all", tags: list[str] | None = None) -> str:
    """The Meta FIX playbook — researched, sourced best-practice fixes.

    `level`: all / campaign / adset / ad / measurement. `tags`: optionally
    filter to fixes matching a diagnosed condition (e.g. ctr_down, cpm_pressure,
    learning_limited, cvr_down, frequency_high, measurement_gate, scale_ready,
    over_target). No competitor/benchmark data is used."""
    valid = ("all", "campaign", "adset", "ad", "measurement")
    if level not in valid:
        return _err(f"level must be one of {'/'.join(valid)}")
    if level == "all" and not tags:
        return _dump({"disclaimer": DISCLAIMER, "playbook": FIXES})
    fixes = get_fixes(None if level == "all" else level, tags)
    return _dump({"disclaimer": DISCLAIMER, "level": level, "tags": tags,
                  "count": len(fixes), "fixes": fixes})


def _preset_for_days(days: int) -> str:
    """Map a day count to the nearest Meta date_preset that covers it."""
    for cutoff, preset in ((7, "last_7d"), (14, "last_14d"), (28, "last_28d"),
                           (30, "last_30d"), (90, "last_90d")):
        if days <= cutoff:
            return preset
    return "last_90d"


def _hours_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except (ValueError, TypeError):
        return None


def _period_dates(days: int) -> tuple[str, str]:
    until = datetime.now(timezone.utc).date()
    since = until - timedelta(days=days)
    return since.isoformat(), until.isoformat()


# ---------------------------------------------------------------------------
# Memory: snapshots, change log, effect analysis
# ---------------------------------------------------------------------------
@mcp.tool()
async def snapshot_now(level: str, kpi_preset: str = "last_7d",
                       baseline_days: int = 28) -> str:
    """Capture and STORE the current state of every active entity at a level:
    its config (status/budget/objective) + trailing KPIs + rolling-average
    baselines. Run this periodically so history accrues and later calls don't
    re-pull. Returns how much was stored."""
    if level not in _VALID_LEVELS:
        return _err(f"level must be one of {'/'.join(_VALID_LEVELS)}")
    try:
        entities = await _client.list_entities(level, effective_status=["ACTIVE"])
        kpi_rows = await _client.get_insights(level, date_preset=kpi_preset)
        daily = await _client.get_insights(
            level, date_preset=_preset_for_days(baseline_days), time_increment=1)
    except MetaAPIError as exc:
        return _err(str(exc))

    id_field, name_field = LEVEL_ID_FIELD[level], LEVEL_NAME_FIELD[level]
    margin = _margin()
    kpi_by_id = {r.get(id_field): r for r in kpi_rows}
    daily_by_id: dict[str, list[dict]] = {}
    for r in daily:
        daily_by_id.setdefault(r.get(id_field), []).append(r)

    metrics = ["cpm", "ctr_link", "cpc_link", "cvr_lpv_to_purchase", "cpa_meta",
               "meta_roas", "frequency"]
    snapped = 0
    rolling_written = 0
    for e in entities:
        eid = e.get("id")
        name = e.get("name")
        kpis = compute_kpis(kpi_by_id[eid], margin) if eid in kpi_by_id else None
        store.save_snapshot(level, eid, name, e, kpis)
        snapped += 1
        rows = daily_by_id.get(eid, [])
        for m in metrics:
            stats = baseline_stats(daily_series(rows, m, margin))
            if stats.get("n"):
                store.save_rolling(level, eid, name, m, baseline_days, stats)
                rolling_written += 1

    return _dump({
        "level": level, "snapshots_saved": snapped,
        "rolling_averages_saved": rolling_written,
        "baseline_days": baseline_days,
        "db": store.db_stats(),
    })


@mcp.tool()
async def record_changes(level: str = "all", days: int = 7) -> str:
    """Fetch and STORE all changes to campaigns/ad sets/ads over the period,
    then OUTPUT them. Manual edits come from Meta's Activity Log (actor +
    timestamp + old->new); a snapshot-diff backstop catches config changes vs
    the last snapshot. Dedupes, so re-running is safe.

    level: all / campaign / adset / ad. Use show_changes to view later."""
    valid = ("all",) + _VALID_LEVELS
    if level not in valid:
        return _err(f"level must be one of {'/'.join(valid)}")
    since, until = _period_dates(days)
    try:
        raw = await _client.get_activities(since=since, until=until)
    except MetaAPIError as exc:
        return _err(str(exc))

    rows = normalize_many(raw)
    if level != "all":
        rows = [r for r in rows if r["level"] == level]
    new_count = store.insert_changes(rows)

    # snapshot-diff backstop (config changes vs last stored snapshot)
    diff_rows = await _snapshot_diff(level, since)
    diff_new = store.insert_changes(diff_rows) if diff_rows else 0

    stored = store.get_changes(level=None if level == "all" else level,
                               since=since, until=until, limit=500)
    return _dump({
        "period": {"since": since, "until": until, "days": days},
        "level": level,
        "activity_log_events_fetched": len(rows),
        "newly_stored": new_count + diff_new,
        "snapshot_diff_changes": diff_new,
        "changes": _fmt_changes(stored),
        "note": "Manual edits from Activity Log; is_manual=false means Meta automated the change.",
    })


@mcp.tool()
async def show_changes(level: str = "all", days: int = 7,
                       entity_id: str | None = None, manual_only: bool = True) -> str:
    """Show previously-recorded changes (run record_changes first to populate).
    Filter by level (all/campaign/adset/ad), an entity_id, and manual-only."""
    valid = ("all",) + _VALID_LEVELS
    if level not in valid:
        return _err(f"level must be one of {'/'.join(valid)}")
    since, until = _period_dates(days)
    rows = store.get_changes(level=None if level == "all" else level, since=since,
                             until=until, entity_id=entity_id, manual_only=manual_only)
    return _dump({
        "period": {"since": since, "until": until, "days": days},
        "level": level, "manual_only": manual_only, "count": len(rows),
        "changes": _fmt_changes(rows),
    })


@mcp.tool()
async def explain_metric_move(level: str, entity_id: str, metric: str = "cpa_meta",
                              window_days: int = 14, recent_days: int = 3) -> str:
    """Explain a recent rise/drop in a metric by cross-referencing the change
    log — as a CAUTIOUS ASSOCIATION, not proof of cause.

    Compares the entity's recent window vs its own baseline for `metric`, lists
    manual changes in the window, and flags confounders (learning-phase reset
    from an edit, seasonality, multiple simultaneous edits)."""
    if level not in _VALID_LEVELS:
        return _err(f"level must be one of {'/'.join(_VALID_LEVELS)}")
    try:
        daily = await _client.get_insights(
            level, date_preset=_preset_for_days(window_days), time_increment=1,
            entity_ids=[entity_id])
    except MetaAPIError as exc:
        return _err(str(exc))
    if len(daily) <= recent_days:
        return _err(f"Not enough daily data ({len(daily)}) for {entity_id}.")

    daily.sort(key=lambda r: r.get("date_start", ""))
    margin = _margin()
    recent = compute_kpis(aggregate_rows(daily[-recent_days:]), margin)
    diag = load_economics().get("diagnostics", {}) or {}
    thresh = {"cpm": diag.get("cpm_material_rise_pct", 0.2),
              "ctr_link": diag.get("ctr_material_drop_pct", 0.2),
              "cvr_lpv_to_purchase": diag.get("cvr_material_drop_pct", 0.2),
              "cpa_meta": diag.get("cpa_over_target_pct", 0.15)}.get(metric, 0.2)
    move = compare_to_baseline(recent.get(metric), daily[:-recent_days], metric, thresh, margin)

    since, until = _period_dates(window_days)
    verb = {"material_adverse": "moved adversely", "material_favorable": "moved favorably",
            "within_normal_range": "did not move materially",
            "insufficient_data": "has insufficient data"}.get(move.get("verdict"), "changed")
    assoc = _change_association(level, entity_id, since, until, metric=metric, move=move)
    return _dump({
        "level": level, "entity_id": entity_id, "metric": metric,
        "finding": f"{metric} {verb} vs the entity's own baseline.",
        **assoc,
    })


async def _snapshot_diff(level: str, since: str) -> list[dict]:
    """Backstop: compare current config to the last stored snapshot; emit
    config-change rows for budget/status/name so we catch edits even if the
    Activity Log is incomplete. Only runs for concrete levels (not 'all')."""
    levels = _VALID_LEVELS if level == "all" else (level,)
    out: list[dict] = []
    for lvl in levels:
        try:
            entities = await _client.list_entities(lvl, effective_status=None)
        except MetaAPIError:
            continue
        for e in entities:
            eid = e.get("id")
            prev = store.latest_snapshot(lvl, eid)
            if not prev:
                continue
            for field, newv, oldv in (
                ("status", e.get("status"), prev.get("status")),
                ("daily_budget", e.get("daily_budget"), prev.get("daily_budget")),
                ("name", e.get("name"), prev.get("entity_name")),
            ):
                if newv is not None and oldv is not None and str(newv) != str(oldv):
                    out.append({
                        "source": "snapshot_diff", "level": lvl, "object_type_raw": None,
                        "entity_id": eid, "entity_name": e.get("name"), "field": field,
                        "old_value": oldv, "new_value": newv, "actor": "unknown (diff)",
                        "is_manual": True, "event_type": f"diff_{field}_change",
                        "event_time": since, "extra": {"detected_by": "snapshot_diff"},
                        "dedupe_key": f"diff|{lvl}|{eid}|{field}|{oldv}|{newv}",
                    })
    return out


def _change_association(level: str, entity_id: str, since: str, until: str,
                        metric: str | None = None, move: dict | None = None) -> dict[str, Any]:
    """Cross-reference an entity's logged manual changes with a metric move —
    a CAUTIOUS ASSOCIATION with confounder flags, never causal proof. Shared by
    explain_metric_move and recommend_action (FIX/STOP). Local DB only."""
    changes = store.get_changes(level=None if level == "all" else level,
                                entity_id=entity_id, since=since, until=until, manual_only=True)
    confounders = ["Meta attribution lag: purchases/value keep updating for days.",
                   "Seasonality / auction shifts are not controlled for."]
    if any((c.get("field") or "").find("run_status") >= 0
           or "status" in (c.get("event_type") or "").lower() for c in changes):
        confounders.append("A run-status/edit in the window likely reset the learning phase — "
                           "expect temporary CPA/CPM elevation regardless of the edit's merit.")
    if len(changes) > 1:
        confounders.append(f"{len(changes)} changes in the window — effects cannot be separated "
                           "without a controlled test.")
    if changes:
        assoc = f"{len(changes)} manual change(s) recorded near this move — possible association only."
    else:
        assoc = (f"No manual changes recorded at the {level} level in this window "
                 "(child ad/ad-set edits are logged under their own IDs).")
    out: dict[str, Any] = {
        "association": assoc,
        "changes_in_window": _fmt_changes(changes),
        "confounders": confounders,
        "caveat": "Observational before/after association, NOT causal proof. Use a controlled "
                  "A/B or conversion-lift test to establish cause.",
    }
    if metric:
        out["metric"] = metric
    if move is not None:
        out["move"] = move
    return out


def _fmt_changes(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        out.append({
            "when": r.get("event_time"),
            "level": r.get("level"),
            "entity": r.get("entity_name") or r.get("entity_id"),
            "entity_id": r.get("entity_id"),
            "change": r.get("event_type"),
            "field": r.get("field"),
            "old": r.get("old_value"),
            "new": r.get("new_value"),
            "by": r.get("actor"),
            "manual": bool(r.get("is_manual", 1)),
            "source": r.get("source"),
        })
    return out


@mcp.tool()
async def store_meta_recommendations(recommendations: list[dict]) -> str:
    """Save Meta Ads Manager's on-screen recommendations so the weekly report
    can include them. These ('High CPR', 'N recommendations', Opportunity-score
    hints) are UI-ONLY — not in the Marketing API — so they must be captured
    from the Ads Manager screen (via the browser) and persisted here.

    Each item: {entity_name, recommendation, and optionally entity_id, level
    (campaign/adset/ad), flag}. Deduped per entity+text+ISO week, so re-running
    the same week won't pile up duplicates."""
    if not recommendations:
        return _err("No recommendations provided. Capture them from Ads Manager first.")
    n = store.insert_recommendations(recommendations)
    return _dump({"received": len(recommendations), "stored_new": n,
                  "source": "ads_manager_ui (browser-captured; not available via API)",
                  "note": "Included automatically in weekly_report."})


@mcp.tool()
async def show_meta_recommendations(days: int = 14, level: str = "all",
                                    entity_id: str | None = None) -> str:
    """Show stored Ads-Manager recommendations captured in the last `days`."""
    since, _ = _period_dates(days)
    rows = store.get_recommendations(since=since, level=level, entity_id=entity_id)
    return _dump({"since": since, "level": level, "count": len(rows),
                  "recommendations": [{
                      "when": r["captured_at"], "level": r["level"],
                      "entity": r["entity_name"] or r["entity_id"],
                      "recommendation": r["recommendation"], "flag": r["flag"],
                      "source": r["source"]} for r in rows]})


@mcp.tool()
async def store_competitor_notes(notes: list[dict]) -> str:
    """Save MANUAL competitor observations for the weekly report — e.g.
    storefront pricing/offers or ad body copy read off the Ad Library site.
    (Ad Library ads themselves are pulled weekly via competitor_scan_plan ->
    connector -> ingest_ad_library_results.) Keep it to OBSERVABLE facts —
    never claimed competitor CPA/CTR/ROAS.

    Each item: {competitor, observation, and optionally category
    (creative/offer/price/general), source (ad_library_web/storefront/manual),
    url}. Deduped per competitor+text+ISO week."""
    if not notes:
        return _err("No competitor notes provided.")
    n = store.insert_competitor_notes(notes)
    return _dump({"received": len(notes), "stored_new": n,
                  "note": "Included automatically in weekly_report. Observable facts only — "
                          "no competitor performance metrics (not knowable)."})


@mcp.tool()
async def show_competitor_notes(days: int = 30, competitor: str | None = None) -> str:
    """Show stored competitor observations captured in the last `days`."""
    since, _ = _period_dates(days)
    rows = store.get_competitor_notes(since=since, competitor=competitor)
    return _dump({"since": since, "count": len(rows), "competitor_notes": [{
        "when": r["captured_at"], "competitor": r["competitor"], "category": r["category"],
        "observation": r["observation"], "source": r["source"], "url": r["url"]} for r in rows]})


_SCAN_STEPS = (
    "1) For EACH item in `plan`, call the Meta Ads connector tool "
    f"`{competitors.CONNECTOR_TOOL}` with exactly `args` (advertiser_job="
    "creative_insights_and_ideas). 2) Call ingest_ad_library_results ONCE with "
    "scans=[{query_id, results: <the connector's raw response>}, ...] covering every "
    "query, including ones that returned no ads. 3) Then call weekly_report.")


@mcp.tool()
async def competitor_scan_plan() -> str:
    """WEEKLY RUN, STEP 1 (competitor data). Returns the Meta Ad Library queries
    for this week's NutriSulin competitor scan (category keyword sweeps +
    tracked brands from config/competitors.yaml). This server can't reach the
    Meta Ads connector itself; the caller runs each query through the
    connector's ads_library_search tool and hands the raw results to
    ingest_ad_library_results."""
    plan = competitors.scan_plan()
    if not plan:
        return _err("No queries configured: add search_terms/tracked to config/competitors.yaml.")
    last = store.latest_ad_library_scan()
    return _dump({"iso_week": store.current_iso_week(),
                  "last_scan": {"scanned_at": last["scanned_at"], "iso_week": last["iso_week"]}
                               if last else None,
                  "connector_tool": competitors.CONNECTOR_TOOL,
                  "plan": plan, "steps": _SCAN_STEPS})


@mcp.tool()
async def ingest_ad_library_results(scans: list[dict]) -> str:
    """WEEKLY RUN, STEP 2 (competitor data). Ingest raw Meta Ad Library results
    pulled through the Meta Ads connector (ads_library_search).

    `scans`: [{query_id (from competitor_scan_plan), results (the connector's
    raw response: as returned, or its decoded {"ads": [...]})}, ...].

    Filters off-topic and own-page ads, stores every ad (tracking first-seen so
    new launches are visible week over week), summarises per competitor (active
    ads, new this scan, longevity, headline & offer signals) and refreshes this
    week's competitor_notes so weekly_report includes them. Observable Ad
    Library facts only; competitor spend/CTR/CPA/ROAS aren't public."""
    if not scans:
        return _err("No scans provided. Run competitor_scan_plan and the connector queries first.")
    ads, drops = competitors.classify(scans)
    raw_total = sum(len(competitors.parse_connector_output(s.get("results"))) for s in scans)
    scan_id = f"{store.current_iso_week()}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"
    query_ids = [str(s.get("query_id")) for s in scans]
    store.record_ad_library_scan(scan_id, query_ids, ads, drops)
    summary = competitors.summarize(store.get_scan_ads(scan_id), scan_id)
    store.set_scan_summary(scan_id, summary)
    n = store.replace_week_notes("meta_ad_library_connector",
                                 competitors.notes_from_summary(summary))
    planned = {p["query_id"] for p in competitors.scan_plan()}
    return _dump({"scan_id": scan_id, "ads_received": raw_total, "ads_kept": len(ads),
                  "dropped": drops, "missing_queries": sorted(planned - set(query_ids)),
                  "competitor_notes_written": n, "summary": summary,
                  "note": "Included automatically in weekly_report (competitor_scan section)."})


def _competitor_scan_section() -> dict[str, Any]:
    last = store.latest_ad_library_scan()
    week = store.current_iso_week()
    if not last or last["iso_week"] != week:
        return {"status": "STALE" if last else "NEVER_RUN",
                "last_scanned_at": last["scanned_at"] if last else None,
                "pre_run_required": ("Competitor data is not from this ISO week. Before "
                                     "presenting the report: call competitor_scan_plan, run its "
                                     "queries through the Meta Ads connector, call "
                                     "ingest_ad_library_results, then call weekly_report again."),
                "steps": _SCAN_STEPS}
    summary = json.loads(last["summary_json"] or "{}")
    return {"status": "FRESH", "scanned_at": last["scanned_at"], "iso_week": last["iso_week"],
            "ads_kept": last["ads_kept"], "dropped": json.loads(last["drops_json"] or "{}"),
            "category_signal_counts": summary.get("category_signal_counts"),
            "competitors": [{k: c[k] for k in ("competitor", "active_ads_seen", "new_ads_this_scan",
                                               "durable_ads", "oldest_running_days",
                                               "top_headlines", "signals", "examples")}
                            for c in summary.get("competitors", [])[:15]],
            "caveat": ("Ad Library shows what competitors run, not how it performs. "
                       "Longevity (durable ads) is the only public proxy for a working ad.")}


@mcp.tool()
async def weekly_report(date_preset: str = "last_7d", include_verdicts: bool = True,
                        total_store_revenue: float | None = None) -> str:
    """The Meta weekly analysis, assembled in one call: the six funnel GATES
    (Visibility -> Click -> Conversion -> Paid Efficiency -> Ad Dependency ->
    Profit) with their atomic values and exact formulas, blended account KPIs vs
    targets, per-campaign SCALE/HOLD/FIX/STOP verdicts, the manual-change digest,
    plus the browser-captured Meta recommendations and competitor notes.

    `total_store_revenue` (optional): pass your TOTAL store revenue (organic +
    paid) for the period to unlock the TACoS gate — Meta can't provide it.

    COMPETITOR STEP (run first each week): competitor data comes from the Meta
    Ad Library via the Meta Ads connector, which this server can't call. If
    `competitor_scan.status` isn't FRESH, run competitor_scan_plan -> the
    connector's ads_library_search per query -> ingest_ad_library_results,
    then call weekly_report again. Report the competitor_scan section as its
    own "Competitor ads (Meta Ad Library)" block.

    The recommendations section reflects whatever was last captured via
    store_meta_recommendations (Ads Manager UI only, browser-captured)."""
    try:
        daily = await _client.get_insights("campaign", date_preset="last_28d", time_increment=1)
    except MetaAPIError as exc:
        return _err(str(exc))

    margin = _margin()
    id_field, name_field = LEVEL_ID_FIELD["campaign"], LEVEL_NAME_FIELD["campaign"]
    groups: dict[str, list[dict]] = {}
    names: dict[str, str] = {}
    for r in daily:
        eid = r.get(id_field)
        if not eid:
            continue
        groups.setdefault(eid, []).append(r)
        names[eid] = r.get(name_field) or names.get(eid, "")

    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()
    recent_rows = [r for r in daily if (r.get("date_start") or "") >= cutoff]
    blended = compute_kpis(aggregate_rows(recent_rows), margin) if recent_rows else {}

    verdicts = []
    if include_verdicts:
        ranked = sorted(groups.items(),
                        key=lambda kv: sum(float(r.get("spend") or 0) for r in kv[1]), reverse=True)
        for eid, rows in ranked:
            hrs = _hours_since(store.last_change_time("campaign", eid, manual_only=True))
            v = rolling_verdict("campaign", rows, margin, 7, hours_since_last_edit=hrs)
            recent_c = [r for r in rows if (r.get("date_start") or "") >= cutoff]
            gates = compute_gates(aggregate_rows(recent_c), margin, total_store_revenue) if recent_c else None
            verdicts.append({"id": eid, "name": names.get(eid), "verdict": v.get("verdict"),
                             "reason": v.get("reason"), "long_term_trend": v.get("long_term_trend"),
                             "top_fixes": [f["fix"] for f in v.get("fixes", [])[:2]],
                             "gates": gates})

    since7, _ = _period_dates(7)
    changes = store.get_changes(since=since7, manual_only=True, limit=500)
    by_actor: dict[str, int] = {}
    for c in changes:
        by_actor[c.get("actor")] = by_actor.get(c.get("actor"), 0) + 1

    recs = store.get_recommendations(since=_period_dates(14)[0])
    notes = store.get_competitor_notes(since=_period_dates(30)[0])

    gates_blended = compute_gates(aggregate_rows(recent_rows), margin,
                                  total_store_revenue) if recent_rows else None

    return _dump({
        "generated": datetime.now(timezone.utc).isoformat(),
        "period": date_preset,
        "gates_audit": gates_audit_block(gates_blended, "GATES (audit) — blended, last 7 days")
                       if gates_blended else None,
        "gates_blended": gates_blended,
        "blended_kpis": blended,
        "target_evaluation": evaluate_targets(blended) if blended else {},
        "profitability": profitability_summary(),
        "campaign_verdicts": verdicts,
        "change_digest": {"manual_changes_7d": len(changes), "by_actor": by_actor},
        "meta_recommendations": [{"entity": r["entity_name"] or r["entity_id"],
                                  "recommendation": r["recommendation"], "flag": r["flag"],
                                  "when": r["captured_at"]} for r in recs],
        "competitor_scan": _competitor_scan_section(),
        "competitor_notes": [{"competitor": r["competitor"], "category": r["category"],
                              "observation": r["observation"], "source": r["source"],
                              "url": r["url"], "when": r["captured_at"]} for r in notes],
        "capture_reminder": ("meta_recommendations are browser-captured (Ads Manager UI only); "
                             "refresh via store_meta_recommendations if stale. Competitor data: "
                             "see competitor_scan.status."),
    })


@mcp.tool()
async def explain_gates(level: str = "campaign", entity_id: str | None = None,
                        date_preset: str = "last_7d",
                        total_store_revenue: float | None = None) -> str:
    """The six funnel GATES (Visibility, Click, Conversion, Paid Efficiency/ACoS,
    Ad Dependency/TACoS, Profit) with FULL transparency: for each, the atomic
    Meta fields used, the formula, and the exact numbers substituted.

    Omit entity_id for the blended account view, or pass one campaign/adset/ad.
    `total_store_revenue` (optional) unlocks the TACoS gate (Meta can't supply
    total organic+paid revenue). Profit needs contribution_margin_ratio in config."""
    if level not in _VALID_LEVELS:
        return _err(f"level must be one of {'/'.join(_VALID_LEVELS)}")
    try:
        rows = await _client.get_insights(level, date_preset=date_preset,
                                          entity_ids=[entity_id] if entity_id else None)
    except MetaAPIError as exc:
        return _err(str(exc))
    if not rows:
        return _err(f"No insights for {level}"
                    + (f" {entity_id}" if entity_id else "") + f" in {date_preset}.")
    margin = _margin()
    agg = aggregate_rows(rows)
    result = compute_gates(agg, margin, total_store_revenue)
    label = f"GATES (audit) — {entity_id or 'blended'} ({date_preset})"
    return _dump({
        "level": level, "entity_id": entity_id, "date_preset": date_preset,
        "entities_aggregated": len(rows),
        "contribution_margin_ratio": margin,
        "total_store_revenue_supplied": total_store_revenue,
        "gates_audit": gates_audit_block(result, label),
        **result,
    })


BREAKDOWN_MAP = {
    "placement": ["publisher_platform", "platform_position"],
    "platform": ["publisher_platform"],
    "device": ["impression_device"],
    "demographic": ["age", "gender"],
    "country": ["country"],
    "hour": ["hourly_stats_aggregated_by_advertiser_time_zone"],
}


@mcp.tool()
async def breakdown_kpis(by: str = "placement", level: str = "campaign",
                         entity_id: str | None = None, date_preset: str = "last_7d",
                         limit: int = 15) -> str:
    """Split performance by a dimension the blended KPIs hide, and compare each
    segment to the blended average.

    `by`: placement (FB/IG x Feed/Reels/Stories) · platform · device ·
    demographic (age+gender) · country · hour. Raw CTR is NOT comparable across
    Reels, Feed and Stories, so each segment also carries its % difference from
    the blended average (cpm/cpa: lower is better; ctr/roas: higher is better).

    `level` is campaign/adset/ad. Omit `entity_id` for an account-wide view
    (all entities at that level, aggregated by the breakdown)."""
    if by not in BREAKDOWN_MAP:
        return _err(f"by must be one of {'/'.join(BREAKDOWN_MAP)}")
    if level not in _VALID_LEVELS:
        return _err(f"level must be one of {'/'.join(_VALID_LEVELS)}")
    dims = BREAKDOWN_MAP[by]
    try:
        rows = await _client.get_insights(
            level, date_preset=date_preset, breakdowns=dims,
            entity_ids=[entity_id] if entity_id else None)
    except MetaAPIError as exc:
        return _err(str(exc))
    if not rows:
        return _err(f"No insights for a {by} breakdown ({level}, {date_preset}).")

    margin = _margin()
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        key = tuple(r.get(d) for d in dims)
        groups.setdefault(key, []).append(r)
    blended = compute_kpis(aggregate_rows(rows), margin)

    def _delta(seg: float | None, base: float | None) -> float | None:
        if seg is None or not base:
            return None
        return round((seg - base) / base, 3)

    segments = []
    for key, rs in groups.items():
        k = compute_kpis(aggregate_rows(rs), margin)
        segments.append({
            "segment": " · ".join("?" if x is None else str(x) for x in key),
            "spend": k["spend"], "impressions": k["impressions"],
            "ctr_link": k["ctr_link"], "cpm": k["cpm"], "cpc_link": k["cpc_link"],
            "cvr_lpv_to_purchase": k["cvr_lpv_to_purchase"],
            "meta_purchases": k["meta_purchases"], "cpa_meta": k["cpa_meta"],
            "meta_roas": k["meta_roas"],
            "vs_blended": {
                "cpm_delta_pct": _delta(k["cpm"], blended["cpm"]),
                "ctr_link_delta_pct": _delta(k["ctr_link"], blended["ctr_link"]),
                "cpa_delta_pct": _delta(k["cpa_meta"], blended["cpa_meta"]),
                "roas_delta_pct": _delta(k["meta_roas"], blended["meta_roas"]),
            },
        })
    segments.sort(key=lambda s: s["spend"], reverse=True)

    return _dump({
        "by": by, "breakdowns": dims, "level": level, "entity_id": entity_id,
        "date_preset": date_preset, "contribution_margin_ratio": margin,
        "segments_count": len(segments),
        "blended": {k: blended[k] for k in
                    ("spend", "ctr_link", "cpm", "cpc_link", "cpa_meta", "meta_roas")},
        "segments": segments[:limit],
        "note": "vs_blended = % difference from the blended average. cpm/cpa lower is "
                "better; ctr/roas higher is better. Ranking fields are omitted by Meta "
                "when a breakdown is applied.",
    })


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
