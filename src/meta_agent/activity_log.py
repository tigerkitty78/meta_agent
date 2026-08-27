"""Meta Activity Log -> normalized change rows.

Meta's activity feed is the authoritative record of who changed what and when.
Its `object_type` uses LEGACY naming that does not match today's UI:

    CAMPAIGN_GROUP  -> campaign   (today's "campaign")
    CAMPAIGN        -> adset      (legacy: old "campaign" == today's ad set)
    ADGROUP         -> ad         (legacy: old "ad group" == today's ad)
    ACCOUNT         -> account

We store the raw type too, so nothing is lost if Meta returns modern names.
`actor_name == "Meta"` marks an automated change; everything else is a manual
edit by a person managing the account (which is what we mostly care about).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

_OBJECT_TYPE_TO_LEVEL = {
    # legacy names (what this account actually returns)
    "CAMPAIGN_GROUP": "campaign",
    "CAMPAIGN": "adset",
    "ADGROUP": "ad",
    "ACCOUNT": "account",
    # modern names, just in case a different endpoint/version returns them
    "AD": "ad",
    "AD_SET": "adset",
    "ADSET": "adset",
}


def object_type_to_level(object_type: str | None) -> str:
    return _OBJECT_TYPE_TO_LEVEL.get((object_type or "").upper(), "other")


def _dedupe_key(a: dict[str, Any]) -> str:
    """Stable identity for an activity event.

    Uses the meaningful fields (time, type, object, actor, old/new values)
    rather than the raw extra_data string — Meta may serialise extra_data with
    non-deterministic key order, which would otherwise produce duplicate rows.
    """
    extra = a.get("extra_data")
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except (ValueError, TypeError):
            extra = {"raw": extra}
    extra = extra or {}

    def scrub(v: Any) -> Any:
        # Meta re-signs CDN image URLs on every call (volatile _nc_* tokens), so
        # keep only the path and drop the query string; recurse into lists/dicts.
        if isinstance(v, str):
            return v.split("?", 1)[0] if "http" in v else v
        if isinstance(v, list):
            return [scrub(x) for x in v]
        if isinstance(v, dict):
            return {k: scrub(x) for k, x in v.items()}
        return v

    def canon(v: Any) -> str:
        v = scrub(v)
        if isinstance(v, (dict, list)):
            return json.dumps(v, sort_keys=True, default=str)
        return "" if v is None else str(v)

    parts = [str(a.get(k, "")) for k in ("event_time", "event_type", "object_id", "actor_id")]
    parts += [canon(extra.get(k)) for k in ("type", "old_value", "new_value")]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def normalize_activity(a: dict[str, Any]) -> dict[str, Any]:
    """Turn one raw activity row into a change_log row dict."""
    extra = a.get("extra_data")
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except (ValueError, TypeError):
            extra = {"raw": extra}
    extra = extra or {}

    actor = a.get("actor_name")
    return {
        "source": "activity_log",
        "level": object_type_to_level(a.get("object_type")),
        "object_type_raw": a.get("object_type"),
        "entity_id": a.get("object_id"),
        "entity_name": a.get("object_name"),
        "field": extra.get("type") or a.get("event_type"),
        "old_value": extra.get("old_value"),
        "new_value": extra.get("new_value"),
        "actor": actor,
        "is_manual": (actor or "").strip().lower() != "meta",
        "event_type": a.get("translated_event_type") or a.get("event_type"),
        "event_time": a.get("event_time"),
        "extra": extra,
        "dedupe_key": _dedupe_key(a),
    }


def normalize_many(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_activity(r) for r in rows]
