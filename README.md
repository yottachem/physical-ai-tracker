# physical-ai-tracker

Which physical AI companies are growing, raising, hiring or shrinking? This project tracks about 75 companies across 11 customer segments (lab automation, robot foundation models, humanoids, warehouse and factory robots, home robots, AI wearables, autonomous mobility, defense, surgical and hospital robotics, agriculture, manufacturing and construction), with a Boston-area filter. It follows each company's status, funding and valuations, employment and size, and public announcements, refreshed on a schedule.

**Status: pre-launch.** Registry and seed ledger built from the Nov 2026 market map; SEC filings, news, job boards, acceptance rules and the review queue run. Site not built yet. Target launch early Jan 2027.

| Signal | Source | Cadence |
|--------|--------|---------|
| Announcements | Bing News RSS (publisher links), GDELT, Google News RSS (discovery only; links resolved to the publisher) | Daily |
| Private funding, listings, material events | SEC EDGAR filings watcher: Form D, S-1/S-4/DRS, Forms 15 and 25, 8-K by item | Daily |
| Funding and valuations | Announcements, accepted by source tier (below) | Daily |
| Open roles | Public job boards: Greenhouse, Lever, Ashby, Workday, Workable, Rippling, BambooHR, Teamtailor | Weekly |
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

uv run python -m ingest.filings      # new SEC filings -> data/review/queue.csv
uv run python -m ingest.news         # headlines -> data/news/articles.csv (--days, --sources)
uv run python -m classify.accept     # tier-1 funding -> ledger (auto); the rest -> review queue
uv run python -m ingest.jobs         # open roles -> data/jobs/counts.csv
uv run python -m classify.review list   # review queue, grouped by event; in Claude Code, /review-events works through it
```

`.github/workflows/update.yml` runs this daily (job boards on Mondays) and commits the data files. Scheduled runs
are off until the repo variable `SCHEDULE_ON` is `true`.

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
| `ingest/` | One module per source; dated raw snapshots in `data/raw/` (not committed) |
| `classify/` | Headline event tagging and figure parsing, acceptance rules, review actions |
| `data/news/articles.csv` | Matched headlines: date, company, publisher link, source tier, event tags |
| `data/review/queue.csv` | Candidate events awaiting review, and the record of auto, duplicate, accepted and rejected decisions |
| `data/jobs/counts.csv` | Open roles per company per run: total, Boston, by function |
| `tests/` | Registry, ledger and tier rules |

## License

Code: MIT. Derived data: CC-BY-4.0, subject to upstream terms listed in `sources.yaml`. Headlines link to their publishers; article text is not stored or republished.
