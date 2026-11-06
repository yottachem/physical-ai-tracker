"""Shared helpers: registry loading and saving, source tiers, secrets, raw snapshots."""
import csv
import json
import os
import subprocess
from datetime import date
from functools import cache
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "reference"
RAW = ROOT / "data" / "raw"
COMPANIES = REF / "companies.yaml"
LEDGER = REF / "ledger.csv"
LEDGER_COLUMNS = ["id", "company", "date", "type", "round", "amount_usd", "valuation_usd", "qualifier", "status",
                  "detail", "sources", "accept", "added", "map_row"]


def load_companies():
    return yaml.safe_load(COMPANIES.read_text())["companies"]


def save_companies(companies):
    """Rewrite companies.yaml, keeping the header comment block."""
    header = "".join(line for line in COMPANIES.read_text().splitlines(keepends=True)
                     if line.startswith("#") or not line.strip()).split("\n\n")[0]
    body = yaml.safe_dump({"companies": companies}, sort_keys=False, allow_unicode=True, width=130,
                          default_flow_style=None)
    COMPANIES.write_text(header.rstrip("\n") + "\n\n" + body)


def load_segments():
    return yaml.safe_load((REF / "segments.yaml").read_text())["segments"]


def load_ledger():
    with LEDGER.open(newline="") as f:
        return list(csv.DictReader(f))


def domain_of(url):
    return urlparse(url).netloc.lower().removeprefix("www.")


def _matches(host, domain):
    return host == domain or host.endswith("." + domain)


@cache
def _tiers():
    t = yaml.safe_load((REF / "source_tiers.yaml").read_text())
    tier1 = [d for group in t["tier1"].values() for d in group]
    company = [d for c in load_companies().values() for d in [c["domain"], *c["other_domains"]] if d]
    return {"company": company, "tier1": tier1, "tier2": t["tier2"], "secondary": t["secondary"]}


def tier_of(url):
    """'tier1' (company domain or tier-1 list), 'tier2', 'secondary', or None for an unclassified domain."""
    host = domain_of(url)
    t = _tiers()
    if any(_matches(host, d) for d in t["company"] + t["tier1"]):
        return "tier1"
    for name in ("tier2", "secondary"):
        if any(_matches(host, d) for d in t[name]):
            return name
    return None


@cache
def secret(name, keychain_service):
    """Env var first, then macOS Keychain. Never log the return value."""
    if v := os.environ.get(name):
        return v
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", keychain_service, "-w"],
                           capture_output=True, text=True)
    except FileNotFoundError:  # not macOS (CI uses env vars)
        return None
    return r.stdout.strip() or None


def contact():
    """Contact email for SEC: CONTACT_EMAIL, else Keychain item physical-ai-tracker-contact (falls back to the
    lifesci-tracker-contact item on Josh's machine). Kept out of the repo."""
    return (secret("CONTACT_EMAIL", "physical-ai-tracker-contact")
            or secret("LIFESCI_CONTACT_EMAIL", "lifesci-tracker-contact"))


def user_agent():
    """SEC wants "name email"; URLs in the UA get 403."""
    if not (email := contact()):
        raise RuntimeError("SEC needs a contact email: set CONTACT_EMAIL or Keychain item physical-ai-tracker-contact")
    return f"physical-ai-tracker {email}"


def write_snapshot(source, payload):
    """Raw snapshot per run: data/raw/<source>/<YYYY-MM-DD>.json."""
    d = RAW / source
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{date.today().isoformat()}.json"
    path.write_text(json.dumps(payload, indent=1, sort_keys=True))
    return path
