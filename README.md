# Nutrisulin Meta Ads Agent (MCP server)

A read-only **observation & diagnosis** layer over the Meta Marketing (Insights)
API, exposed to **Claude Desktop** as an MCP server. It computes the KPI
hierarchy at the **campaign → ad set → ad** levels, benchmarks each metric the
way the design doc requires, and runs the root-cause / creative-fatigue
diagnostics — without ever inventing industry benchmark numbers.

This is **Stage 1 (Observation)** from the design doc: it can read, calculate,
benchmark, diagnose and recommend, but it **cannot modify Meta**. Guarded write
actions (budget/pause) are a deliberate later stage.

## Design principles (from the doc)

- **No hard-coded industry benchmarks.** CTR / CPC / CPM / CVR / frequency are
  benchmarked against **this account's own rolling baseline**. CPA / ROAS /
  contribution are benchmarked against **configured business targets** in
  `config/economics.yaml`. Anything left `null` is reported as "requires config",
  never guessed.
- **Optimize contribution profit, not raw Meta ROAS.** Contribution is estimated
  from Meta-attributed revenue × your configured margin ratio, and is clearly
  labelled a *Meta-attributed estimate* (realized finance needs the store
  backend, which isn't wired yet).
- **Meta relevance rankings are diagnostic only** — never a stand-alone pause
  trigger.
- **Explicit metric names.** `ctr_link` vs `ctr_all`; `cvr_lpv_to_purchase` vs
  `cvr_link_click_to_purchase` — so denominators never get confused.

## The three phases

| Phase | Focus | Primary KPIs |
|-------|-------|--------------|
| **Campaign** | Overall efficiency, budget pacing, profit vs targets | spend, CPA, ROAS, contribution |
| **Ad set** | Audience / placement / offer | CPM, CVR (LPV→purchase), frequency |
| **Ad** | Creative — attention & relevance | CTR (link), CPC, quality/eng/conv rankings |

## Setup

1. Create the virtualenv and install (already done once; repeat if you re-clone):
   ```bash
   python -m venv .venv
   .venv/Scripts/python.exe -m pip install -e .
   ```
2. Configure credentials:
   ```bash
   cp .env.example .env
   ```
   Set `META_ACCESS_TOKEN` (needs `ads_read`) and `META_AD_ACCOUNT_ID` (with the
   `act_` prefix).
3. Fill in `config/economics.yaml` — at minimum a `contribution_margin_ratio`
   (or a product price + COGS) and your `cpa_target` / `roas_floor`. Until you
   do, profit KPIs and target checks report "requires config" instead of
   guessing.

## Wire into Claude Desktop

Edit `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "nutrisulin-meta": {
      "command": "D:\\meta_agent\\.venv\\Scripts\\python.exe",
      "args": ["-m", "meta_agent.server"]
    }
  }
}
```

Restart Claude Desktop. The tools below appear under the 🔌 menu.

## Tools

| Tool | What it does |
|------|--------------|
| `check_setup` | Verify token/account; list unspecified targets & un-wired sources. **Run first.** |
| `get_economics_config` | Show targets, guardrails, contribution margin, breakeven ROAS. |
| `describe_kpis` | The KPI dictionary — formula, cadence, benchmark source, interpretation (filter by phase). |
| `list_entities` | List campaigns / ad sets / ads with status & budget. |
| `get_kpis` | **Main tool.** Full KPI set at a phase + target checks + evidence check. |
| `diagnose_entity` | Compare one entity to its own baseline → root-cause tree + creative-diagnosis matrix. |
| `account_summary` | Account-wide blended rollup vs targets. |
| `recommend_action` | **Rolling-average SCALE/HOLD/FIX/STOP verdict** + matched fixes, per entity or ranked across a level. Respects a cooldown after recent edits, and on **FIX/STOP** auto-attaches the change-log association for that entity. |
| `get_fix_playbook` | The sourced Meta FIX playbook (campaign/adset/ad/measurement), filterable by diagnosed condition. |
| `snapshot_now` | Capture + **store** current config, KPIs and rolling-average baselines for a level. Run periodically so history accrues. |
| `record_changes` | Fetch + **store** all changes over a period (Meta Activity Log + snapshot-diff backstop) and output them. Idempotent. |
| `show_changes` | View stored changes anytime — filter by level / entity / manual-only. |
| `explain_metric_move` | Cross-reference a metric rise/drop against logged changes — as a **cautious association**, with confounder flags. |
| `store_meta_recommendations` | Persist Ads-Manager UI recommendations (High CPR, Opportunity hints) — **UI-only, not in the API**, so browser-captured. |
| `show_meta_recommendations` | View stored UI recommendations. |
| `store_competitor_notes` | Persist competitor observations (creative/offer/price) browsed from Ad Library site or storefronts — observable facts only. |
| `show_competitor_notes` | View stored competitor observations. |
| `weekly_report` | **One-call weekly analysis:** funnel gates + blended KPIs vs targets + per-campaign verdicts + change digest + stored recommendations + competitor notes. |
| `explain_gates` | The six funnel gates with **full transparency** — atomic fields, formula, and the exact numbers substituted. |

## Funnel gates (with atomic-value transparency)

`explain_gates` (and the `gates_blended` / per-campaign `gates` sections of
`weekly_report`) compute the Amazon-style funnel gates, translated to Meta, and
for each one show the **atomic Meta fields used**, the **formula**, and the
**exact numbers substituted** — so every figure is auditable.

| Gate | Formula | Atomic values | Available |
|------|---------|---------------|-----------|
| Visibility (Impressions) | `impressions` | impressions | ✅ |
| Click (CTR) | `link_clicks / impressions * 100` | inline_link_clicks, impressions | ✅ |
| Conversion (CVR) | `purchases / landing_page_views * 100` | purchases, landing_page_views | ✅ |
| Paid Efficiency (ACoS) | `spend / purchase_value * 100` (= 100/ROAS) | spend, purchase_value | ✅ |
| Ad Dependency (TACoS) | `spend / total_store_revenue * 100` | spend, **total store revenue** | ⚠️ pass `total_store_revenue` (Meta has no organic sales) |
| Profit | `purchase_value * margin - spend` | purchase_value, spend, **margin** | ⚠️ needs `contribution_margin_ratio` in config |

TACoS and Profit are **blocked** until their external input is provided — the
tool returns the formula with a `BLOCKED` computation rather than guessing.

Both `weekly_report` and `explain_gates` also return a **`gates_audit`** block —
a pre-rendered markdown table plus a `render_verbatim` instruction — so a
summarising model surfaces the atomic-value/formula breakdown exactly rather
than folding the numbers into prose.

## Weekly report & browser-captured data

`weekly_report` is the single weekly roll-up. Most of it is computed server-side
(KPIs, verdicts, change digest). Two sections — **Meta recommendations** and
**competitor notes** — are **not available via any Meta API**:

- Ads-Manager recommendations ("High CPR", "N recommendations", Opportunity
  score) are **UI-only**. Confirmed: the API drops the `recommendations` field
  and the account `recommendations` edge is empty.
- Competitor ad data isn't served by the Ad Library API for US commercial ads.

So those two are **browser-captured**: in a Claude session with the browser, read
them off Ads Manager / the Ad Library site / competitor storefronts, then call
`store_meta_recommendations` / `store_competitor_notes` to persist them. The
server can't drive the browser itself, so this is a **capture step you run**, not
a silent cron job. Once stored, every `weekly_report` includes them (deduped per
ISO week). Competitor notes must be **observable facts only** — never claimed
competitor CPA/CTR/ROAS (not knowable).

## Memory (local SQLite store)

State lives in `data/meta_agent.db` (override with `NUTRISULIN_DB`). Three things:

- **Snapshots + rolling averages** — `snapshot_now` stores each entity's config,
  trailing KPIs and its rolling-baseline stats, so history builds up and repeat
  calls don't re-pull/recompute.
- **Change log** — `record_changes` pulls Meta's **Activity Log** (the
  authoritative record of manual edits: actor + timestamp + old→new) and adds a
  **snapshot-diff backstop** for budget/status/name. Every row is deduped, so
  re-running is safe. `is_manual=false` marks changes Meta automated.
  - Object-type mapping uses Meta's *legacy* names: `CAMPAIGN_GROUP`→campaign,
    `CAMPAIGN`→adset, `ADGROUP`→ad.
- **Effect analysis** — `explain_metric_move` compares a metric to the entity's
  own baseline and lists changes in the window as a **flagged association, never
  causal proof** (it warns about learning-phase resets, seasonality, and
  multiple simultaneous edits — per the doc's no-false-causation rule).

Because the change log knows *when the last manual edit happened*,
`recommend_action` now enforces the doc's **cooldown**: it won't SCALE on top of
a just-edited entity (the edit likely reset the learning phase) — it downgrades
to recommendation-only until the cooldown clears.

**Auto-attached association (FIX/STOP only).** When `recommend_action` returns a
FIX or STOP for an entity, it automatically attaches that entity's change-log
association — the manual changes near the decline, plus confounder flags — in the
same result. SCALE/HOLD stay clean (no adverse move to explain). This is
entity-level: a campaign/ad-set FIX shows changes logged *at that level*; child
ad edits live under their own IDs, so run `recommend_action level="ad"` for
per-ad attribution. It remains a **cautious association, never causal proof**.
`account_summary` deliberately does not do this — a single blended total has no
one entity to attribute a change to.

Typical loop: run `snapshot_now` and `record_changes` on a schedule (e.g. weekly
per level), then ask `show_changes` / `explain_metric_move` whenever a number
moves. Note: the store is **local to this machine**, unshared and un-backed-up;
snapshot-diff only catches changes *between* runs (the Activity Log fills that gap).

## Rolling-average verdict (SCALE / HOLD / FIX / STOP)

`recommend_action` answers "is this doing better long-term — scale, or fix?" It
compares an entity's **recent window** (default last 7 days) against its **own
prior baseline** (the rest of a 28-day pull), then combines the trend with
target checks, evidence and safety gates:

- **SCALE** — improving vs baseline **and** profitable **and** enough evidence.
- **HOLD** — not enough evidence, unconfirmed profitability (no targets/margin
  set), or no material change.
- **FIX** — declining vs baseline or unprofitable → attaches the matching
  playbook fixes for the diagnosed condition (creative fatigue, CPM pressure,
  CVR/offer, learning-limited, measurement).
- **STOP** — materially over CPA target with enough spend (stop-loss).

Measurement is a **gate**: if tracking looks broken (clicks but no LPV), the
verdict is FIX(measurement) and scaling is frozen regardless of apparent numbers.

## FIX playbook

`get_fix_playbook` returns researched, **sourced** best-practice fixes per level
(the tables from the research pass), each tagged to a diagnosed condition so the
verdict engine can point at the right ones. Note: unlike an Amazon fix table it
has **no category-average / competitor column** — no universal Meta benchmark
exists and competitor CPA/CTR/ROAS aren't observable. Effort/impact are
synthesised judgment calls from the sources, not Meta-official ratings. You chose
"live search" for freshness, so treat this baked-in copy as the stable fallback;
re-run web search in Desktop for the latest.

## Example asks in Claude Desktop

- "Run check_setup, then give me an account_summary for last_7d."
- "Get campaign KPIs for last_14d and flag anything over its CPA target."
- "Diagnose ad 1234567890 — is the CPA rise creative, auction, or landing page?"

## What's intentionally NOT here yet

Realized orders/refunds/net revenue (Shopify/Stripe), landing-page drop-off &
onsite funnel (GA4), new-vs-returning CAC and cohort LTV (CRM), inventory days
on hand (ERP), CAPI Event Match Quality, and competitor Ad Library data. These
are the ❌ items in the KPI table — they need data sources beyond the Meta API
and are left as clean config stubs in `economics.yaml → external_sources`.

## Project layout

```
config/economics.yaml        product economics, targets, guardrails, thresholds
src/meta_agent/
  config.py                  env + YAML loading
  kpi_dictionary.py          machine-readable KPI dictionary (formulas, benchmarks)
  meta_client.py             async Graph API wrapper (read-only)
  kpis.py                    deterministic KPI engine
  baselines.py               own-history rolling baselines + comparison
  profitability.py           contribution margin & breakeven ROAS
  diagnostics.py             target checks, creative matrix, root-cause tree
  server.py                  FastMCP server (the 7 tools)
```
