"""Synthetic Meta Insights rows for tests — no network, deterministic."""

from __future__ import annotations


def mkrow(spend=100.0, impressions=10000, link_clicks=200, clicks=None,
          purchases=5, value=250.0, lpv=150, atc=0, date="2026-07-01",
          qr="average", er="average", cr="average", purchase_type="purchase",
          ids=None):
    actions = []
    if lpv:
        actions.append({"action_type": "landing_page_view", "value": str(lpv)})
    if atc:
        actions.append({"action_type": "add_to_cart", "value": str(atc)})
    if purchases:
        actions.append({"action_type": purchase_type, "value": str(purchases)})
    row = {
        "spend": str(spend), "impressions": str(impressions),
        "reach": str(int(impressions * 0.7)),
        "clicks": str(clicks if clicks is not None else link_clicks + 50),
        "inline_link_clicks": str(link_clicks),
        "actions": actions,
        "action_values": [{"action_type": purchase_type, "value": str(value)}] if value else [],
        "quality_ranking": qr, "engagement_rate_ranking": er,
        "conversion_rate_ranking": cr,
        "date_start": date, "date_stop": date,
        "campaign_id": "c1", "campaign_name": "Camp",
        "adset_id": "s1", "adset_name": "Set", "ad_id": "a1", "ad_name": "Ad",
    }
    if ids:
        row.update(ids)
    return row


def mkdays(count, start=1, **kw):
    """count daily rows, dated 2026-07-01 onward."""
    return [mkrow(date=f"2026-07-{start + i:02d}", **kw) for i in range(count)]
