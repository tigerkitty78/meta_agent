"""Nutrisulin Meta Ads agent — a Claude Desktop MCP server.

Read-only observation / diagnosis layer over the Meta Marketing (Insights) API.
Computes the KPI hierarchy (delivery -> engagement -> conversion -> financial)
at the campaign, ad set and ad levels, benchmarks each metric against the
account's own rolling baselines or configured business targets, and runs the
root-cause / creative-fatigue diagnostics from the design doc.
"""

__version__ = "0.1.0"
