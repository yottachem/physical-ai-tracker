"""Review-queue actions for the /review-events skill. Every decision is written by this script, never by hand.

  uv run python -m classify.review list [--company ID] [--source news|sec] [--limit N]   (limit counts groups)
  uv run python -m classify.review accept QID --type funding [--date D] [--round R] [--amount USD] [--valuation USD]
                                         [--qualifier approx|at_least|up_to] [--status closed|reported|announced]
                                         [--detail TEXT] [--source URL ...] [--group]
  uv run python -m classify.review reject QID --reason TEXT [--group]
  uv run python -m classify.review dup QID EXXXX [--group]

list shows open items grouped by event (classify.group); each group's lead item comes first.
accept appends a ledger row with accept = reviewed, citing the item's URL plus any --source URLs; the queue row
becomes status accepted with the ledger id. reject and dup close the row with the reason or the ledger id.
--group applies the decision to every open item in QID's group: after accept, the other members close as
duplicates of the new ledger row; reject and dup close them all the same way. To record two ledger events from one
group (an acquisition and the valuation reported with it), accept one member without --group first.
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date

from classify.group import group_of, groups
from ingest.common import LEDGER, LEDGER_COLUMNS, load_ledger, tier_of
from ingest.filings import read_queue, write_queue

TYPES = ["funding", "valuation", "revenue", "deployment", "product", "partnership", "contract", "facility",
         "acquisition", "regulatory", "headcount", "layoff", "listing", "market", "status"]


def find(queue, qid):
    for q in queue:
        if q["qid"] == qid:
            if q["status"] != "open":
                sys.exit(f"{qid} is already {q['status']}")
            return q
    sys.exit(f"{qid} not in queue")


def cmd_list(a):
    rows = [q for q in read_queue() if q["status"] == "open" and (not a.company or q["company"] == a.company)
            and (not a.source or q["source"] == a.source)]
    gs = groups(rows)
    by = defaultdict(list)
    for g in gs:
        by[g[0]["company"]].append(g)
    shown = 0
    for cid in sorted(by, key=lambda k: -sum(len(g) for g in by[k])):
        print(f"\n## {cid} ({sum(len(g) for g in by[cid])} open, {len(by[cid])} groups)")
        for g in sorted(by[cid], key=lambda g: max(q["date"] for q in g), reverse=True):
            if shown >= a.limit:
                print(f"\n... {len(gs) - shown} more groups (raise --limit)")
                return
            q = g[0]
            p = json.loads(q["parsed"] or "{}")
            why = "; ".join(p.get("reasons", [])) or p.get("items", "")
            size = f" [group of {len(g)}, {min(r['date'] for r in g)}..{max(r['date'] for r in g)}]" if len(g) > 1 else ""
            print(f"- {q['qid']} | {q['date']} | {q['kind']} | {q['suggested_type']} | {q['title'][:110]}{size}\n"
                  f"  {q['url'] or '(no link)'}" + (f"\n  why: {why}" if why else ""))
            for r in g[1:a.members + 1]:
                print(f"    + {r['qid']} | {r['date']} | {r['kind']} | {r['title'][:90]}")
            if len(g) > a.members + 1:
                print(f"    + ... {len(g) - a.members - 1} more")
            shown += 1
    print(f"\n{len(rows)} open in {len(gs)} groups")


def cmd_accept(a):
    queue = read_queue()
    q = find(queue, a.qid)
    a.members_of = group_of(queue, a.qid) if a.group else []
    sources = [s for s in [q["url"], *a.source] if s]
    if not sources:
        sys.exit("no source URL: pass --source")
    unknown = [s for s in sources if tier_of(s) is None]
    if unknown:
        print(f"note: unclassified source domain(s), add to reference/source_tiers.yaml: {unknown}")
    ledger = load_ledger()
    eid = f"E{max(int(e['id'][1:]) for e in ledger) + 1:04d}"
    row = {k: "" for k in LEDGER_COLUMNS}
    row.update(id=eid, company=q["company"], date=a.date or q["date"], type=a.type, round=a.round or "",
               amount_usd=a.amount or "", valuation_usd=a.valuation or "", qualifier=a.qualifier or "",
               status=a.status, detail=a.detail or q["title"], sources=" ".join(sources), accept="reviewed",
               added=date.today().isoformat())
    with open(LEDGER, "a", newline="") as fh:
        csv.DictWriter(fh, LEDGER_COLUMNS).writerow(row)
    q.update(status="accepted", parsed=json.dumps(dict(json.loads(q["parsed"] or "{}"), ledger=eid), sort_keys=True))
    rest = close_group(queue, a, "dup", {"duplicate_of": eid}) if a.group else 0
    write_queue(queue)
    print(f"{a.qid} -> {eid}: {row['type']} {row['status']} {row['amount_usd'] or ''} {row['valuation_usd'] or ''}"
          + (f"; {rest} group members -> dup {eid}" if rest else ""))


def close_row(q, status, note):
    q.update(status=status, parsed=json.dumps(dict(json.loads(q["parsed"] or "{}"), **note), sort_keys=True))


def close_group(queue, a, status, note):
    """Close the other open members of a.qid's group (computed before a.qid itself closed); returns how many."""
    members = [r for r in a.members_of if r["qid"] != a.qid]
    for r in members:
        close_row(r, status, note)
    return len(members)


def cmd_close(a, status, note):
    queue = read_queue()
    q = find(queue, a.qid)
    a.members_of = group_of(queue, a.qid) if a.group else []
    close_row(q, status, note)
    rest = close_group(queue, a, status, note) if a.group else 0
    write_queue(queue)
    print(f"{a.qid} -> {status}" + (f"; {rest} group members -> {status}" if rest else ""))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("--company")
    p.add_argument("--source", choices=["news", "sec"])
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--members", type=int, default=3, help="group members shown under each lead")
    p = sub.add_parser("accept")
    p.add_argument("qid")
    p.add_argument("--type", required=True, choices=TYPES)
    p.add_argument("--date")
    p.add_argument("--round")
    p.add_argument("--amount")
    p.add_argument("--valuation")
    p.add_argument("--qualifier", choices=["approx", "at_least", "up_to"])
    p.add_argument("--status", default="closed", choices=["closed", "reported", "announced"])
    p.add_argument("--detail")
    p.add_argument("--source", action="append", default=[])
    p.add_argument("--group", action="store_true")
    p = sub.add_parser("reject")
    p.add_argument("qid")
    p.add_argument("--reason", required=True)
    p.add_argument("--group", action="store_true")
    p = sub.add_parser("dup")
    p.add_argument("qid")
    p.add_argument("eid")
    p.add_argument("--group", action="store_true")
    a = ap.parse_args()
    if a.cmd == "list":
        cmd_list(a)
    elif a.cmd == "accept":
        cmd_accept(a)
    elif a.cmd == "reject":
        cmd_close(a, "rejected", {"reason": a.reason})
    else:
        if a.eid not in {e["id"] for e in load_ledger()}:
            sys.exit(f"{a.eid} not in ledger")
        cmd_close(a, "dup", {"duplicate_of": a.eid})


if __name__ == "__main__":
    main()
