"""News ingest: Bing News RSS, Google News RSS, GDELT and company newsroom feeds -> data/news/articles.csv.

- Bing News RSS: primary for links. Its redirect links carry the publisher URL in the `url` parameter.
- GDELT DOC 2.0: publisher URLs directly; at most 1 request per 5 seconds; backs off and skips on HTTP 429.
- Google News RSS: discovery only. Items keep the publisher name and domain; the publisher link comes from Bing or
  GDELT carrying the same headline, or from a Bing search scoped to the publisher's site. The site never links to
  Google.
- Newsroom: the company's own RSS/Atom feed (companies.yaml newsroom_feed), a primary source. Its headlines often
  omit the company name, so the news-term filter is skipped for it; posts without an event stay feed items.
Only headlines, links, dates and publishers are stored, never article text.

A headline counts for a company when one of its news terms (all quoted phrases in the term) appears in the title or
summary, and, when the company has context words, one of those appears too. Phrases in `exclude` (other
companies with the same name) rule a headline out.

Usage: uv run python -m ingest.news [--sources bing,gnews,gdelt,newsroom] [--days N] [company-id ...]
"""
import argparse
import csv
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests

from classify.events import events
from ingest.common import ROOT, domain_of, load_companies, tier_of, write_snapshot

ARTICLES = ROOT / "data" / "news" / "articles.csv"
COLUMNS = ["aid", "date", "company", "title", "url", "domain", "publisher", "tier", "via", "events", "found"]
UA = {"User-Agent": "Mozilla/5.0 (compatible; physical-ai-tracker; github.com/yottachem/physical-ai-tracker)"}


def phrases(term):
    return re.findall(r'"([^"]+)"', term) or [term]


def query(c, short_ok=True):
    terms = " OR ".join(" ".join(f'"{p}"' for p in phrases(t)) for t in c["news"]["terms"])
    q = f"({terms})" if len(c["news"]["terms"]) > 1 else terms
    ctx = [w for w in c["news"].get("context", []) if short_ok or len(w) >= 3]
    if ctx:
        q += " (" + " OR ".join(f'"{w}"' if " " in w else w for w in ctx) + ")"
    return q


def _has(text, phrase):
    return re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", text, re.I) is not None


def relevant(c, title, summary=""):
    text = f"{title} {summary}"
    if any(_has(text, x) for x in c["news"].get("exclude", [])):
        return False
    if not any(all(_has(text, p) for p in phrases(t)) for t in c["news"]["terms"]):
        return False
    ctx = c["news"].get("context")
    return not ctx or any(_has(text, w) for w in ctx)


def canonical(url):
    u = urlparse(url)
    q = [(k, v) for k, v in parse_qs(u.query).items() if not k.lower().startswith(("utm_", "ocid", "cmpid", "guccounter"))]
    return urlunparse((u.scheme or "https", u.netloc.lower(), u.path.rstrip("/") or "/", "", urlencode(q, doseq=True), ""))


def norm_title(t):
    t = re.sub(r"\s+[-|]\s+[^-|]{2,60}$", "", t)  # trailing " - Publisher"
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def _day(dt):
    return dt.astimezone(timezone.utc).date().isoformat()


def bing_rss(q):
    r = requests.get("https://www.bing.com/news/search", headers=UA, timeout=30,
                     params={"q": q, "format": "rss", "count": 100, "mkt": "en-US"})
    r.raise_for_status()
    out = []
    for i in ET.fromstring(r.content).iter("item"):
        link = i.findtext("link") or ""
        url = parse_qs(urlparse(link).query).get("url", [link])[0]
        out.append({"title": (i.findtext("title") or "").strip(), "summary": i.findtext("description") or "",
                    "url": url, "date": _day(parsedate_to_datetime(i.findtext("pubDate"))),
                    "publisher": (i.findtext("{http://www.bing.com/news/search}Source") or domain_of(url))})
    return out


def bing(c, days):
    """Bing's RSS ignores OR groups, so one simple query per term: its phrases plus the first context word."""
    ctx = c["news"].get("context", [])[:1]
    out = []
    for t in c["news"]["terms"]:
        out += bing_rss(" ".join(f'"{p}"' for p in phrases(t)) + (f" {ctx[0]}" if ctx else ""))
        time.sleep(1)
    return out


def _tokens(t):
    return set(norm_title(t).split())


def resolve(item):
    """Publisher URL for a Google News headline: Bing search scoped to the publisher's site, accepted only when the
    hit is on that domain and its headline matches (token overlap >= 0.75)."""
    domain = domain_of(item.get("publisher_url", ""))
    if not domain:
        return ""
    want = _tokens(item["title"])
    for hit in bing_rss(f"{item['title']} site:{domain}"):
        if domain_of(hit["url"]).endswith(domain):
            got = _tokens(hit["title"])
            if want and len(want & got) / len(want | got) >= 0.75:
                return hit["url"]
    return ""


def gnews(c, days):
    r = requests.get("https://news.google.com/rss/search", headers=UA, timeout=30,
                     params={"q": f"{query(c)} when:{days}d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
    r.raise_for_status()
    out = []
    for i in ET.fromstring(r.content).iter("item"):
        src = i.find("source")
        title = (i.findtext("title") or "").strip()
        if src is not None and src.text and title.endswith(f" - {src.text}"):
            title = title[: -len(src.text) - 3]
        out.append({"title": title, "summary": "", "url": "",
                    "publisher_url": src.get("url", "") if src is not None else "",
                    "publisher": src.text if src is not None else "",
                    "date": _day(parsedate_to_datetime(i.findtext("pubDate")))})
    return out


ATOM = "{http://www.w3.org/2005/Atom}"


def newsroom(c, days):
    if not c.get("newsroom_feed"):
        return []
    r = requests.get(c["newsroom_feed"], headers=UA, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    since = (date.today() - timedelta(days=days)).isoformat()
    out = []
    for i in root.iter("item"):  # RSS
        when = i.findtext("pubDate")
        out.append({"title": (i.findtext("title") or "").strip(), "summary": "", "url": (i.findtext("link") or "").strip(),
                    "date": _day(parsedate_to_datetime(when)) if when else ""})
    for e in root.iter(ATOM + "entry"):  # Atom
        link = next((x.get("href") for x in e.iter(ATOM + "link") if x.get("rel", "alternate") == "alternate"), "")
        when = e.findtext(ATOM + "published") or e.findtext(ATOM + "updated") or ""
        out.append({"title": (e.findtext(ATOM + "title") or "").strip(), "summary": "", "url": link or "",
                    "date": _day(datetime.fromisoformat(when.replace("Z", "+00:00"))) if when else ""})
    return [dict(it, publisher=c["name"]) for it in out if it["date"] >= since]


class Gdelt:
    """Spaced requests; after a 429 it waits once, then stops for the rest of the run."""
    def __init__(self):
        self.last, self.off = 0.0, False

    def __call__(self, c, days):
        if self.off:
            return []
        for attempt in (1, 2):
            time.sleep(max(0, self.last + 5.5 - time.time()))
            self.last = time.time()
            r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc", timeout=60, headers=UA,
                             params={"query": query(c, short_ok=False) + " sourcelang:english", "mode": "ArtList",
                                     "format": "json", "maxrecords": 250, "timespan": f"{min(days, 90)}d",
                                     "sort": "DateDesc"})
            if r.status_code == 429:
                if attempt == 1:
                    time.sleep(60)
                    continue
                self.off = True
                raise RuntimeError("GDELT rate limit; skipped for the rest of this run")
            r.raise_for_status()
            arts = json.loads(r.text or "{}").get("articles", []) if r.text.strip().startswith("{") else []
            return [{"title": a["title"].strip(), "summary": "", "url": a["url"], "publisher": a.get("domain", ""),
                     "date": datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").date().isoformat()} for a in arts]
        return []


def read_articles():
    if not ARTICLES.exists():
        return []
    with ARTICLES.open() as fh:
        return list(csv.DictReader(fh))


def write_articles(rows):
    ARTICLES.parent.mkdir(parents=True, exist_ok=True)
    with ARTICLES.open("w", newline="") as fh:
        w = csv.DictWriter(fh, COLUMNS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda a: (a["date"], a["company"], a["title"]), reverse=True))


def merge(company, items, store, by_url, by_title, today):
    """Add new items to the store; return the rows added. Same URL or same headline = same article."""
    added = []
    for it in sorted(items, key=lambda x: not x["url"]):  # linked items first, so Google items can match them
        if not it["title"]:
            continue
        url = canonical(it["url"]) if it["url"] else ""
        key_t = (company, norm_title(it["title"]))
        row = (by_url.get((company, url)) if url else None) or by_title.get(key_t)
        if row:
            vias = set(row["via"].split("|")) | {it["via"]}
            row["via"] = "|".join(sorted(vias))
            if url and not row["url"]:
                row.update(url=url, domain=domain_of(url), tier=tier_of(url) or "")
            continue
        domain = domain_of(url) if url else domain_of(it.get("publisher_url", ""))
        row = {"aid": hashlib.sha1(f"{company}|{url or key_t[1]}".encode()).hexdigest()[:12], "date": it["date"],
               "company": company, "title": re.sub(r"\s+", " ", it["title"]), "url": url, "domain": domain,
               "publisher": it.get("publisher", "") or domain, "tier": (tier_of("https://" + domain) or "") if domain
               else "", "via": it["via"], "events": "|".join(events(it["title"])), "found": today}
        store.append(row)
        if url:
            by_url[(company, url)] = row
        by_title[key_t] = row
        added.append(row)
    return added


def main(ids, sources, days, resolve_max=400):
    recent = (date.today() - timedelta(days=3)).isoformat()
    companies = load_companies()
    fetch = {"bing": bing, "gnews": gnews, "gdelt": Gdelt(), "newsroom": newsroom}
    store = read_articles()
    by_url = {(a["company"], a["url"]): a for a in store if a["url"]}
    by_title = {(a["company"], norm_title(a["title"])): a for a in store}
    today = date.today().isoformat()
    raw, errors, new = {}, {}, []
    for cid in ids or companies:
        c = companies[cid]
        got = []
        for name in sources:
            try:
                items = fetch[name](c, days)
            except (requests.RequestException, ET.ParseError, RuntimeError, ValueError, TypeError) as e:
                errors[f"{cid}:{name}"] = f"{type(e).__name__}: {e}"[:200]
                continue
            kept = [dict(it, via=name) for it in items if name == "newsroom" or relevant(c, it["title"], it["summary"])]
            raw[f"{cid}:{name}"] = {"fetched": len(items), "kept": len(kept), "items": kept}
            got += kept
            if name != "gdelt" and (name != "newsroom" or c.get("newsroom_feed")):
                time.sleep(1)
        added = merge(cid, got, store, by_url, by_title, today)
        new += added
        print(f"{cid}: {len(got)} relevant, {len(added)} new", flush=True)
    # Google-only rows get a publisher link where Bing can find the same headline on the publisher's site.
    # Rows found in the last 3 days are retried, newest first, up to resolve_max lookups per run.
    pending = [a for a in store if not a["url"] and a["via"] == "gnews" and a["found"] >= recent]
    resolved = 0
    for a in sorted(pending, key=lambda a: a["date"], reverse=True)[:resolve_max]:
        try:
            url = resolve({"title": a["title"], "publisher_url": "https://" + a["domain"]})
        except (requests.RequestException, ET.ParseError, ValueError, TypeError):
            url = ""
        time.sleep(1)
        if url:
            a.update(url=canonical(url), tier=tier_of(url) or a["tier"])
            resolved += 1
    print(f"resolved {resolved} of {min(len(pending), resolve_max)} Google-only headlines")
    write_snapshot("news", {"sources": sources, "days": days, "results": raw, "errors": errors})
    write_articles(store)
    print(f"{len(new)} new articles; {len(store)} stored; {len(errors)} errors"
          + (f" ({sorted(set(k.split(':')[1] for k in errors))})" if errors else ""))
    return new


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="bing,gnews,gdelt")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--resolve-max", type=int, default=400)
    ap.add_argument("ids", nargs="*")
    a = ap.parse_args()
    main(a.ids, a.sources.split(","), a.days, a.resolve_max)
