"""Shared test fixtures: point the config loader at the fixed test config so
target/guardrail/verdict tests are deterministic and never read the live
economics.yaml."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from meta_agent import config

_TEST_CONFIG = Path(__file__).parent / "test_config.yaml"


@pytest.fixture(autouse=True)
def _use_test_config():
    prev = os.environ.get("NUTRISULIN_CONFIG")
    os.environ["NUTRISULIN_CONFIG"] = str(_TEST_CONFIG)
    config.load_economics.cache_clear()
    yield
    config.load_economics.cache_clear()
    if prev is None:
        os.environ.pop("NUTRISULIN_CONFIG", None)
    else:
        os.environ["NUTRISULIN_CONFIG"] = prev
