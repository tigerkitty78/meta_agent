"""Thin async wrapper over the Meta Marketing (Graph) API.

Only read endpoints are used in this build: entity listing + insights. Write
endpoints (budget/status edits) are intentionally NOT implemented yet — the
first production stage is observation / diagnosis only.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

# httpx logs each request URL at INFO — which includes the access_token query
# param. Keep it at WARNING so tokens never land in MCP/Desktop logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

from .config import MetaCredentials, load_credentials

# Fields requested from the insights endpoint. Kept in one place so the KPI
# layer and the client never disagree about what was fetched.
INSIGHTS_FIELDS = [
    "campaign_id", "campaign_name",
    "adset_id", "adset_name",
    "ad_id", "ad_name",
    "date_start", "date_stop",
    "spend", "impressions", "reach", "frequency",
    "clicks", "inline_link_clicks",
    "cpc", "cpm", "ctr", "inline_link_click_ctr",
    "actions", "action_values",
    "purchase_roas",
    "quality_ranking", "engagement_rate_ranking", "conversion_rate_ranking",
]

LEVEL_ID_FIELD = {"campaign": "campaign_id", "adset": "adset_id", "ad": "ad_id"}
LEVEL_NAME_FIELD = {"campaign": "campaign_name", "adset": "adset_name", "ad": "ad_name"}


class MetaAPIError(RuntimeError):
    """Raised when the Graph API returns an error payload."""


class MetaClient:
    def __init__(self, creds: MetaCredentials | None = None) -> None:
        self.creds = creds or load_credentials()
        self.base = f"https://graph.facebook.com/{self.creds.api_version}"

    # -- low level ----------------------------------------------------------
    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.creds.is_configured:
            raise MetaAPIError(
                "Meta access token is not configured. Copy .env.example to .env "
                "and set META_ACCESS_TOKEN and META_AD_ACCOUNT_ID."
            )
        params = {**params, "access_token": self.creds.access_token}
        url = f"{self.base}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, params=params)
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise MetaAPIError(f"Non-JSON response ({resp.status_code}): {resp.text[:300]}") from exc
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            raise MetaAPIError(
                f"Graph API error {err.get('code')}: {err.get('message')} "
                f"(type={err.get('type')})"
            )
        return data

    async def _get_all_pages(self, path: str, params: dict[str, Any],
                             max_pages: int = 25) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        data = await self._get(path, params)
        rows.extend(data.get("data", []))
        pages = 1
        while pages < max_pages:
            nxt = data.get("paging", {}).get("next")
            if not nxt:
                break
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(nxt)
            data = resp.json()
            if isinstance(data, dict) and data.get("error"):
                break
            rows.extend(data.get("data", []))
            pages += 1
        return rows

    # -- entities -----------------------------------------------------------
    async def list_entities(self, level: str, limit: int = 200,
                            effective_status: list[str] | None = None) -> list[dict[str, Any]]:
        """List campaigns / adsets / ads with basic metadata."""
        edge = {"campaign": "campaigns", "adset": "adsets", "ad": "ads"}[level]
        fields = {
            "campaign": "id,name,status,effective_status,objective,daily_budget,lifetime_budget",
            "adset": "id,name,status,effective_status,campaign_id,daily_budget,lifetime_budget,optimization_goal",
            "ad": "id,name,status,effective_status,adset_id,campaign_id,creative{id,name}",
        }[level]
        params: dict[str, Any] = {"fields": fields, "limit": limit}
        if effective_status:
            params["effective_status"] = str(effective_status).replace("'", '"')
        return await self._get_all_pages(f"{self.creds.ad_account_id}/{edge}", params)

    # -- insights -----------------------------------------------------------
    async def get_insights(
        self,
        level: str,
        date_preset: str | None = None,
        time_range: dict[str, str] | None = None,
        time_increment: int | str | None = None,
        entity_ids: list[str] | None = None,
        breakdowns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Pull insights at a hierarchy level.

        Either date_preset (e.g. 'last_7d', 'yesterday') or time_range
        ({'since': 'YYYY-MM-DD', 'until': 'YYYY-MM-DD'}) must be given.
        time_increment=1 returns one row per day (used for baselines).
        """
        params: dict[str, Any] = {
            "level": level,
            "fields": ",".join(INSIGHTS_FIELDS),
            "limit": 500,
        }
        if self.creds.attribution_windows:
            params["action_attribution_windows"] = ",".join(self.creds.attribution_windows)
        if date_preset:
            params["date_preset"] = date_preset
        if time_range:
            params["time_range"] = str(time_range).replace("'", '"')
        if time_increment is not None:
            params["time_increment"] = time_increment
        if breakdowns:
            params["breakdowns"] = ",".join(breakdowns)
        if entity_ids:
            field = {"campaign": "campaign.id", "adset": "adset.id", "ad": "ad.id"}[level]
            filt = [{"field": field, "operator": "IN", "value": entity_ids}]
            params["filtering"] = str(filt).replace("'", '"')

        return await self._get_all_pages(f"{self.creds.ad_account_id}/insights", params)

    ACTIVITY_FIELDS = [
        "event_type", "translated_event_type", "event_time",
        "actor_id", "actor_name",
        "object_id", "object_name", "object_type", "extra_data",
    ]

    async def get_activities(self, since: str | None = None, until: str | None = None,
                             limit: int = 500) -> list[dict[str, Any]]:
        """Account Activity Log — the authoritative record of manual edits.

        `since`/`until` are 'YYYY-MM-DD' (inclusive-ish). Meta accepts them as
        strtotime strings on the activities edge.
        """
        params: dict[str, Any] = {
            "fields": ",".join(self.ACTIVITY_FIELDS),
            "limit": limit,
        }
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        return await self._get_all_pages(f"{self.creds.ad_account_id}/activities", params)

    async def verify_access(self) -> dict[str, Any]:
        """Cheap call to confirm the token + account work."""
        data = await self._get(
            self.creds.ad_account_id,
            {"fields": "name,account_status,currency,timezone_name,amount_spent"},
        )
        return data
