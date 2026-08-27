"""Configuration loading: environment credentials + economics/targets YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file: src/meta_agent/).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")


@dataclass
class MetaCredentials:
    access_token: str
    ad_account_id: str
    api_version: str = "v21.0"
    attribution_windows: list[str] = field(default_factory=lambda: ["7d_click", "1d_view"])

    @property
    def is_configured(self) -> bool:
        return bool(self.access_token) and self.access_token != "your_long_lived_access_token_here"


def load_credentials() -> MetaCredentials:
    windows = os.getenv("META_ATTRIBUTION_WINDOWS", "7d_click,1d_view")
    return MetaCredentials(
        access_token=os.getenv("META_ACCESS_TOKEN", "").strip(),
        ad_account_id=os.getenv("META_AD_ACCOUNT_ID", "").strip(),
        api_version=os.getenv("META_API_VERSION", "v21.0").strip(),
        attribution_windows=[w.strip() for w in windows.split(",") if w.strip()],
    )


def db_path() -> Path:
    """Path to the local SQLite store (snapshots, rolling averages, change log)."""
    raw = os.getenv("NUTRISULIN_DB", "data/meta_agent.db")
    p = Path(raw)
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    return p


def _config_path() -> Path:
    raw = os.getenv("NUTRISULIN_CONFIG", "config/economics.yaml")
    p = Path(raw)
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    return p


@lru_cache(maxsize=1)
def load_economics() -> dict[str, Any]:
    """Load the economics/targets/guardrails config. Cached for the process."""
    path = _config_path()
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def get_targets() -> dict[str, Any]:
    return load_economics().get("targets", {}) or {}


def get_guardrails() -> dict[str, Any]:
    return load_economics().get("decision_guardrails", {}) or {}


def get_diagnostics_cfg() -> dict[str, Any]:
    return load_economics().get("diagnostics", {}) or {}


def get_unit_economics() -> dict[str, Any]:
    return load_economics().get("unit_economics", {}) or {}


def get_compliance() -> dict[str, Any]:
    return load_economics().get("compliance", {}) or {}
