from meta_agent.gates import compute_gates, gates_markdown
from ._util import mkrow


def _g(result):
    return {g["gate"]: g for g in result["gates"]}


def test_gate_values_and_atomics():
    r = compute_gates(mkrow(spend=100, impressions=10000, link_clicks=200,
                            purchases=5, value=250, lpv=150), margin=0.55)
    g = _g(r)
    assert g["Click (CTR)"]["value"] == 2.0
    assert g["Click (CTR)"]["atomic_values"] == {"inline_link_clicks": 200, "impressions": 10000}
    assert "200 / 10000" in g["Click (CTR)"]["computation"]
    assert g["Paid Efficiency (ACoS)"]["value"] == 40.0        # 100/250*100
    assert g["Profit"]["value"] == 37.5                        # 250*0.55 - 100


def test_profit_blocked_without_margin():
    r = compute_gates(mkrow(value=250, spend=100), margin=None)
    g = _g(r)
    assert g["Profit"]["value"] is None
    assert "BLOCKED" in g["Profit"]["computation"]
    assert "Profit" in r["blocked"]


def test_tacos_blocked_without_store_revenue():
    r = compute_gates(mkrow(), margin=0.55)
    g = _g(r)
    assert g["Ad Dependency (TACoS)"]["value"] is None
    assert "Ad Dependency (TACoS)" in r["blocked"]


def test_tacos_unlocks_with_store_revenue():
    r = compute_gates(mkrow(spend=100), margin=0.55, total_store_revenue=1000)
    g = _g(r)
    assert g["Ad Dependency (TACoS)"]["value"] == 10.0          # 100/1000*100


def test_gates_markdown_renders_table():
    md = gates_markdown(compute_gates(mkrow(), margin=0.55))
    assert "| Gate |" in md
    assert "Visibility (Impressions)" in md
