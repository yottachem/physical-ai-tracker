"""Weekly open roles per company from public job boards: total, by function, and Boston-area count.

Greenhouse, Lever and Ashby have public JSON APIs. Workday career sites answer the same POST their own pages use
(unofficial). Posting titles and locations go to the raw snapshot only; the site publishes counts.
Divisions (ownership: division) are skipped: a parent's board cannot be split to the robotics unit.
Run: uv run python -m ingest.jobs [company-id ...]
"""
import re
import sys
import time

import requests

from ingest.common import load_companies, write_snapshot

UA = {"User-Agent": "physical-ai-tracker (job counts; github.com/yottachem/physical-ai-tracker)"}

# First match wins, so the specific families come before the broad ones
FUNCTIONS = [
    ("research", r"\bresearch (scientist|engineer)|\bscientist\b|\bphd\b|research"),
    ("ml-ai", r"machine learning|\bml\b|\bai\b|deep learning|perception|computer vision|\bllm\b|reinforcement|foundation model"),
    ("robotics-controls", r"robot|controls?\b|motion planning|autonomy|navigation|slam|manipulation|locomotion"),
    ("hardware", r"mechanical|electrical|hardware|mechatronic|actuator|firmware|embedded|optic|sensor|pcb|thermal|materials?\b|battery|power electronics"),
    ("software", r"software|\bswe\b|backend|front.?end|full.?stack|platform|infrastructure|devops|\bsre\b|data engineer|security engineer"),
    ("field-deployment", r"field|deployment|customer success|support engineer|solutions|integration|service"),
    ("manufacturing-ops", r"manufactur|production|technician|assembly|supply chain|quality|procurement|operations|logistics|facilities|\bnpi\b|test engineer"),
    ("go-to-market", r"sales|account|business development|marketing|partnership|\bbd\b|commercial|growth"),
    ("g-and-a", r"finance|legal|counsel|recruit|talent|people|\bhr\b|accounting|payroll|admin|executive assistant|office"),
]
BOSTON = re.compile(r"boston|cambridge, ?ma|massachusetts|\bma\b|waltham|somerville|watertown|woburn|burlington, ?ma|"
                    r"bedford, ?ma|billerica|wilmington, ?ma|north reading|beverly|medford|lexington, ?ma|charlestown", re.I)


def function_of(title):
    t = title.lower()
    return next((f for f, rx in FUNCTIONS if re.search(rx, t)), "other")


def greenhouse(token):
    r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", headers=UA, timeout=60)
    r.raise_for_status()
    return [{"title": j["title"], "location": (j.get("location") or {}).get("name", "")} for j in r.json()["jobs"]]


def lever(token):
    r = requests.get(f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"}, headers=UA, timeout=60)
    r.raise_for_status()
    return [{"title": j["text"], "location": " / ".join(filter(None, [(j.get("categories") or {}).get("location"),
             *((j.get("categories") or {}).get("allLocations") or [])]))} for j in r.json()]


def ashby(token):
    r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}", headers=UA, timeout=60)
    r.raise_for_status()
    return [{"title": j["title"], "location": " / ".join(filter(None, [j.get("location"),
             *[s.get("location", "") for s in j.get("secondaryLocations") or []]]))} for j in r.json()["jobs"]]


def workday(token):
    """token = '<tenant>.wd<N>.myworkdayjobs.com/<site>'."""
    host, site = token.split("/", 1)
    tenant = host.split(".")[0]
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    jobs, offset = [], 0
    while True:
        r = requests.post(url, json={"limit": 20, "offset": offset, "searchText": "", "appliedFacets": {}},
                          headers={**UA, "Accept": "application/json"}, timeout=60)
        r.raise_for_status()
        d = r.json()
        jobs += [{"title": j["title"], "location": j.get("locationsText", "")} for j in d.get("jobPostings", [])]
        offset += 20
        if offset >= d.get("total", 0) or not d.get("jobPostings"):
            return jobs
        time.sleep(0.5)


FETCH = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workday": workday}


def summarize(jobs):
    by_function = {}
    for j in jobs:
        f = function_of(j["title"])
        by_function[f] = by_function.get(f, 0) + 1
    return {"total": len(jobs), "boston": sum(bool(BOSTON.search(j["location"])) for j in jobs),
            "by_function": dict(sorted(by_function.items()))}


def main(ids):
    companies = load_companies()
    out, errors = {}, {}
    for cid in ids or companies:
        c = companies[cid]
        board = c.get("careers")
        if not board or board["ats"] not in FETCH or c["ownership"] == "division":
            continue
        try:
            jobs = FETCH[board["ats"]](board["token"])
        except (requests.RequestException, KeyError, ValueError) as e:
            errors[cid] = f"{type(e).__name__}: {e}"[:200]
            print(f"{cid}: ERROR {errors[cid]}", flush=True)
            continue
        out[cid] = {"ats": board["ats"], "token": board["token"], **summarize(jobs), "postings": jobs}
        print(f"{cid}: {out[cid]['total']} roles, {out[cid]['boston']} Boston", flush=True)
        time.sleep(0.3)
    path = write_snapshot("jobs", {"companies": out, "errors": errors})
    print(f"{len(out)} boards, {len(errors)} errors -> {path.relative_to(path.parents[3])}")
    return out, errors


if __name__ == "__main__":
    main(sys.argv[1:])
