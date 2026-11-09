"""Weekly closing prices and market value for public companies.

Prices: Yahoo Finance's chart endpoint (query1.finance.yahoo.com/v8/finance/chart), weekly closes since 2025. It is
unofficial and unkeyed; if it stops answering, the run logs the error and keeps the last prices.csv.
Market value: latest close x common shares outstanding from the latest SEC filing (data/public/financials.csv,
metric shares), so it exists only for US filers whose shares are known. Non-US listings (688836.SS) get prices only.

Scope: public companies whose filings describe the tracked business (hiring_scope company); parents (NVIDIA, Tesla)
are skipped, as in ingest.financials.

Usage: uv run python -m ingest.prices [company-id ...]
"""
import argparse
import csv
from datetime import date, datetime, timezone

import requests

from ingest.common import load_companies, write_snapshot
from ingest.financials import FIN, OUT, read, write

PRICES = OUT / "prices.csv"
VALUE = OUT / "market_value.csv"
PRICE_COLUMNS = ["company", "ticker", "date", "close", "currency"]
VALUE_COLUMNS = ["company", "ticker", "as_of", "close", "currency", "shares", "shares_as_of", "shares_accn",
                 "market_cap"]
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={start}&period2={end}&interval=1wk"
SINCE = datetime(2025, 1, 1, tzinfo=timezone.utc)
UA = {"User-Agent": "physical-ai-tracker (+https://github.com/yottachem/physical-ai-tracker)"}


def in_scope(c):
    return c["ownership"] == "public" and c.get("ticker") and c["hiring_scope"] == "company"


def closes(ticker):
    """[(date, close)], currency; weeks without a close are dropped."""
    url = CHART.format(ticker=ticker, start=int(SINCE.timestamp()), end=int(datetime.now(timezone.utc).timestamp()))
    resp = requests.get(url, headers=UA, timeout=30)
    resp.raise_for_status()
    res = resp.json()["chart"]["result"][0]
    out = [(datetime.fromtimestamp(t, timezone.utc).date().isoformat(), round(c, 4))
           for t, c in zip(res.get("timestamp", []), res["indicators"]["quote"][0]["close"]) if c is not None]
    return out, res["meta"].get("currency", "")


def latest_shares(fin, cid):
    rows = [r for r in fin if r["company"] == cid and r["metric"] == "shares"]
    return max(rows, key=lambda r: (r["end"], r["filed"]), default=None)


def market_value(cid, ticker, series, currency, shares):
    as_of, close = series[-1]
    row = dict(company=cid, ticker=ticker, as_of=as_of, close=close, currency=currency, shares="", shares_as_of="",
               shares_accn="", market_cap="")
    if shares:
        row.update(shares=shares["value"], shares_as_of=shares["end"], shares_accn=shares["accn"],
                   market_cap=round(close * float(shares["value"])))
    return row


def main(ids):
    companies = load_companies()
    fin = read(FIN)
    prices = [r for r in read(PRICES) if ids and r["company"] not in ids]  # a full run rebuilds; a subset keeps the rest
    values = {r["company"]: r for r in read(VALUE)}
    errors = {}
    for cid in ids or companies:
        c = companies[cid]
        if not in_scope(c):
            continue
        try:
            series, currency = closes(c["ticker"])
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as e:
            errors[cid] = f"{type(e).__name__}: {e}"[:200]
            prices += [r for r in read(PRICES) if r["company"] == cid]  # keep the last good series
            print(f"{cid}: ERROR {errors[cid]}", flush=True)
            continue
        if not series:
            print(f"{cid}: no closes", flush=True)
            continue
        prices += [dict(company=cid, ticker=c["ticker"], date=d, close=p, currency=currency) for d, p in series]
        values[cid] = market_value(cid, c["ticker"], series, currency, latest_shares(fin, cid))
        v = values[cid]
        cap = f"market cap {int(v['market_cap']):,} {currency}" if v["market_cap"] else "no share count; price only"
        print(f"{cid}: {len(series)} weeks, close {v['close']} {currency} on {v['as_of']}; {cap}", flush=True)
    write(PRICES, PRICE_COLUMNS, prices, key=lambda r: (r["company"], r["date"]))
    write(VALUE, VALUE_COLUMNS, values.values(), key=lambda r: r["company"])
    write_snapshot("prices", {"run": date.today().isoformat(), "errors": errors})
    print(f"{len(prices)} weekly closes, {len(values)} companies; {len(errors)} errors")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    main(ap.parse_args().ids)
