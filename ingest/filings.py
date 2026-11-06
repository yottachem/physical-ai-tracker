"""SEC filings watcher: new filings for every tracked CIK go to the review queue.

Source: data.sec.gov submissions JSON (public domain; User-Agent with contact email; <= 10 requests/second).
Watched forms are the ones that mark funding (Form D), listing changes (S-1/S-4/DRS, Form 25, Form 15) and material
events (8-K, by item number). Form D amounts are parsed from primary_doc.xml: Form D reports amount sold to date for
an offering, not a round size or valuation, so it is queued as evidence, never summed as a round.
Parent-scope companies (Alphabet, Amazon, Meta, ...) and divisions are skipped: their filings describe the parent.

Usage: uv run python -m ingest.filings [--since YYYY-MM-DD] [company-id ...]
"""
import argparse
import csv
import json
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests

from ingest.common import ROOT, load_companies, load_ledger, user_agent, write_snapshot

QUEUE = ROOT / "data" / "review" / "queue.csv"
QUEUE_COLUMNS = ["qid", "found", "source", "company", "date", "kind", "suggested_type", "title", "url", "parsed",
                 "status"]

FORMS = {
    "D": "funding", "D/A": "funding",
    "S-1": "listing", "S-1/A": "listing", "F-1": "listing", "F-1/A": "listing", "DRS": "listing", "DRS/A": "listing",
    "S-4": "listing", "S-4/A": "listing", "F-4": "listing", "424B4": "listing",
    "25-NSE": "listing", "25": "listing", "15-12B": "listing", "15-12G": "listing", "15-15D": "listing",
    "8-K": None, "6-K": "market", "10-K": "headcount", "20-F": "headcount",
}
# 8-K item -> event type. Items not listed (9.01 exhibits, 5.07 votes, ...) do not by themselves queue a filing.
ITEMS = {"1.01": "contract", "1.03": "status", "2.01": "acquisition", "2.02": "revenue", "2.05": "layoff",
         "3.01": "listing", "5.01": "acquisition", "5.02": "status", "7.01": "market", "8.01": "market"}


def sec_get(url, **kw):
    r = requests.get(url, headers={"User-Agent": user_agent()}, timeout=60, **kw)
    r.raise_for_status()
    time.sleep(0.15)
    return r


def filings(cik, since):
    d = sec_get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json").json()
    r = d["filings"]["recent"]
    for form, fdate, acc, doc, items, desc in zip(r["form"], r["filingDate"], r["accessionNumber"],
                                                  r["primaryDocument"], r["items"], r["primaryDocDescription"]):
        if fdate < since:
            break
        if form not in FORMS:
            continue
        base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}"
        yield {"form": form, "date": fdate, "accession": acc, "items": items, "description": desc,
               "url": f"{base}/{doc}", "base": base}


def suggested_type(f):
    if FORMS[f["form"]]:
        return FORMS[f["form"]]
    types = [ITEMS[i] for i in f["items"].split(",") if i in ITEMS]
    return types[0] if types else None


def form_d(f):
    """Offering amounts from a Form D primary_doc.xml."""
    x = ET.fromstring(sec_get(f"{f['base']}/primary_doc.xml").content)
    od = x.find(".//offeringData")

    def num(path):
        v = od.findtext(path) if od is not None else None
        return int(float(v)) if v and v.replace(".", "").isdigit() else v

    return {"total_offering": num("offeringSalesAmounts/totalOfferingAmount"),
            "amount_sold": num("offeringSalesAmounts/totalAmountSold"),
            "first_sale": od.findtext("typeOfFiling/dateOfFirstSale/value") if od is not None else None,
            "new_or_amendment": "amendment" if od is not None and od.findtext("typeOfFiling/newOrAmendment/isAmendment")
            == "true" else "new",
            "securities": [e.tag for e in (od.find("typesOfSecuritiesOffered") if od is not None else None)
                           if e.text == "true"] if od is not None and od.find("typesOfSecuritiesOffered") is not None
            else []}


def read_queue():
    if not QUEUE.exists():
        return []
    with QUEUE.open() as fh:
        return list(csv.DictReader(fh))


def write_queue(rows):
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE.open("w", newline="") as fh:
        w = csv.DictWriter(fh, QUEUE_COLUMNS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda q: (q["status"] != "open", q["date"], q["company"])))


def main(ids, since):
    companies = load_companies()
    queue = read_queue()
    known = {q["qid"] for q in queue}
    cited = " ".join(e["sources"] for e in load_ledger())
    snapshot, errors, added = {}, {}, 0
    for cid in ids or companies:
        c = companies[cid]
        if not c.get("cik") or c["hiring_scope"] == "parent" or c["ownership"] == "division":
            continue
        try:
            found = list(filings(c["cik"], since))
        except (requests.RequestException, KeyError, ValueError) as e:
            errors[cid] = f"{type(e).__name__}: {e}"[:200]
            print(f"{cid}: ERROR {errors[cid]}", flush=True)
            continue
        snapshot[cid] = found
        new = 0
        for f in found:
            qid = f"sec:{f['accession']}"
            kind = suggested_type(f)
            if qid in known or kind is None or f["accession"].replace("-", "") in cited:
                continue
            # Form D's items field holds the Reg D exemption (06b = Rule 506(b)), not 8-K items
            parsed = {("exemption" if f["form"] in ("D", "D/A") else "items"): f["items"]} if f["items"] else {}
            if f["form"] in ("D", "D/A"):
                try:
                    parsed |= form_d(f)
                except (requests.RequestException, ET.ParseError) as e:
                    parsed["parse_error"] = type(e).__name__
            queue.append({"qid": qid, "found": date.today().isoformat(), "source": "sec", "company": cid,
                          "date": f["date"], "kind": f["form"], "suggested_type": kind,
                          "title": f"{c['name']}: {f['form']} {f['description']}".strip(), "url": f["url"],
                          "parsed": json.dumps(parsed, sort_keys=True), "status": "open"})
            known.add(qid)
            new += 1
        added += new
        print(f"{cid}: {len(found)} watched filings since {since}, {new} queued", flush=True)
    write_snapshot("filings", {"since": since, "companies": snapshot, "errors": errors})
    write_queue(queue)
    print(f"{added} queued; {sum(q['status'] == 'open' for q in queue)} open in {QUEUE.relative_to(ROOT)}; "
          f"{len(errors)} errors")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=(date.today() - timedelta(days=14)).isoformat())
    ap.add_argument("ids", nargs="*")
    a = ap.parse_args()
    main(a.ids, a.since)
