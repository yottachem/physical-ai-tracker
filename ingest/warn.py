"""State WARN layoff notices -> review queue (suggested type layoff).

Sources (public state spreadsheets, fetched as published):
  CA  EDD "Detailed WARN Report", current fiscal year (July 1 on), updated Tuesdays and Thursdays
  TX  TWC WARN Act listings, current and previous calendar year, read from data/warn/tx/: twc.texas.gov serves
      GitHub runners an empty page, so tools/push_tx_warn.py copies the files into the repo daily from a Mac
  MA  the WARN report (fiscal year to date, July 1 on; downloaded as "WARN Report for the Week Ending ....csv"),
      saved by hand into data/warn/ma/ (mass.gov refuses scripted downloads). Every .csv and .xlsx there is read and
      repeated rows are dropped; columns are found by their headers, so layout changes are tolerated.

An employer matches a tracked company when its name, after dropping a trailing " - site" and legal suffixes,
starts with the company's name or one of its quoted news terms. One-word names of companies with ambiguous names
(those with news.context words: Sunday, Potato, Figure, ...) must match the whole employer name. Parent-scope companies and divisions are skipped:
their notices describe the parent. Every match is queued for review; nothing reaches the ledger without approval.

Usage: uv run python -m ingest.warn [company-id ...]
"""
import argparse
import csv
import hashlib
import io
import json
import re
from datetime import date, datetime

import warnings

import openpyxl
import requests

from ingest.common import ROOT, load_companies, write_snapshot
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


TX_DIR = ROOT / "data" / "warn" / "tx"
TX_URL = "https://www.twc.texas.gov/sites/default/files/oei/docs/warn-act-listings-{y}-twc.xlsx"


def tx():
    year = date.today().year
    paths = [p for y in (year, year - 1) if (p := TX_DIR / f"warn-act-listings-{y}-twc.xlsx").exists()]
    if not paths:
        raise ValueError(f"no Texas file in {TX_DIR.relative_to(ROOT)} (pushed daily by tools/push_tx_warn.py)")
    for path in paths:
        url = TX_URL.format(y=path.name.split("-")[3])
        for r in sheet_values(path.read_bytes(), None):
            if isinstance(r[0], datetime) and r[1]:
                yield dict(state="TX", url=url, employer=str(r[1]), notice=r[0].date().isoformat(),
                           effective=r[5].date().isoformat() if isinstance(r[5], datetime) else "",
                           count=r[4], kind="", site=f"{r[7] or ''}, {r[2] or ''} County".strip(", "))


MA_DIR = ROOT / "data" / "warn" / "ma"
MA_PAGE = "https://www.mass.gov/info-details/worker-adjustment-and-retraining-act-warn-weekly-report"
MA_FIELDS = {  # field: header keywords, first matching column wins
    "employer": ("company", "employer"),
    "notice": ("received", "notice date", "warn date"),
    "effective": ("effective", "layoff date", "layoffs", "separation"),
    "count": ("employees", "affected", "number", "#"),
    "site": ("location", "city", "address", "town"),
    "kind": ("type", "closure", "layoff/"),
}


def ma():
    seen = set()  # each weekly file repeats the fiscal year so far
    for path in sorted([*MA_DIR.glob("*.xlsx"), *MA_DIR.glob("*.csv")]):
        rows = list(sheet_values(path.read_bytes(), None)) if path.suffix == ".xlsx" else csv_values(path.read_bytes())
        if not any(header_map(r).keys() >= {"employer", "notice"} for r in rows[:20]):
            raise ValueError(f"no header row with company and notice-date columns in data/warn/ma/{path.name}")
        for n in ma_rows(rows, MA_PAGE):
            key = (n["employer"], n["notice"], n["site"], str(n["count"]))
            if key not in seen:
                seen.add(key)
                yield n


def csv_values(content):
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252")  # mass.gov exports are Windows-encoded ("Labour\xe9")
    return list(csv.reader(io.StringIO(text)))


def ma_rows(rows, url):
    rows = iter(rows)
    for header in rows:
        cols = header_map(header)
        if "employer" in cols and "notice" in cols:
            break
    else:
        raise ValueError(f"no header row with company and notice-date columns in {url}")
    for r in rows:
        get = lambda f: r[cols[f]] if f in cols and cols[f] < len(r) else None  # noqa: E731
        notice = as_date(get("notice"))
        if notice and get("employer"):
            employer = str(get("employer")).strip()
            updated = employer.lower().startswith("*updated*")
            kind = re.sub(r"\s+", " ", str(get("kind") or "")).strip()
            effective = get("effective")
            yield dict(state="MA", url=url, employer=employer[9:].strip() if updated else employer, notice=notice,
                       effective=as_date(effective) or re.sub(r"\s+", " ", str(effective or "")).strip(),
                       count=get("count") or "", kind=", ".join(filter(None, [kind, "updated notice" if updated else ""])),
                       site=re.sub(r"\s+", " ", str(get("site") or "")).strip())


def header_map(header):
    """{field: column index}; each column is used once, fields in MA_FIELDS order."""
    names = [re.sub(r"\s+", " ", str(h or "")).strip().lower() for h in header]
    cols = {}
    for field, keys in MA_FIELDS.items():
        i = next((i for i, n in enumerate(names) if n and i not in cols.values() and any(k in n for k in keys)), None)
        if i is not None:
            cols[field] = i
    return cols


def as_date(v):
    if isinstance(v, datetime):
        return v.date().isoformat()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%B %d, %Y"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


SOURCES = {"CA": ca, "TX": tx, "MA": ma}


warnings.filterwarnings("ignore", message="Data Validation extension", module="openpyxl")


def sheet_rows(url, name):
    resp = requests.get(url, headers=UA, timeout=60)
    resp.raise_for_status()
    if not resp.content.startswith(b"PK"):  # e.g. a block page served to cloud runners; logged as a source error
        raise ValueError(f"not a spreadsheet ({resp.headers.get('Content-Type', '?')}, {len(resp.content)} bytes)")
    yield from sheet_values(resp.content, name)


def sheet_values(content, name):
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
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
        latest = max((n["notice"] for n in notices), default="none")  # an old MA date means the file needs refreshing
        snapshot[state] = {"notices": len(notices), "latest": latest,
                           "matches": [dict(n, company=cid) for n, cid in hits]}
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
        print(f"{state}: {len(notices)} notices (latest {latest}), {len(hits)} match tracked companies", flush=True)
    write_snapshot("warn", {"companies": snapshot, "errors": errors})
    write_queue(queue)
    print(f"{added} queued; {len(errors)} errors")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    main(ap.parse_args().ids)
