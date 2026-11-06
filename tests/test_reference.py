"""Registry, ledger and source-tier rules. A failure here means a figure would publish wrong or unattributed.

LAUNCH_GATE=1 also runs the launch-only checks (no verify entries left).
"""
import os
import re
from datetime import date

import pytest
import yaml

from ingest.common import LEDGER_COLUMNS, REF, domain_of, load_companies, load_ledger, load_segments, tier_of

COMPANIES = load_companies()
SEGMENTS = load_segments()
LEDGER = load_ledger()
OWNERSHIP = {"private", "public", "subsidiary", "division"}
TYPES = {"funding", "valuation", "revenue", "deployment", "product", "partnership", "contract", "facility",
         "acquisition", "regulatory", "headcount", "layoff", "listing", "market", "status"}
STATUS = {"closed", "reported", "announced"}
ACCEPT = {"seed", "auto", "reviewed"}
QUALIFIERS = {"", "approx", "at_least", "up_to"}
ATS = {"greenhouse", "lever", "ashby", "workable", "workday", "rippling", "other"}
VERIFY_FIELDS = {"hq", "domain", "ticker", "cik", "careers", "ownership", "segments"}


@pytest.mark.parametrize("cid", COMPANIES)
def test_company_fields(cid):
    c = COMPANIES[cid]
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", cid)
    assert c["segments"] and set(c["segments"]) <= set(SEGMENTS), c["segments"]
    assert c["ownership"] in OWNERSHIP
    assert isinstance(c["boston"], bool)
    if c["ownership"] in {"subsidiary", "division"}:
        assert c["parent"], "subsidiaries and divisions name their parent"
    if c["ownership"] == "public":
        assert c["ticker"] and c["cik"], "public companies need ticker and CIK (financials come from EDGAR)"
    assert set(c["verify"]) <= VERIFY_FIELDS
    if c["careers"]:
        assert c["careers"]["ats"] in ATS and c["careers"]["token"]


@pytest.mark.parametrize("cid", COMPANIES)
def test_news_terms_are_quoted_phrases(cid):
    # Bare words match unrelated stories ("Figure", "Sunday", "Potato"); every term is an exact phrase
    for t in COMPANIES[cid]["news"]["terms"]:
        assert re.fullmatch(r'("[^"]+"\s*)+', t), t


def test_ledger_shape():
    assert list(LEDGER[0]) == LEDGER_COLUMNS
    ids = [r["id"] for r in LEDGER]
    assert ids == [f"E{n:04d}" for n in range(1, len(ids) + 1)], "ids are sequential and never reused"


@pytest.mark.parametrize("row", LEDGER, ids=[r["id"] for r in LEDGER])
def test_ledger_row(row):
    assert row["company"] in COMPANIES
    assert row["type"] in TYPES and row["status"] in STATUS and row["accept"] in ACCEPT
    assert row["qualifier"] in QUALIFIERS
    assert row["date"] == "" or re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", row["date"])
    for k in ("amount_usd", "valuation_usd"):
        assert row[k] == "" or row[k].isdigit()
    assert row["sources"], "every figure carries its source"
    date.fromisoformat(row["added"])
    if row["accept"] == "seed":
        assert row["map_row"].isdigit()
    if row["accept"] == "auto":
        assert any(tier_of(u) == "tier1" for u in row["sources"].split()), "auto-accept needs a tier-1 source"


def test_every_source_domain_has_a_tier():
    missing = {domain_of(u) for r in LEDGER for u in r["sources"].split() if tier_of(u) is None}
    assert not missing, f"add to reference/source_tiers.yaml: {sorted(missing)}"


def test_tiers_do_not_overlap():
    t = yaml.safe_load((REF / "source_tiers.yaml").read_text())
    tier1 = [d for g in t["tier1"].values() for d in g]
    lists = [tier1, t["tier2"], t["secondary"]]
    seen = [d for lst in lists for d in lst]
    assert len(seen) == len(set(seen))


@pytest.mark.skipif(not os.environ.get("LAUNCH_GATE"), reason="launch-only check")
def test_launch_gate_nothing_left_to_verify():
    left = {cid: c["verify"] for cid, c in COMPANIES.items() if c["verify"]}
    assert not left, left
