from classify.accept import decide
from classify.events import events, money, reported, round_of, valuation
from ingest.news import canonical, norm_title, relevant

COMPANIES = {
    "medra": {"name": "Medra", "news": {"terms": ['"Medra"'], "context": ["robot", "lab", "AI"]}},
    "nvidia": {"name": "NVIDIA", "news": {"terms": ['"NVIDIA"'], "context": ["robotics"]}},
    "figure-ai": {"name": "Figure AI", "news": {"terms": ['"Figure AI"']}},
    "automata": {"name": "Automata", "news": {"terms": ['"Automata"'], "context": ["lab"],
                                              "exclude": ["Veritas Automata"]}},
}
LEDGER = [{"id": "E0001", "company": "medra", "round": "Seed", "amount_usd": "12000000", "valuation_usd": ""}]


def art(title, company="medra", tier="tier1", url="https://www.businesswire.com/x"):
    return {"title": title, "company": company, "tier": tier, "url": url, "date": "2026-11-01", "aid": "a"}


def test_figures():
    t = "Medra Raises $52 Million Series A at a $400M valuation"
    assert money(t) == [52_000_000] and valuation(t) == 400_000_000 and round_of(t) == "Series A"
    assert money("Startup lands US$1.2bn") == [1_200_000_000]
    assert valuation("valued at about $8.5 billion") == 8_500_000_000
    assert reported("Nvidia reportedly eyes $1B investment") and not reported("Medra raises $52M")


def test_events():
    assert events("Medra Raises $52 Million Series A")[0] == "funding"
    assert "acquisition" in events("Teradyne acquires robot maker")
    assert "layoff" in events("Startup lays off 20% of staff")
    assert events("A quiet week in robotics") == []


def test_relevance_and_exclude():
    assert relevant(COMPANIES["medra"], "Medra opens a robot lab")
    assert not relevant(COMPANIES["medra"], "Medra festival returns")  # no context word
    assert not relevant(COMPANIES["automata"], "Veritas Automata launches lab platform")
    assert not relevant(COMPANIES["medra"], "Medrano lab robot")  # word boundary


def test_url_and_title_normalization():
    assert canonical("https://Example.com/a/?utm_source=x&id=2#top") == "https://example.com/a?id=2"
    assert norm_title("Medra Raises $52M - Bloomberg") == "medra raises 52m"


def test_auto_accept_clean_tier1_funding():
    d, row = decide(art("Medra Raises $52 Million Series A to Build Physical AI Scientists"), COMPANIES, LEDGER)
    assert d == "auto" and row["amount_usd"] == "52000000" and row["status"] == "closed" and row["round"] == "Series A"


def test_reported_stays_reported():
    d, row = decide(art("Medra reportedly in talks to raise $200 million"), COMPANIES, LEDGER)
    assert d == "auto" and row["status"] == "reported"


def test_duplicate_within_ten_percent():
    assert decide(art("Medra raises $12.5 million seed"), COMPANIES, LEDGER) == ("dup", "E0001")


def test_conflict_queues():
    d, p = decide(art("Medra raises $30 million seed round"), COMPANIES, LEDGER)
    assert d == "queue" and any("conflicts with E0001" in r for r in p["reasons"])


def test_non_tier1_and_other_company_queue():
    d, p = decide(art("Medra raises $52 million", tier="tier2"), COMPANIES, LEDGER)
    assert d == "queue" and "tier tier2" in p["reasons"]
    d, p = decide(art("NVIDIA invests $1 billion in Figure AI", company="figure-ai"), COMPANIES, [])
    assert d == "queue" and any("nvidia" in r for r in p["reasons"])


def test_figureless_funding_is_feed_only():
    assert decide(art("Medra announces new funding to expand lab"), COMPANIES, LEDGER) == (None, None)


def test_loose_funding_headlines_queue():
    for title in ["Cellino Awarded $25M in Funding from ARPA-H", "Waymo Closes $5 Billion Debt Financing",
                  "Medra and U.S. government investment in program reaches $400 million"]:
        d, p = decide(art(title.replace("Cellino", "Medra").replace("Waymo", "Medra")), COMPANIES, LEDGER)
        assert d == "queue", title


def test_reported_language():
    assert reported("Skild AI Raising from SoftBank at $4 Billion Valuation")
    assert reported("Shield AI CEO Says Planning At Least $1 Billion Raise")
    assert valuation("in Talks for Valuation of at Least $20 Billion") == 20_000_000_000
    assert money("in Talks for Valuation of at Least $20 Billion") == []


def test_valuation_near_round_queues():
    ledger = [{"id": "E0009", "company": "medra", "type": "funding", "date": "2026-10-30", "round": "",
               "amount_usd": "1500000000", "valuation_usd": ""}]
    d, p = decide(art("Medra hits $21.5B valuation"), COMPANIES, ledger)
    assert d == "queue" and any("E0009" in r for r in p["reasons"])


def test_qualifier():
    from classify.events import qualifier
    assert qualifier("Shield AI in Talks for Valuation of at Least $20 Billion") == "at_least"
    assert qualifier("raises up to $50M") == "up_to" and qualifier("raises about $10M") == "approx"
    assert qualifier("raises $10M") == ""


def test_duplicate_with_new_valuation_queues():
    d, p = decide(art("Medra raises $12M at a $90M valuation"), COMPANIES, LEDGER)
    assert d == "queue" and p["reasons"] == ["adds a valuation to E0001"]
