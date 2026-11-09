"""Group open review-queue items that describe the same event, so one decision covers them all.

News items (same company and event type; funding and valuation count as one type) are linked when they share a
figure (any amount or valuation within 10%) dated within 45 days, or, when either has no figure, when their titles
overlap (token Jaccard >= 0.4) within 10 days. A company lists once, so its listing items within 30 days always link.
Links are transitive. SEC filings group only when routine: same company, form and 8-K items (earnings, votes, Reg FD,
other events, officer changes, 6-K, 10-K, 20-F), so a stack of quarterly reports is one decision; Form D,
registrations, delistings and material 8-Ks stay one item each.

Groups are computed from the open items each time, never stored; the group id is its lead item's qid.
"""
import json

from classify.accept import close, days_apart
from ingest.news import norm_title

RANK = {"tier1": 0, "tier2": 1, "secondary": 2, "unclassified": 3}
ROUTINE_FORMS = {"6-K", "10-K", "10-K/A", "20-F", "10-Q"}
ROUTINE_ITEMS = {"2.02", "5.02", "5.07", "7.01", "8.01", "9.01"}
STOP = {"a", "an", "the", "to", "of", "in", "on", "for", "and", "with", "as", "at", "its", "by", "from", "is", "it",
        "s", "new", "says", "after"}


def figures(q):
    p = json.loads(q["parsed"] or "{}")
    return [f for f in [*(p.get("amounts") or []), p.get("valuation")] if f]


def tokens(title):
    return {t for t in norm_title(title).split() if t not in STOP and not t.replace(".", "").isdigit()}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def family(t):
    return "money" if t in ("funding", "valuation") else t


def linked(a, b):
    if a["company"] != b["company"] or a["source"] != "news" or b["source"] != "news":
        return False
    if family(a["suggested_type"]) != family(b["suggested_type"]):
        return False
    fa, fb = figures(a), figures(b)
    gap = days_apart(a["date"], b["date"])
    if a["suggested_type"] == "listing":
        return gap <= 30
    if fa and fb:
        return gap <= 45 and any(close(x, y) for x in fa for y in fb)
    return gap <= 10 and jaccard(tokens(a["title"]), tokens(b["title"])) >= 0.4


def sec_key(q):
    if q["source"] != "sec":
        return None
    items = json.loads(q["parsed"] or "{}").get("items", "")
    if q["kind"] in ROUTINE_FORMS or (q["kind"] == "8-K" and items and set(items.split(",")) <= ROUTINE_ITEMS):
        return (q["company"], q["kind"], items)
    return None


def lead_key(q):
    return (RANK.get(q["kind"], 2) if q["source"] == "news" else 0, not figures(q), not q["url"], q["date"], q["qid"])


def groups(rows):
    """Open rows -> list of groups (lists of rows), each sorted lead first; groups ordered by company then date."""
    rows = [r for r in rows if r["status"] == "open"]
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_key = {}
    for i, r in enumerate(rows):
        k = sec_key(r)
        if k:
            parent[find(i)] = find(by_key.setdefault(k, i))
    news = [i for i, r in enumerate(rows) if r["source"] == "news"]
    for x, i in enumerate(news):
        for j in news[x + 1:]:
            if linked(rows[i], rows[j]):
                parent[find(i)] = find(j)
    out = {}
    for i, r in enumerate(rows):
        out.setdefault(find(i), []).append(r)
    gs = [sorted(g, key=lead_key) for g in out.values()]
    return sorted(gs, key=lambda g: (g[0]["company"], min(r["date"] for r in g)))


def group_of(rows, qid):
    for g in groups(rows):
        if any(r["qid"] == qid for r in g):
            return g
    return None
