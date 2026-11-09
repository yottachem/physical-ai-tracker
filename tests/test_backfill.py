from classify.backfill import in_ledger

LEDGER = [
    {"id": "E0001", "company": "anduril", "date": "2026-03", "type": "funding", "amount_usd": "1000000000",
     "valuation_usd": ""},
    {"id": "E0002", "company": "liquid-ai", "date": "", "type": "funding", "amount_usd": "250000000",
     "valuation_usd": ""},
    {"id": "E0003", "company": "dexterity", "date": "2025-03", "type": "valuation", "amount_usd": "",
     "valuation_usd": "1650000000"},
]


def row(company, date, amount="", valuation=""):
    return {"company": company, "date": date, "amount_usd": amount, "valuation_usd": valuation}


def test_in_ledger():
    assert in_ledger(row("anduril", "2026-04-01", "1050000000"), LEDGER) == "E0001"   # same year, within 10%
    assert in_ledger(row("anduril", "2022-12-02", "1000000000"), LEDGER) is None      # other year
    assert in_ledger(row("liquid-ai", "2024-12-13", "250000000"), LEDGER) == "E0002"  # undated ledger row
    assert in_ledger(row("dexterity", "2025-03-11", "", "1650000000"), LEDGER) == "E0003"
    assert in_ledger(row("dexterity", "2025-03-11", "95000000", "1650000000"), LEDGER) is None  # funding not logged
