"""CSV export content/escaping and tracker status/date rules."""

import csv
import io
from datetime import date

import pytest

from scholarpath.cleaning import validate_record
from scholarpath.exports import COLUMNS, safe_cell, to_csv
from scholarpath.repository import SearchFilters
from scholarpath.services import ScholarPathService, ServiceError

from .conftest import FIXED_TODAY, by_key, real_record


def parse(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def test_csv_contains_only_the_filtered_records_with_provenance(example_service):
    views = example_service.search(SearchFilters(host_countries=["United Kingdom"]))
    rows = parse(to_csv([v.record for v in views], FIXED_TODAY))
    assert list(rows[0]) == COLUMNS
    assert {r["name"] for r in rows} == {"Cedar Public Health Scholarship", "Harbourview Business Leaders Grant"}
    cedar = next(r for r in rows if r["name"].startswith("Cedar"))
    assert cedar["deadline_status"] == "Open" and cedar["days_until_deadline"] == "3"
    assert cedar["dataset_origin"] == "example" and cedar["source_url"].startswith("https://example.org/")
    assert cedar["manual_verified_at"] == "Not manually verified"
    assert cedar["subjects"] == "Medicine & health; Public policy & development"
    harbour = next(r for r in rows if r["name"].startswith("Harbourview"))
    assert harbour["deadline_status"] == "Rolling" and harbour["days_until_deadline"] == ""
    assert harbour["nationality_rule"] == "Unrestricted" and harbour["nationality_exclusions"] == "United Kingdom"


@pytest.mark.parametrize("value", ["=HYPERLINK(\"x\")", "+1", "-2+3", "@SUM(A1)", "   =1+1", "\t=1", "\r=1", " =1"])
def test_formula_injection_is_neutralised(value):
    assert safe_cell(value).startswith("'")


@pytest.mark.parametrize("value", ["Normal text", "2026-12-08", "India; Kenya", ""])
def test_ordinary_text_is_unchanged(value):
    assert safe_cell(value) == value


def test_exported_file_escapes_untrusted_source_text():
    rec = validate_record(real_record(name="=cmd|' /C calc'!A0", eligibility_text="x",
                                      funding_description="  @SUM(1,2)"))
    row = parse(to_csv([rec], FIXED_TODAY))[0]
    assert row["name"] == "'=cmd|' /C calc'!A0"
    assert row["funding_description"].startswith("'")
    assert row["days_until_deadline"] == "26"


@pytest.mark.parametrize("status, submitted, outcome, ok", [
    ("interested", None, None, True),
    ("preparing", None, None, True),
    ("preparing", date(2026, 11, 1), None, False),   # submission date before applying
    ("applied", None, None, False),                  # must record your own submission date
    ("applied", date(2026, 11, 1), None, True),
    ("applied", date(2026, 11, 1), "awarded", False),
    ("applied", date(2026, 12, 1), None, False),     # future submission date
    ("result_received", date(2026, 11, 1), None, False),
    ("result_received", date(2026, 11, 1), "not_selected", True),
    ("unknown_status", None, None, False),
])
def test_allowed_status_date_combinations(status, submitted, outcome, ok):
    errors = ScholarPathService.validate_application(status, None, submitted, outcome, FIXED_TODAY)
    assert (errors == []) is ok


def test_target_date_is_personal_and_independent_of_source_deadline(example_service, example_records):
    sid = by_key(example_records, "cedar-public-health")["id"]
    example_service.start_tracking(sid)
    app = example_service.update_application(sid, "preparing", target_date=date(2026, 11, 13))
    assert app.target_date == date(2026, 11, 13)
    assert example_service.get(sid).record.deadline_date == date(2026, 11, 15)


def test_invalid_tracker_edit_changes_nothing(example_service, example_records):
    sid = by_key(example_records, "cedar-public-health")["id"]
    example_service.start_tracking(sid)
    with pytest.raises(ServiceError, match="submitted"):
        example_service.update_application(sid, "applied")
    assert example_service.get_application(sid).status == "interested"


def test_previous_entries_can_be_corrected(example_service, example_records):
    sid = by_key(example_records, "cedar-public-health")["id"]
    example_service.start_tracking(sid)
    example_service.update_application(sid, "applied", submitted_date=date(2026, 11, 10))
    corrected = example_service.update_application(sid, "preparing", notes="Marked applied by mistake",
                                                   history_note="Correction")
    assert corrected.status == "preparing" and corrected.submitted_date is None
    assert example_service.application_history(sid)[0]["note"] == "Correction"


def test_start_tracking_twice_does_not_duplicate(example_service, example_records):
    sid = by_key(example_records, "cedar-public-health")["id"]
    first = example_service.start_tracking(sid)
    second = example_service.start_tracking(sid)
    assert first.id == second.id and len(example_service.applications()) == 1
