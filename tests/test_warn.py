from ingest.warn import match, matchers, norm

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
