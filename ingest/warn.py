"""State WARN layoff notices -> review queue (suggested type layoff).

Sources (public state spreadsheets, fetched as published):
  CA  EDD "Detailed WARN Report", current fiscal year (July 1 on), updated Tuesdays and Thursdays
  TX  TWC WARN Act listings, current and previous calendar year
Massachusetts posts its WARN reports on mass.gov, which refuses scripted downloads; MA is not covered yet.

An employer matches a tracked company when its name, after dropping a trailing " - site" and legal suffixes,
starts with the company's name or one of its quoted news terms. One-word names of companies with ambiguous names
(those with news.context words: Sunday, Potato, Figure, ...) must match the whole employer name. Parent-scope companies and divisions are skipped:
their notices describe the parent. Every match is queued for review; nothing reaches the ledger without approval.

Usage: uv run python -m ingest.warn [company-id ...]
"""
import argparse
import hashlib
import io
import json
import re
from datetime import date, datetime

import warnings

import openpyxl
import requests

from ingest.common import load_companies, write_snapshot
from ingest.filings import read_queue, write_queue

UA = {"User-Agent": "physical-ai-tracker (+https://github.com/yottachem/physical-ai-tracker)"}
LEGAL = re.compile(r"[,.]?\s+(inc|llc|l\.l\.c|corp|corporation|co|company|ltd|limited|lp|pbc|holdings)\b\.?", re.I)


def ca():
    url = "https://edd.ca.gov/siteassets/files/jobs_and_training/warn/warn_report1.xlsx"
    for r in sheet_rows(url, "Detailed WARN Report"):
        if isinstance(r[1], datetime) and r[4]:
            yield dict(state="CA", url=url, employer=str(r[4]), notice=r[1].date().isoformat(),
                       effective=r[3].date().isoformat() if isinstance(r[3], datetime) else "",
                       count=r[6], kind=str(r[5] or "").replace("\n", " "), site=re.sub(r"\s+", " ", str(r[7] or "")))


def tx():
    year = date.today().year
    for y in (year, year - 1):
        url = f"https://www.twc.texas.gov/sites/default/files/oei/docs/warn-act-listings-{y}-twc.xlsx"
        try:
            rows = list(sheet_rows(url, None))
        except requests.HTTPError:
            continue
        for r in rows:
            if isinstance(r[0], datetime) and r[1]:
                yield dict(state="TX", url=url, employer=str(r[1]), notice=r[0].date().isoformat(),
                           effective=r[5].date().isoformat() if isinstance(r[5], datetime) else "",
                           count=r[4], kind="", site=f"{r[7] or ''}, {r[2] or ''} County".strip(", "))


SOURCES = {"CA": ca, "TX": tx}


warnings.filterwarnings("ignore", message="Data Validation extension", module="openpyxl")


def sheet_rows(url, name):
    resp = requests.get(url, headers=UA, timeout=60)
    resp.raise_for_status()
    wb = openpyxl.load_workbook(io.BytesIO(resp.content), read_only=True, data_only=True)
    ws = next((s for s in wb.worksheets if name and s.title.strip() == name), wb.worksheets[0])
    yield from ws.iter_rows(values_only=True)


def norm(name):
    name = re.split(r"\s+-\s+|\(|\bdba\b", name, flags=re.I)[0]
    return re.sub(r"\s+", " ", LEGAL.sub("", name.replace("’", "'"))).strip(" ,.").lower()


def matchers(companies):
    out = []
    for cid, c in companies.items():
        if c["hiring_scope"] == "parent" or c["ownership"] == "division":
            continue
        names = {c["name"], *[t.strip('"') for t in c["news"]["terms"] if t.count('"') == 2]}
        ambiguous = bool(c["news"].get("context"))
        out += [(cid, norm(n), ambiguous and " " not in norm(n)) for n in names if len(norm(n)) >= 4]
    return out


def match(employer, ms):
    e = norm(employer)
    return next((cid for cid, n, exact in ms if e == n or (not exact and e.startswith(n + " "))), None)


def main(ids):
    companies = load_companies()
    ms = [m for m in matchers(companies) if not ids or m[0] in ids]
    queue = read_queue()
    known = {q["qid"] for q in queue}
    snapshot, errors, added = {}, {}, 0
    for state, fetch in SOURCES.items():
        try:
            notices = list(fetch())
        except (requests.RequestException, ValueError, KeyError) as e:
            errors[state] = f"{type(e).__name__}: {e}"[:200]
            print(f"{state}: ERROR {errors[state]}", flush=True)
            continue
        hits = [(n, cid) for n in notices if (cid := match(n["employer"], ms))]
        snapshot[state] = {"notices": len(notices), "matches": [dict(n, company=cid) for n, cid in hits]}
        for n, cid in hits:
            key = "|".join(str(n[k]) for k in ("employer", "notice", "site", "count"))
            qid = f"warn:{state}:{hashlib.sha1(key.encode()).hexdigest()[:12]}"
            if qid in known:
                continue
            title = (f"{n['employer']}: {n['count']} employees, {n['site']}"
                     + (f", {n['kind']}" if n["kind"] else "") + (f", effective {n['effective']}" if n["effective"] else ""))
            queue.append({"qid": qid, "found": date.today().isoformat(), "source": "warn", "company": cid,
                          "date": n["notice"], "kind": f"{state} WARN", "suggested_type": "layoff", "title": title,
                          "url": n["url"], "parsed": json.dumps(n, sort_keys=True), "status": "open"})
            known.add(qid)
            added += 1
        print(f"{state}: {len(notices)} notices, {len(hits)} match tracked companies", flush=True)
    write_snapshot("warn", {"companies": snapshot, "errors": errors})
    write_queue(queue)
    print(f"{added} queued; {len(errors)} errors")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    main(ap.parse_args().ids)
