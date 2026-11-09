"""Checked statements: every interpretive sentence on the home page is a claim in analysis/claims.yaml, stored with
the condition it rests on. Each build re-checks every claim:

- condition holds: the text is shown, numbers filled in from this run
- condition fails: the neutral fallback is shown (or nothing, if it's ""), marked under review
- a value the claim uses is outside its plausibility range: treated as a possible data problem, shown the same way,
  and reported separately as a data check

Writes analysis/results/review.json (claims under review, which the daily run turns into a GitHub issue). Rewriting
a claim is a reviewed, manual step: change `text` and `holds` together so the condition states exactly what the text
asserts.

Values: `market` (all tracked companies, each round counted once) and one entry per segment, keyed by the segment id
with dashes as underscores (lab_automation). In a claim, `t` is the claim's own entry and `m` is the market. Money is
closed equity rounds with a disclosed amount, the same rule as the site's "raised" figures; the last 12 months run by
month (a round dated 2025-11 counts in a run on 2026-11-09). Companies in two segments count in both. Fractions are
fractions (0.31, shown with :pct as 31%).

Usage: uv run python -m analysis.claims            # print claims under review, write review.json
       uv run python -m analysis.claims --values   # also print every value claims can use
       uv run python -m analysis.claims --markdown # claims under review as an issue body
"""
import html
import importlib.util
import json
import re
import sys
from datetime import date, timedelta
from types import SimpleNamespace

import yaml

from ingest.common import ROOT

SPEC = ROOT / "analysis" / "claims.yaml"
REVIEW = ROOT / "analysis" / "results" / "review.json"
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*\.[a-z0-9_]+)(?::([a-z0-9_]+))?\}")
NAME = re.compile(r"\b([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)\b")
SAFE = {"abs": abs, "min": min, "max": max, "round": round, "None": None, "True": True, "False": False}
EQUITY = re.compile(r"\b(debt|loan|credit|grant|award|bridge)\b", re.I)  # matches site/build.py NOT_EQUITY


def key(sid):
    return sid.replace("-", "_")


def load_site():
    """site/build.py as a module (it isn't a package)."""
    spec = importlib.util.spec_from_file_location("site_build", ROOT / "site" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rounds(recs):
    """Closed and reported equity rounds with an amount and a date: (company, row)."""
    return [(cid, r) for cid, rec in recs.items() for r in rec["rows"]
            if r["type"] == "funding" and r["amount"] and r["date"] and not EQUITY.search(f"{r['round']} {r['detail']}")]


def within(d, lo, hi):
    """True when every month the date could mean falls in [lo, hi) (YYYY-MM bounds); a year-only date counts only
    when the whole year does."""
    first, last = (d[:7], d[:7]) if len(d) >= 7 else (d + "-01", d + "-12")
    return first >= lo and last < hi


def summarize(recs, members, eq, today):
    """Values for one group of companies (a segment, or the market)."""
    since = (today - timedelta(days=365)).isoformat()[:7]
    prev = (today - timedelta(days=730)).isoformat()[:7]
    end = "9999"
    ids = {r["id"] for r in members}
    sel = [(cid, r) for cid, r in eq if cid in ids]
    last = sorted((x for x in sel if within(x[1]["date"], since, end) and x[1]["status"] == "closed"),
                  key=lambda x: -x[1]["amount"])
    before = [x for x in sel if within(x[1]["date"], prev, since) and x[1]["status"] == "closed"]
    raised, raised_prev = sum(r["amount"] for _, r in last), sum(r["amount"] for _, r in before)
    top = last[0] if last else None
    vals = sorted((r for r in members if r["valuation"]), key=lambda r: -r["valuation"]["valuation"])
    hiring = sorted((r for r in members if r["counted"] and r["roles"] is not None), key=lambda r: -r["roles"])
    roles = sum(r["roles"] for r in hiring)
    boston_roles = sum(r["boston_roles"] for r in hiring)
    fn = {}
    for r in hiring:
        for k, v in r["functions"].items():
            fn[k] = fn.get(k, 0) + v
    top_fn = max(fn, key=fn.get) if fn else None
    return {
        "n": len(members), "boston_n": sum(1 for r in members if r["c"]["boston"]),
        "public_n": sum(1 for r in members if r["ownership"] == "public" and not r["wound_down"]),
        "private_n": sum(1 for r in members if r["ownership"] == "private"),
        "wound_down_n": sum(1 for r in members if r["wound_down"]),
        "raised_12m": raised, "rounds_12m": len(last), "raised_prev_12m": raised_prev,
        "raised_multiple": raised / raised_prev if raised_prev else None,
        "reported_12m": sum(r["amount"] for _, r in sel if within(r["date"], since, end) and r["status"] != "closed"),
        "raised_since_2021": sum(r["amount"] for _, r in sel if r["date"] >= "2021" and r["status"] == "closed"),
        "top_round": top[1]["amount"] if top else None,
        "top_round_company": recs[top[0]]["c"]["name"] if top else None,
        "top_round_label": top[1]["round"] or "round" if top else None,
        "top_round_share": top[1]["amount"] / raised if top else None,
        "top3_share": sum(r["amount"] for _, r in last[:3]) / raised if raised else None,
        "top_val": vals[0]["valuation"]["valuation"] if vals else None,
        "top_val_company": vals[0]["c"]["name"] if vals else None,
        "top_val_status": vals[0]["valuation"]["status"] if vals else None,
        "valued_n": len(vals),
        "boards": len(hiring), "roles": roles, "boston_roles": boston_roles,
        "boston_share": boston_roles / roles if roles else None,
        "top_hirer": hiring[0]["c"]["name"] if hiring else None,
        "top_hirer_roles": hiring[0]["roles"] if hiring else None,
        "top_hirer_share": hiring[0]["roles"] / roles if roles else None,
        "top_function": top_fn, "top_function_share": fn[top_fn] / roles if top_fn and roles else None,
    }


def values(recs, segments, today=None, functions=None):
    """{'market' or segment key: {name: value}} for every value a claim can use."""
    today = today or date.today()
    eq = rounds(recs)
    out = {"market": {"name": "All tracked companies", **summarize(recs, list(recs.values()), eq, today)}}
    for sid, s in segments.items():
        members = [r for r in recs.values() if sid in r["c"]["segments"]]
        out[key(sid)] = {"name": s["name"], **summarize(recs, members, eq, today)}
    for v in out.values():
        if functions and v["top_function"]:
            v["top_function"] = functions.get(v["top_function"], v["top_function"])
    segs = [k for k in out if k != "market"]
    m = out["market"]
    for k in segs:
        v = out[k]
        v["raised_share"] = v["raised_12m"] / m["raised_12m"] if m["raised_12m"] else None
        v["roles_share"] = v["roles"] / m["roles"] if m["roles"] else None
    # ranks among segments, 1 = most (ties share a rank); boston_share_rank only among segments with at least 100
    # counted roles
    for name, field, among in (("raised_rank", "raised_12m", segs), ("roles_rank", "roles", segs),
                               ("n_rank", "n", segs), ("since_2021_rank", "raised_since_2021", segs),
                               ("boston_n_rank", "boston_n", segs), ("public_rank", "public_n", segs),
                               ("boston_share_rank", "boston_share", [k for k in segs if out[k]["roles"] >= 100])):
        for k in segs:
            x = out[k][field] or 0
            out[k][name] = 1 + sum((out[j][field] or 0) > x for j in among) if k in among else None
    top = min(segs, key=lambda k: out[k]["raised_rank"])
    hire = min(segs, key=lambda k: out[k]["roles_rank"])
    m.update(boston_frac=m["boston_n"] / m["n"], n_seg=len(segs), top_segment=out[top]["name"], top_segment_raised=out[top]["raised_12m"],
                         top_hiring_segment=out[hire]["name"], top_hiring_segment_roles=out[hire]["roles"])
    for k in segs:
        out[k]["n_seg"] = len(segs)
    return out


def fmt(x, spec=None):
    if x is None:
        return "n/a"
    match spec:
        case "pct":  # fraction -> whole percent
            return f"{x:.0%}"
        case "spct":  # signed
            return f"{'+' if round(x * 100) > 0 else '−' if round(x * 100) < 0 else ''}{abs(x):.0%}"
        case "apct":  # magnitude only, for "fell 5%"
            return f"{abs(x):.0%}"
        case "x":  # multiple
            return f"{x:.1f}x" if x < 10 else f"{x:.0f}x"
        case "usd":
            return f"${x / 1e9:,.1f} billion" if abs(x) >= 1e9 else f"${x / 1e6:,.0f} million"
        case "int":
            return f"{x:,.0f}"
        case "f1":
            return f"{x:,.1f}"
        case "ord":
            return {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}.get(x, f"{x}th")
        case "lower":
            return str(x).lower()
        case "poss":  # possessive: Anduril's, Mind Robotics'
            return f"{x}'" if str(x).endswith("s") else f"{x}'s"
        case _:
            return str(x)


def namespace(v, tid):
    env = {k: SimpleNamespace(**d) for k, d in v.items()}
    env["t"], env["m"] = env[tid], env["market"]
    return env


def fill(text, env, as_html=True):
    def sub(m):
        obj, attr = m.group(1).split(".")
        return fmt(getattr(env[obj], attr), m.group(2))
    s = PLACEHOLDER.sub(sub, (text or "").strip())
    if as_html:
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(s, quote=False))
    return s


def holds(expr, env):
    return bool(eval(str(expr), {"__builtins__": {}}, {**SAFE, **env}))  # noqa: S307  expressions are repo-authored


def names_in(claim):
    """(object, attribute) pairs a claim reads, from its text, fallback and condition."""
    found = set()
    for s in (claim.get("text", ""), claim.get("fallback", "")):
        found |= {tuple(m.group(1).split(".")) for m in PLACEHOLDER.finditer(s or "")}
    found |= set(NAME.findall(re.sub(r"(['\"]).*?\1", "", str(claim.get("holds", "True")))))
    return found


def resolve(o, tid):
    return {"t": tid, "m": "market"}.get(o, o)


def evaluate(v, spec=None):
    """({entry: [claim rows]}, [claims under review])."""
    spec = spec or yaml.safe_load(SPEC.read_text())
    checks = spec.get("checks", {})
    out, review = {}, []
    for tid, claims in spec["claims"].items():
        env = namespace(v, tid)
        rows = []
        for c in claims:
            bad = sorted(f"{resolve(o, tid)}.{a}" for o, a in names_in(c)
                         if a in checks and (x := v[resolve(o, tid)].get(a)) is not None
                         and not checks[a][0] <= x <= checks[a][1])
            ok = not bad and holds(c.get("holds", True), env)
            status = "ok" if ok else "data_check" if bad else "review"
            rows.append({"id": c["id"], "status": status, "holds": str(c.get("holds", True)),
                         "html": fill(c["text"], env) if ok else fill(c.get("fallback", ""), env)})
            if not ok:
                review.append({"entry": tid, "id": c["id"], "status": status, "holds": str(c.get("holds")),
                               "text": fill(c["text"], env, as_html=False), "out_of_range": bad})
        out[tid] = rows
    return out, review


def current():
    site = load_site()
    d = site.load()
    return values(d["recs"], d["segments"], functions=site.FUNCTIONS)


def run(v=None):
    out, review = evaluate(v or current())
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    REVIEW.write_text(json.dumps(review, indent=1))
    n = sum(len(r) for r in out.values())
    print(f"{n} claims, {n - len(review)} hold, {len(review)} under review")
    for r in review:
        print(f"  {r['status']:10} {r['entry']}.{r['id']}: {r['holds']}  {r['out_of_range'] or ''}")
    return out


def markdown():
    """Claims under review as a GitHub issue body (empty when none)."""
    rows = json.loads(REVIEW.read_text()) if REVIEW.exists() else []
    return "".join(f"- **{r['entry']}.{r['id']}** ({r['status']}): {r['text']}\n  holds: `{r['holds']}`"
                   f"{'  out of range: ' + ', '.join(r['out_of_range']) if r['out_of_range'] else ''}\n" for r in rows)


if __name__ == "__main__":
    if "--markdown" in sys.argv:
        sys.exit(print(markdown(), end=""))
    v = current()
    if "--values" in sys.argv:
        for tid, d in v.items():
            print(f"== {tid}")
            for k, x in d.items():
                print(f"  {k:26} {x if not isinstance(x, float) else round(x, 4)}")
    run(v) if SPEC.exists() else None
