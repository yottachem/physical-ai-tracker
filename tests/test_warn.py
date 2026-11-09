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
