# Massachusetts WARN reports

mass.gov refuses scripted downloads, so the fiscal-year WARN report is saved here by hand about once a month.

1. Open https://www.mass.gov/info-details/worker-adjustment-and-retraining-act-warn-weekly-report
2. Download the current fiscal year's Excel report (the fiscal year starts July 1: FY2027 runs 2026-07-01 to 2027-06-30).
3. Upload it here, replacing the older copy of the same fiscal year: on GitHub, open this folder, Add file >
   Upload files, commit to main.

The daily workflow reads every .xlsx in this folder (`ingest/warn.py`) and queues notices from tracked companies
for review. Keep the previous fiscal year's file until its notices are older than a few months.
