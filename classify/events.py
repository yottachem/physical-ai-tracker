"""Headline event detection and figure parsing (regex; free tier, no model calls).

events(title) returns every event type the headline matches, in LEDGER order first. money(), round_of() and
valuation() pull figures from the headline; reported() spots talks and rumors, which stay status "reported".
"""
import re

# Types that become ledger rows when accepted. The rest (product, partnership, ...) are feed items only.
LEDGER = ["funding", "valuation", "listing", "acquisition", "layoff", "status"]

PATTERNS = {
    "listing": r"\b(IPO|go(?:es|ing)? public|SPAC|direct listing|files? (?:confidentially )?for (?:an )?IPO|delist\w*|"
               r"(?:Nasdaq|NYSE) debut|public listing)\b",
    "acquisition": r"\b(acquires?|acquired|acquisition|to buy|buys|merg(?:e|er|es|ing) with|takeover)\b",
    "layoff": r"\b(lay(?:s|ing)? off|layoffs?|job cuts?|cuts? (?:\d+|hundreds of) (?:jobs|workers|staff)|"
              r"workforce reduction|WARN notice)\b",
    "status": r"\b(shut(?:s|ting)? down|bankrupt\w*|Chapter 11|winds? down|ceases? operations|insolven\w*|"
              r"assignment for the benefit of creditors)\b",
    "funding": r"\b(rais(?:e|es|ed|ing)|funding|financing|Series [A-H]\b|seed round|pre-seed|investment|invests?|"
               r"backed by|round)\b",
    "valuation": r"\b(valu(?:ed|ation)|unicorn)\b",
    "partnership": r"\b(partner(?:s|ship|ing)?|collaborat\w+|teams? up|alliance)\b",
    "contract": r"\b(contract|awarded|wins? (?:a |an )?(?:\$|deal|order)|purchase order|orders?)\b",
    "deployment": r"\b(deploy\w*|roll(?:s|ing)? out|rollout|expands? (?:to|into)|fleet|commercial service)\b",
    "product": r"\b(launch\w*|unveil\w*|introduc\w+|debuts?|releases?|announces? new|reveals?)\b",
    "headcount": r"\b(\d[\d,]* employees|headcount|hiring spree|to hire \d[\d,]*)\b",
}
RX = {k: re.compile(v, re.I) for k, v in PATTERNS.items()}

MONEY = re.compile(r"(?:US)?\$\s?(\d+(?:\.\d+)?)\s?(billion|bn|b|million|mn|m)\b", re.I)
SCALE = {"b": 1e9, "bn": 1e9, "billion": 1e9, "m": 1e6, "mn": 1e6, "million": 1e6}
ROUND = re.compile(r"\b(pre-seed|seed|Series [A-H](?:[- ]?\d|\+)?(?: extension)?|bridge round|growth round)\b", re.I)
VALUATION = re.compile(r"(?:valu(?:ed|ation)\s+(?:of\s+|at\s+)?(?:[a-z]+\s+){0,3}(?:US)?\$\s?(\d+(?:\.\d+)?)\s?"
                       r"(billion|bn|b|million|mn|m)\b)|"
                       r"(?:(?:US)?\$\s?(\d+(?:\.\d+)?)\s?(billion|bn|b|million|mn|m)\b\s+valuation)", re.I)
REPORTED = re.compile(r"\b(in talks|talks|seeks?|seeking|reportedly|report(?:s|ed)? that|eyes|eyeing|nears?|"
                      r"considering|discuss\w*|plan(?:s|ning|ned)?|looking to|could|said to|sources say|"
                      r"according to|explores?|exploring|weighs?|in discussions|raising|aims? to|set to|"
                      r"expected to|would|may)\b", re.I)
# Auto-accept needs a closing verb or a named round; investments into the company by a named party, debt and grants
# go to review.
CLOSED = re.compile(r"\b(rais(?:es|ed)|clos(?:es|ed)|secur(?:es|ed)|lands?|landed|grabs?|nabs?|bags?|snags?|"
                    r"announces? \$|completes?|completed|Series [A-H]|seed round|pre-seed)\b", re.I)
NOT_EQUITY = re.compile(r"\b(debt|loan|credit facility|grant|award\w*|contract|government|program|invests? (?:in|into)|"
                        r"investment (?:in|into))\b", re.I)


def events(title):
    return [k for k in PATTERNS if RX[k].search(title)]


def _usd(num, unit):
    return int(round(float(num) * SCALE[unit.lower()]))


def valuation(title):
    m = VALUATION.search(title)
    if not m:
        return None
    num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    return _usd(num, unit)


def money(title):
    """Dollar amounts in the headline, valuation figures removed."""
    v = VALUATION.search(title)
    rest = title[:v.start()] + title[v.end():] if v else title
    return [_usd(n, u) for n, u in MONEY.findall(rest)]


def round_of(title):
    m = ROUND.search(title)
    return m.group(1).title().replace("Pre-Seed", "Pre-seed") if m else ""


def reported(title):
    return bool(REPORTED.search(title))


def clean_round(title):
    """A headline that states a closed equity round: closing verb, and no debt, grant or third-party investment."""
    return bool(CLOSED.search(title)) and not NOT_EQUITY.search(title)


def qualifier(title):
    """Ledger qualifier for the headline's figure: at_least, up_to, approx or ''."""
    t = title.lower()
    if re.search(r"\b(at least|more than|over|north of|upwards of)\s+(?:us)?\$", t):
        return "at_least"
    if re.search(r"\b(up to|as much as)\s+(?:us)?\$", t):
        return "up_to"
    if re.search(r"\b(about|around|nearly|roughly|almost|some|approximately)\s+(?:us)?\$|~\$", t):
        return "approx"
    return ""
