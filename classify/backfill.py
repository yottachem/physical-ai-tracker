"""Funding-history backfill: researched rounds -> review queue (source backfill). Nothing reaches the ledger here.

Input: data/review/backfill.csv, one disclosed round per row, researched by hand from company releases, filings and
tier-1 reporting:
  company, date (YYYY-MM-DD, YYYY-MM or YYYY), round, amount_usd, valuation_usd (post-money when stated),
  qualifier (approx | at_least | up_to), status (closed | reported | announced), detail, url (best source)
A row is skipped when the ledger already holds the round: a funding row for the company in the same year (or
undated) with an amount within 10%, or for a valuation-only row, a valuation within 10%. Rows already queued (same
qid) are skipped too. The proposed figures ride in the queue row's parsed field; /review-events accepts them as
proposed or corrected.

Usage: uv run python -m classify.backfill
"""
import csv
import hashlib
import json
from datetime import date

from classify.accept import close, num
from ingest.common import ROOT, load_companies, load_ledger
from ingest.filings import read_queue, write_queue

BACKFILL = ROOT / "data" / "review" / "backfill.csv"
FIELDS = ["company", "date", "round", "amount_usd", "valuation_usd", "qualifier", "status", "detail", "url"]


def in_ledger(row, ledger):
    amount, val = num(row["amount_usd"]), num(row["valuation_usd"])
    for e in ledger:
        if e["company"] != row["company"] or (e["date"] and e["date"][:4] != row["date"][:4]):
            continue
        if amount and e["type"] == "funding" and close(amount, num(e["amount_usd"])):
            return e["id"]
        if not amount and val and close(val, num(e["valuation_usd"])):
            return e["id"]
    return None


def main():
    companies, ledger, queue = load_companies(), load_ledger(), read_queue()
    known = {q["qid"] for q in queue}
    with BACKFILL.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    added = skipped = 0
    for r in rows:
        assert r["company"] in companies, r["company"]
        qid = "backfill:" + hashlib.sha1("|".join(r[k] for k in FIELDS[:5]).encode()).hexdigest()[:12]
        if (eid := in_ledger(r, ledger)) or qid in known:
            print(f"{r['company']} {r['date']} {r['round']}: {'in ledger as ' + eid if eid else 'already queued'}")
            skipped += 1
            continue
        kind = "funding" if r["amount_usd"] else "valuation"
        queue.append({"qid": qid, "found": date.today().isoformat(), "source": "backfill", "company": r["company"],
                      "date": r["date"], "kind": "funding history", "suggested_type": kind,
                      "title": f"{companies[r['company']]['name']}: {r['detail']}", "url": r["url"],
                      "parsed": json.dumps({k: r[k] for k in FIELDS[1:8]}, sort_keys=True), "status": "open"})
        known.add(qid)
        added += 1
    write_queue(queue)
    print(f"{added} queued, {skipped} skipped")


if __name__ == "__main__":
    main()
