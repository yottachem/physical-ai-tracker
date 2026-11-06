"""Suggest SEC CIKs: public tickers from company_tickers.json; US private issuers from Form D full-text search.

Prints suggestions only. Josh or Claude confirms a Form D match (name, business city) before it goes into companies.yaml,
because full-text search also returns SPVs and funds named after a company ("Nuvion Physical Intelligence VII").
Run: uv run python -m discover.cik
"""
import re
import time

import requests

from ingest.common import load_companies, user_agent

TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEARCH = "https://efts.sec.gov/LATEST/search-index"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SPV = re.compile(r"\b(LLC|LP|L\.P\.|Fund|SPV|Series|Ventures?|Capital|Holdings? I+)\b", re.I)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("inc", "").replace("corp", ""))


def main():
    h = {"User-Agent": user_agent()}
    tickers = {v["ticker"]: v["cik_str"] for v in requests.get(TICKERS, headers=h, timeout=60).json().values()}
    for cid, c in load_companies().items():
        if c["ticker"]:
            print(f"{cid}\tpublic\t{c['ticker']}\t{tickers.get(c['ticker'], 'NOT FOUND')}")
            continue
        if c["ownership"] != "private":
            continue
        name = c["name"].split(" (")[0]
        r = requests.get(SEARCH, params={"q": f'"{name}"', "forms": "D"}, headers=h, timeout=60)
        time.sleep(0.2)
        seen = {}
        for hit in r.json().get("hits", {}).get("hits", []):
            for dn in hit["_source"].get("display_names", []):
                m = re.match(r"(.*?)\s+\(CIK (\d+)\)", dn)
                if m and norm(m.group(1)).startswith(norm(name)) and not SPV.search(m.group(1)):
                    seen.setdefault(int(m.group(2)), m.group(1))
        for cik, filer in seen.items():
            sub = requests.get(SUBMISSIONS.format(cik=cik), headers=h, timeout=60).json()
            time.sleep(0.2)
            city = (sub.get("addresses", {}).get("business") or {}).get("city")
            forms = sub["filings"]["recent"]["form"]
            print(f"{cid}\tformD\t{filer}\t{cik}\t{city}\t{sum(f.startswith('D') for f in forms)} Form D")
        if not seen:
            print(f"{cid}\tformD\tnone")


if __name__ == "__main__":
    main()
