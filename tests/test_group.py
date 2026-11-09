import csv
import json
import sys

import pytest

import classify.review as review
import ingest.common as common
import ingest.filings as filings
from classify.group import groups
from ingest.filings import QUEUE_COLUMNS


def item(qid, title, date="2026-11-05", company="zipline", stype="funding", kind="tier2", source="news", **parsed):
    return {"qid": qid, "found": "2026-11-07", "source": source, "company": company, "date": date, "kind": kind,
            "suggested_type": stype, "title": title, "url": f"https://x.com/{qid}", "parsed": json.dumps(parsed),
            "status": "open"}


def qids(gs):
    return sorted(sorted(r["qid"] for r in g) for g in gs)


def test_shared_figure_links_funding_and_valuation():
    rows = [item("a", "Zipline raises $1.5B at $21.5B valuation", amounts=[1_500_000_000], valuation=21_500_000_000),
            item("b", "Zipline hits $21.5B valuation", stype="valuation", kind="tier1", valuation=21_000_000_000),
            item("c", "Zipline raised $1.5B in 2023", date="2023-04-01", amounts=[1_500_000_000])]
    gs = groups(rows)
    assert qids(gs) == [["a", "b"], ["c"]]
    assert next(g for g in gs if len(g) == 2)[0]["qid"] == "b"  # tier1 leads


def test_types_and_companies_do_not_mix():
    rows = [item("a", "Shield AI to buy Echodyne for $5.3B", company="shield-ai", stype="acquisition",
                 amounts=[5_300_000_000]),
            item("b", "Shield AI raises $5.3B", company="shield-ai", amounts=[5_300_000_000]),
            item("c", "Zipline raises $5.3B", amounts=[5_300_000_000])]
    assert len(groups(rows)) == 3


def test_figureless_titles_link_by_overlap():
    rows = [item("a", "Tesla to wind down Cybertruck production in Texas next year", company="tesla", stype="status"),
            item("b", "Tesla will wind down Cybertruck production next year", company="tesla", stype="status"),
            item("c", "Tesla opens robotaxi service in Austin", company="tesla", stype="status")]
    assert qids(groups(rows)) == [["a", "b"], ["c"]]


def test_listing_news_links_within_30_days():
    rows = [item("a", "Agility goes public on Nasdaq", company="agility", stype="listing"),
            item("b", "Agility clears SPAC vote", date="2026-10-20", company="agility", stype="listing"),
            item("c", "Agility files confidentially", date="2026-06-01", company="agility", stype="listing")]
    assert qids(groups(rows)) == [["a", "b"], ["c"]]


def test_sec_routine_filings_group_material_ones_do_not():
    sec = dict(source="sec", company="serve", stype="market")
    rows = [item("a", "8-K", kind="8-K", items="2.02,9.01", **sec), item("b", "8-K", kind="8-K", items="2.02,9.01", **sec),
            item("c", "8-K", kind="8-K", items="1.01,9.01", **sec), item("d", "8-K", kind="8-K", items="1.01,9.01", **sec),
            item("e", "6-K", kind="6-K", **sec), item("f", "6-K", kind="6-K", **sec), item("g", "D", kind="D", **sec)]
    assert qids(groups(rows)) == [["a", "b"], ["c"], ["d"], ["e", "f"], ["g"]]


@pytest.fixture
def files(tmp_path, monkeypatch):
    queue, ledger = tmp_path / "queue.csv", tmp_path / "ledger.csv"
    with ledger.open("w", newline="") as fh:
        w = csv.DictWriter(fh, common.LEDGER_COLUMNS)
        w.writeheader()
        w.writerow({k: "" for k in common.LEDGER_COLUMNS} | {"id": "E0001", "company": "zipline"})
    monkeypatch.setattr(filings, "QUEUE", queue)
    monkeypatch.setattr(common, "LEDGER", ledger)
    monkeypatch.setattr(review, "LEDGER", ledger)
    filings.write_queue([item("a", "Zipline raises $1.5B", kind="tier1", amounts=[1_500_000_000]),
                         item("b", "Zipline lands $1.5B", amounts=[1_500_000_000]),
                         item("c", "Zipline opens in Dallas", stype="deployment")])
    return queue, ledger


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["review", *argv])
    review.main()


def test_accept_group_closes_members_as_dups(files, monkeypatch):
    run(monkeypatch, "accept", "a", "--type", "funding", "--amount", "1500000000", "--group")
    status = {q["qid"]: (q["status"], json.loads(q["parsed"])) for q in filings.read_queue()}
    assert status["a"][0] == "accepted" and status["a"][1]["ledger"] == "E0002"
    assert status["b"][0] == "dup" and status["b"][1]["duplicate_of"] == "E0002"
    assert status["c"][0] == "open"


def test_reject_without_group_closes_one(files, monkeypatch):
    def status():
        return {q["qid"]: q["status"] for q in filings.read_queue()}
    run(monkeypatch, "reject", "a", "--reason", "test")
    assert status() == {"a": "rejected", "b": "open", "c": "open"}
    run(monkeypatch, "reject", "b", "--reason", "test", "--group")
    assert status() == {"a": "rejected", "b": "rejected", "c": "open"}


def test_queue_columns_unchanged():
    assert QUEUE_COLUMNS[-1] == "status" and "group" not in QUEUE_COLUMNS
