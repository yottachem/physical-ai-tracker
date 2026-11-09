# Massachusetts WARN reports

mass.gov refuses scripted downloads, so the WARN report is saved here by hand about once a month.

1. Open https://www.mass.gov/info-details/worker-adjustment-and-retraining-act-warn-weekly-report
2. Download the report as CSV. It is named "WARN Report for the Week Ending MM-DD-YYYY.csv" but lists every notice
   of the fiscal year so far (the fiscal year starts July 1: FY2027 runs 2026-07-01 to 2027-06-30).
3. Add it to this folder and commit to main (from a local checkout, or on GitHub: Add file > Upload files).
   Older weekly files can stay; repeated notices are read once.

The daily workflow reads every .csv and .xlsx in this folder (`ingest/warn.py`) and queues notices from tracked
companies for review. The first file (week ending 2026-11-06, 24 notices from 2026-07-01) confirmed the columns:
RECEIVED, EMPLOYER, CITY/TOWN, REGION, DATE(S) OF LAYOFFS, # EMPLOYEES IMPACTED.
