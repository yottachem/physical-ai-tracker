from datetime import datetime

import pytest

from ingest.warn import as_date, header_map, ma_rows, match, matchers, norm

COMPANIES = {
    "figure-ai": {"name": "Figure AI", "hiring_scope": "company", "ownership": "private",
                  "news": {"terms": ['"Figure AI"', '"Figure 03"'], "context": ["robot"]}},
    "sunday": {"name": "Sunday", "hiring_scope": "company", "ownership": "private",
               "news": {"terms": ['"Sunday Robotics"'], "context": ["robot"]}},
    "diligent-robotics": {"name": "Diligent Robotics", "hiring_scope": "company", "ownership": "private",
                          "news": {"terms": ['"Diligent Robotics"']}},
    "apple": {"name": "Apple", "hiring_scope": "parent", "ownership": "public", "news": {"terms": ['"Apple"']}},
}


def test_norm():
    assert norm("Apptronik, Inc. - Austin") == "apptronik"
    assert norm("OTS Solutions, LLC dba On Time Staffing") == "ots solutions"
    assert norm("MV Transportation, Inc (Corpus Christi)") == "mv transportation"


def test_match():
    ms = matchers(COMPANIES)
    assert match("Figure AI, Inc.", ms) == "figure-ai"
    assert match("Diligent Robotics Inc. - Austin", ms) == "diligent-robotics"
    assert match("Sunday Robotics, Inc.", ms) == "sunday"
    assert match("Sunday", ms) == "sunday"
    assert match("Sunday Bakery LLC", ms) is None          # ambiguous one-word name needs a whole-name match
    assert match("Apple, Inc. - Cupertino", ms) is None    # parent scope is skipped
    assert match("Diligent Robots Co", ms) is None


def test_ma_rows_find_columns_by_header():
    rows = [("Massachusetts WARN Report FY2027",), (),
            ("Company Name", "Location", "WARN Received Date", "Effective Date", "Number of Employees Affected", "Type"),
            ("Diligent Robotics Inc", "Boston", datetime(2026, 10, 2), "12/1/2026", 40, "Layoff"),
            ("Total", None, None, None, 40, None)]
    got = list(ma_rows(rows, "u"))
    assert got == [dict(state="MA", url="u", employer="Diligent Robotics Inc", notice="2026-10-02",
                        effective="2026-12-01", count=40, kind="Layoff", site="Boston")]


def test_ma_rows_without_header_is_an_error():
    with pytest.raises(ValueError):
        list(ma_rows([("Name", "Date"), ("x", "1/1/2026")], "u"))


def test_header_map_uses_each_column_once():
    assert header_map(["Employer", "Notice Date", "Employees Affected", "City"]) == \
        {"employer": 0, "notice": 1, "count": 2, "site": 3}
    assert as_date("10/02/2026") == "2026-10-02" and as_date("n/a") is None


def test_tx_reads_repo_copy(tmp_path, monkeypatch):
    import io
    from datetime import date, datetime

    import openpyxl
    import pytest

    from ingest import warn
    monkeypatch.setattr(warn, "TX_DIR", tmp_path)
    with pytest.raises(ValueError):
        list(warn.tx())
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Notice Date", "Job Site Name", "County", "WDA", "Employees", "Layoff Date", "Address", "City"])
    ws.append([datetime(2026, 11, 2), "Acme Robotics", "Travis", "", 40, datetime(2027, 1, 2), "", "Austin"])
    buf = io.BytesIO()
    wb.save(buf)
    (tmp_path / f"warn-act-listings-{date.today().year}-twc.xlsx").write_bytes(buf.getvalue())
    [row] = list(warn.tx())
    assert row["employer"] == "Acme Robotics" and row["notice"] == "2026-11-02" and row["site"] == "Austin, Travis County"
    assert row["url"].endswith(f"warn-act-listings-{date.today().year}-twc.xlsx")


def test_ma_csv_export(tmp_path, monkeypatch):
    from ingest import warn
    monkeypatch.setattr(warn, "MA_DIR", tmp_path)
    text = ("RECEIVED,EMPLOYER,CITY/TOWN,REGION,DATE(S) OF LAYOFFS,# EMPLOYEES IMPACTED\r\n"
            '9/25/2026,*Updated* Revvity,"Lawrence, MA",Northeast,12/09/2025 - 06/30/2027,53\r\n'
            '7/1/2026,"Labouré College of Healthcare, Inc.","Milton, MA",Southeast,8/30/2026,65\r\n,,,,,\r\n')
    for week in ("10-30", "11-06"):  # weekly files repeat the fiscal year so far
        (tmp_path / f"WARN Report for the Week Ending {week}-2026.csv").write_bytes(text.encode("cp1252"))
    rows = list(warn.ma())
    assert [(r["employer"], r["notice"], r["effective"], r["kind"]) for r in rows] == [
        ("Revvity", "2026-09-25", "12/09/2025 - 06/30/2027", "updated notice"),
        ("Labouré College of Healthcare, Inc.", "2026-07-01", "2026-08-30", "")]
    assert rows[0]["site"] == "Lawrence, MA" and rows[0]["count"] == "53"
