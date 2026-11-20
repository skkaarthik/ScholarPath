"""Expiry: when an opportunity closes, and what closing does (and does not) change.

Rules are documented in scholarpath/dates.py. A closed opportunity leaves active
discovery (search, counts, CSV export) the moment it closes, even between data
refreshes, but saved items, applications and their history are never touched.
"""

from datetime import date, datetime, timezone

import pytest

from scholarpath import config, dates
from scholarpath.exports import to_csv
from scholarpath.repository import SearchFilters
from scholarpath.services import ScholarPathService

from .conftest import FIXED_TODAY, real_record

UTC = timezone.utc


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


# --- the closing instant ---------------------------------------------------------------

def test_date_only_deadline_stays_open_through_that_day_in_the_source_time_zone():
    # 8 Dec 2026 in London is GMT (UTC+0): closes at 23:59:59 UTC that day.
    assert dates.closes_at("dated", date(2026, 12, 8), tz_name="Europe/London") == at("2026-12-08T23:59:59+00:00")
    # 20 Oct 2026 in London is BST (UTC+1): the day ends an hour earlier in UTC.
    assert dates.closes_at("dated", date(2026, 10, 20), tz_name="Europe/London") == at("2026-10-20T22:59:59+00:00")
    # Fictional example records use the app time zone (Asia/Kolkata, UTC+5:30).
    assert dates.closes_at("dated", date(2026, 11, 12), tz_name="Asia/Kolkata") == at("2026-11-12T18:29:59+00:00")


def test_date_without_a_known_zone_closes_at_the_end_of_the_day_anywhere_on_earth():
    moment = dates.closes_at("dated", date(2026, 12, 8))
    assert moment == at("2026-12-09T11:59:59+00:00")        # 23:59:59 at UTC-12
    assert not dates.is_closed("dated", date(2026, 12, 8), at("2026-12-09T11:59:58+00:00"))
    assert dates.is_closed("dated", date(2026, 12, 8), at("2026-12-09T11:59:59+00:00"))


def test_an_exact_closing_time_wins_and_the_boundary_is_exact():
    exact = "2026-12-08T16:00:00+00:00"                   # "16:00 GMT on 8 December 2026"
    assert not dates.is_closed("dated", date(2026, 12, 8), at("2026-12-08T15:59:59+00:00"), deadline_at=exact,
                               tz_name="Europe/London")
    assert dates.is_closed("dated", date(2026, 12, 8), at("2026-12-08T16:00:00+00:00"), deadline_at=exact,
                           tz_name="Europe/London")


@pytest.mark.parametrize("kind", ["rolling", "unknown"])
def test_rolling_and_unknown_deadlines_are_never_treated_as_closed(kind):
    far_future = at("2099-01-01T00:00:00+00:00")
    assert dates.closes_at(kind, None) is None
    assert not dates.is_closed(kind, None, far_future)
    status, days = dates.deadline_status(kind, None, date(2099, 1, 1), closed=False)
    assert status == kind and days is None


def test_a_page_that_says_closed_is_closed_even_without_or_before_a_date():
    now = at("2026-11-19T12:00:00+00:00")
    assert dates.is_closed("unknown", None, now, closed_by_source=True)
    assert dates.is_closed("dated", date(2027, 1, 1), now, tz_name="Europe/London", closed_by_source=True)
    status, _ = dates.deadline_status("unknown", None, now.date(), closed=True)
    assert status == "expired"
    assert dates.describe_deadline("unknown", None, now.date(), closed=True).startswith("Closed: the official page")


# --- what closing does in the app ------------------------------------------------------

def service_at(monkeypatch, instant: str) -> ScholarPathService:
    monkeypatch.setenv("SCHOLARPATH_NOW", instant)
    return ScholarPathService(config.MODE_REAL)


def closing_record(**overrides):
    return real_record(source_key="closing", name="Closing Award", deadline_kind="dated",
                       deadline_date="2026-12-08", deadline_timezone="Europe/London", **overrides)


def test_an_opportunity_leaves_discovery_the_moment_it_closes_between_refreshes(monkeypatch):
    before = service_at(monkeypatch, "2026-12-08T23:59:58+00:00")
    before.import_records([closing_record(), real_record(source_key="rolling", name="Rolling Award",
                                                         deadline_kind="rolling", deadline_date=None)])
    assert {v.record.name for v in before.search()} == {"Closing Award", "Rolling Award"}
    assert before.overview()["active"] == 2

    after = service_at(monkeypatch, "2026-12-08T23:59:59+00:00")      # no import in between
    assert {v.record.name for v in after.search()} == {"Rolling Award"}
    assert after.overview()["active"] == 1 and after.overview()["scholarships"] == 2
    closed = after.search(SearchFilters(include_closed=True))
    assert {v.record.name: v.status for v in closed}["Closing Award"] == "expired"
    csv = to_csv([v.record for v in after.search()], date(2026, 12, 9), after.now())
    assert "Closing Award" not in csv and "Rolling Award" in csv


def test_closing_keeps_saved_items_applications_and_history(monkeypatch):
    open_svc = service_at(monkeypatch, "2026-12-01T00:00:00+00:00")
    rec = closing_record()
    open_svc.import_records([rec])
    open_svc.save(rec["id"])
    open_svc.mark_applied(rec["id"], date(2026, 11, 30))
    open_svc.update_application(rec["id"], "applied", submitted_date=date(2026, 11, 30), notes="Sent")

    closed_svc = service_at(monkeypatch, "2027-01-15T00:00:00+00:00")
    assert closed_svc.search() == []                                    # gone from discovery
    saved = closed_svc.shortlist()
    assert [v.record.id for v in saved] == [rec["id"]] and saved[0].status == "expired"
    app = closed_svc.get_application(rec["id"])
    assert (app.status, app.submitted_date, app.notes) == ("applied", date(2026, 11, 30), "Sent")
    assert len(closed_svc.application_history(rec["id"])) == 2
    assert closed_svc.get(rec["id"]).status == "expired"                 # its own page still opens


def test_fixed_test_clock_gives_a_consistent_now():
    clock = config.Clock(fixed_today=FIXED_TODAY)
    assert clock.now().astimezone(config.APP_TIMEZONE).date() == FIXED_TODAY
