from ingest.financials import headcount, in_scope, shell_cutoff, stated_date


def test_headcount_sentences():
    cases = {
        "Human Capital As of December 31, 2025, we had approximately 1,900 employees.": (1900, "approx"),
        "As of December 31, 2025, we had approximately 17,021 full-time employees, with approximately 2,288 in research"
        " and development, 7,625 in manufacturing operations, 4,837 in commercial and service operations": (17021, "approx"),
        "We had a total of 1,669 employees as of December 31, 2025.": (1669, ""),
        "As of December 31, 2025, we employed a total of 370 full-time and 10 part-time employees globally.": (370, ""),
        "As of March 9, 2026, we had 26 employees, 11 of whom were engaged directly in research.": (26, ""),
        "we employed more than 2,000 people worldwide.": (2000, "at_least"),
    }
    for text, (n, q) in cases.items():
        got = headcount(text)
        assert got and got[:2] == (n, q), text


def test_headcount_ignores_non_counts():
    assert headcount("an average of 79 R&D employees in 2025 compared to 103 in 2024") is None
    assert headcount("880,001 PRSUs were granted to certain employees.") is None


def test_stated_date():
    assert stated_date("As of March 9, 2026, we had 26 employees") == "2026-03-09"
    assert stated_date("we had 26 employees") is None


def test_shell_cutoff():
    assert shell_cutoff({"name": "Churchill Capital Corp XI", "formerNames": []}) is None
    assert shell_cutoff({"name": "Kodiak AI, Inc.", "formerNames": [
        {"name": "Ares Acquisition Corp II", "from": "2021-04-01T00:00:00", "to": "2025-09-24T00:00:00"}]}) == "2025-09-24"
    assert shell_cutoff({"name": "Intuitive Surgical", "formerNames": [{"name": "Intuitive Surgical Inc"}]}) == ""


def test_scope():
    base = {"ownership": "public", "cik": 1, "hiring_scope": "company", "ticker": "SYM"}
    assert in_scope(base)
    assert not in_scope(base | {"hiring_scope": "parent"})
    assert not in_scope(base | {"ticker": "688836.SS", "cik": None})
    assert not in_scope(base | {"ownership": "private"})
