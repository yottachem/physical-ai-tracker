"""Suggest company domains and job-board (ATS) tokens.

1. Domain: GET the registry domain (or name-based guesses when it is null); keep it if the page names the company.
2. ATS: scan the home page and common careers paths for Greenhouse, Lever, Ashby, Workable, Workday or Rippling links.
3. Fallback: try name-based tokens against the public Greenhouse, Lever and Ashby APIs. A Greenhouse hit is kept only
   when the board's own name matches; Lever and Ashby hits are printed as "guess" for a manual check.
Prints TSV suggestions; nothing is written to companies.yaml.
Run: uv run python -m discover.careers [company-id ...]
"""
import re
import sys

import requests

from ingest.common import load_companies

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Safari/605.1.15"}
PATHS = ["", "/careers", "/jobs", "/company/careers", "/about/careers", "/join", "/join-us", "/careers/"]
ATS = [
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?([A-Za-z0-9_-]+)"),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_.-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)"),
    ("workable", r"apply\.workable\.com/([A-Za-z0-9_-]+)"),
    ("workday", r"([a-z0-9-]+\.wd\d+\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?[A-Za-z0-9_-]+)"),
    ("rippling", r"ats\.rippling\.com/([A-Za-z0-9_-]+)"),
]
NOT_TOKENS = {"embed", "v1", "js", "api", "jobs", "job_board", "static"}


def get(url):
    try:
        r = requests.get(url, headers=UA, timeout=20, allow_redirects=True)
        return r if r.ok else None
    except requests.RequestException:
        return None


def names_company(html, name):
    words = [w for w in re.findall(r"[A-Za-z0-9]+", name.split(" (")[0]) if len(w) > 2 or w.isdigit()]
    return all(w.lower() in html.lower() for w in words[:2])


def slugs(cid, name):
    base = name.split(" (")[0]
    s = {cid, cid.replace("-", ""), re.sub(r"[^a-z0-9]", "", base.lower())}
    first = re.sub(r"[^a-z0-9]", "", base.split()[0].lower())
    s |= {first, first + "ai", first + "robotics", first + "labs"}
    return [x for x in s if len(x) > 2]


def domain_guesses(cid, name):
    s = slugs(cid, name)
    return [f"{x}.{tld}" for x in s for tld in ("com", "ai", "io", "tech", "co")]


def probe_api(token):
    out = []
    r = get(f"https://boards-api.greenhouse.io/v1/boards/{token}")
    if r:
        out.append(("greenhouse", token, r.json().get("name", "")))
    r = get(f"https://api.lever.co/v0/postings/{token}?mode=json&limit=1")
    if r and isinstance(r.json(), list) and r.json():
        out.append(("lever", token, "guess"))
    r = get(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
    if r and r.json().get("jobs") is not None:
        out.append(("ashby", token, "guess"))
    return out


def main(ids):
    companies = load_companies()
    for cid in ids or companies:
        c = companies[cid]
        domain, home = c["domain"], None
        candidates = [domain] if domain else domain_guesses(cid, c["name"])
        for d in candidates:
            if (r := get(f"https://{d}")) and names_company(r.text, c["name"]):
                domain, home = d, r
                break
        else:
            domain = None
        found = {}
        if domain:
            for p in PATHS:
                r = home if p == "" else get(f"https://{domain}{p}")
                if not r:
                    continue
                for ats, rx in ATS:
                    for tok in re.findall(rx, r.text):
                        if ats == "workday":  # tenant host + site, without the locale segment
                            tok = re.sub(r"/[a-z]{2}-[A-Z]{2}/", "/", tok)
                        if tok.lower() not in NOT_TOKENS:
                            found.setdefault((ats, tok.rstrip("/")), r.url)
                if found:
                    break
        status = "ok" if domain == c["domain"] and domain else ("new" if domain else "none")
        if found:
            for (ats, tok), url in found.items():
                print(f"{cid}\t{domain}\t{status}\t{ats}\t{tok}\tlink\t{url}", flush=True)
        else:
            hits = [h for s in slugs(cid, c["name"]) for h in probe_api(s)]
            for ats, tok, note in hits or [("-", "-", "-")]:
                print(f"{cid}\t{domain}\t{status}\t{ats}\t{tok}\tapi:{note}\t", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
