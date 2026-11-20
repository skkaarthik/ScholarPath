"""Scheduled refresh: due dates, all-or-nothing validation, atomic publishing, state,
locking, app synchronisation, annual cycles and preservation of user data.

Sources here are fakes (tests/test_collectors.py covers the real parsers on saved pages),
so these tests run offline and say nothing about whether the live sites are reachable.
"""

import json
import os
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from scholarpath import config, refresh
from scholarpath.collectors import runner
from scholarpath.models import stable_id
from scholarpath.repository import SearchFilters
from scholarpath.services import ScholarPathService

from .conftest import real_record

NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)
UTC = timezone.utc


def rec(key, name=None, source="Fake Source", **overrides):
    record = real_record(source_key=key, name=name or f"Award {key}", source_name=source, **overrides)
    record["id"] = stable_id(source, key)
    return record


class FakeSource:
    """A collector whose pages are a list we control: records, or ('failed', ...) items."""

    def __init__(self, source_name, items, enabled=True):
        self.SOURCE_NAME, self.items, self.ENABLED = source_name, items, enabled
        self.ALLOWED_HOSTS = {"example.ac.uk"}

    def collect(self, fetcher, collected_at):
        for item in self.items:
            if isinstance(item, tuple):
                yield item
            else:
                yield "record", {**item, "collected_at": collected_at, "source_fetched_at": collected_at}


@pytest.fixture
def paths(tmp_path):
    return SimpleNamespace(dataset=tmp_path / "pub" / "real_scholarships.json",
                           state=tmp_path / "pub" / "state.json", lock=tmp_path / "pub" / "refresh.lock")


@pytest.fixture
def sources(monkeypatch):
    registry = {}
    monkeypatch.setattr(runner, "SOURCES", registry)
    return registry


def run(paths, now=NOW, **kwargs):
    return refresh.run_refresh(now=now, dataset_path=paths.dataset, state_path=paths.state, lock_path=paths.lock,
                               fetcher_factory=lambda source_id, use_snapshots: None, **kwargs)


def published(paths):
    return json.loads(paths.dataset.read_text())


# --- when a refresh is due ------------------------------------------------------------

def test_due_after_15_elapsed_days_since_the_last_success_and_forced_runs(paths, sources):
    sources["fake"] = FakeSource("Fake Source", [rec("a")])
    assert refresh.is_due(refresh.load_state(paths.state), NOW)                       # never refreshed
    assert run(paths).outcome == "published"
    state = refresh.load_state(paths.state)
    assert state["last_success_at"] == NOW.isoformat()
    assert refresh.next_due(state) == NOW + timedelta(days=15)
    almost = NOW + timedelta(days=14, hours=23, minutes=59)
    result = run(paths, now=almost)
    assert result.outcome == "not_due" and result.next_due_at == (NOW + timedelta(days=15)).isoformat()
    assert run(paths, now=almost, force=True).outcome == "unchanged"                  # forced: runs anyway
    assert refresh.load_state(paths.state)["last_success_at"] == almost.replace(microsecond=0).isoformat()
    assert run(paths, now=almost + timedelta(days=15)).outcome == "unchanged"         # 15 days after the force


def test_a_failed_run_does_not_advance_the_last_success_and_is_retried(paths, sources):
    sources["fake"] = FakeSource("Fake Source", [rec("a"), rec("b")])
    run(paths)
    before = paths.dataset.read_bytes()
    sources["fake"].items = [rec("a"), ("failed", {"url": "https://example.ac.uk/b", "error": "HTTP 503",
                                                   "status": 503})]
    later = NOW + timedelta(days=16)
    result = run(paths, now=later)
    assert result.outcome == "failed" and result.exit_code == 1
    assert any("HTTP 503" in p for p in result.problems)
    state = refresh.load_state(paths.state)
    assert state["last_success_at"] == NOW.isoformat()                                 # unchanged
    assert state["latest_attempt"]["status"] == "failed"
    assert paths.dataset.read_bytes() == before                                        # nothing published
    assert refresh.is_due(state, later + timedelta(days=1))                            # tomorrow tries again
    # the same failure the next day does not rewrite the status file (no daily commits)
    stamp = paths.state.stat().st_mtime_ns
    assert run(paths, now=later + timedelta(days=1)).state_changed is False
    assert paths.state.stat().st_mtime_ns == stamp
    sources["fake"].items = [rec("a"), rec("b")]
    assert run(paths, now=later + timedelta(days=2)).outcome == "unchanged"
    assert refresh.load_state(paths.state)["latest_attempt"]["status"] == "success"


def test_any_failing_source_keeps_the_whole_previous_dataset(paths, sources):
    sources["one"] = FakeSource("Source One", [rec("a", source="Source One")])
    sources["two"] = FakeSource("Source Two", [rec("b", source="Source Two")])
    run(paths)
    before = paths.dataset.read_bytes()
    sources["one"].items = [rec("a", source="Source One", name="Renamed Award")]       # a real change...
    sources["two"].items = [("failed", {"url": "https://example.ac.uk/x", "error": "timeout", "status": None})]
    assert run(paths, force=True).outcome == "failed"
    assert paths.dataset.read_bytes() == before                                        # ...is not published


# --- validation thresholds (explicit, see refresh.Thresholds) --------------------------

def collected(records, failed=(), rejected=(), duplicates=0):
    report = runner.CollectionReport(records=list(records), failed=list(failed), rejected=list(rejected),
                                     duplicates=duplicates)
    return report


@pytest.fixture
def one_source(sources):
    sources["fake"] = FakeSource("Fake Source", [])
    return ["fake"]


def test_thresholds_are_explicit():
    t = refresh.DEFAULT_THRESHOLDS
    assert (t.max_failed_pages, t.max_rejected_records, t.max_duplicate_ids, t.min_records_per_source) == (0, 0, 0, 1)
    assert (t.max_drop_fraction, t.drop_check_min_records) == (0.25, 4)


@pytest.mark.parametrize("report, expected", [
    (collected([rec("a")], rejected=[{"source_url": "u", "reasons": ["deadline_date: not an ISO date"]}]),
     "Malformed record"),
    (collected([rec("a")], duplicates=1), "duplicate ID"),
    (collected([]), "no records collected"),
    (collected([rec("a", deadline_date="2099-01-01")]), "Implausible deadline"),
    (collected([rec("a", deadline_date="2019-01-01")]), "Implausible deadline"),
])
def test_validation_rejects_unsafe_collections(one_source, report, expected):
    problems = refresh.validate_collection(report, [], one_source, date(2026, 11, 19))
    assert any(expected in p for p in problems)


def test_a_large_unexplained_drop_fails_but_a_small_one_is_allowed(one_source):
    previous = [rec(k) for k in "abcdefgh"]                                            # 8 published
    assert any("more than 25% fewer" in p for p in refresh.validate_collection(
        collected([rec(k) for k in "abcde"]), previous, one_source, date(2026, 11, 19)))     # 5 = -37 %
    assert refresh.validate_collection(collected([rec(k) for k in "abcdef"]), previous, one_source,
                                       date(2026, 11, 19)) == []                        # 6 = -25 % allowed
    small = [rec(k) for k in "abc"]                                                    # below 4: no drop check
    assert refresh.validate_collection(collected([rec("a")]), small, one_source, date(2026, 11, 19)) == []


# --- publishing ------------------------------------------------------------------------

def test_publishing_is_atomic_versioned_and_only_on_meaningful_change(paths, sources):
    sources["fake"] = FakeSource("Fake Source", [rec("a"), rec("b")])
    assert run(paths).outcome == "published"
    first = published(paths)
    assert first["dataset_version"] == refresh.dataset_version(first["records"]) and len(first["records"]) == 2
    assert not list(paths.dataset.parent.glob(".*staging*"))                           # no leftovers
    stamp = paths.dataset.stat().st_mtime_ns
    result = run(paths, now=NOW + timedelta(days=15))                                  # new timestamps only
    assert result.outcome == "unchanged" and not result.dataset_changed
    assert paths.dataset.stat().st_mtime_ns == stamp                                   # file not rewritten
    sources["fake"].items = [rec("a", deadline_date="2027-01-15"), rec("b")]
    assert run(paths, now=NOW + timedelta(days=30)).outcome == "published"
    assert published(paths)["dataset_version"] != first["dataset_version"]


def test_a_record_missing_from_the_source_is_kept_not_treated_as_expired(paths, sources):
    sources["fake"] = FakeSource("Fake Source", [rec(k) for k in "abcd"])
    run(paths)
    sources["fake"].items = [rec(k) for k in "abc"]                                    # 'd' vanished (-25 %)
    assert run(paths, force=True).outcome == "unchanged"
    assert {r["source_key"] for r in published(paths)["records"]} == set("abcd")


def test_dry_run_writes_nothing(paths, sources):
    sources["fake"] = FakeSource("Fake Source", [rec("a")])
    result = run(paths, dry_run=True)
    assert result.outcome == "dry_run" and not paths.dataset.exists() and not paths.state.exists()


def test_only_enabled_sources_are_refreshed(paths, sources):
    sources["on"] = FakeSource("Source On", [rec("a", source="Source On")])
    sources["off"] = FakeSource("Source Off", [("failed", {"url": "u", "error": "x", "status": None})],
                                enabled=False)
    assert refresh.enabled_sources() == ["on"]
    assert run(paths).outcome == "published"


def test_overlapping_refreshes_are_prevented_and_a_stale_lock_is_ignored(paths, sources):
    sources["fake"] = FakeSource("Fake Source", [rec("a")])
    with refresh.refresh_lock(paths.lock, NOW):
        with pytest.raises(refresh.RefreshLocked):
            run(paths)
    assert not paths.lock.exists()
    paths.lock.parent.mkdir(parents=True, exist_ok=True)
    paths.lock.write_text("crashed run")
    old = (NOW - timedelta(hours=4)).timestamp()
    os.utime(paths.lock, (old, old))
    assert run(paths).outcome == "published" and not paths.lock.exists()


# --- the published dataset reaching the app ----------------------------------------------

def publish_records(paths, records):
    report = runner.CollectionReport(records=records)
    refresh.publish(records, report, paths.dataset, NOW)


def test_sync_imports_each_published_version_once_and_never_duplicates(paths):
    real = ScholarPathService(config.MODE_REAL)
    publish_records(paths, [rec("a"), rec("b")])
    assert real.sync_published(paths.dataset) == "imported"
    assert real.sync_published(paths.dataset) == "current"                             # same version: no import
    assert real.overview()["scholarships"] == 2
    publish_records(paths, [rec("a"), rec("b", name="Award B (renamed)"), rec("c")])
    assert real.sync_published(paths.dataset) == "imported"
    assert real.sync_published(paths.dataset) == "current"
    assert real.overview()["scholarships"] == 3                                        # updated in place, no copies
    names = {v.record.name for v in real.search(SearchFilters(include_closed=True))}
    assert names == {"Award a", "Award B (renamed)", "Award c"}


def test_a_refreshed_dataset_never_resets_saved_items_applications_or_history(paths):
    real = ScholarPathService(config.MODE_REAL)
    publish_records(paths, [rec("a"), rec("b")])
    real.sync_published(paths.dataset)
    a = stable_id("Fake Source", "a")
    real.save(a)
    real.mark_applied(a, date(2026, 11, 10))
    real.update_application(a, "result_received", submitted_date=date(2026, 11, 10), outcome="awarded",
                            notes="Interview went well")
    history = real.application_history(a)
    publish_records(paths, [rec("a", eligibility_text="New wording."), rec("b")])
    assert real.sync_published(paths.dataset) == "imported"
    app = real.get_application(a)
    assert (app.status, app.submitted_date, app.outcome, app.notes) == (
        "result_received", date(2026, 11, 10), "awarded", "Interview went well")
    assert real.application_history(a) == history and real.saved_ids() == [a]
    assert real.get(a).record.eligibility_text == "New wording."


def test_sync_only_touches_the_real_dataset(paths, example_records):
    example = ScholarPathService(config.MODE_EXAMPLE)
    example.import_records(example_records, source_file="test")
    example.save(example_records[0]["id"])
    publish_records(paths, [rec("a")])
    assert example.sync_published(paths.dataset) == "missing"                          # example is never synced
    ScholarPathService(config.MODE_REAL).sync_published(paths.dataset)
    assert example.overview()["scholarships"] == 15 and example.saved_ids() == [example_records[0]["id"]]
    assert all(v.record.dataset_origin == "example" for v in example.search(SearchFilters(include_closed=True)))


def test_the_running_app_shows_a_newly_published_dataset_without_manual_steps(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    from .test_ui import APP

    published_file = tmp_path / "published" / "real_scholarships.json"
    monkeypatch.setattr(config, "REAL_DATASET_FILE", published_file)
    target = SimpleNamespace(dataset=published_file)
    publish_records(target, [rec("a", name="First Published Award")])
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["mode"] = config.MODE_REAL
    at.run()
    assert not at.exception, at.exception
    assert "First Published Award" in [s.value for s in at.subheader]
    publish_records(target, [rec("a", name="First Published Award"), rec("b", name="Second Published Award")])
    at.run()                                                                           # a later rerun, same session
    assert {"First Published Award", "Second Published Award"} <= {s.value for s in at.subheader}
    assert ScholarPathService(config.MODE_REAL).imported_version() == published(target)["dataset_version"]


# --- annual cycles ---------------------------------------------------------------------

def test_a_new_cycle_of_a_tracked_scholarship_becomes_a_separate_record(paths):
    real = ScholarPathService(config.MODE_REAL)
    old = rec("csc", award_cycle="2026/27", deadline_date="2025-12-09")
    real.import_records([old])
    real.mark_applied(old["id"], date(2025, 12, 1))
    new = rec("csc", award_cycle="2027/28", deadline_date="2026-12-08")
    report = real.import_records([new])
    assert report.new_cycles == 1
    kept = real.get(old["id"]).record
    assert (kept.award_cycle, kept.deadline_date) == ("2026/27", date(2025, 12, 9))     # old context intact
    assert real.get_application(old["id"]).submitted_date == date(2025, 12, 1)
    cycle_id = stable_id("Fake Source", "csc#2027/28")
    assert real.get(cycle_id).record.award_cycle == "2027/28"
    real.import_records([rec("csc", award_cycle="2027/28", deadline_date="2026-12-10")])  # later refresh
    assert real.get(cycle_id).record.deadline_date == date(2026, 12, 10)               # same separate record
    assert real.overview()["scholarships"] == 2                                        # no third copy


def test_an_untracked_scholarship_simply_moves_on_to_the_new_cycle(paths):
    real = ScholarPathService(config.MODE_REAL)
    real.import_records([rec("great", award_cycle="2025-26", deadline_date="2026-05-01")])
    report = real.import_records([rec("great", award_cycle="2026-27", deadline_date="2026-12-01")])
    assert report.new_cycles == 0 and real.overview()["scholarships"] == 1
    assert real.get(stable_id("Fake Source", "great")).record.award_cycle == "2026-27"
