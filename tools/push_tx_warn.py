"""Copy the Texas WARN spreadsheets into the repo (data/warn/tx/) from a machine twc.texas.gov will serve.

twc.texas.gov answers GitHub-hosted runners with an empty page, so the daily workflow reads the repo copy instead.
This runs on the maintainer's Mac (launchd, daily): it downloads the current and previous year's file and, only when
one changed, commits it through the GitHub contents API, so no local checkout is touched. Standard library plus the
gh CLI (logged in); exits non-zero on any failure so the launchd log shows it.

Usage: python3 tools/push_tx_warn.py [--dry-run]
"""
import base64
import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date

REPO = "yottachem/physical-ai-tracker"
URL = "https://www.twc.texas.gov/sites/default/files/oei/docs/warn-act-listings-{y}-twc.xlsx"
DEST = "data/warn/tx/warn-act-listings-{y}-twc.xlsx"
UA = {"User-Agent": "physical-ai-tracker (+https://github.com/yottachem/physical-ai-tracker)"}


def download(url):
    """File bytes, or None when the year's file is not published (404)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if not body.startswith(b"PK"):
        raise ValueError(f"not a spreadsheet ({len(body)} bytes) from {url}")
    return body


def remote_sha(path):
    r = subprocess.run(["gh", "api", f"repos/{REPO}/contents/{path}", "--jq", ".sha"], capture_output=True, text=True)
    if r.returncode == 0:
        return r.stdout.strip()
    if "Not Found" in r.stderr or "404" in r.stderr:
        return None
    raise RuntimeError(f"gh api: {r.stderr.strip()[:200]}")


def blob_sha(body):
    return hashlib.sha1(b"blob %d\0" % len(body) + body).hexdigest()


def push(path, body, sha):
    payload = {"message": f"Texas WARN file {date.today().isoformat()} ({path.rsplit('/', 1)[-1]})",
               "content": base64.b64encode(body).decode()}
    if sha:
        payload["sha"] = sha
    subprocess.run(["gh", "api", "-X", "PUT", f"repos/{REPO}/contents/{path}", "--input", "-", "--silent"],
                   input=json.dumps(payload), text=True, check=True)


def main(dry_run=False):
    year, failed = date.today().year, False
    for y in (year, year - 1):
        url, path = URL.format(y=y), DEST.format(y=y)
        try:
            body = download(url)
            if body is None:
                print(f"{y}: not published yet")
                continue
            sha = remote_sha(path)
            if sha == blob_sha(body):
                print(f"{y}: unchanged ({len(body):,} bytes)")
            elif dry_run:
                print(f"{y}: would push {len(body):,} bytes")
            else:
                push(path, body, sha)
                print(f"{y}: pushed {len(body):,} bytes to {path}")
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as e:
            print(f"{y}: ERROR {type(e).__name__}: {e}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    print(f"--- {date.today().isoformat()}")
    sys.exit(main(dry_run="--dry-run" in sys.argv))
