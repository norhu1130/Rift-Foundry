from decimal import Decimal

from lol_build.buildtime.drift import diff_records


def test_unchanged_records_produce_empty_drift() -> None:
    records = {"1": {"name": "One", "ratio": Decimal("0.5")}, "2": {"name": "Two"}}

    assert diff_records(records, records) == {"added": [], "removed": [], "changed": []}


def test_added_removed_and_changed_records_are_separated_and_sorted() -> None:
    old = {
        "10": {"name": "Ten", "cost": 100},
        "2": {"name": "Two"},
        "gone": {"name": "Gone"},
    }
    new = {
        "10": {"name": "Ten", "cost": 125},
        "2": {"name": "Two"},
        "3": {"name": "Three"},
    }

    assert diff_records(old, new) == {
        "added": ["3"],
        "removed": ["gone"],
        "changed": ["10"],
    }
