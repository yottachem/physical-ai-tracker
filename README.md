# physical-ai-tracker

Which physical AI companies are growing, raising, hiring or shrinking? This project tracks about 75 companies across 11 customer segments (lab automation, robot foundation models, humanoids, warehouse and factory robots, home robots, AI wearables, autonomous mobility, defense, surgical and hospital robotics, agriculture, manufacturing and construction), with a Boston-area filter. It follows each company's status, funding and valuations, employment and size, and public announcements, refreshed on a schedule.

**Status: pre-launch.** Registry and seed ledger built from the Nov 2026 market map; SEC filings, news, job boards, acceptance rules and the review queue run. Site in internal preview (`site/build.py --preview`); not published. Target launch early Jan 2027.

| Signal | Source | Cadence |
|--------|--------|---------|
| Announcements | Bing News RSS (publisher links), GDELT, Google News RSS (discovery only; links resolved to the publisher), company newsroom RSS/Atom feeds (17 companies) | Daily |
| Private funding, listings, material events | SEC EDGAR filings watcher: Form D, S-1/S-4/DRS, Forms 15 and 25, 8-K by item | Daily |
| Funding and valuations | Announcements, accepted by source tier (below) | Daily |
| Open roles | Public job boards: Greenhouse, Lever, Ashby, Workday, Workable, Rippling, BambooHR, Teamtailor | Weekly |
| Layoffs | State WARN notices: California; Texas from a daily copy in data/warn/tx/ (twc.texas.gov blocks GitHub runners; `tools/push_tx_warn.py` pushes it from a Mac); Massachusetts from a monthly hand-saved file (data/warn/ma/) | Daily |
| Headcount | 10-K / 20-F employee count (public); company-stated figures (private) | Weekly / on detection |
| Public companies | SEC EDGAR XBRL: revenue, net income, R&D, cash, shares outstanding | Weekly |
| Market value | Yahoo Finance weekly closes (unofficial endpoint) x SEC shares outstanding | Weekly |

## Acceptance

Every figure on the site carries its source link. Figures from **tier-1 sources** (company newsroom or IR, wire services, SEC filings, government, and an outlet allowlist in `reference/source_tiers.yaml`) are accepted automatically when they parse cleanly and do not conflict with the ledger. Everything else, including secondary trackers and aggregators, waits in a review queue. "Reported" figures (talks, not a closed round) are shown as reported and never summed with closed rounds. Form D amounts are amounts sold to date as filed, not round sizes.

## Run

```sh
uv sync
uv run python -m discover.cik        # suggest SEC CIKs (public tickers, Form D issuers)
uv run python -m discover.careers    # suggest domains and job-board tokens
uv run pytest                        # registry, ledger and tier rules
LAUNCH_GATE=1 uv run pytest          # also fails while any registry field is still marked verify

uv run python -m ingest.filings      # new SEC filings -> data/review/queue.csv
uv run python -m ingest.warn         # CA, TX and MA WARN notices naming tracked companies -> data/review/queue.csv
uv run python -m ingest.news         # headlines -> data/news/articles.csv (--days, --sources)
uv run python -m classify.accept     # tier-1 funding -> ledger (auto); the rest -> review queue
uv run python -m ingest.jobs         # open roles -> data/jobs/counts.csv
uv run python -m ingest.financials   # public pure plays: XBRL facts and annual-report headcount -> data/public/
uv run python -m ingest.prices       # weekly closes and market value (run after financials) -> data/public/
uv run python -m analysis.claims         # re-check the home-page statements (--values lists every value they can use)
uv run python -m classify.review list   # review queue, grouped by event; in Claude Code, /review-events works through it
uv run python site/build.py --preview   # site -> site/dist (market map, company pages, feed, funding, hiring, methods, status)
```

`.github/workflows/update.yml` runs this daily (job boards on Mondays) and commits the data files. Scheduled runs
are off until the repo variable `SCHEDULE_ON` is `true`.

SEC requires a contact email: set `CONTACT_EMAIL`, or the macOS Keychain item `physical-ai-tracker-contact`.

## Layout

| Path | Purpose |
|------|---------|
| `reference/companies.yaml` | Company registry: segments, HQ, Boston flag, ownership, ticker/CIK, domains, news terms, job board, newsroom feed |
| `reference/segments.yaml` | The 11 customer segments |
| `reference/source_tiers.yaml` | Tier-1, tier-2 and secondary source domains |
| `reference/ledger.csv` | Accepted events: funding, valuation, revenue, deployments, status, headcount; each with sources and accept path |
| `reference/seed/` | The Nov 2026 market map the registry and ledger were seeded from |
| `discover/` | Suggestion scripts for registry fields (print only; nothing is written automatically) |
| `ingest/` | One module per source; dated raw snapshots in `data/raw/` (not committed) |
| `classify/` | Headline event tagging and figure parsing, acceptance rules, review actions |
| `data/news/articles.csv` | Matched headlines: date, company, publisher link, source tier, event tags |
| `data/review/queue.csv` | Candidate events awaiting review, and the record of auto, duplicate, accepted and rejected decisions |
| `data/jobs/counts.csv` | Open roles per company per run: total, Boston, by function |
| `data/public/financials.csv` | XBRL facts per company and calendar frame (revenue, net income, R&D, cash, shares), with filing accession |
| `data/public/headcount.csv` | Employee count from each 10-K / 20-F, with the quoted sentence and filing link |
| `data/public/prices.csv` | Weekly closing price per public company since 2025, with currency |
| `data/public/market_value.csv` | Latest close x latest SEC share count; blank market cap where shares are unknown (non-US, SPAC-shell CIK) |
| `analysis/claims.yaml` | Checked statements on the home page, each with the condition it rests on; `analysis/claims.py` re-checks them |
| `site/` | `build.py` + Jinja templates + server-rendered SVG charts (`charts.py`, shared with lifesci-tools-tracker); output in `site/dist/` (gitignored) |
| `tools/push_tx_warn.py` | Run daily on the maintainer's Mac (launchd): copies the Texas WARN files into data/warn/tx/ through the GitHub API when they change |
| `tests/` | Registry, ledger, tier rules, ingest parsers, site build |

## License

Code: MIT. Derived data: CC-BY-4.0, subject to upstream terms listed in `sources.yaml`. Headlines link to their publishers; article text is not stored or republished.
