"""Claims rules: every statement reads only values that exist, every condition evaluates, ids are unique,
and a failed condition or out-of-range value swaps in the fallback."""
import copy
from datetime import date

import pytest
import yaml

from analysis import claims

SPEC = yaml.safe_load(claims.SPEC.read_text())


@pytest.fixture(scope="module")
def vals():
    return claims.current()


def test_ids_unique_and_entries_known(vals):
    for tid, cs in SPEC["claims"].items():
        assert tid in vals, tid
        ids = [c["id"] for c in cs]
        assert len(ids) == len(set(ids)), tid


def test_every_name_exists_and_condition_evaluates(vals):
    for tid, cs in SPEC["claims"].items():
        env = claims.namespace(vals, tid)
        for c in cs:
            for obj, attr in claims.names_in(c):
                assert obj in env and hasattr(env[obj], attr), f"{tid}.{c['id']}: {obj}.{attr}"
            claims.holds(c.get("holds", True), env)
            claims.fill(c["text"], env)
            claims.fill(c.get("fallback", ""), env)


def test_checks_name_real_values(vals):
    some = vals["defense"]
    for name, (lo, hi) in SPEC["checks"].items():
        assert name in some and lo < hi, name


def test_failed_condition_shows_fallback(vals):
    spec = {"checks": {"boston_share": [0, 1]}, "claims": {"defense": [
        {"id": "a", "holds": "t.roles > 10**9", "text": "big", "fallback": "plain {t.roles:int}"},
        {"id": "b", "holds": "True", "text": "{t.boston_share:pct}", "fallback": ""}]}}
    v = copy.deepcopy(vals)
    out, review = claims.evaluate(v, spec)
    assert out["defense"][0]["status"] == "review" and out["defense"][0]["html"].startswith("plain")
    v["defense"]["boston_share"] = 5.0
    out, review = claims.evaluate(v, spec)
    assert out["defense"][1]["status"] == "data_check" and out["defense"][1]["html"] == ""
    assert {r["id"] for r in review} == {"a", "b"}


def test_window_and_ranks():
    assert claims.within("2026", "2025-11", "9999") and not claims.within("2025", "2025-11", "9999")
    assert not claims.within("2025", "2024-11", "2025-11") and claims.within("2025-03", "2024-11", "2025-11")
    seg = {"name": "S", "customers": ""}

    def rec(cid, segs, amount, d="2026-05"):
        return {"id": cid, "c": {"name": cid.title(), "segments": segs, "boston": False}, "ownership": "private",
                "wound_down": None, "valuation": None, "counted": False, "roles": None, "boston_roles": None,
                "functions": {}, "rows": [{"type": "funding", "amount": amount, "date": d, "round": "Series A",
                                            "detail": "", "status": "closed"}]}
    recs = {"a": rec("a", ["x"], 5e8), "b": rec("b", ["y"], 5e8), "c": rec("c", ["x", "y"], 1e8)}
    v = claims.values(recs, {"x": seg, "y": seg}, today=date(2026, 11, 9))
    assert v["x"]["raised_rank"] == v["y"]["raised_rank"] == 1  # a tie shares the rank
    assert v["market"]["raised_12m"] == 1.1e9 and v["x"]["raised_12m"] == 6e8  # each round once in the market
    assert claims.fmt("Mind Robotics", "poss") == "Mind Robotics'" and claims.fmt("Anduril", "poss") == "Anduril's"
