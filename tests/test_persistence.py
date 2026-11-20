"""Phase 2: service + SQLite integration (imports, persistence, isolation, rollback, migrations)."""

import sqlite3
from datetime import date, timedelta

import pytest

from scholarpath import config, repository
from scholarpath.repository import SearchFilters
from scholarpath.database import LATEST_VERSION, connect, migrate, schema_version
from scholarpath.services import ImportFailed, ScholarPathService, ServiceError

from .conftest import FIXED_TODAY, by_key, real_record


def reopen(service: ScholarPathService) -> ScholarPathService:
    """A brand-new service object = a fresh process reading the same file."""
    return ScholarPathService(service.mode, db_path=service.db_path, clock=service.clock)


def test_import_and_retrieve_through_the_service_used_by_the_ui(example_service, example_records):
    views = example_service.search(SearchFilters(include_closed=True))
    assert len(views) == 15
    assert len(example_service.search()) == 13          # discovery leaves out the 2 closed records
    rec = example_service.get(by_key(example_records, "lakeshore-stem-excellence")["id"]).record
    assert rec.nationalities.values == ["Bangladesh", "India", "Nepal", "Sri Lanka"]
    assert rec.subjects.values == ["computer_science", "engineering", "natural_sciences"]
    assert rec.source_url.startswith("https://example.org/") and rec.collected_at


def test_repeat_import_is_idempotent(example_service, example_records):
    report = example_service.import_records(example_records)
    assert (report.inserted, report.updated, report.unchanged) == (0, 0, 15)
    with connect(example_service.db_path) as conn:
        assert repository.count_scholarships(conn) == 15
        assert conn.execute("SELECT COUNT(*) FROM scholarship_host_countries").fetchone()[0] == 17


def test_updating_source_data_keeps_id_and_user_references(example_service, example_records):
    target = by_key(example_records, "lakeshore-stem-excellence")
    example_service.save(target["id"])
    example_service.start_tracking(target["id"])
    example_service.update_application(target["id"], "preparing", target_date=date(2026, 11, 20), notes="SOP draft")

    target["deadline_date"] = "2027-01-15"
    target["eligibility_text"] = "Updated wording from the provider."
    report = example_service.import_records(example_records)
    assert report.updated == 1 and report.inserted == 0

    service = reopen(example_service)
    rec = service.get(target["id"]).record
    assert rec.deadline_date == date(2027, 1, 15) and rec.eligibility_text.startswith("Updated")
    assert target["id"] in service.saved_ids()
    app = service.get_application(target["id"])
    assert app.status == "preparing" and app.notes == "SOP draft"


def test_saved_item_survives_closing_and_reopening(example_service, example_records):
    sid = by_key(example_records, "cedar-public-health")["id"]
    assert example_service.save(sid) is True
    assert example_service.save(sid) is False  # duplicate prevented
    assert reopen(example_service).saved_ids() == [sid]


def test_tracker_update_survives_reopening_and_records_history(example_service, example_records):
    sid = by_key(example_records, "vega-cs-masters")["id"]
    example_service.start_tracking(sid)
    example_service.update_application(sid, "applied", target_date=date(2026, 11, 15),
                                       submitted_date=date(2026, 11, 10), notes="Submitted via portal")
    service = reopen(example_service)
    app = service.get_application(sid)
    assert app.status == "applied" and app.submitted_date == date(2026, 11, 10)
    assert app.target_date == date(2026, 11, 15)
    assert [h["status"] for h in service.application_history(sid)] == ["applied", "interested"]


def test_removing_from_shortlist_keeps_application_history(example_service, example_records):
    sid = by_key(example_records, "vega-cs-masters")["id"]
    example_service.save(sid)
    example_service.start_tracking(sid)
    example_service.update_application(sid, "preparing")
    assert example_service.unsave(sid) is True
    service = reopen(example_service)
    assert sid not in service.saved_ids()
    assert service.get_application(sid).status == "preparing"
    assert len(service.application_history(sid)) == 2
    assert sid in {v.record.id for group in service.dashboard().values() for v in group}


def test_removing_an_application_deletes_only_the_entry_and_its_history(example_service, example_records):
    sid = by_key(example_records, "vega-cs-masters")["id"]
    other = by_key(example_records, "lakeshore-stem-excellence")["id"]
    example_service.save(sid)
    example_service.mark_applied(sid, FIXED_TODAY)
    example_service.mark_applied(other, FIXED_TODAY)
    example_service.update_application(sid, "result_received", submitted_date=FIXED_TODAY, outcome="not_selected")
    assert example_service.remove_application(sid) is True
    service = reopen(example_service)
    assert service.get_application(sid) is None and service.application_history(sid) == []
    assert [a.scholarship_id for a in service.applications()] == [other]   # other entries untouched
    assert service.saved_ids() == [sid] and service.get(sid) is not None   # Saved and the record stay
    with connect(service.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM application_history ah LEFT JOIN applications a "
                            "ON a.id = ah.application_id WHERE a.id IS NULL").fetchone()[0] == 0
    assert service.remove_application(sid) is False                        # a repeated click is harmless
    service.mark_applied(sid, FIXED_TODAY)                                 # and it can be added again
    assert len(service.application_history(sid)) == 1


def test_scholarships_referenced_by_user_data_cannot_be_deleted(example_service, example_records):
    sid = by_key(example_records, "vega-cs-masters")["id"]
    example_service.save(sid)
    with connect(example_service.db_path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM scholarships WHERE id = ?", (sid,))


def test_failed_batch_rolls_back_completely(example_service, example_records, monkeypatch):
    for record in example_records:
        record["notes"] = record["notes"] + " Revised."
    new = real_record(dataset_origin="example", fetch_method="fictional", source_fetched_at=None,
                      source_key="brand-new")
    calls = {"n": 0}
    original = repository.update_scholarship

    def failing_update(conn, rec, digest, now):
        calls["n"] += 1
        if calls["n"] == 3:
            raise sqlite3.OperationalError("disk I/O error (simulated)")
        return original(conn, rec, digest, now)

    monkeypatch.setattr(repository, "update_scholarship", failing_update)
    with pytest.raises(ImportFailed, match="rolled back"):
        example_service.import_records(example_records + [new])
    monkeypatch.undo()

    views = example_service.search(SearchFilters(include_closed=True))
    assert len(views) == 15
    assert not any(v.record.notes.endswith("Revised.") for v in views)
    with connect(example_service.db_path) as conn:
        statuses = [r["status"] for r in conn.execute("SELECT status FROM import_runs ORDER BY id")]
    assert statuses == ["success", "failed"]


def test_invalid_records_are_rejected_before_any_write(example_service):
    with pytest.raises(ImportFailed, match="No valid records"):
        example_service.import_records([{"name": "no fields"}])
    assert len(example_service.search(SearchFilters(include_closed=True))) == 15


def test_multi_step_tracker_write_rolls_back_on_error(example_service, example_records, monkeypatch):
    sid = by_key(example_records, "vega-cs-masters")["id"]

    def broken_history(*args, **kwargs):
        raise sqlite3.OperationalError("simulated failure after the application row was inserted")

    monkeypatch.setattr(repository, "history_insert", broken_history)
    with pytest.raises(sqlite3.OperationalError):
        example_service.start_tracking(sid)
    monkeypatch.undo()
    assert example_service.get_application(sid) is None


def test_example_and_real_modes_are_isolated(tmp_path, clock, example_records):
    example = ScholarPathService(config.MODE_EXAMPLE, clock=clock)
    real = ScholarPathService(config.MODE_REAL, clock=clock)
    assert example.db_path != real.db_path
    example.import_records(example_records)
    real.import_records([real_record()])

    with pytest.raises(ImportFailed):  # real records cannot enter the example DB and vice versa
        example.import_records([real_record()])
    with pytest.raises(ImportFailed):
        real.import_records(example_records)

    example.save(example_records[0]["id"])
    assert real.saved_ids() == []
    with pytest.raises(ServiceError):
        real.save(example_records[0]["id"])
    everything = SearchFilters(include_closed=True)
    assert len(example.search(everything)) == 15 and len(real.search(everything)) == 1
    assert example.overview()["saved"] == 1 and real.overview()["saved"] == 0


def test_database_file_cannot_be_reused_for_the_other_mode(tmp_path, clock):
    path = tmp_path / "shared.sqlite3"
    ScholarPathService(config.MODE_EXAMPLE, db_path=path, clock=clock).ensure_schema()
    with pytest.raises(ServiceError, match="belongs to mode"):
        ScholarPathService(config.MODE_REAL, db_path=path, clock=clock).ensure_schema()


def test_migration_from_v1_preserves_user_data(tmp_path, clock, example_records):
    path = tmp_path / "old.sqlite3"
    assert migrate(path, target=1) == 1
    with connect(path) as conn:
        conn.execute("INSERT INTO meta VALUES ('dataset_mode', 'example')")
    # Simulate an older version of the app that imported data and saved/tracked one item.
    service = ScholarPathService(config.MODE_EXAMPLE, db_path=path, clock=clock)
    from scholarpath.cleaning import content_hash, validate_record

    rec = validate_record(example_records[0])
    with connect(path) as conn:   # a version-1 row, written with version-1 columns only
        params = repository._scholarship_params(rec, content_hash(rec), "2026-01-01T00:00:00+00:00")
        columns = [r["name"] for r in conn.execute("PRAGMA table_info(scholarships)")]
        values = {c: params.get(c, params["now"]) for c in columns}
        conn.execute(f"INSERT INTO scholarships ({', '.join(columns)}) VALUES "
                     f"({', '.join(':' + c for c in columns)})", values)
        repository.replace_children(conn, rec)
        conn.execute("INSERT INTO shortlist VALUES (?, '2026-01-02T00:00:00+00:00')", (rec.id,))
        conn.execute("INSERT INTO applications (scholarship_id, status, notes, created_at, updated_at) "
                     "VALUES (?, 'preparing', 'my notes', '2026-01-02T00:00:00+00:00', '2026-01-03T00:00:00+00:00')",
                     (rec.id,))

    assert service.ensure_schema() == LATEST_VERSION
    with connect(path) as conn:
        assert schema_version(conn) == LATEST_VERSION
    assert service.saved_ids() == [rec.id]
    assert service.get_application(rec.id).notes == "my notes"
    history = service.application_history(rec.id)
    assert len(history) == 1 and history[0]["status"] == "preparing"
    assert service.ensure_schema() == LATEST_VERSION  # re-running is a no-op
    with connect(path) as conn:   # v3 gave the old dated row a closing instant (end of day, AoE)
        row = conn.execute("SELECT deadline_date, closes_at, closed_by_source FROM scholarships").fetchone()
    assert row["closes_at"].startswith(str(date.fromisoformat(row["deadline_date"]) + timedelta(days=1)))
    assert row["closes_at"].endswith("T11:59:59+00:00") and row["closed_by_source"] == 0


def test_unavailable_pages_are_flagged_not_deleted(tmp_path, clock):
    real = ScholarPathService(config.MODE_REAL, clock=clock)
    record = real_record()
    real.import_records([record])
    real.save(record["id"])
    real.import_records([record], unavailable_urls=[record["source_url"]])
    view = real.shortlist()[0]
    assert view.record.source_status == "unavailable" and view.record.name == record["name"]


def test_manual_verification_timestamp_is_not_erased_by_reimport(tmp_path, clock):
    real = ScholarPathService(config.MODE_REAL, clock=clock)
    real.import_records([real_record(manual_verified_at="2026-11-12T12:00:00+00:00")])
    real.import_records([real_record(eligibility_text="Changed wording.")])
    assert real.get(real_record()["id"]).record.manual_verified_at == "2026-11-12T12:00:00+00:00"


def test_dashboard_uses_saved_and_tracked_items_in_distinct_groups(example_service, example_records):
    for key in ("cedar-public-health", "vega-cs-masters", "harbourview-business-leaders",
                "kestrel-arts-design-bursary", "coral-education-leaders", "lumen-humanities",
                "aurora-global-masters-southgate"):
        example_service.save(by_key(example_records, key)["id"])
    groups = example_service.dashboard()
    names = {group: [v.record.name for v in views] for group, views in groups.items()}
    assert names["due_7"] == ["Aurora Global Master's Scholarship", "Cedar Public Health Scholarship"]
    assert names["due_30"] == ["Vega Computer Science Master's Award"]
    assert names["later"] == ["Lumen Humanities Scholarship"]
    assert names["expired"] == ["Coral Education Leaders Fellowship"]
    assert names["rolling"] == ["Harbourview Business Leaders Grant"]
    assert names["unknown"] == ["Kestrel Arts & Design Bursary"]
    assert FIXED_TODAY == example_service.today()
