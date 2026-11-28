"""Application services: the only API the UI and CLI use.

One ``ScholarPathService`` instance is bound to one dataset mode and therefore
one database file. Each method opens a short-lived connection, so there is no
shared global connection and every write commits (or rolls back) before the
method returns.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path

from . import advisor, chat_context, config, repository as repo
from .cleaning import content_hash, validate_many
from .config import Clock
from .database import DatabaseBusyError, connect, migrate, schema_version, transaction
from .dates import dashboard_group, deadline_status, record_closed
from .matching import MatchResult, StudentProfile, evaluate
from .models import TRACKER_OUTCOMES, TRACKER_STATUSES, ScholarshipRecord, stable_id
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
    new_cycles: int = 0           # records kept apart because a saved/tracked one is an older cycle

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

    @property
    def item_id(self) -> str:
        """The opportunity this entry tracks (a scholarship or an internship ID)."""
        return self.scholarship_id


def _parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _to_application(row) -> Application:
    return Application(
        id=row["id"], scholarship_id=row["item_id"], status=row["status"],
        target_date=_parse_date(row["target_date"]), submitted_date=_parse_date(row["submitted_date"]),
        outcome=row["outcome"], notes=row["notes"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


class ScholarPathService:
    kind = "scholarship"
    T = repo.SCHOLARSHIP_TABLES      # where this opportunity type keeps saved items and applications
    noun = "scholarship"

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

    def now(self) -> datetime:
        """The current instant (UTC); deadlines close at an instant, not just on a date."""
        return self.clock.now()

    def now_iso(self) -> str:
        return self.now().replace(microsecond=0).isoformat()

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
                    rec = self._cycle_target(conn, rec, report)
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

    @staticmethod
    def _cycle_target(conn, rec: ScholarshipRecord, report: ImportReport) -> ScholarshipRecord:
        """Annual cycles: where an incoming record is written.

        A record keeps its stable ID while it stays in the same award cycle, or while nobody
        saved or tracked it (then it simply moves on to the new cycle). If the stored record is
        for an earlier cycle AND the user saved or applied to it, the new cycle becomes a
        separate record with its own ID, so the old application keeps its original cycle and
        deadline. Later imports of that cycle find and update the separate record.
        """
        if not rec.award_cycle:
            return rec
        cycle_key = f"{rec.source_key}#{rec.award_cycle}"
        cycle_id = stable_id(rec.source_name, cycle_key)
        if repo.existing_state(conn, cycle_id) is not None:
            return replace(rec, id=cycle_id, source_key=cycle_key)
        stored = repo.existing_state(conn, rec.id)
        if (stored is not None and stored["award_cycle"] and stored["award_cycle"] != rec.award_cycle
                and repo.is_referenced(conn, rec.id)):
            report.new_cycles += 1
            return replace(rec, id=cycle_id, source_key=cycle_key)
        return rec

    # --- published dataset (the scheduled refresh's output) -------------------------------

    def imported_version(self) -> str | None:
        if not self.database_exists():
            return None
        self.ensure_schema()
        with connect(self.db_path) as conn:
            return repo.get_meta(conn, "published_version")

    def sync_published(self, path: Path = config.REAL_DATASET_FILE) -> str:
        """Bring this database up to the published real dataset, once per dataset version.

        Returns "imported", "current" or "missing". Idempotent: the version is stored in
        the same transaction as the import, a second caller finds it current, and an
        import changes scholarships only (saved items, applications and history are other
        tables and are never touched). Only the Real dataset is synchronised.
        """
        from .refresh import load_published

        if self.mode != config.MODE_REAL or not Path(path).exists():
            return "missing"
        payload = load_published(path)
        version = payload["dataset_version"]
        if self.imported_version() == version:
            return "current"
        self.import_records(payload.get("records", []), source_file=str(path),
                            unavailable_urls=payload.get("unavailable_urls") or [],
                            meta={"published_version": version})
        return "imported"

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
        closed = record_closed(rec, self.now())
        status, days_left = deadline_status(rec.deadline_kind, rec.deadline_date, today, closed)
        return ScholarshipView(rec, status, days_left,
                               dashboard_group(rec.deadline_kind, rec.deadline_date, today, closed))

    def search(self, filters: SearchFilters | None = None, sort: str = "deadline") -> list[ScholarshipView]:
        """Active discovery: closed opportunities are left out unless filters.include_closed."""
        today = self.today()
        with connect(self.db_path) as conn:
            ids = repo.search_ids(conn, filters or SearchFilters(), today, sort, self.now_iso())
            return [self._view(r, today) for r in repo.load_records(conn, ids)]

    @staticmethod
    def _load(conn, ids: list[str]) -> list:
        """Full records for ``ids``, in that order (each opportunity type loads its own)."""
        return repo.load_records(conn, ids)

    def get(self, scholarship_id: str) -> ScholarshipView | None:
        with connect(self.db_path) as conn:
            records = self._load(conn, [scholarship_id])
        return self._view(records[0], self.today()) if records else None

    # --- ScholarPath assistant (read-only: it never changes a record) -------------------------

    @staticmethod
    def assistant_mode() -> str:
        """"live" when an AI provider is configured, otherwise "demo" (labelled record-only answers)."""
        return "live" if advisor.settings_from_env() is not None else "demo"

    def chat(self, question: str, history: list[tuple[str, str]], current_id: str | None = None,
             profile=None) -> advisor.ChatReply:
        """Answer one question using only the records the server selects for it.

        ``history`` is [(question, answer), ...] from this browser session; ``profile`` is the
        Check my fit profile, if the student filled it in. Raises advisor.AdvisorError with a
        plain message (kind "input", "quota", "config" or "unavailable") when no answer is possible.
        Application entries are read through the same service as the Applications page: the
        assistant can see nothing that page does not show.
        """
        question = advisor.check_question(question)
        today = self.today()
        views = self.search(sort="deadline")          # open opportunities only
        if current_id and current_id not in {v.record.id for v in views}:
            current = self.get(current_id)               # a closed one being reviewed is still the context
            views = views + ([current] if current else [])
        chat = chat_context.select(views, question, history, current_id, profile, self.applications())
        names = [c.view.record.name for c in chat.records]
        settings = advisor.settings_from_env()
        if settings is None:
            shown = chat.records[:1] if chat.current_tag else chat.records[:3]
            if chat.intent == "progress":
                shown = [c for c in chat.records if any(a["tag"] == c.tag for a in chat.applications or [])]
            return advisor.ChatReply(advisor.demo_answer(chat, today), shown, demo=True, context_names=names)
        context = chat_context.context_block(chat, today, profile, config.MODE_LABELS.get(self.mode, self.mode))
        raw = advisor.call_provider(settings, advisor.build_messages(context, question, history))
        text, references, invented = chat_context.clean_answer(raw, chat)
        return advisor.ChatReply(text, references, demo=False, context_names=names, invented=invented)

    def filter_options(self) -> dict[str, list[str]]:
        with connect(self.db_path) as conn:
            return repo.distinct_values(conn)

    def overview(self) -> dict:
        with connect(self.db_path) as conn:
            fresh = repo.freshness(conn)
            run = repo.latest_import_run(conn)
            data = {
                "scholarships": repo.count_scholarships(conn),
                "active": repo.count_active(conn, self.now_iso()),
                "saved": len(repo.shortlist_ids(conn)),
                "tracked": len(repo.application_list(conn)),
                "oldest_collected": fresh["oldest_collected"],
                "newest_collected": fresh["newest_collected"],
                "oldest_fetched": fresh["oldest_fetched"],
                "newest_fetched": fresh["newest_fetched"],
                "verified_count": fresh["verified_count"] or 0,
                "unavailable_count": fresh["unavailable_count"] or 0,
                "last_import": dict(run) if run else None,
                "example_anchor_date": repo.get_meta(conn, "example_anchor_date"),
            }
        return data

    # --- shortlist ---------------------------------------------------------------

    def _require_scholarship(self, conn, scholarship_id: str) -> None:
        if not repo.scholarship_exists(conn, scholarship_id, t=self.T):
            raise ServiceError(f"Unknown {self.noun} ID {scholarship_id!r} in the {self.mode} dataset.")

    def save(self, scholarship_id: str) -> bool:
        """Add to shortlist. Returns False if it was already saved (no duplicate)."""
        with connect(self.db_path) as conn, transaction(conn):
            self._require_scholarship(conn, scholarship_id)
            return repo.shortlist_add(conn, scholarship_id, config.utc_now_iso(), t=self.T)

    def unsave(self, scholarship_id: str) -> bool:
        """Remove from shortlist only. Any tracker entry and its history are kept."""
        with connect(self.db_path) as conn, transaction(conn):
            return repo.shortlist_remove(conn, scholarship_id, t=self.T)

    def saved_ids(self) -> list[str]:
        with connect(self.db_path) as conn:
            return repo.shortlist_ids(conn, t=self.T)

    def shortlist(self) -> list[ScholarshipView]:
        today = self.today()
        with connect(self.db_path) as conn:
            return [self._view(r, today) for r in self._load(conn, repo.shortlist_ids(conn, t=self.T))]

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
            existing = repo.application_for(conn, scholarship_id, t=self.T)
            if existing is None:
                app_id = repo.application_insert(conn, scholarship_id, "interested", now, t=self.T)
                repo.history_insert(conn, app_id, {"status": "interested"}, "Started tracking", now, t=self.T)
            row = repo.application_for(conn, scholarship_id, t=self.T)
        return _to_application(row)

    def mark_applied(self, scholarship_id: str, submitted_date: date | None) -> Application:
        """Record that the user confirmed they submitted on the provider's site.

        This is how an application enters the tracker from the Review page: the
        entry is created (or an earlier Interested/Preparing entry is moved on)
        in one transaction. An entry that is already Applied or further is left
        untouched and returned as it is, so a repeated click or a rerun can
        never create a second entry, rewrite the first one or raise an error.
        """
        now = config.utc_now_iso()
        with connect(self.db_path) as conn, transaction(conn):
            self._require_scholarship(conn, scholarship_id)
            row = repo.application_for(conn, scholarship_id, t=self.T)
            if row is not None and row["status"] in ("applied", "result_received"):
                return _to_application(row)
            errors = self.validate_application("applied", None, submitted_date, None, self.today())
            if errors:
                raise ServiceError(" ".join(errors))  # leaves the transaction: nothing is written
            app_id = row["id"] if row is not None else repo.application_insert(conn, scholarship_id, "applied", now, t=self.T)
            values = {
                "status": "applied",
                "target_date": row["target_date"] if row is not None else None,
                "submitted_date": submitted_date.isoformat(),
                "outcome": None,
                "notes": row["notes"] if row is not None else "",
            }
            repo.application_update(conn, app_id, values, now, t=self.T)
            repo.history_insert(conn, app_id, values, "Marked as applied", now, t=self.T)
            row = repo.application_for(conn, scholarship_id, t=self.T)
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
            row = repo.application_for(conn, scholarship_id, t=self.T)
            if row is None:
                raise ServiceError(f"Start tracking this {self.noun} before editing it.")
            if all(row[key] == value for key, value in values.items()) and not history_note.strip():
                return _to_application(row)  # nothing changed: no write, no empty history entry
            repo.application_update(conn, row["id"], values, now, t=self.T)
            repo.history_insert(conn, row["id"], values, history_note or "Edited", now, t=self.T)
            row = repo.application_for(conn, scholarship_id, t=self.T)
        return _to_application(row)

    def remove_application(self, scholarship_id: str) -> bool:
        """Remove the tracker entry for a scholarship, with its history, in one transaction.

        Only the user's own tracking is deleted: the scholarship record and the Saved
        list are untouched. Returns False when there was no entry (e.g. a repeated click).
        """
        with connect(self.db_path) as conn, transaction(conn):
            row = repo.application_for(conn, scholarship_id, t=self.T)
            if row is None:
                return False
            repo.application_delete(conn, row["id"], t=self.T)
        return True

    def get_application(self, scholarship_id: str) -> Application | None:
        with connect(self.db_path) as conn:
            row = repo.application_for(conn, scholarship_id, t=self.T)
        return _to_application(row) if row else None

    def applications(self) -> list[Application]:
        with connect(self.db_path) as conn:
            return [_to_application(r) for r in repo.application_list(conn, t=self.T)]

    def application_history(self, scholarship_id: str) -> list[dict]:
        with connect(self.db_path) as conn:
            row = repo.application_for(conn, scholarship_id, t=self.T)
            return [dict(r) for r in repo.history_for(conn, row["id"], t=self.T)] if row else []

    # --- dashboard and matching ------------------------------------------------------

    def dashboard(self) -> dict[str, list[ScholarshipView]]:
        """Saved or tracked scholarships, in non-overlapping deadline groups."""
        today = self.today()
        with connect(self.db_path) as conn:
            ids = list(dict.fromkeys(repo.shortlist_ids(conn, t=self.T)
                                     + [r["item_id"] for r in repo.application_list(conn, t=self.T)]))
            views = [self._view(r, today) for r in self._load(conn, ids)]
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


# --- internships (v2) ---------------------------------------------------------------

class InternshipService(ScholarPathService):
    """The same service for internships: one dataset mode, one database file, the same
    short-lived connections and transactions. Saving, Mark as applied, status updates,
    removal and history are inherited unchanged; only reading and importing records differ.
    """

    kind = "internship"
    T = repo.INTERNSHIP_TABLES
    noun = "internship"

    @staticmethod
    def _load(conn, ids: list[str]) -> list:
        return repo.load_internships(conn, ids)

    # --- imports ------------------------------------------------------------------

    def import_file(self, path: Path) -> ImportReport:
        path = Path(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ImportFailed(f"Could not read {path}: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
            raise ImportFailed(f"{path} has no 'records' list")
        return self.import_payload(payload, source_file=str(path))

    def import_payload(self, payload: dict, source_file: str = "<memory>", meta: dict | None = None) -> ImportReport:
        meta = dict(meta or {})
        if payload.get("sources") is not None:
            meta["internship_sources"] = json.dumps(payload["sources"], sort_keys=True)
        if payload.get("example_anchor_date"):
            meta["example_anchor_date"] = payload["example_anchor_date"]
        read_ok = [s["source_name"] for s in payload.get("sources") or [] if s.get("status") == "ok"]
        return self.import_records(payload["records"], source_file=source_file, meta=meta, sources_read=read_ok)

    def import_records(self, raw_records: list, source_file: str = "<memory>", unavailable_urls=None,
                       meta: dict | None = None, sources_read: list[str] | None = None) -> ImportReport:
        """Validate first, then write every valid record in ONE transaction (rolled back on any error).

        ``sources_read`` names the job boards read successfully in this collection: their postings
        that are no longer listed are marked closed (never deleted). Records of a source that
        failed are left exactly as they were.
        """
        from .cleaning import validate_many_internships

        self.ensure_schema()
        started = config.utc_now_iso()
        report = ImportReport(source_file=f"internships:{source_file}")
        valid, rejected, duplicates = validate_many_internships(raw_records)
        expected = MODE_TO_ORIGIN[self.mode]
        accepted = []
        for rec in valid:
            if rec.dataset_origin != expected:
                rejected.append({"name": rec.title, "reasons": [
                    f"dataset_origin {rec.dataset_origin!r} cannot be imported into the {self.mode!r} database"]})
            else:
                accepted.append(rec)
        report.rejected, report.duplicates = rejected, duplicates
        if not accepted:
            self._log_run(started, report, "failed", "No valid internship records; nothing imported.")
            raise ImportFailed(f"No valid internship records in {source_file}; nothing was changed. "
                               f"First rejection: {rejected[:1]}")
        now = config.utc_now_iso()
        try:
            with connect(self.db_path) as conn, transaction(conn):
                for rec in accepted:
                    digest = content_hash(rec)
                    existing = repo.internship_state(conn, rec.id)
                    if existing is None:
                        repo.insert_internship(conn, rec, digest, now)
                        report.inserted += 1
                    elif existing["content_hash"] != digest:
                        repo.update_internship(conn, rec, digest, now)
                        report.updated += 1
                    else:
                        repo.touch_internship(conn, rec, now)
                        report.unchanged += 1
                seen = {rec.id for rec in accepted}
                for source_name in sources_read or []:
                    report.marked_unavailable += repo.close_missing_internships(conn, source_name, seen)
                for key, value in meta.items():
                    repo.set_meta(conn, key, value)
                repo.set_meta(conn, "internships_last_import_at", now)
                self._insert_run(conn, started, report, "success", "")
        except Exception as exc:
            self._log_run(started, report, "failed", f"Rolled back: {exc}")
            raise ImportFailed(f"Import rolled back, database unchanged: {exc}") from exc
        return report

    def imported_version(self) -> str | None:
        if not self.database_exists():
            return None
        self.ensure_schema()
        with connect(self.db_path) as conn:
            return repo.get_meta(conn, "internships_published_version")

    def sync_published(self, path: Path = config.REAL_INTERNSHIPS_FILE) -> str:
        """Import the live finder's latest dataset once per version (Real dataset only).
        Returns "imported", "current" or "missing"; saved items and applications are untouched."""
        if self.mode != config.MODE_REAL or not Path(path).exists():
            return "missing"
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ImportFailed(f"Could not read {path}: {exc}") from exc
        version = payload.get("dataset_version")
        if not version:
            raise ImportFailed(f"{path} has no dataset_version")
        if self.imported_version() == version:
            return "current"
        self.import_payload(payload, source_file=str(path), meta={"internships_published_version": version})
        return "imported"

    # --- reads --------------------------------------------------------------------

    def search(self, filters: "repo.InternshipFilters | None" = None, sort: str = "deadline") -> list[ScholarshipView]:
        today = self.today()
        with connect(self.db_path) as conn:
            ids = repo.search_internship_ids(conn, filters or repo.InternshipFilters(), sort, self.now_iso())
            return [self._view(r, today) for r in repo.load_internships(conn, ids)]

    def filter_options(self) -> dict[str, list[str]]:
        from .locations import order_places, order_states

        with connect(self.db_path) as conn:
            values = repo.internship_values(conn)
        return {"cities": order_places(values["cities"]), "states": order_states(values["states"])}

    def overview(self) -> dict:
        with connect(self.db_path) as conn:
            fresh = repo.internship_freshness(conn)
            run = repo.latest_import_run(conn, internships=True)
            sources = repo.get_meta(conn, "internship_sources")
            return {
                "scholarships": repo.count_internships(conn),        # key shared with the scholarship overview
                "active": repo.count_active_internships(conn, self.now_iso()),
                "saved": len(repo.shortlist_ids(conn, t=self.T)),
                "tracked": len(repo.application_list(conn, t=self.T)),
                "oldest_collected": fresh["oldest_collected"], "newest_collected": fresh["newest_collected"],
                "oldest_fetched": fresh["oldest_fetched"], "newest_fetched": fresh["newest_fetched"],
                "verified_count": fresh["verified_count"] or 0,
                "unavailable_count": fresh["unavailable_count"] or 0,
                "last_import": dict(run) if run else None,
                "example_anchor_date": repo.get_meta(conn, "example_anchor_date"),
                "sources": json.loads(sources) if sources else [],
            }

    def coverage(self) -> dict[str, int]:
        """Open internships in Chennai, in Bengaluru, elsewhere in India and remote (for Data & sources
        and the live-finder report). One internship in two cities counts in each."""
        views = self.search()
        chennai = sum(1 for v in views if "Chennai" in v.record.cities)
        bengaluru = sum(1 for v in views if "Bengaluru" in v.record.cities)
        elsewhere = sum(1 for v in views if any(c not in ("Chennai", "Bengaluru") for c in v.record.cities)
                        or (not v.record.cities and v.record.work_arrangement != "remote"))
        remote = sum(1 for v in views if v.record.work_arrangement == "remote")
        return {"open": len(views), "chennai": chennai, "bengaluru": bengaluru, "rest_of_india": elsewhere,
                "remote": remote}

    # --- Check my fit ------------------------------------------------------------------

    def match(self, profile, filters=None):
        from .matching import evaluate_internship

        filters = filters or repo.InternshipFilters()
        place = profile.preferred_place
        if place == "remote":
            filters = replace(filters, place="remote")
        elif place:
            filters = replace(filters, cities=[place])
        views = self.search(filters, sort="name")
        order = {"Matches recorded requirements": 0, "Needs manual verification": 1,
                 "Does not match recorded requirements": 2}
        results = [(v, evaluate_internship(profile, v.record)) for v in views]
        return sorted(results, key=lambda pair: (order[pair[1].overall], pair[0].record.name, pair[0].record.id))

    # --- assistant -------------------------------------------------------------------------

    def chat(self, question: str, history: list[tuple[str, str]], current_id: str | None = None,
             profile=None) -> advisor.ChatReply:
        """The same read-only assistant, answering from internship records only."""
        question = advisor.check_question(question)
        today = self.today()
        views = self.search(sort="deadline")
        if current_id and current_id not in {v.record.id for v in views}:
            current = self.get(current_id)
            views = views + ([current] if current else [])
        chat = chat_context.select(views, question, history, current_id, profile, self.applications())
        names = [c.view.record.name for c in chat.records]
        settings = advisor.settings_from_env()
        if settings is None:
            shown = chat.records[:1] if chat.current_tag else chat.records[:3]
            if chat.intent == "progress":
                shown = [c for c in chat.records if any(a["tag"] == c.tag for a in chat.applications or [])]
            return advisor.ChatReply(advisor.demo_answer(chat, today, kind=self.kind), shown, demo=True,
                                     context_names=names)
        context = chat_context.context_block(chat, today, profile, config.MODE_LABELS.get(self.mode, self.mode),
                                             kind=self.kind)
        raw = advisor.call_provider(settings, advisor.build_messages(context, question, history, kind=self.kind))
        text, references, invented = chat_context.clean_answer(raw, chat)
        return advisor.ChatReply(text, references, demo=False, context_names=names, invented=invented)


def service_for(kind: str, mode: str, db_path: Path | None = None, clock: Clock | None = None) -> ScholarPathService:
    """The service for one opportunity type in one dataset."""
    cls = InternshipService if kind == config.KIND_INTERNSHIP else ScholarPathService
    return cls(mode, db_path=db_path, clock=clock)
