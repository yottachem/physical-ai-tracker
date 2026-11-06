"""Acceptance rules: news headlines -> ledger (auto), review queue (open) or closed as a duplicate.

A headline is a ledger candidate when it carries a ledger event type (classify.events.LEDGER). Funding and valuation
headlines also need a dollar figure; without one they stay feed items.

Auto-accept (accept = auto) needs all of:
  - a tier-1 source with a publisher link
  - a funding or valuation headline naming the company in the title and no other tracked company
  - exactly one funding amount, or none with a stated valuation
  - for amounts: a closing verb or named round (raises, closes, secures, Series B) and no debt, grant, award,
    government program or "X invests in" wording; talks and plans are exempt because they stay reported
  - a valuation-only headline within 14 days of a funding row without a valuation goes to review (same round?)
  - no conflict with the ledger: an existing row for the company with the same round but an amount more than 10%
    away is a conflict and goes to review
Talks and rumors ("in talks", "reportedly", ...) are accepted from tier 1 with status reported, never closed.
A figure within 10% of an existing funding or valuation row for the company is a duplicate: the queue keeps a closed
"dup" row naming the ledger id, and the ledger is not touched.
Everything else (other tiers, listing/acquisition/layoff/status news, parse doubts) goes to the queue as open.

Usage: uv run python -m classify.accept      (processes every stored article not yet decided)
"""
import csv
import json
from datetime import date

from classify.events import LEDGER as LEDGER_TYPES
from classify.events import clean_round, events, money, qualifier, reported, round_of, valuation
from ingest.common import LEDGER as LEDGER_PATH
from ingest.common import LEDGER_COLUMNS, load_companies, load_ledger, tier_of
from ingest.filings import read_queue, write_queue
from ingest.news import _has, phrases, read_articles, write_articles


def named(c, title):
    """True when one of the company's news terms appears in the title itself (context not required)."""
    return any(all(_has(title, p) for p in phrases(t)) for t in c["news"]["terms"])


def close(a, b, tol=0.10):
    return a and b and abs(a - b) <= tol * max(a, b)


def num(v):
    return int(float(v)) if v not in ("", None) else None


def days_apart(a, b):
    """Days between two ledger dates; partial dates (YYYY-MM, YYYY) compare from their first day, empty = far."""
    if not a or not b:
        return 10**6
    pad = lambda d: date.fromisoformat((d + "-01-01")[:10] if len(d) == 4 else (d + "-01")[:10])  # noqa: E731
    return abs((pad(a) - pad(b)).days)


def decide(article, companies, ledger):
    """Return (decision, payload): ("auto", ledger_row) | ("dup", ledger_id) | ("queue", parsed) | (None, None)."""
    title, cid = article["title"], article["company"]
    c = companies[cid]
    found = [t for t in events(title) if t in LEDGER_TYPES]
    if not found:
        return None, None
    kind = found[0]
    amounts, val, rnd, rep = money(title), valuation(title), round_of(title), reported(title)
    parsed = {"type": kind, "events": found, "amounts": amounts, "valuation": val, "round": rnd, "reported": rep}
    if kind in ("funding", "valuation") and not (amounts or val):
        return None, None  # no figure: feed item only
    rows = [e for e in ledger if e["company"] == cid]
    if kind in ("funding", "valuation"):
        for e in rows:
            if (amounts and any(close(a, num(e["amount_usd"])) for a in amounts)) or close(val, num(e["valuation_usd"])):
                if val and not e["valuation_usd"]:
                    return "queue", dict(parsed, reasons=[f"adds a valuation to {e['id']}"])
                return "dup", e["id"]
    others = [k for k, o in companies.items() if k != cid and named(o, title)]
    reasons = []
    if article["tier"] != "tier1":
        reasons.append(f"tier {article['tier'] or 'unclassified'}")
    if not article["url"]:
        reasons.append("no publisher link")
    if kind not in ("funding", "valuation"):
        reasons.append(f"{kind} news needs review")
    if not named(c, title):
        reasons.append("company not named in title")
    if others:
        reasons.append("also names " + ", ".join(others))
    if len(amounts) > 1:
        reasons.append("several amounts")
    if kind == "funding" and amounts and not rep and not clean_round(title):
        reasons.append("not clearly a closed equity round (debt, grant, third-party investment or no closing verb)")
    if not amounts and val:
        near = [e["id"] for e in rows if e["type"] == "funding" and not e["valuation_usd"]
                and days_apart(e["date"], article["date"]) <= 14]
        if near:
            reasons.append(f"valuation may belong to {', '.join(near)}")
    if rnd:
        for e in rows:
            if e["round"].lower() == rnd.lower() and num(e["amount_usd"]) and amounts \
                    and not close(amounts[0], num(e["amount_usd"])):
                reasons.append(f"conflicts with {e['id']} ({e['round']} {e['amount_usd']})")
    if reasons:
        return "queue", dict(parsed, reasons=reasons)
    row = {k: "" for k in LEDGER_COLUMNS}
    row.update(company=cid, date=article["date"], type="funding" if amounts else "valuation", round=rnd,
               amount_usd=str(amounts[0]) if amounts else "", valuation_usd=str(val) if val else "",
               qualifier=qualifier(title),
               status="reported" if rep else "closed", detail=title, sources=article["url"], accept="auto",
               added=date.today().isoformat())
    return "auto", row


def main():
    companies = load_companies()
    ledger = load_ledger()
    queue = read_queue()
    done = {q["qid"] for q in queue}
    cited = " ".join(e["sources"] for e in ledger)
    today = date.today().isoformat()
    next_id = max(int(e["id"][1:]) for e in ledger) + 1
    counts = {"auto": 0, "dup": 0, "queue": 0}
    new_rows = []
    articles = read_articles()
    for a in articles:  # this stage owns the events and tier columns, so pattern or tier changes re-tag stored rows
        a["events"] = "|".join(events(a["title"]))
        if a["url"] or a["domain"]:
            a["tier"] = tier_of(a["url"] or "https://" + a["domain"]) or ""
    write_articles(articles)
    for a in sorted(articles, key=lambda a: a["date"]):
        qid = f"news:{a['aid']}"
        if qid in done or a["company"] not in companies or (a["url"] and a["url"] in cited):
            continue
        decision, payload = decide(a, companies, ledger + new_rows)
        if decision is None:
            continue
        counts[decision] += 1
        base = {"qid": qid, "found": today, "source": "news", "company": a["company"], "date": a["date"],
                "kind": a["tier"] or "unclassified", "title": a["title"], "url": a["url"]}
        if decision == "auto":
            payload["id"] = f"E{next_id:04d}"
            next_id += 1
            new_rows.append(payload)
            queue.append(dict(base, suggested_type=payload["type"], parsed=json.dumps({"ledger": payload["id"]}),
                              status="auto"))
        elif decision == "dup":
            queue.append(dict(base, suggested_type="funding", parsed=json.dumps({"duplicate_of": payload}),
                              status="dup"))
        else:
            queue.append(dict(base, suggested_type=payload["type"], parsed=json.dumps(payload, sort_keys=True),
                              status="open"))
        done.add(qid)
    if new_rows:
        with open(LEDGER_PATH, "a", newline="") as fh:
            csv.DictWriter(fh, LEDGER_COLUMNS).writerows(new_rows)
    write_queue(queue)
    print(f"auto-accepted {counts['auto']} (ledger {new_rows[0]['id'] + '..' + new_rows[-1]['id'] if new_rows else '-'}),"
          f" {counts['dup']} duplicates, {counts['queue']} queued; {sum(q['status'] == 'open' for q in queue)} open")


if __name__ == "__main__":
    main()
