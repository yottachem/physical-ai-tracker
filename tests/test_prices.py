from ingest.prices import in_scope, market_value

SERIES = [("2026-11-02", 3.2), ("2026-11-09", 3.5)]


def test_market_value_uses_latest_close_and_shares():
    shares = {"value": "100000000", "end": "2026-09-30", "accn": "0001-26-1"}
    v = market_value("serve-robotics", "SERV", SERIES, "USD", shares)
    assert v["as_of"] == "2026-11-09" and v["market_cap"] == 350_000_000 and v["shares_as_of"] == "2026-09-30"


def test_market_value_without_shares_is_price_only():
    v = market_value("unitree", "688836.SS", SERIES, "CNY", None)
    assert v["close"] == 3.5 and v["market_cap"] == ""


def test_scope():
    base = {"ownership": "public", "ticker": "SYM", "hiring_scope": "company"}
    assert in_scope(base)
    assert in_scope(base | {"ticker": "688836.SS"})          # non-US listings get prices
    assert not in_scope(base | {"hiring_scope": "parent"})   # parents' market value is not the tracked business
    assert not in_scope(base | {"ownership": "private", "ticker": None})
