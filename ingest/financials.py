"""Public-company financials (XBRL) and headcount (annual report text) from SEC EDGAR.

Scope: public companies with a CIK whose filings describe the tracked business (hiring_scope company). Parent-scope
companies (NVIDIA, Tesla, Apple, Meta) and divisions are skipped: their financials describe the parent. Non-US
listings (ticker with an exchange suffix) have no SEC filings.

Financials: data.sec.gov companyfacts. Only facts carrying an SEC "frame" are kept; the frame is the calendar period
(CY2026Q2, CY2025, CY2025Q4I for an instant) and EDGAR assigns it to one fact per company, concept and period, which
removes the duplicates that comparatives in later filings create. Periods from 2023 on.
  revenue, net_income, rnd (R&D expense): quarterly and annual durations
  cash (cash and equivalents), shares (common shares outstanding, all classes summed): instants
Facts filed while the CIK was still a SPAC shell (current or former EDGAR name like "... Acquisition Corp" or
"... Capital Corp") describe the shell, not the company, and are dropped; a CIK that is still a shell is skipped
until EDGAR renames it.

Headcount: the latest 10-K or 20-F's employee sentence ("As of December 31, 2025, we had approximately 1,840
full-time employees"), with the quote kept as evidence. Each annual report adds one row.

Usage: uv run python -m ingest.financials [company-id ...]
"""
import argparse
import csv
import html
import re
from datetime import date, datetime

import requests

from ingest.common import ROOT, load_companies, write_snapshot
from ingest.filings import sec_get

OUT = ROOT / "data" / "public"
FIN = OUT / "financials.csv"
HEAD = OUT / "headcount.csv"
FIN_COLUMNS = ["company", "metric", "frame", "start", "end", "value", "unit", "form", "accn", "filed", "tag"]
HEAD_COLUMNS = ["company", "as_of", "employees", "qualifier", "form", "accn", "filed", "url", "quote"]
FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "6-K", "8-K", "8-K/A"}
SINCE = "2023-01-01"
METRICS = {  # first tag present for a frame wins
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "rnd": ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
}
SHELL = re.compile(r"\b(acquisition|capital)\s+corp", re.I)
EMPLOYEES = re.compile(
    r"(?P<quote>[^.]{0,160}?\b(?:had|employ(?:ed|s)?|workforce of|team of|consisted of)\s+(?:a total of\s+)?"
    r"(?P<q>approximately|about|over|more than|nearly|around)?\s*(?P<n>\d{1,3}(?:,\d{3})+|\d{2,6})\s+"
    r"(?:full-time\s+|total\s+|global\s+)?(?:and\s+\d[\d,]*\s+part-time\s+)?"
    r"(?:employees|team members|people|personnel|staff)[^.]{0,400}\.?)", re.I)
QUAL = {"approximately": "approx", "about": "approx", "around": "approx", "nearly": "approx", "over": "at_least",
        "more than": "at_least"}


def shell_cutoff(sub):
    """'' if the CIK never was a SPAC shell; the date it stopped being one; None if it still is."""
    if SHELL.search(sub["name"]):
        return None
    ends = [f["to"][:10] for f in sub.get("formerNames", []) if SHELL.search(f["name"]) and f.get("to")]
    return max(ends, default="")


def facts(cik, cutoff):
    data = sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json").json()["facts"]
    gaap, dei = data.get("us-gaap", {}), data.get("dei", {})
    keep = lambda f: f.get("frame") and f["form"] in FORMS and f["end"] >= SINCE and f["filed"] >= cutoff  # noqa: E731
    rows = {}
    for metric, tags in METRICS.items():
        for tag in tags:
            for unit, items in gaap.get(tag, {}).get("units", {}).items():
                for f in filter(keep, items):
                    rows.setdefault((metric, f["frame"]), dict(metric=metric, frame=f["frame"], start=f.get("start", ""),
                                                               end=f["end"], value=f["val"], unit=unit, form=f["form"],
                                                               accn=f["accn"], filed=f["filed"], tag=tag))
    shares = {}
    for f in dei.get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", []):
        if f["form"] in FORMS and f["end"] >= SINCE and f["filed"] >= cutoff:
            k = (f["accn"], f["end"])  # one row per filing; multiple share classes are summed
            s = shares.setdefault(k, dict(metric="shares", frame=f.get("frame", ""), start="", end=f["end"], value=0,
                                          unit="shares", form=f["form"], accn=f["accn"], filed=f["filed"],
                                          tag="dei:EntityCommonStockSharesOutstanding"))
            s["value"] += f["val"]
    return [*rows.values(), *shares.values()]


def text_of(url):
    raw = sec_get(url).text
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub("[\u2010-\u2015\u2212]", "-", text.replace("\u200b", "").replace("\u2019", "'"))
    return re.sub(r"\s+", " ", text)


def headcount(text):
    """(employees, qualifier, quote) from the first employee sentence after a human capital heading, else anywhere."""
    i = max(text.lower().find("human capital"), 0)
    for chunk in (text[i:i + 20000], text):
        for m in EMPLOYEES.finditer(chunk):
            n = int(m["n"].replace(",", ""))
            if 10 <= n <= 500_000 and not re.search(r"\b(19|20)\d\d\b$", m["n"]):
                return n, QUAL.get((m["q"] or "").lower(), ""), m["quote"].strip()[:300]
    return None


def stated_date(quote):
    """ISO date from 'As of March 9, 2026' in the quote, else None (the report period end is used)."""
    m = re.search(r"as of ([A-Z][a-z]+ \d{1,2}, \d{4})", quote, re.I)
    try:
        return datetime.strptime(m[1], "%B %d, %Y").date().isoformat() if m else None
    except ValueError:
        return None


def latest_annual(sub, cutoff):
    r = sub["filings"]["recent"]
    for i, form in enumerate(r["form"]):
        if form in ("10-K", "20-F", "40-F") and r["filingDate"][i] >= cutoff:
            acc = r["accessionNumber"][i]
            url = f"https://www.sec.gov/Archives/edgar/data/{int(sub['cik'])}/{acc.replace('-', '')}/{r['primaryDocument'][i]}"
            return dict(form=form, accn=acc, filed=r["filingDate"][i], as_of=r["reportDate"][i], url=url)
    return None


def read(path):
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def write(path, columns, rows, key):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, columns)
        w.writeheader()
        w.writerows(sorted(rows, key=key))


def in_scope(c):
    return (c["ownership"] == "public" and c.get("cik") and c["hiring_scope"] == "company"
            and "." not in (c.get("ticker") or ""))


def main(ids):
    companies = load_companies()
    fin = [r for r in read(FIN) if ids and r["company"] not in ids]  # a full run rebuilds; a subset keeps the rest
    heads = read(HEAD)
    seen = {r["accn"] for r in heads}
    errors, snapshot = {}, {}
    for cid in ids or companies:
        c = companies[cid]
        if not in_scope(c):
            continue
        try:
            sub = sec_get(f"https://data.sec.gov/submissions/CIK{c['cik']:010d}.json").json()
            cutoff = shell_cutoff(sub)
            if cutoff is None:
                print(f"{cid}: CIK {c['cik']} is still the SPAC shell ({sub['name']}); skipped", flush=True)
                continue
            rows = facts(c["cik"], cutoff)
            fin += [dict(r, company=cid) for r in rows]
            ann = latest_annual(sub, cutoff)
            found = None
            if ann and ann["accn"] not in seen:
                found = headcount(text_of(ann["url"]))
                if found:
                    n, q, quote = found
                    heads.append(dict(ann, company=cid, employees=n, qualifier=q, quote=quote,
                                      as_of=stated_date(quote) or ann["as_of"]))
                    seen.add(ann["accn"])
            snapshot[cid] = {"cutoff": cutoff, "facts": len(rows), "annual": ann, "headcount": found}
            note = (f"headcount {found[0]} ({ann['form']} {ann['as_of']})" if found else "no annual report" if not ann
                    else "headcount already recorded" if ann["accn"] in seen else "headcount NOT FOUND in " + ann["url"])
            print(f"{cid}: {len(rows)} facts; {note}", flush=True)
        except (requests.RequestException, KeyError, ValueError) as e:
            errors[cid] = f"{type(e).__name__}: {e}"[:200]
            print(f"{cid}: ERROR {errors[cid]}", flush=True)
    write(FIN, FIN_COLUMNS, fin, key=lambda r: (r["company"], r["metric"], r["end"], r["frame"]))
    write(HEAD, HEAD_COLUMNS, heads, key=lambda r: (r["company"], r["as_of"]))
    write_snapshot("financials", {"run": date.today().isoformat(), "companies": snapshot, "errors": errors})
    print(f"{len(fin)} facts, {len(heads)} headcount rows; {len(errors)} errors")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    main(ap.parse_args().ids)
