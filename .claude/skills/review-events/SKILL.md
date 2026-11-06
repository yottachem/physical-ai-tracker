---
name: review-events
description: Work through the physical AI tracker's review queue (data/review/queue.csv) - news headlines and SEC filings that were not auto-accepted. Proposes accept, reject or duplicate for each item, checking the source, and records only what the owner approves. Run only when the owner asks (/review-events).
---

# Review queued events

The queue holds candidate ledger events the acceptance rules would not take on their own (`classify/accept.py`
explains the rules): non-tier-1 sources, headlines naming several companies, listing, acquisition, layoff and
status news, conflicts with the ledger, and every SEC filing the watcher found. Accepted items become rows in
`reference/ledger.csv` with `accept = reviewed`, and the site shows their sources. Nothing is written until the
owner approves.

## Steps

1. **Refresh and list.** `uv run python -m classify.accept` (decides any new articles), then
   `uv run python -m classify.review list --limit 40`. Work one company at a time when the queue is long
   (`--company ID`), largest first. Say how many are open and how you will batch them.

2. **Check each item before proposing anything.**
   - Open the source (WebFetch for news; for SEC, the filing itself). Confirm the company, the event, the figures
     and the date from the source text, not the headline. Headlines round, mix up rounds, and attribute other
     companies' news.
   - Look at the company's existing ledger rows (`grep ',<company-id>,' reference/ledger.csv`) for duplicates
     and conflicts.
   - Form D: `amount_sold` is cumulative for that offering, not a round size. Accept it as `type funding`,
     `round "Form D"`, `qualifier at_least`, only when no announced round already covers it; otherwise mark it
     `dup` against that round. A Form D/A for the same offering supersedes the earlier filing: reject the older one.
   - SEC 8-K, 6-K, 10-K and 20-F items: say in one line what the filing reports. Most are routine (earnings,
     votes, officer changes): propose reject with the reason. Propose accept only for events that change what
     the site says about the company (funding, listing, acquisition, layoff, shutdown, major contract).
   - Talks, rumors and "reportedly" stay `--status reported`, never closed.
   - If a figure needs a better source than the one queued, find the company release or a tier-1 report and pass
     it with `--source`. A tier-1 source is better than several secondary ones.

3. **Propose in a table**: qid, company, proposal (accept / reject / dup), type, round, amount, valuation, status,
   date, sources, one-line reason. Group obvious rejects (wrong company, routine filings) in one row each line.

4. **Apply only what the owner approves**, using the script, never by editing CSVs:
   ```
   uv run python -m classify.review accept QID --type funding --round "Series B" --amount 50000000 \
       --status closed --source https://company.com/press/...
   uv run python -m classify.review reject QID --reason "different company named Medra"
   uv run python -m classify.review dup QID E0042
   ```
   If the script notes an unclassified source domain, propose a tier for it in `reference/source_tiers.yaml`.

5. **Verify and wait.** `uv run pytest -q` must pass. Show `git diff --stat` and the new ledger rows. Do not
   commit or push until the owner says to; then commit as "Review queue: N accepted, N rejected, N duplicates".

## Rules

- A wrong company match is the most common error. Same-name companies (Medra, Automata, Figure, Sunday, Potato,
  Dexterity) need the source to say what the company does. Add a phrase to the company's `news.exclude` in
  `reference/companies.yaml` when a same-name company keeps appearing.
- Never change an existing ledger row's figures. If a queued item shows a seeded or auto-accepted row is wrong,
  report it to the owner with both sources.
- Keep `detail` short and factual; no em dashes.
