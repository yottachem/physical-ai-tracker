"""Weekly open roles per company from public job boards: total, by function, and Boston-area count.

Greenhouse, Lever, Ashby, Workable, Rippling, BambooHR and SmartRecruiters have public JSON job-board endpoints;
Teamtailor has an RSS
feed. Workday career sites answer the
same POST their own pages use (unofficial). Posting titles and locations go to the raw snapshot only; the site publishes
counts. Companies with hiring_scope: parent are skipped: a parent's board (NVIDIA, Amazon, BICO) cannot be split to the
physical AI unit.
Run: uv run python -m ingest.jobs [company-id ...]
"""
import csv
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date

import requests

from ingest.common import RAW, ROOT, load_companies, write_snapshot

UA = {"User-Agent": "physical-ai-tracker (job counts; github.com/yottachem/physical-ai-tracker)"}

# First match wins, so the specific families come before the broad ones. The second block holds domain words (radar,
# operator, commercial) that decide only when the title names no function the first block knows.
FUNCTIONS = [
    ("regulatory-clinical", r"regulatory|clinical (affairs|research|study|studies|trial|evidence|data|operations|"
                            r"science|development)|post.?market|surveillance|vigilance|\braqa\b|\bqa/ra\b|"
                            r"\bra specialist|medical affairs|compliance|biostatistic"),
    ("go-to-market", r"sales|territory|market development|\baccount (executive|manager|director|lead)|key account|"
                     r"business development|marketing|\bbd\b|da vinci specialist|contract negotiat|market access|"
                     r"\bmarket insights?\b|reimbursement|health economics|value (&|and) economics|"
                     r"competitive insights|tender|commercial operations|account management|"
                     r"strategic accounts"),
    ("research", r"\bresearch (scientist|engineer)|\bscientist\b|\bphd\b|research"),
    ("ml-ai", r"machine learning|\bml\b|\bai\b|deep learning|perception|computer vision|\bllm\b|reinforcement|"
              r"foundation model|annotation|labell?ing|data scien"),
    ("robotics-controls", r"robot|controls?\b|motion planning|autonomy|navigation|slam|manipulation|locomotion"),
    ("product-design", r"product manag|product owner|product lead|program manag|project manag|\btpm\b|"
                       r"product design|industrial design|user experience|\bux\b|(visual|interaction|product|"
                       r"industrial|graphic|experience) designer|human factors|usability|technical writ|documentation"),
    ("hardware", r"mechanical|electrical|hardware|mechatronic|actuator|firmware|embedded|optic|sensor|pcb|thermal|"
                 r"materials?\b|battery|power electronics|fpga|asic|ultrasound|design engineer|\bnpd\b"),
    ("software", r"software|\bswe\b|backend|front.?end|full.?stack|platform|infrastructure|devops|\bsre\b|"
                 r"data engineer|security engineer|developer|cloud|\bit\b|business systems?|\bsap\b|"
                 r"analytics engineer"),
    ("field-deployment", r"field|deployment|customer success|support engineer|technical support|customer support|"
                         r"solutions?|integration|service|applications? (engineer|specialist)|trainer|training|"
                         r"education|implementation|onsite|install|consultant|learning (content|product)"),
    ("manufacturing-ops", r"manufactur|production|technician|assembl|supply chain|quality|procurement|operations|"
                          r"logistics|facilities|\bnpi\b|test engineer|supplier|process engineer|validation|"
                          r"inspector|\biqc\b|warehouse|material handler|materialista|machinist|planner|buyer|"
                          r"sourcing|monteur|monta[zž]|industrial engineer|equipment engineer|component engineer|"
                          r"\bq[ac]\b|shipping|lagerlogistik|produktion|feinoptik|category manag"),
    ("g-and-a", r"financ|legal|counsel|recruit|talent|people|\bhr\b|accounting|accountant|payroll|admin|"
                r"executive assistant|office|tax\b|treasury|controller|audit|paralegal|kaufm|workplace|"
                r"environmental|health and safety|\behs\b|communications|compensation|accounts payable|"
                r"accounts receivable|revenue analyst|fixed assets|fp&a|business partner|chief of staff|"
                r"corporate (strategy|development)|"
                r"investor|public affairs|government|\bhrb|human resources"),

    ("manufacturing-ops", r"welder|metrology|inspection|construction|\bbim\b|cell operator|machine operator|inventory"),
    ("hardware", r"radar|aerodynamic|propulsion|structur(al|es)|avionics|\bgnc\b|guidance|warhead|mass properties|"
                 r"low observables|antenna|actuation|closures|flight sciences|air vehicle|rocket|munition|energetic|"
                 r"payload|electronic|\brf\b|systems engineer|safety engineer|reliability|instrument"),
    ("robotics-controls", r"autonomous (vehicle|driving)|mapping|simulation|state estimation"),
    ("ml-ai", r"data (creator|collection)"),
    ("software", r"android|\bios\b|mobile|test automation|information security|cyber|\bsecurity\b"),
    ("field-deployment", r"operator|fleet|maintenance|launch|forward deployed|site acquisition|readiness|mission ops"),
    ("go-to-market", r"commercial|growth|partnership|partner (program|relationship)|pricing|proposal|capture"),
    ("product-design", r"program (director|coordinator|lead)|project lead|strategic project"),
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


def workable(token):
    url = f"https://apply.workable.com/api/v3/accounts/{token}/jobs"
    jobs, body = [], {"query": "", "location": [], "department": [], "worktype": [], "remote": []}
    while True:
        r = requests.post(url, json=body, headers=UA, timeout=60)
        r.raise_for_status()
        d = r.json()
        jobs += [{"title": j["title"], "location": " / ".join(
                 ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
                 for loc in j.get("locations") or [j.get("location") or {}])} for j in d["results"]]
        if not d.get("nextPage"):
            return jobs
        body = {**body, "token": d["nextPage"]}
        time.sleep(0.5)


def rippling(token):
    r = requests.get(f"https://api.rippling.com/platform/api/ats/v1/board/{token}/jobs", headers=UA, timeout=60)
    r.raise_for_status()
    return [{"title": j["name"], "location": (j.get("workLocation") or {}).get("label", "")} for j in r.json()]


def bamboohr(token):
    r = requests.get(f"https://{token}.bamboohr.com/careers/list", headers=UA, timeout=60)
    r.raise_for_status()
    return [{"title": j["jobOpeningName"], "location": ", ".join(filter(None, [
             (j.get("location") or {}).get("city"), (j.get("location") or {}).get("state")]))}
            for j in r.json()["result"]]


def teamtailor(token):
    r = requests.get(f"https://{token}.teamtailor.com/jobs.rss", headers=UA, timeout=60)
    r.raise_for_status()
    tt = "{https://teamtailor.com/locations}"
    return [{"title": i.findtext("title"), "location": " / ".join(
             ", ".join(filter(None, [loc.findtext(tt + "city"), loc.findtext(tt + "country")]))
             for loc in i.iter(tt + "location")) or (i.findtext("remoteStatus") or "")}
            for i in ET.fromstring(r.content).iter("item")]


def smartrecruiters(token):
    url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
    jobs, offset = [], 0
    while True:
        r = requests.get(url, params={"limit": 100, "offset": offset}, headers=UA, timeout=60)
        r.raise_for_status()
        d = r.json()
        jobs += [{"title": j["name"], "location": (j.get("location") or {}).get("fullLocation", "")}
                 for j in d.get("content", [])]
        offset += 100
        if offset >= d.get("totalFound", 0) or not d.get("content"):
            return jobs
        time.sleep(0.5)


FETCH = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workday": workday, "workable": workable,
         "rippling": rippling,
         "bamboohr": bamboohr, "teamtailor": teamtailor, "smartrecruiters": smartrecruiters}


def summarize(jobs):
    by_function = {}
    for j in jobs:
        f = function_of(j["title"])
        by_function[f] = by_function.get(f, 0) + 1
    return {"total": len(jobs), "boston": sum(bool(BOSTON.search(j["location"])) for j in jobs),
            "by_function": dict(sorted(by_function.items()))}


COUNTS = ROOT / "data" / "jobs" / "counts.csv"
COUNT_COLUMNS = ["date", "company", "ats", "total", "boston", "by_function"]


def write_counts(out):
    """Committed series: one row per company per run day (today's rows replaced on a rerun). Raw postings stay in
    the gitignored snapshot."""
    today = date.today().isoformat()
    rows = []
    if COUNTS.exists():
        with COUNTS.open() as fh:
            rows = [r for r in csv.DictReader(fh) if not (r["date"] == today and r["company"] in out)]
    rows += [{"date": today, "company": cid, "ats": o["ats"], "total": o["total"], "boston": o["boston"],
              "by_function": json.dumps(o["by_function"], sort_keys=True)} for cid, o in out.items()]
    COUNTS.parent.mkdir(parents=True, exist_ok=True)
    with COUNTS.open("w", newline="") as fh:
        w = csv.DictWriter(fh, COUNT_COLUMNS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["date"], r["company"])))


def main(ids):
    companies = load_companies()
    out, errors = {}, {}
    for cid in ids or companies:
        c = companies[cid]
        board = c.get("careers")
        if not board or board["ats"] not in FETCH or c["hiring_scope"] == "parent":
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
    if ids:  # a partial rerun updates today's snapshot instead of replacing it
        today = RAW / "jobs" / f"{date.today().isoformat()}.json"
        if today.exists():
            prev = json.loads(today.read_text())
            out = {**prev["companies"], **out}
            errors = {k: v for k, v in {**prev["errors"], **errors}.items() if k not in out or k in errors}
    path = write_snapshot("jobs", {"companies": out, "errors": errors})
    write_counts(out)
    print(f"{len(out)} boards, {len(errors)} errors -> {path.relative_to(path.parents[3])}")
    return out, errors


if __name__ == "__main__":
    main(sys.argv[1:])
