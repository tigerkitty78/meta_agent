"""The Meta FIX playbook — researched, sourced best-practice fixes per level.

Baked-in equivalent of the "FIX Research Table", adapted for Meta. Unlike an
Amazon table, there is NO category-average / competitor-performance column:
the design doc is explicit that no universal Meta benchmark exists and
competitor CPA/CTR/ROAS are not observable. Each fix's "expected_impact" is
therefore tied to a platform mechanic or to the entity's OWN baseline, never a
competitor number.

Each fix carries `tags` linking it to a diagnosed condition, so the verdict
engine (verdict.py) can attach the right fixes to a FIX/STOP/SCALE call.

Sources are best-practice references gathered via web research (2026). Effort
and impact are judgment calls synthesised from those sources, not Meta-official
ratings.
"""

from __future__ import annotations

# Condition tags vocabulary (also produced by verdict.py):
#   scale_ready, learning_limited, learning_reset_risk, cpm_pressure,
#   ctr_down, creative_fatigue, cvr_down, offer_issue, frequency_high,
#   over_target, measurement_gate, structure

FIXES: dict[str, list[dict]] = {
    "campaign": [
        {
            "id": "cmp_consolidate_cbo",
            "fix": "Consolidate to 1-3 ad sets/campaign; use CBO (Advantage campaign budget)",
            "addresses": "Learning / delivery",
            "expected_impact": "High — 5 ad sets at $20 = 5 starved learning cycles; one at "
                               "$100 exits learning ~5x faster",
            "effort": "Medium",
            "tags": ["learning_limited", "structure"],
            "sources": [
                {"name": "OptiFOX", "url": "https://optifox.in/blog/meta-ads-best-practices-2026/"},
                {"name": "ModernMktg", "url": "https://www.modernmarketinginstitute.com/blog/how-to-exit-the-meta-ads-learning-phase-fast-and-start-scaling-profitably-in-2026"},
            ],
        },
        {
            "id": "cmp_scale_20pct",
            "fix": "Scale budget <=20% every 3-4 days (no big jumps)",
            "addresses": "Efficiency without learning reset",
            "expected_impact": "High — >20% change resets the learning phase; incremental is the "
                               "most reliable non-resetting scale lever",
            "effort": "Low",
            "tags": ["scale_ready"],
            "sources": [
                {"name": "benly.ai", "url": "https://benly.ai/learn/meta-ads/learning-phase-optimization"},
                {"name": "growwithsakib", "url": "https://growwithsakib.com/meta-ads-learning-phase/"},
            ],
        },
        {
            "id": "cmp_scale_horizontal",
            "fix": "Scale winners horizontally (duplicate) rather than one big vertical push",
            "addresses": "Scale without reset",
            "expected_impact": "Medium — duplication avoids resetting the original's learning",
            "effort": "Medium",
            "tags": ["scale_ready"],
            "sources": [
                {"name": "ModernMktg", "url": "https://www.modernmarketinginstitute.com/blog/how-to-exit-the-meta-ads-learning-phase-fast-and-start-scaling-profitably-in-2026"},
            ],
        },
        {
            "id": "cmp_freeze_edits",
            "fix": "Freeze edits during learning (respect a cooldown)",
            "addresses": "Delivery stability",
            "expected_impact": "High — premature edits discard accumulated signal",
            "effort": "Low",
            "tags": ["learning_reset_risk"],
            "sources": [
                {"name": "OptiFOX", "url": "https://optifox.in/blog/meta-ads-best-practices-2026/"},
                {"name": "benly.ai", "url": "https://benly.ai/learn/meta-ads/learning-phase-optimization"},
            ],
        },
        {
            "id": "cmp_50_events",
            "fix": "Ensure each ad set can hit >=50 optimization events/week (budget floor / event choice)",
            "addresses": "Learning exit",
            "expected_impact": "High — below 50/wk, variance is too high to optimise on",
            "effort": "Medium",
            "tags": ["learning_limited", "structure"],
            "sources": [
                {"name": "Lebesgue", "url": "https://lebesgue.io/facebook-ads/facebook-ads-learning-phase-what-you-need-to-know-2024-update"},
                {"name": "adlibrary", "url": "https://adlibrary.com/posts/meta-ads-learning-phase-50-events-guide"},
            ],
        },
    ],
    "adset": [
        {
            "id": "ast_broaden_advantage_audience",
            "fix": "Broaden targeting / enable Advantage+ audience",
            "addresses": "Learning + finding converters",
            "expected_impact": "High — broad targeting exits learning faster, steadier delivery",
            "effort": "Low",
            "tags": ["learning_limited", "cvr_down"],
            "sources": [
                {"name": "ModernMktg", "url": "https://www.modernmarketinginstitute.com/blog/how-to-exit-the-meta-ads-learning-phase-fast-and-start-scaling-profitably-in-2026"},
                {"name": "IgniteVisibility", "url": "https://ignitevisibility.com/meta-learning-phase/"},
            ],
        },
        {
            "id": "ast_advantage_placements",
            "fix": "Use Advantage+ placements (not narrow manual)",
            "addresses": "Delivery / CPM",
            "expected_impact": "Medium — wider auction pool typically lowers CPM pressure",
            "effort": "Low",
            "tags": ["cpm_pressure"],
            "sources": [
                {"name": "ClickCease", "url": "https://support.clickcease.com/hc/en-us/articles/11197131777169-Everything-About-Facebook-Ads-Learning-Phase"},
                {"name": "Cometly", "url": "https://www.cometly.com/post/facebook-ads-learning-phase-optimization"},
            ],
        },
        {
            "id": "ast_merge_segments",
            "fix": "Stop over-segmenting; merge overlapping ad sets",
            "addresses": "Learning exit",
            "expected_impact": "High — fragmenting splits the 50 events so none exit learning",
            "effort": "Medium",
            "tags": ["learning_limited", "structure"],
            "sources": [
                {"name": "adlibrary", "url": "https://adlibrary.com/posts/meta-ads-learning-phase-50-events-guide"},
            ],
        },
        {
            "id": "ast_cost_cap",
            "fix": "Set Cost Cap 10-20% above target CPA — AFTER learning, not day one",
            "addresses": "CPA control",
            "expected_impact": "Medium — balances CPA vs volume; day-one caps cause underdelivery",
            "effort": "Low",
            "tags": ["over_target"],
            "sources": [
                {"name": "benly.ai", "url": "https://benly.ai/learn/meta-ads/bidding-strategies-guide"},
            ],
        },
        {
            "id": "ast_correct_event",
            "fix": "Optimize for the correct conversion event (Purchase, not clicks)",
            "addresses": "Conversion signal",
            "expected_impact": "High — wrong event trains the algorithm on the wrong people",
            "effort": "Low",
            "tags": ["cvr_down", "structure"],
            "sources": [
                {"name": "ClickCease", "url": "https://support.clickcease.com/hc/en-us/articles/11197131777169-Everything-About-Facebook-Ads-Learning-Phase"},
            ],
        },
        {
            "id": "ast_frequency_cap",
            "fix": "Watch frequency; act when >3.0 at ad-set level",
            "addresses": "Audience saturation",
            "expected_impact": "Medium — rising frequency signals the audience is wearing out",
            "effort": "Low",
            "tags": ["frequency_high"],
            "sources": [
                {"name": "Atria", "url": "https://www.tryatria.com/blog/meta-creative-fatigue-diagnose-and-fix-2026"},
                {"name": "bir.ch", "url": "https://bir.ch/blog/facebook-ad-fatigue"},
            ],
        },
    ],
    "ad": [
        {
            "id": "ad_refresh_on_ctr_drop",
            "fix": "Refresh creative when CTR drops 20-30% below your baseline or frequency >3",
            "addresses": "Creative fatigue",
            "expected_impact": "High — CTR fatigue precedes CPA by days; waiting for CPA reacts too late",
            "effort": "Medium",
            "tags": ["ctr_down", "creative_fatigue", "frequency_high"],
            "sources": [
                {"name": "Atria", "url": "https://www.tryatria.com/blog/meta-creative-fatigue-diagnose-and-fix-2026"},
                {"name": "TheOptimizer", "url": "https://theoptimizer.io/blog/meta-ads-creative-fatigue-how-to-detect-it-early-and-what-to-do-about-it"},
            ],
        },
        {
            "id": "ad_real_refresh",
            "fix": "Make it a real refresh — new hook / first-3s / angle, not a recolor",
            "addresses": "Attention + CVR",
            "expected_impact": "High — cosmetic tweaks don't reset fatigue",
            "effort": "Medium-High",
            "tags": ["ctr_down", "creative_fatigue", "cvr_down"],
            "sources": [
                {"name": "Atria", "url": "https://www.tryatria.com/blog/meta-creative-fatigue-diagnose-and-fix-2026"},
                {"name": "hawky.ai", "url": "https://hawky.ai/blog/identify-fix-creative-fatigue-ads"},
            ],
        },
        {
            "id": "ad_cpm_flat_ctr_warning",
            "fix": "Treat CPM-up-with-flat-CTR as the earliest fatigue warning",
            "addresses": "Early diagnosis",
            "expected_impact": "Medium — precedes CTR drop by 2-3 days",
            "effort": "Low",
            "tags": ["cpm_pressure", "creative_fatigue"],
            "sources": [
                {"name": "Atria", "url": "https://www.tryatria.com/blog/meta-creative-fatigue-diagnose-and-fix-2026"},
            ],
        },
        {
            "id": "ad_rankings_leading_not_pause",
            "fix": "Use relevance rankings (quality/eng/conv) as a leading indicator, NOT a pause trigger",
            "addresses": "Creative diagnosis",
            "expected_impact": "Medium — Engagement-rank to 'Below Average' flags overexposure",
            "effort": "Low",
            "tags": ["creative_fatigue"],
            "sources": [
                {"name": "Atria", "url": "https://www.tryatria.com/blog/meta-creative-fatigue-diagnose-and-fix-2026"},
                {"name": "Nutrisulin design doc", "url": "internal"},
            ],
        },
        {
            "id": "ad_upload_fresh_monthly",
            "fix": "Upload fresh creatives a few times/month; test hooks/proof/formats/lengths",
            "addresses": "Sustained delivery",
            "expected_impact": "Medium — keeps delivery stable at scale",
            "effort": "Medium",
            "tags": ["creative_fatigue"],
            "sources": [
                {"name": "Atria", "url": "https://www.tryatria.com/blog/meta-creative-fatigue-diagnose-and-fix-2026"},
                {"name": "inBeat", "url": "https://inbeat.agency/blog/facebook-creative-fatigue"},
            ],
        },
    ],
    "measurement": [
        {
            "id": "msr_capi_coverage",
            "fix": "Send CAPI purchase events; reach ~75% coverage vs Pixel",
            "addresses": "Signal robustness",
            "expected_impact": "High — Meta's recommended coverage floor",
            "effort": "Medium",
            "tags": ["measurement_gate"],
            "sources": [
                {"name": "adsuploader", "url": "https://adsuploader.com/blog/meta-conversions-api"},
                {"name": "trackbee", "url": "https://www.trackbee.io/blog/meta-conversions-api-shopify-complete-guide"},
            ],
        },
        {
            "id": "msr_emq",
            "fix": "Raise EMQ to 7+/10 (send hashed email, real-time events)",
            "addresses": "Match quality -> CPA/ROAS",
            "expected_impact": "High, but vendor-reported: one case cites EMQ 8.6->9.3 = CPA -18%, "
                               "ROAS +22% (unverified for your account)",
            "effort": "Medium",
            "tags": ["measurement_gate"],
            "sources": [
                {"name": "trackbee", "url": "https://www.trackbee.io/blog/how-to-improve-metas-event-match-quality-score-for-better-ad-performance-with-trackbee"},
                {"name": "aknigam", "url": "https://aknigam.com/insights/meta-conversions-api-match-quality/"},
            ],
        },
        {
            "id": "msr_dedup",
            "fix": "Deduplicate Pixel + CAPI via event_id",
            "addresses": "Overcounting",
            "expected_impact": "Medium — prevents double-counted purchases inflating ROAS",
            "effort": "Low",
            "tags": ["measurement_gate"],
            "sources": [
                {"name": "adsuploader", "url": "https://adsuploader.com/blog/meta-conversions-api"},
            ],
        },
    ],
}

_BY_ID = {f["id"]: {**f, "level": lvl} for lvl, items in FIXES.items() for f in items}


def get_fixes(level: str | None = None, tags: list[str] | None = None) -> list[dict]:
    """Return fixes, optionally filtered by level and/or matching ANY of `tags`."""
    if level and level in FIXES:
        pool = [{**f, "level": level} for f in FIXES[level]]
    else:
        pool = list(_BY_ID.values())
    if tags:
        tagset = set(tags)
        pool = [f for f in pool if tagset & set(f["tags"])]
    return pool


def fixes_by_ids(ids: list[str]) -> list[dict]:
    out, seen = [], set()
    for i in ids:
        if i in _BY_ID and i not in seen:
            out.append(_BY_ID[i])
            seen.add(i)
    return out


DISCLAIMER = ("No universal Meta benchmark or competitor performance is used. Expected-impact is "
              "tied to platform mechanics or your own baseline. Effort/impact are synthesised "
              "judgment calls from the cited sources, not Meta-official ratings.")
