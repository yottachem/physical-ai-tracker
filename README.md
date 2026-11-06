# physical-ai-tracker

Which physical AI companies are growing, raising, hiring or shrinking? This project tracks about 75 companies across 11 customer segments (lab automation, robot foundation models, humanoids, warehouse and factory robots, home robots, AI wearables, autonomous mobility, defense, surgical and hospital robotics, agriculture, manufacturing and construction), with a Boston-area filter. It follows each company's status, funding and valuations, employment and size, and public announcements, refreshed on a schedule.

**Status: pre-launch.** Registry and seed ledger built from the Nov 2026 market map; ingest not started. Target launch early Jan 2027.

| Signal | Source | Cadence |
|--------|--------|---------|
| Announcements | GDELT, Google News RSS (discovery only), company newsrooms | Daily |
| Private funding | SEC EDGAR Form D | Daily |
| Funding and valuations | Announcements, accepted by source tier (below) | Daily |
| Open roles | Greenhouse, Lever and Ashby public job boards | Weekly |
| Layoffs | State WARN notices | Weekly |
| Headcount | 10-K human capital (public); company-stated figures (private) | Monthly / on detection |
| Public companies | SEC EDGAR financials; derived month-end market value | Monthly |

## Acceptance

Every figure on the site carries its source link. Figures from **tier-1 sources** (company newsroom or IR, wire services, SEC filings, government, and an outlet allowlist in `reference/source_tiers.yaml`) are accepted automatically when they parse cleanly and do not conflict with the ledger. Everything else, including secondary trackers and aggregators, waits in a review queue. "Reported" figures (talks, not a closed round) are shown as reported and never summed with closed rounds. Form D amounts are amounts sold to date as filed, not round sizes.

## Run

```sh
uv sync
uv run python -m discover.cik        # suggest SEC CIKs (public tickers, Form D issuers)
uv run python -m discover.careers    # suggest domains and job-board tokens
uv run pytest                        # registry, ledger and tier rules
LAUNCH_GATE=1 uv run pytest          # also fails while any registry field is still marked verify
```

SEC requires a contact email: set `CONTACT_EMAIL`, or the macOS Keychain item `physical-ai-tracker-contact`.

## Layout

| Path | Purpose |
|------|---------|
| `reference/companies.yaml` | Company registry: segments, HQ, Boston flag, ownership, ticker/CIK, domains, news terms, job board |
| `reference/segments.yaml` | The 11 customer segments |
| `reference/source_tiers.yaml` | Tier-1, tier-2 and secondary source domains |
| `reference/ledger.csv` | Accepted events: funding, valuation, revenue, deployments, status, headcount; each with sources and accept path |
| `reference/seed/` | The Nov 2026 market map the registry and ledger were seeded from |
| `discover/` | Suggestion scripts for registry fields (print only; nothing is written automatically) |
| `ingest/` | One module per source; dated raw snapshots in `data/raw/` |
| `tests/` | Registry, ledger and tier rules |

## License

Code: MIT. Derived data: CC-BY-4.0, subject to upstream terms listed in `sources.yaml`. Headlines link to their publishers; article text is not stored or republished.
