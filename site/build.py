"""Build the site into site/dist from the registry, ledger and data files. No JavaScript is needed to read it; a small
inline script adds the home and feed filters.

Pages: home (market map grid by segment, with the checked statements in analysis/claims.yaml), one page per company, feed, funding, hiring, methods, status.

Figures:
  raised     closed equity rounds with a disclosed amount, summed; debt, loans, grants and awards are left out, and
             "reported" rows (talks) are never summed with closed ones
  valuation  the latest ledger row carrying one, shown with its status (closed or reported)
  open roles the latest weekly job-board count; boards listed as a careers-page link are not counted, and parent-scope
             companies (NVIDIA, Tesla, ...) are left out of hiring totals because their boards describe the parent
Only headlines with a publisher link are shown; the site never links to Google.

Usage: uv run python site/build.py [--preview]
--preview marks every page as an internal preview (noindex, banner) and shows sections still waiting on Josh.
"""
import csv
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
import charts  # noqa: E402  (site/charts.py)
from analysis import claims  # noqa: E402
from ingest.common import load_companies, load_ledger, load_segments  # noqa: E402
from ingest.filings import read_queue  # noqa: E402
from ingest.news import read_articles  # noqa: E402

DIST = HERE / "dist"
REPO = "https://github.com/yottachem/physical-ai-tracker"
SITE_URL = "https://yottachem.github.io/physical-ai-tracker/"
ANALYTICS_TOKEN = ""  # Cloudflare Web Analytics token, set at launch
FEED_DAYS = 60
NOT_EQUITY = re.compile(r"\b(debt|loan|credit|grant|award|bridge)\b", re.I)
STAGE = re.compile(r"^(Pre-seed|Seed|Series [A-Z](-\d)?)\b", re.I)
OWNERSHIP = {"private": "Private", "public": "Public", "subsidiary": "Subsidiary", "division": "Division"}
TYPE_LABELS = {"funding": "Funding", "valuation": "Valuation", "revenue": "Revenue", "deployment": "Deployment",
               "product": "Product", "partnership": "Partnership", "contract": "Contract", "facility": "Facility",
               "acquisition": "Acquisition", "regulatory": "Regulatory", "headcount": "Headcount", "layoff": "Layoff",
               "listing": "Listing", "market": "Market", "status": "Status"}
FUNCTIONS = {"ml-ai": "ML and AI", "software": "Software", "robotics-controls": "Robotics and controls",
             "hardware": "Hardware", "research": "Research", "manufacturing-ops": "Manufacturing and ops",
             "field-deployment": "Field deployment", "product-design": "Product and design",
             "regulatory-clinical": "Regulatory and clinical", "go-to-market": "Go to market", "g-and-a": "G&A",
             "other": "Other"}
# Hand-curated inputs listed on the status page: everything else is fetched each run
CURATED = [("reference/companies.yaml", "Company registry: segments, HQ, Boston flag, ownership, domains, news terms, boards"),
           ("reference/segments.yaml", "Customer segments from the Nov 2026 market map"),
           ("reference/source_tiers.yaml", "Source tiers that decide auto-acceptance"),
           ("reference/ledger.csv", "Accepted events (auto-accepted rows are added by the daily run)")]


def read(path):
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def day(d):
    """Sort key for ledger dates, which may be YYYY, YYYY-MM or YYYY-MM-DD; undated rows sort last."""
    return d or "0000"


def show_date(d):
    return d or "undated"


def month(d):
    """'Jul 2026' from 'YYYY-MM[-DD]'."""
    return date(int(d[:4]), int(d[5:7]), 1).strftime("%b %Y")


def half(d):
    """'2026 H2' when the month is known, else the year, else None."""
    if len(d) >= 7:
        return f"{d[:4]} H{1 if int(d[5:7]) <= 6 else 2}"
    return d[:4] or None


def is_equity(r):
    return r["type"] == "funding" and not NOT_EQUITY.search(f"{r['round']} {r['detail']}")


def links(sources):
    return [{"url": u, "host": re.sub(r"^www\.", "", u.split("/")[2]) if "://" in u else u} for u in sources.split()]


def ledger_row(r, companies):
    return {**r, "amount": num(r["amount_usd"]), "valuation": num(r["valuation_usd"]), "links": links(r["sources"]),
            "type_label": TYPE_LABELS.get(r["type"], r["type"]), "name": companies[r["company"]]["name"]}


def jobs_by_company():
    """{company: [(date, total, boston, by_function)]} in date order."""
    out = defaultdict(list)
    for r in sorted(read(ROOT / "data" / "jobs" / "counts.csv"), key=lambda r: r["date"]):
        out[r["company"]].append((r["date"], int(r["total"]), int(r["boston"]), json.loads(r["by_function"] or "{}")))
    return out


def company_records(companies, segments, ledger, articles, jobs, values, heads, fin):
    out = {}
    for cid, c in companies.items():
        rows = sorted((r for r in ledger if r["company"] == cid), key=lambda r: day(r["date"]), reverse=True)
        closed = [r for r in rows if is_equity(r) and r["status"] == "closed" and r["amount"]]
        val = next((r for r in rows if r["valuation"]), None)
        rnd = next((STAGE.match(r["round"])[1] for r in rows if r["type"] == "funding" and STAGE.match(r["round"])), None)
        own = c["ownership"]
        stage = (f"Public ({c['ticker']})" if own == "public" else f"{OWNERSHIP[own]} of {c['parent']}" if c["parent"]
                 else rnd or OWNERSHIP[own])
        if c.get("wound_down"):
            stage = f"Wound down {month(c['wound_down'])}" + (f", ex-{c['ticker']}" if own == "public" else "")
        series = jobs.get(cid, [])
        counted = c["careers"] and c["careers"]["ats"] != "other"
        news = sorted((a for a in articles if a["company"] == cid and a["url"]), key=lambda a: a["date"], reverse=True)
        mv = values.get(cid)
        head = sorted([{"as_of": h["as_of"], "n": int(h["employees"]), "qualifier": h["qualifier"], "source": h["url"],
                        "via": h["form"]} for h in heads if h["company"] == cid]
                      + [{"as_of": r["date"], "n": None, "qualifier": r["qualifier"], "source": r["links"][0]["url"]
                          if r["links"] else "", "via": r["detail"]} for r in rows if r["type"] == "headcount"],
                      key=lambda h: day(h["as_of"]), reverse=True)
        f = [x for x in fin if x["company"] == cid]
        annual = sorted((x for x in f if x["metric"] == "revenue" and re.fullmatch(r"CY\d{4}", x["frame"])),
                        key=lambda x: x["frame"])
        cash = sorted((x for x in f if x["metric"] == "cash"), key=lambda x: x["end"])
        out[cid] = {
            "id": cid, "c": c, "segments": [(s, segments[s]["name"]) for s in c["segments"]],
            "rows": rows, "funding": [r for r in rows if r["type"] in ("funding", "valuation")],
            "events": [r for r in rows if r["type"] not in ("funding", "valuation")],
            "raised": sum(r["amount"] for r in closed), "raised_n": len(closed),
            "raised_floor": any(r["qualifier"] == "at_least" for r in closed),
            "valuation": val, "stage": stage, "ownership": own, "wound_down": c.get("wound_down"),
            "counted": bool(counted) and c["hiring_scope"] == "company",
            "careers_url": c["careers"]["token"] if c["careers"] and c["careers"]["ats"] == "other" else None,
            "roles": series[-1][1] if series and counted else None, "boston_roles": series[-1][2] if series and counted else None,
            "functions": series[-1][3] if series and counted else {}, "roles_series": series,
            "spark": charts.spark_seq([s[1] for s in series]) if counted else "",
            "news": news[:25], "last_news": next((a for a in news if a["events"] or a["tier"] == "tier1"), None),
            "market_value": mv, "headcount": head,
            "revenue": annual[-1] if annual else None, "cash": cash[-1] if cash else None,
        }
    return out


def home_context(recs, segments):
    groups = []
    for sid, s in segments.items():
        members = sorted((r for r in recs.values() if sid in r["c"]["segments"]),
                         key=lambda r: (-(r["valuation"]["valuation"] if r["valuation"] else 0), r["c"]["name"]))
        groups.append({"id": sid, "name": s["name"], "customers": s["customers"], "rows": members})
    company = [r for r in recs.values() if r["counted"] and r["roles"] is not None]
    since = (date.today() - timedelta(days=365)).isoformat()
    figs = {"companies": len(recs), "boston": sum(r["c"]["boston"] for r in recs.values()),
            "raised_12m": sum(x["amount"] for r in recs.values() for x in r["rows"]
                              if is_equity(x) and x["status"] == "closed" and x["amount"] and x["date"] >= since[:7]),
            "roles": sum(r["roles"] for r in company), "boston_roles": sum(r["boston_roles"] for r in company),
            "boards": len(company)}
    return {"groups": groups, "figs": figs}


def feed_context(recs, articles):
    since = (date.today() - timedelta(days=FEED_DAYS)).isoformat()
    items = sorted((a for a in articles if a["url"] and a["date"] >= since), key=lambda a: (a["date"], a["company"]),
                   reverse=True)
    rows = [{**a, "r": recs[a["company"]], "event_list": [e for e in a["events"].split("|") if e]} for a in items]
    used = sorted({e for r in rows for e in r["event_list"]})
    return {"rows": rows, "days": FEED_DAYS, "event_types": [(e, TYPE_LABELS.get(e, e)) for e in used]}


def funding_context(recs, segments, ledger):
    rows = sorted((r for r in ledger if r["type"] in ("funding", "valuation")), key=lambda r: day(r["date"]), reverse=True)
    periods = sorted({half(r["date"]) for r in rows if len(r["date"]) >= 7 and r["date"] >= "2024"}, reverse=True)
    table = []
    for sid, s in segments.items():
        cells = {}
        for p in periods:
            sel = [r for r in rows if is_equity(r) and r["amount"] and half(r["date"]) == p
                   and sid in recs[r["company"]]["c"]["segments"]]
            cells[p] = {"closed": sum(r["amount"] for r in sel if r["status"] == "closed"),
                        "reported": sum(r["amount"] for r in sel if r["status"] != "closed"),
                        "n": len(sel)}
        table.append({"name": s["name"], "cells": cells})
    return {"rows": rows, "periods": periods, "table": table, **funding_charts(recs, segments, rows)}


def funding_charts(recs, segments, rows, start="2021"):
    """Closed and reported equity per half-year since start: the market (each round once) and each segment."""
    now = half(date.today().isoformat())
    span = [f"{y} H{h}" for y in range(int(start), int(now[:4]) + 1) for h in (1, 2)]
    span = span[:span.index(now) + 1]
    eq = [r for r in rows if is_equity(r) and r["amount"] and len(r["date"]) >= 7 and r["date"] >= start]

    def sums(sel, closed):
        out = defaultdict(float)
        for r in sel:
            if (r["status"] == "closed") == closed:
                out[half(r["date"])] += r["amount"]
        return out

    def chart(sel, name, **kw):
        return charts.half_bars(span, sums(sel, True), sums(sel, False), partial=now,
                                desc=f"{name}: disclosed equity per half-year since {start}", **kw)

    panels = []
    for sid, s in segments.items():
        sel = [r for r in eq if sid in recs[r["company"]]["c"]["segments"]]
        if sel:
            panels.append({"name": s["name"], "total": sum(r["amount"] for r in sel if r["status"] == "closed"),
                           "svg": chart(sel, s["name"], width=320, height=130, small=True)})
    return {"market_chart": chart(eq, "All tracked companies", width=1000, height=280),
            "market_chart_small": chart(eq, "All tracked companies", width=340, height=170, small=True), "panels": sorted(panels, key=lambda p: -p["total"]),
            "chart_start": start}


def hiring_context(recs, segments, jobs):
    counted = [r for r in recs.values() if r["counted"] and r["roles"] is not None]
    dates = sorted({d for s in jobs.values() for d, *_ in s})
    first, last = (dates[0], dates[-1]) if dates else (None, None)

    def at(r, d):
        return next((t for dd, t, *_ in r["roles_series"] if dd == d), None)

    for r in counted:
        a = at(r, first)
        r["change"] = r["roles"] - a if a is not None and first != last else None
    seg_rows = []
    for sid, s in segments.items():
        m = [r for r in counted if sid in r["c"]["segments"]]
        seg_rows.append({"name": s["name"], "companies": len(m), "roles": sum(r["roles"] for r in m),
                         "boston": sum(r["boston_roles"] for r in m)})
    fn = defaultdict(int)
    for r in counted:
        for k, v in r["functions"].items():
            fn[k] += v
    total = sum(r["roles"] for r in counted)
    not_counted = sorted((r for r in recs.values() if not r["counted"]), key=lambda r: r["c"]["name"])
    return {"rows": sorted(counted, key=lambda r: -r["roles"]), "seg_rows": seg_rows, "first": first, "last": last,
            "by_function": sorted(((FUNCTIONS.get(k, k), v) for k, v in fn.items()), key=lambda x: -x[1]),
            "total": total, "boston": sum(r["boston_roles"] for r in counted), "not_counted": not_counted}


def last_changed(path):
    r = subprocess.run(["git", "log", "-1", "--format=%cs", "--", path], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip() or None


def status_context(ledger, articles, jobs, values, heads, fin):
    queue = read_queue()
    warn = [q for q in queue if q["source"] == "warn"]
    sec = [q for q in queue if q["source"] not in ("warn", "news")]
    prices = read(ROOT / "data" / "public" / "prices.csv")
    sources = [
        {"name": "News: Bing, GDELT, Google News, company newsrooms", "what": "Headlines and publisher links",
         "last": max((a["found"] for a in articles), default=None), "cadence": "Daily"},
        {"name": "SEC EDGAR filings", "what": "Form D, 8-K, S-1/S-4, Forms 15 and 25 (to the review queue)",
         "last": max((q["found"] for q in sec), default=None), "cadence": "Daily"},
        {"name": "State WARN notices", "what": "Layoff notices: California, Texas, Massachusetts (monthly file)",
         "last": max((q["found"] for q in warn), default=None), "cadence": "Daily"},
        {"name": "Job boards", "what": "Open roles by function and location", "last": max(
            (d for s in jobs.values() for d, *_ in s), default=None), "cadence": "Weekly (Mondays)"},
        {"name": "SEC XBRL financials and annual reports", "what": "Revenue, net income, R&D, cash, shares, headcount",
         "last": max((x["filed"] for x in fin), default=None), "cadence": "Weekly (Mondays)"},
        {"name": "Weekly closing prices", "what": "Market value with SEC shares outstanding",
         "last": max((p["date"] for p in prices), default=None), "cadence": "Weekly (Mondays)"},
    ]
    return {"sources": sources, "open": sum(q["status"] == "open" for q in queue), "ledger_n": len(ledger),
            "auto_n": sum(r["accept"] == "auto" for r in ledger),
            "curated": [{"path": p, "what": w, "changed": last_changed(p)} for p, w in CURATED]}


def load():
    """Everything the pages are built from; analysis/claims.py uses it too."""
    companies = load_companies()
    segments = load_segments()
    ledger = [ledger_row(r, companies) for r in load_ledger()]
    articles = read_articles()
    jobs = jobs_by_company()
    values = {r["company"]: {**r, "cap": num(r["market_cap"]), "close_n": num(r["close"])}
              for r in read(ROOT / "data" / "public" / "market_value.csv")}
    heads = read(ROOT / "data" / "public" / "headcount.csv")
    fin = read(ROOT / "data" / "public" / "financials.csv")
    recs = company_records(companies, segments, ledger, articles, jobs, values, heads, fin)
    return {"companies": companies, "segments": segments, "ledger": ledger, "articles": articles, "jobs": jobs,
            "values": values, "heads": heads, "fin": fin, "recs": recs}


def main(preview=False):
    d = load()
    companies, segments, ledger, articles, jobs, values, heads, fin, recs = (
        d[k] for k in ("companies", "segments", "ledger", "articles", "jobs", "values", "heads", "fin", "recs"))

    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape(["html", "j2"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters["fmt"] = charts.fmt
    env.filters["show_date"] = show_date
    built = date.today().isoformat()
    common = {"repo": REPO, "preview": preview, "site_url": SITE_URL, "built": built,
              "analytics_token": "" if preview else ANALYTICS_TOKEN, "segments": segments,
              "type_labels": TYPE_LABELS, "functions": FUNCTIONS}
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "company").mkdir(parents=True)

    def render(template, path, page, **ctx):
        (DIST / path).write_text(env.get_template(template).render(**common, page=page, **ctx))

    said, _ = claims.evaluate(claims.values(recs, segments, functions=FUNCTIONS)) if claims.SPEC.exists() else ({}, [])
    render("index.html.j2", "index.html", "index", **home_context(recs, segments), claims=said)
    for r in recs.values():
        render("company.html.j2", f"company/{r['id']}.html", "company", r=r, up="../")
    render("feed.html.j2", "feed.html", "feed", **feed_context(recs, articles))
    render("funding.html.j2", "funding.html", "funding", **funding_context(recs, segments, ledger))
    render("hiring.html.j2", "hiring.html", "hiring", **hiring_context(recs, segments, jobs))
    render("methods.html.j2", "methods.html", "methods")
    render("status.html.j2", "status.html", "status", **status_context(ledger, articles, jobs, values, heads, fin))
    for f in (HERE / "static").iterdir():
        shutil.copy(f, DIST / f.name)
    (DIST / ".nojekyll").touch()
    print(f"site/dist: {sum(1 for _ in DIST.rglob('*') if _.is_file())} files{' (preview)' if preview else ''}")


if __name__ == "__main__":
    main(preview="--preview" in sys.argv)
