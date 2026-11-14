"""Application services: the only API the UI and CLI use.

One ``ScholarPathService`` instance is bound to one dataset mode and therefore
one database file. Each method opens a short-lived connection, so there is no
shared global connection and every write commits (or rolls back) before the
method returns.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import config, repository as repo
from .cleaning import content_hash, validate_many
from .config import Clock
from .database import DatabaseBusyError, connect, migrate, schema_version, transaction
from .dates import dashboard_group, deadline_status
from .matching import MatchResult, StudentProfile, evaluate
from .models import TRACKER_OUTCOMES, TRACKER_STATUSES, ScholarshipRecord
from .repository import SearchFilters

MODE_TO_ORIGIN = {config.MODE_EXAMPLE: "example", config.MODE_REAL: "real_source"}


# Storage failures the UI should report calmly instead of crashing (see ui/common.run_page).
STORAGE_ERRORS = (DatabaseBusyError, sqlite3.Error)


class ServiceError(ValueError):
    """A user-correctable problem (invalid input, unknown ID...)."""


class ImportFailed(RuntimeError):
    pass


@dataclass
class ImportReport:
    source_file: str
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: list[dict] = field(default_factory=list)
    duplicates: int = 0
    marked_unavailable: int = 0

    def summary(self) -> str:
        return (f"inserted={self.inserted} updated={self.updated} unchanged={self.unchanged} "
                f"rejected={len(self.rejected)} duplicates={self.duplicates} "
                f"marked_unavailable={self.marked_unavailable}")


@dataclass
class ScholarshipView:
    record: ScholarshipRecord
    status: str
    days_left: int | None
    group: str


@dataclass
class Application:
    id: int
    scholarship_id: str
    status: str
    target_date: date | None
    submitted_date: date | None
    outcome: str | None
    notes: str
    created_at: str
    updated_at: str


def _parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _to_application(row) -> Application:
    return Application(
        id=row["id"], scholarship_id=row["scholarship_id"], status=row["status"],
        target_date=_parse_date(row["target_date"]), submitted_date=_parse_date(row["submitted_date"]),
        outcome=row["outcome"], notes=row["notes"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


class ScholarPathService:
    def __init__(self, mode: str, db_path: Path | None = None, clock: Clock | None = None):
        if mode not in config.MODES:
            raise ValueError(f"Unknown mode {mode!r}")
        self.mode = mode
        self.db_path = Path(db_path) if db_path else config.db_path(mode)
        self.clock = clock or Clock()

    # --- setup ------------------------------------------------------------------

    def ensure_schema(self) -> int:
        """Create or upgrade the schema. Never deletes data."""
        version = migrate(self.db_path)
        with connect(self.db_path) as conn:
            stored = repo.get_meta(conn, "dataset_mode")
            if stored is None:
                with transaction(conn):
                    repo.set_meta(conn, "dataset_mode", self.mode)
            elif stored != self.mode:
                raise ServiceError(f"{self.db_path} belongs to mode {stored!r}, not {self.mode!r}.")
        return version

    def database_exists(self) -> bool:
        return self.db_path.exists()

    def schema_version(self) -> int:
        with connect(self.db_path) as conn:
            return schema_version(conn)

    def today(self) -> date:
        return self.clock.today()

    # --- imports ----------------------------------------------------------------

    def import_file(self, path: Path) -> ImportReport:
        path = Path(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ImportFailed(f"Could not read {path}: {exc}") from exc
        records = payload.get("records") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            raise ImportFailed(f"{path} has no 'records' list")
        meta = {}
        if payload.get("example_anchor_date"):
            meta["example_anchor_date"] = payload["example_anchor_date"]
        return self.import_records(records, source_file=str(path),
                                   unavailable_urls=payload.get("unavailable_urls") or [], meta=meta)

    def import_records(self, raw_records: list, source_file: str = "<memory>",
                       unavailable_urls: list[str] | None = None, meta: dict | None = None) -> ImportReport:
        """Validate everything first, then write all valid records in ONE transaction.

        Policy: invalid records are rejected individually with reasons; if any
        database error happens while writing, the whole batch is rolled back.
        An input with zero valid records is refused (nothing is changed).
        """
        self.ensure_schema()
        started = config.utc_now_iso()
        report = ImportReport(source_file=source_file)
        valid, rejected, duplicates = validate_many(raw_records)
        expected_origin = MODE_TO_ORIGIN[self.mode]
        accepted = []
        for rec in valid:
            if rec.dataset_origin != expected_origin:
                rejected.append({"name": rec.name, "reasons": [
                    f"dataset_origin {rec.dataset_origin!r} cannot be imported into the {self.mode!r} database"]})
            else:
                accepted.append(rec)
        report.rejected, report.duplicates = rejected, duplicates
        if not accepted:
            self._log_run(started, report, "failed", "No valid records; nothing imported.")
            raise ImportFailed(f"No valid records in {source_file}; nothing was changed. "
                               f"First rejection: {rejected[:1]}")

        now = config.utc_now_iso()
        try:
            with connect(self.db_path) as conn, transaction(conn):
                for rec in accepted:
                    digest = content_hash(rec)
                    existing = repo.existing_state(conn, rec.id)
                    if existing is None:
                        repo.insert_scholarship(conn, rec, digest, now)
                        report.inserted += 1
                    elif existing["content_hash"] != digest:
                        repo.update_scholarship(conn, rec, digest, now)
                        report.updated += 1
                    else:
                        repo.touch_unchanged(conn, rec, now)
                        report.unchanged += 1
                report.marked_unavailable = repo.mark_unavailable(conn, unavailable_urls or [])
                for key, value in (meta or {}).items():
                    repo.set_meta(conn, key, value)
                repo.set_meta(conn, "last_import_at", now)
                self._insert_run(conn, started, report, "success", "")
        except Exception as exc:
            self._log_run(started, report, "failed", f"Rolled back: {exc}")
            raise ImportFailed(f"Import rolled back, database unchanged: {exc}") from exc
        return report

    def _insert_run(self, conn, started: str, report: ImportReport, status: str, message: str) -> None:
        repo.record_import_run(conn, {
            "started_at": started, "finished_at": config.utc_now_iso(), "source_file": report.source_file,
            "status": status, "inserted": report.inserted, "updated": report.updated,
            "unchanged": report.unchanged, "rejected": len(report.rejected),
            "duplicates": report.duplicates, "message": message[:500],
        })

    def _log_run(self, started: str, report: ImportReport, status: str, message: str) -> None:
        if status == "failed":
            report.inserted = report.updated = report.unchanged = 0
        with connect(self.db_path) as conn, transaction(conn):
            self._insert_run(conn, started, report, status, message)

    # --- reads -------------------------------------------------------------------

    def _view(self, rec: ScholarshipRecord, today: date) -> ScholarshipView:
        status, days_left = deadline_status(rec.deadline_kind, rec.deadline_date, today)
        return ScholarshipView(rec, status, days_left, dashboard_group(rec.deadline_kind, rec.deadline_date, today))

    def search(self, filters: SearchFilters | None = None, sort: str = "deadline") -> list[ScholarshipView]:
        today = self.today()
        with connect(self.db_path) as conn:
            ids = repo.search_ids(conn, filters or SearchFilters(), today, sort)
            return [self._view(r, today) for r in repo.load_records(conn, ids)]

    def get(self, scholarship_id: str) -> ScholarshipView | None:
        with connect(self.db_path) as conn:
            records = repo.load_records(conn, [scholarship_id])
        return self._view(records[0], self.today()) if records else None

    def filter_options(self) -> dict[str, list[str]]:
        with connect(self.db_path) as conn:
            return repo.distinct_values(conn)

    def overview(self) -> dict:
        with connect(self.db_path) as conn:
            fresh = repo.freshness(conn)
            run = repo.latest_import_run(conn)
            data = {
                "scholarships": repo.count_scholarships(conn),
                "saved": len(repo.shortlist_ids(conn)),
                "tracked": len(repo.application_list(conn)),
                "oldest_collected": fresh["oldest_collected"],
                "newest_collected": fresh["newest_collected"],
                "newest_fetched": fresh["newest_fetched"],
                "verified_count": fresh["verified_count"] or 0,
                "unavailable_count": fresh["unavailable_count"] or 0,
                "last_import": dict(run) if run else None,
                "example_anchor_date": repo.get_meta(conn, "example_anchor_date"),
            }
        return data

    # --- shortlist ---------------------------------------------------------------

    def _require_scholarship(self, conn, scholarship_id: str) -> None:
        if not repo.scholarship_exists(conn, scholarship_id):
            raise ServiceError(f"Unknown scholarship ID {scholarship_id!r} in the {self.mode} dataset.")

    def save(self, scholarship_id: str) -> bool:
        """Add to shortlist. Returns False if it was already saved (no duplicate)."""
        with connect(self.db_path) as conn, transaction(conn):
            self._require_scholarship(conn, scholarship_id)
            return repo.shortlist_add(conn, scholarship_id, config.utc_now_iso())

    def unsave(self, scholarship_id: str) -> bool:
        """Remove from shortlist only. Any tracker entry and its history are kept."""
        with connect(self.db_path) as conn, transaction(conn):
            return repo.shortlist_remove(conn, scholarship_id)

    def saved_ids(self) -> list[str]:
        with connect(self.db_path) as conn:
            return repo.shortlist_ids(conn)

    def shortlist(self) -> list[ScholarshipView]:
        today = self.today()
        with connect(self.db_path) as conn:
            return [self._view(r, today) for r in repo.load_records(conn, repo.shortlist_ids(conn))]

    # --- tracker -----------------------------------------------------------------

    @staticmethod
    def validate_application(status: str, target_date: date | None, submitted_date: date | None,
                             outcome: str | None, today: date) -> list[str]:
        """Allowed combinations (documented in docs/DATA_DICTIONARY.md)."""
        errors = []
        if status not in TRACKER_STATUSES:
            errors.append(f"Unknown status {status!r}.")
        if outcome is not None and outcome not in TRACKER_OUTCOMES:
            errors.append(f"Unknown outcome {outcome!r}.")
        if status in ("interested", "preparing"):
            if submitted_date is not None:
                errors.append("A submission date can only be recorded once the status is Applied or Result received.")
            if outcome is not None:
                errors.append("An outcome can only be recorded with status Result received.")
        if status in ("applied", "result_received") and submitted_date is None:
            errors.append("Enter the date you submitted the application yourself.")
        if status == "applied" and outcome is not None:
            errors.append("An outcome can only be recorded with status Result received.")
        if status == "result_received" and outcome is None:
            errors.append("Choose the outcome you received.")
        if submitted_date is not None and submitted_date > today:
            errors.append("Submission date cannot be in the future.")
        return errors

    def start_tracking(self, scholarship_id: str) -> Application:
        now = config.utc_now_iso()
        with connect(self.db_path) as conn, transaction(conn):
            self._require_scholarship(conn, scholarship_id)
            existing = repo.application_for(conn, scholarship_id)
            if existing is None:
                app_id = repo.application_insert(conn, scholarship_id, "interested", now)
                repo.history_insert(conn, app_id, {"status": "interested"}, "Started tracking", now)
            row = repo.application_for(conn, scholarship_id)
        return _to_application(row)

    def update_application(self, scholarship_id: str, status: str, target_date: date | None = None,
                           submitted_date: date | None = None, outcome: str | None = None,
                           notes: str = "", history_note: str = "") -> Application:
        errors = self.validate_application(status, target_date, submitted_date, outcome, self.today())
        if errors:
            raise ServiceError(" ".join(errors))
        values = {
            "status": status,
            "target_date": target_date.isoformat() if target_date else None,
            "submitted_date": submitted_date.isoformat() if submitted_date else None,
            "outcome": outcome,
            "notes": (notes or "").strip(),
        }
        now = config.utc_now_iso()
        with connect(self.db_path) as conn, transaction(conn):
            row = repo.application_for(conn, scholarship_id)
            if row is None:
                raise ServiceError("Start tracking this scholarship before editing it.")
            if all(row[key] == value for key, value in values.items()) and not history_note.strip():
                return _to_application(row)  # nothing changed: no write, no empty history entry
            repo.application_update(conn, row["id"], values, now)
            repo.history_insert(conn, row["id"], values, history_note or "Edited", now)
            row = repo.application_for(conn, scholarship_id)
        return _to_application(row)

    def get_application(self, scholarship_id: str) -> Application | None:
        with connect(self.db_path) as conn:
            row = repo.application_for(conn, scholarship_id)
        return _to_application(row) if row else None

    def applications(self) -> list[Application]:
        with connect(self.db_path) as conn:
            return [_to_application(r) for r in repo.application_list(conn)]

    def application_history(self, scholarship_id: str) -> list[dict]:
        with connect(self.db_path) as conn:
            row = repo.application_for(conn, scholarship_id)
            return [dict(r) for r in repo.history_for(conn, row["id"])] if row else []

    # --- dashboard and matching ------------------------------------------------------

    def dashboard(self) -> dict[str, list[ScholarshipView]]:
        """Saved or tracked scholarships, in non-overlapping deadline groups."""
        today = self.today()
        with connect(self.db_path) as conn:
            ids = list(dict.fromkeys(repo.shortlist_ids(conn) + [r["scholarship_id"] for r in repo.application_list(conn)]))
            views = [self._view(r, today) for r in repo.load_records(conn, ids)]
        groups: dict[str, list[ScholarshipView]] = {}
        for view in sorted(views, key=lambda v: (v.record.deadline_date or date.max, v.record.name)):
            groups.setdefault(view.group, []).append(view)
        return groups

    def match(self, profile: StudentProfile, filters: SearchFilters | None = None) -> list[tuple[ScholarshipView, MatchResult]]:
        filters = filters or SearchFilters()
        if profile.preferred_destination:
            filters = SearchFilters(**{**filters.__dict__, "host_countries": [profile.preferred_destination]})
        views = self.search(filters, sort="name")
        order = {"Matches recorded requirements": 0, "Needs manual verification": 1,
                 "Does not match recorded requirements": 2}
        results = [(v, evaluate(profile, v.record)) for v in views]
        return sorted(results, key=lambda pair: (order[pair[1].overall], pair[0].record.name, pair[0].record.id))
