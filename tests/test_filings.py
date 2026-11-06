from ingest.filings import FORMS, QUEUE_COLUMNS, suggested_type


def f(form, items=""):
    return {"form": form, "items": items}


def test_8k_items_map_to_types():
    assert suggested_type(f("8-K", "2.02,9.01")) == "revenue"
    assert suggested_type(f("8-K", "1.03")) == "status"
    assert suggested_type(f("8-K", "5.07,9.01")) is None  # votes and exhibits alone do not queue


def test_forms_map_to_ledger_types():
    from tests.test_reference import TYPES
    assert {t for t in FORMS.values() if t} <= TYPES
    assert suggested_type(f("D")) == "funding" and suggested_type(f("15-12G")) == "listing"


def test_queue_columns():
    assert QUEUE_COLUMNS[0] == "qid" and "status" in QUEUE_COLUMNS
