"""Weekly competitor scan over the Meta Ad Library (via the Meta Ads connector).

The server can't reach the connector (a claude.ai remote connector bound to the
user's session), so this module only (a) plans the ads_library_search calls the
calling model must make and (b) parses/filters/summarises the raw results it
hands back. Everything derived is observable in the Ad Library: ad counts, new
launches, longevity, headline/offer patterns. Never spend/CTR/CPA/ROAS.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONNECTOR_TOOL = "ads_library_search"

# Headline/page-name patterns -> offer & framing signals. Regex over public text only.
_SIGNALS: dict[str, re.Pattern[str]] = {
    "discount": re.compile(r"\b\d{1,2}\s?%\s?off\b|\bsave\s?\d{1,2}\s?%|\bdiscount\b", re.I),
    "free_bottle_or_gift": re.compile(r"free (bottle|gift|jar|bonus)|\bbonus\b", re.I),
    "multi_buy": re.compile(r"\bbogo\b|buy \d+,? get|\b\d\s?\+\s?\d\s?free", re.I),
    "guarantee": re.compile(r"money[- ]?back|guarantee|risk[- ]free", re.I),
    "free_shipping": re.compile(r"free shipping", re.I),
    "glp1_framing": re.compile(r"ozempic|glp-?1|wegovy|mounjaro", re.I),
    "dosage_headline": re.compile(r"\b\d{3,5}\s?mg\b", re.I),
    "expert_persona_page": re.compile(r"(,\s*(rn|md|np|phd)\b)|\bdr\.?\s|\bdoctor\b|\bnurse\b", re.I),
}


def _config_path() -> Path:
    raw = os.getenv("NUTRISULIN_COMPETITORS", "config/competitors.yaml")
    p = Path(raw)
    return p if p.is_absolute() else _PROJECT_ROOT / p


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    p = _config_path()
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def scan_plan() -> list[dict[str, Any]]:
    """The exact connector calls for this week's scan, one per query."""
    cfg = load_config()
    base = {"countries": cfg.get("countries") or ["US"],
            "ad_active_status": cfg.get("ad_active_status", "ACTIVE"),
            "limit": min(int(cfg.get("limit_per_query", 50)), 50)}
    plan: list[dict[str, Any]] = []
    for term in cfg.get("search_terms") or []:
        plan.append({"query_id": f"kw:{term}", "kind": "category",
                     "args": {**base, "search_terms": term}})
    for t in cfg.get("tracked") or []:
        if t.get("page_id"):
            args = {**base, "page_ids": [str(t["page_id"])]}
        else:
            args = {**base, "search_terms": t["name"]}
        plan.append({"query_id": f"brand:{t['name']}", "kind": "tracked",
                     "competitor": t["name"], "args": args})
    return plan


def parse_connector_output(raw: Any) -> list[dict[str, Any]]:
    """Accept the connector result in whatever shape the caller passes it:
    the full tool response ({"results": "<json string>"}), the decoded
    {"ads": [...]} object, a bare list of ads, or any of those as a string."""
    for _ in range(3):
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return []
        elif isinstance(raw, dict) and "ads" not in raw and "results" in raw:
            raw = raw["results"]
        else:
            break
    if isinstance(raw, dict):
        raw = raw.get("ads") or []
    return [a for a in raw if isinstance(a, dict) and a.get("id")] if isinstance(raw, list) else []


def _epoch_iso(v: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(v), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def classify(scans: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Flatten + filter connector results. Returns (kept ads, drop counts).
    Each kept ad carries `competitor` (tracked name or page name) and the
    query_ids it matched."""
    cfg = load_config()
    tracked_by_query = {f"brand:{t['name']}": t for t in cfg.get("tracked") or []}
    rel = [k.lower() for k in cfg.get("relevance_keywords") or []]
    excl = [k.lower() for k in cfg.get("exclude_page_names") or []]
    kept: dict[str, dict[str, Any]] = {}
    drops = {"own_page": 0, "off_topic": 0, "brand_mismatch": 0}

    for scan in scans:
        qid = str(scan.get("query_id") or "adhoc")
        tracked = tracked_by_query.get(qid)
        for ad in parse_connector_output(scan.get("results")):
            page = str(ad.get("page_name") or "")
            title = str(ad.get("ad_creative_link_title") or "")
            hay = f"{page} {title}".lower()
            if any(e in page.lower() for e in excl):
                drops["own_page"] += 1
                continue
            competitor = None
            if tracked:
                if tracked.get("page_id") or any(m.lower() in page.lower()
                                                 for m in tracked.get("match") or []):
                    competitor = tracked["name"]
                else:
                    drops["brand_mismatch"] += 1
                    continue
            elif not any(k in hay for k in rel):
                drops["off_topic"] += 1
                continue
            aid = str(ad["id"])
            row = kept.setdefault(aid, {
                "ad_id": aid, "page_id": str(ad.get("page_id") or ""), "page_name": page,
                "competitor": competitor or page, "link_title": title,
                "created_at": _epoch_iso(ad.get("ad_creation_time")),
                "delivery_start": _epoch_iso(ad.get("ad_delivery_start_time")),
                "snapshot_url": ad.get("ad_snapshot_url"), "queries": []})
            if competitor:  # a tracked match outranks a keyword-sweep label
                row["competitor"] = competitor
            row["queries"].append(qid)
    return list(kept.values()), drops


def signals_for(text: str) -> list[str]:
    return [k for k, rx in _SIGNALS.items() if rx.search(text or "")]


def days_running(delivery_start: str | None, now: datetime | None = None) -> int | None:
    if not delivery_start:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0, (now - datetime.fromisoformat(delivery_start)).days)


def summarize(ads: list[dict[str, Any]], scan_id: str) -> dict[str, Any]:
    """Per-competitor + category summary of the ads seen in one scan. `ads` are
    store rows (with first_scan_id) so 'new this week' is first-seen-this-scan."""
    durable = int(load_config().get("durable_ad_days", 30))
    now = datetime.now(timezone.utc)
    by: dict[str, dict[str, Any]] = {}
    sig_total: dict[str, int] = {}
    for a in ads:
        c = by.setdefault(a["competitor"], {
            "competitor": a["competitor"], "active_ads_seen": 0, "new_ads_this_scan": 0,
            "durable_ads": 0, "oldest_running_days": None, "headlines": {}, "signals": set(),
            "pages": set(), "examples": []})
        c["active_ads_seen"] += 1
        c["pages"].add(a["page_name"])
        if a.get("first_scan_id") == scan_id:
            c["new_ads_this_scan"] += 1
        d = days_running(a.get("delivery_start"), now)
        if d is not None:
            c["oldest_running_days"] = max(d, c["oldest_running_days"] or 0)
            if d >= durable:
                c["durable_ads"] += 1
        t = a.get("link_title") or ""
        if t:
            c["headlines"][t] = c["headlines"].get(t, 0) + 1
        for s in signals_for(f"{a['page_name']} {t}"):
            c["signals"].add(s)
            sig_total[s] = sig_total.get(s, 0) + 1
        if len(c["examples"]) < 2 and a.get("snapshot_url"):
            c["examples"].append(a["snapshot_url"])

    rows = []
    for c in by.values():
        heads = sorted(c.pop("headlines").items(), key=lambda kv: -kv[1])[:3]
        rows.append({**c, "top_headlines": [h for h, _ in heads],
                     "signals": sorted(c["signals"]), "pages": sorted(c["pages"])})
    rows.sort(key=lambda r: (-r["active_ads_seen"], r["competitor"]))
    return {"durable_ad_days": durable, "competitors": rows,
            "category_signal_counts": dict(sorted(sig_total.items(), key=lambda kv: -kv[1])),
            "ads_total": len(ads)}


def notes_from_summary(summary: dict[str, Any], max_competitors: int = 12) -> list[dict[str, Any]]:
    """competitor_notes rows (observable facts only) for the weekly report."""
    tracked = {t["name"] for t in load_config().get("tracked") or []}
    comps = summary["competitors"]
    chosen = [c for c in comps if c["competitor"] in tracked]
    chosen += [c for c in comps if c["competitor"] not in tracked][:max(0, max_competitors - len(chosen))]
    notes = []
    for c in chosen:
        parts = [f"{c['active_ads_seen']} active ads seen ({c['new_ads_this_scan']} new this scan)"]
        if c["oldest_running_days"] is not None:
            parts.append(f"oldest running {c['oldest_running_days']}d, "
                         f"{c['durable_ads']} running >={summary['durable_ad_days']}d")
        if c["top_headlines"]:
            parts.append("headlines: " + " | ".join(f"'{h}'" for h in c["top_headlines"]))
        if c["signals"]:
            parts.append("signals: " + ", ".join(c["signals"]))
        notes.append({"competitor": c["competitor"], "category": "creative",
                      "observation": "; ".join(parts), "source": "meta_ad_library_connector",
                      "url": (c["examples"] or [None])[0]})
    if summary["category_signal_counts"]:
        sig = ", ".join(f"{k} x{v}" for k, v in summary["category_signal_counts"].items())
        notes.append({"competitor": "Category pattern", "category": "general",
                      "observation": f"Across {summary['ads_total']} relevant active ads: {sig}",
                      "source": "meta_ad_library_connector"})
    return notes
