"""Phase 2: combined filters, sorting and deadline boundaries."""

from datetime import date, timedelta

import pytest

from scholarpath.dates import dashboard_group, deadline_status, describe_deadline
from scholarpath.repository import SearchFilters

from .conftest import FIXED_TODAY


def names(views) -> set[str]:
    return {v.record.name for v in views}


def test_or_within_a_category(example_service):
    views = example_service.search(SearchFilters(host_countries=["Germany", "Japan"]))
    assert names(views) == {"Lakeshore STEM Excellence Award", "Sakura Research Scholarship"}


def test_and_across_categories(example_service):
    views = example_service.search(SearchFilters(host_countries=["United Kingdom"], funding=["full"]))
    assert names(views) == {"Cedar Public Health Scholarship"}


def test_unknown_subject_never_satisfies_a_subject_filter_but_unrestricted_does(example_service):
    found = names(example_service.search(SearchFilters(subjects=["computer_science"])))
    assert "Atlas Open Short-Course Grant" not in found  # subjects unknown
    assert "Aurora Global Master's Scholarship" in found  # explicitly unrestricted
    assert {"Lakeshore STEM Excellence Award", "Vega Computer Science Master's Award",
            "Sakura Research Scholarship"} <= found
    assert "Cedar Public Health Scholarship" not in found


def test_degree_filter_matches_any_selected_degree(example_service):
    found = names(example_service.search(SearchFilters(degrees=["bachelor", "non_degree"])))
    assert found == {"Orion Undergraduate Access Award", "Atlas Open Short-Course Grant"}


def test_text_search_matches_name_or_provider_and_escapes_wildcards(example_service):
    assert len(example_service.search(SearchFilters(text="aurora"))) == 2
    assert names(example_service.search(SearchFilters(text="Southgate"))) == {"Aurora Global Master's Scholarship"}
    assert example_service.search(SearchFilters(text="100%")) == []
    assert example_service.search(SearchFilters(text="_")) == []


def test_deadline_status_filter_keeps_statuses_distinct(example_service):
    expired = names(example_service.search(SearchFilters(deadline_statuses=["expired"])))
    assert expired == {"Orion Undergraduate Access Award", "Coral Education Leaders Fellowship"}
    rolling = names(example_service.search(SearchFilters(deadline_statuses=["rolling"])))
    assert rolling == {"Harbourview Business Leaders Grant", "Atlas Open Short-Course Grant"}
    unknown = names(example_service.search(SearchFilters(deadline_statuses=["unknown"])))
    assert unknown == {"Kestrel Arts & Design Bursary"}
    assert len(example_service.search(SearchFilters(deadline_statuses=["open"]))) == 10


def test_clearing_filters_returns_everything(example_service):
    assert SearchFilters().is_empty()
    assert len(example_service.search(SearchFilters())) == 15


def test_deadline_sort_order_open_then_rolling_then_unknown_then_expired(example_service):
    views = example_service.search(sort="deadline")
    statuses = [v.status for v in views]
    assert statuses == sorted(statuses, key=["open", "rolling", "unknown", "expired"].index)
    open_dates = [v.record.deadline_date for v in views if v.status == "open"]
    assert open_dates == sorted(open_dates)
    expired = [v.record.deadline_date for v in views if v.status == "expired"]
    assert expired == sorted(expired, reverse=True)  # most recently closed first


def test_name_sort_is_stable_for_identical_names(example_service):
    first = [v.record.id for v in example_service.search(sort="name")]
    second = [v.record.id for v in example_service.search(sort="name")]
    assert first == second
    auroras = [v.record.provider for v in example_service.search(SearchFilters(text="Aurora"), sort="name")]
    assert auroras == sorted(auroras)


@pytest.mark.parametrize("offset, status, group", [
    (0, "open", "due_7"),
    (7, "open", "due_7"),
    (8, "open", "due_30"),
    (30, "open", "due_30"),
    (31, "open", "later"),
    (-1, "expired", "expired"),
])
def test_deadline_boundaries(offset, status, group):
    deadline = FIXED_TODAY + timedelta(days=offset)
    assert deadline_status("dated", deadline, FIXED_TODAY) == (status, offset)
    assert dashboard_group("dated", deadline, FIXED_TODAY) == group


def test_date_only_deadline_is_open_through_that_day():
    assert "closes today" in describe_deadline("dated", FIXED_TODAY, FIXED_TODAY)
    assert deadline_status("dated", FIXED_TODAY, FIXED_TODAY + timedelta(days=1))[0] == "expired"


def test_rolling_and_unknown_are_never_open_or_expired():
    assert deadline_status("rolling", None, FIXED_TODAY) == ("rolling", None)
    assert deadline_status("unknown", None, FIXED_TODAY) == ("unknown", None)
    assert dashboard_group("rolling", None, FIXED_TODAY) == "rolling"


def test_clock_override_is_used_by_service(example_service):
    assert example_service.today() == date(2026, 11, 12)


def test_sql_and_python_deadline_status_agree(example_service):
    everything = example_service.search()
    for status in ("open", "expired", "rolling", "unknown"):
        via_sql = {v.record.id for v in example_service.search(SearchFilters(deadline_statuses=[status]))}
        via_python = {v.record.id for v in everything if v.status == status}
        assert via_sql == via_python, status
