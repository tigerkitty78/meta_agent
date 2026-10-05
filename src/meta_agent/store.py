"""Local SQLite store: snapshots, rolling averages, and the change log.

Turns the previously-stateless server into one with memory, so we:
  - stop re-pulling + recomputing the same windows every call,
  - keep history longer than a single API call conveniently returns,
  - record every change (manual edits from Meta's Activity Log + a snapshot-diff
    backstop) so metric moves can be explained against what changed.

Single-process MCP server, so a connection-per-operation with WAL is plenty.
Nothing here talks to the network; callers pass already-fetched data in.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

from .config import db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    level TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_name TEXT,
    status TEXT,
    daily_budget REAL,
    lifetime_budget REAL,
    objective TEXT,
    optimization_goal TEXT,
    config_json TEXT,
    kpis_json TEXT,
    date_start TEXT,
    date_stop TEXT
);
CREATE INDEX IF NOT EXISTS ix_snap_entity ON snapshots(level, entity_id, captured_at);

CREATE TABLE IF NOT EXISTS rolling_averages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of TEXT NOT NULL,
    level TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_name TEXT,
    metric TEXT NOT NULL,
    window_days INTEGER NOT NULL,
    mean REAL, std REAL, n INTEGER, min REAL, max REAL
);
CREATE INDEX IF NOT EXISTS ix_roll_entity ON rolling_averages(level, entity_id, metric, window_days);

CREATE TABLE IF NOT EXISTS change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,              -- 'activity_log' | 'snapshot_diff'
    level TEXT,                        -- campaign | adset | ad | account | other
    object_type_raw TEXT,
    entity_id TEXT,
    entity_name TEXT,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    actor TEXT,
    is_manual INTEGER DEFAULT 1,       -- 0 for automated ('Meta') changes
    event_type TEXT,
    event_time TEXT,                   -- when the change happened (ISO)
    recorded_at TEXT,                  -- when we stored it (ISO)
    extra_json TEXT,
    dedupe_key TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_change_level_time ON change_log(level, event_time);
CREATE INDEX IF NOT EXISTS ix_change_entity ON change_log(entity_id, event_time);

CREATE TABLE IF NOT EXISTS meta_recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    iso_week TEXT,
    level TEXT,
    entity_id TEXT,
    entity_name TEXT,
    recommendation TEXT,
    flag TEXT,                         -- e.g. 'High CPR', 'opportunity'
    source TEXT,                       -- default 'ads_manager_ui' (UI-only, not in API)
    raw_json TEXT,
    dedupe_key TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_rec_time ON meta_recommendations(captured_at);

CREATE TABLE IF NOT EXISTS competitor_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    iso_week TEXT,
    competitor TEXT,
    category TEXT,                     -- creative | offer | price | general
    observation TEXT,
    source TEXT,                       -- ad_library_web | storefront | manual
    url TEXT,
    raw_json TEXT,
    dedupe_key TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_comp_time ON competitor_notes(captured_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _conn():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with _conn() as con:
        con.executescript(_SCHEMA)


# --- change log ------------------------------------------------------------
def insert_changes(rows: Iterable[dict[str, Any]]) -> int:
    """Insert change rows, skipping any whose dedupe_key already exists.
    Returns the count of newly-inserted rows."""
    init_db()
    new = 0
    with _conn() as con:
        for r in rows:
            try:
                con.execute(
                    """INSERT INTO change_log
                       (source, level, object_type_raw, entity_id, entity_name, field,
                        old_value, new_value, actor, is_manual, event_type, event_time,
                        recorded_at, extra_json, dedupe_key)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r.get("source"), r.get("level"), r.get("object_type_raw"),
                     r.get("entity_id"), r.get("entity_name"), r.get("field"),
                     _s(r.get("old_value")), _s(r.get("new_value")), r.get("actor"),
                     1 if r.get("is_manual", True) else 0, r.get("event_type"),
                     r.get("event_time"), _now(),
                     json.dumps(r.get("extra")) if r.get("extra") is not None else None,
                     r.get("dedupe_key")),
                )
                new += 1
            except sqlite3.IntegrityError:
                pass  # duplicate dedupe_key — already recorded
    return new


def get_changes(level: str | None = None, since: str | None = None,
                until: str | None = None, entity_id: str | None = None,
                manual_only: bool = False, limit: int = 500) -> list[dict[str, Any]]:
    init_db()
    q = "SELECT * FROM change_log WHERE 1=1"
    args: list[Any] = []
    if level and level != "all":
        q += " AND level = ?"; args.append(level)
    if entity_id:
        q += " AND entity_id = ?"; args.append(entity_id)
    if since:
        q += " AND event_time >= ?"; args.append(since)
    if until:
        q += " AND event_time <= ?"; args.append(until)
    if manual_only:
        q += " AND is_manual = 1"
    q += " ORDER BY event_time DESC LIMIT ?"; args.append(limit)
    with _conn() as con:
        return [dict(r) for r in con.execute(q, args).fetchall()]


def last_change_time(level: str, entity_id: str, manual_only: bool = True) -> str | None:
    init_db()
    q = "SELECT MAX(event_time) AS t FROM change_log WHERE level=? AND entity_id=?"
    args: list[Any] = [level, entity_id]
    if manual_only:
        q += " AND is_manual=1"
    with _conn() as con:
        row = con.execute(q, args).fetchone()
    return row["t"] if row and row["t"] else None


# --- snapshots -------------------------------------------------------------
def save_snapshot(level: str, entity_id: str, entity_name: str | None,
                  config: dict[str, Any], kpis: dict[str, Any] | None,
                  date_start: str | None = None, date_stop: str | None = None) -> None:
    init_db()
    with _conn() as con:
        con.execute(
            """INSERT INTO snapshots
               (captured_at, level, entity_id, entity_name, status, daily_budget,
                lifetime_budget, objective, optimization_goal, config_json, kpis_json,
                date_start, date_stop)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_now(), level, entity_id, entity_name,
             config.get("status") or config.get("effective_status"),
             _num(config.get("daily_budget")), _num(config.get("lifetime_budget")),
             config.get("objective"), config.get("optimization_goal"),
             json.dumps(config), json.dumps(kpis) if kpis is not None else None,
             date_start, date_stop),
        )


def latest_snapshot(level: str, entity_id: str) -> dict[str, Any] | None:
    init_db()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM snapshots WHERE level=? AND entity_id=? ORDER BY captured_at DESC LIMIT 1",
            (level, entity_id)).fetchone()
    return dict(row) if row else None


# --- rolling averages ------------------------------------------------------
def save_rolling(level: str, entity_id: str, entity_name: str | None,
                 metric: str, window_days: int, stats: dict[str, Any]) -> None:
    init_db()
    with _conn() as con:
        con.execute(
            """INSERT INTO rolling_averages
               (as_of, level, entity_id, entity_name, metric, window_days, mean, std, n, min, max)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (_now(), level, entity_id, entity_name, metric, window_days,
             stats.get("mean"), stats.get("std"), stats.get("n"),
             stats.get("min"), stats.get("max")),
        )


def latest_rolling(level: str, entity_id: str, metric: str,
                   window_days: int) -> dict[str, Any] | None:
    init_db()
    with _conn() as con:
        row = con.execute(
            """SELECT * FROM rolling_averages WHERE level=? AND entity_id=? AND metric=?
               AND window_days=? ORDER BY as_of DESC LIMIT 1""",
            (level, entity_id, metric, window_days)).fetchone()
    return dict(row) if row else None


def db_stats() -> dict[str, Any]:
    init_db()
    with _conn() as con:
        def c(t):
            return con.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
        last = con.execute("SELECT MAX(event_time) AS t FROM change_log").fetchone()["t"]
        return {"path": str(db_path()), "snapshots": c("snapshots"),
                "rolling_averages": c("rolling_averages"), "change_log": c("change_log"),
                "meta_recommendations": c("meta_recommendations"),
                "competitor_notes": c("competitor_notes"),
                "latest_change_event_time": last}


# --- UI-captured Meta recommendations & competitor notes -------------------
def _iso_week() -> str:
    y, w, _ = datetime.now(timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


def _dk(*parts: Any) -> str:
    return hashlib.sha1("|".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()


def insert_recommendations(rows: Iterable[dict[str, Any]]) -> int:
    """Store Ads-Manager UI recommendations. Deduped per entity+text+ISO week."""
    init_db(); new = 0; wk = _iso_week()
    with _conn() as con:
        for r in rows:
            key = r.get("dedupe_key") or _dk(r.get("level"), r.get("entity_id") or r.get("entity_name"),
                                             r.get("recommendation"), wk)
            try:
                con.execute(
                    """INSERT INTO meta_recommendations
                       (captured_at, iso_week, level, entity_id, entity_name, recommendation,
                        flag, source, raw_json, dedupe_key)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (_now(), wk, r.get("level", "campaign"), r.get("entity_id"), r.get("entity_name"),
                     r.get("recommendation"), r.get("flag"), r.get("source", "ads_manager_ui"),
                     json.dumps(r.get("raw")) if r.get("raw") is not None else None, key))
                new += 1
            except sqlite3.IntegrityError:
                pass
    return new


def get_recommendations(since: str | None = None, level: str | None = None,
                        entity_id: str | None = None, limit: int = 300) -> list[dict[str, Any]]:
    init_db(); q = "SELECT * FROM meta_recommendations WHERE 1=1"; a: list[Any] = []
    if since:
        q += " AND captured_at >= ?"; a.append(since)
    if level and level != "all":
        q += " AND level = ?"; a.append(level)
    if entity_id:
        q += " AND entity_id = ?"; a.append(entity_id)
    q += " ORDER BY captured_at DESC LIMIT ?"; a.append(limit)
    with _conn() as con:
        return [dict(r) for r in con.execute(q, a).fetchall()]


def insert_competitor_notes(rows: Iterable[dict[str, Any]]) -> int:
    """Store competitor observations. Deduped per competitor+text+ISO week."""
    init_db(); new = 0; wk = _iso_week()
    with _conn() as con:
        for r in rows:
            key = r.get("dedupe_key") or _dk(r.get("competitor"), r.get("category"),
                                             r.get("observation"), wk)
            try:
                con.execute(
                    """INSERT INTO competitor_notes
                       (captured_at, iso_week, competitor, category, observation, source, url,
                        raw_json, dedupe_key)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (_now(), wk, r.get("competitor"), r.get("category", "general"),
                     r.get("observation"), r.get("source", "manual"), r.get("url"),
                     json.dumps(r.get("raw")) if r.get("raw") is not None else None, key))
                new += 1
            except sqlite3.IntegrityError:
                pass
    return new


def get_competitor_notes(since: str | None = None, competitor: str | None = None,
                         limit: int = 300) -> list[dict[str, Any]]:
    init_db(); q = "SELECT * FROM competitor_notes WHERE 1=1"; a: list[Any] = []
    if since:
        q += " AND captured_at >= ?"; a.append(since)
    if competitor:
        q += " AND competitor = ?"; a.append(competitor)
    q += " ORDER BY captured_at DESC LIMIT ?"; a.append(limit)
    with _conn() as con:
        return [dict(r) for r in con.execute(q, a).fetchall()]


def _s(v: Any) -> str | None:
    if v is None:
        return None
    return v if isinstance(v, str) else json.dumps(v)


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
