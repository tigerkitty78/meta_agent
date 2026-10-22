import pytest

from meta_agent.fixes import FIXES, fixes_by_ids, get_fixes
from meta_agent.profitability import breakeven_roas, contribution_margin_ratio


# ---- fixes playbook ----
def test_get_fixes_by_level_and_tag():
    ad_fatigue = get_fixes("ad", ["ctr_down"])
    assert ad_fatigue
    assert all("ctr_down" in f["tags"] for f in ad_fatigue)
    assert all(f["level"] == "ad" for f in ad_fatigue)


def test_fixes_by_ids_round_trips_with_level():
    first_id = FIXES["ad"][0]["id"]
    got = fixes_by_ids([first_id])
    assert len(got) == 1
    assert got[0]["id"] == first_id
    assert got[0]["level"] == "ad"
    assert got[0]["sources"]           # every fix is sourced


def test_every_fix_has_trigger_and_source():
    for level, items in FIXES.items():
        for f in items:
            assert f["tags"], f["id"]
            assert f["sources"], f["id"]


# ---- profitability (reads the fixed test config: margin 0.55) ----
def test_margin_from_config():
    ratio, _ = contribution_margin_ratio()
    assert ratio == pytest.approx(0.55)


def test_breakeven_roas_is_inverse_margin():
    be, _ = breakeven_roas()
    assert be == pytest.approx(1 / 0.55, abs=0.01)   # ~1.818
