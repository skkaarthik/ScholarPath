"""SQLite connections and ordered schema migrations.

* Every connection enables foreign keys and a busy timeout.
* Connections are opened per operation by ``connect()`` and always closed;
  there is no shared global connection.
* ``transaction()`` wraps multi-step writes: commit on success, rollback on any
  exception.
* Migrations are an ordered list of SQL scripts. ``PRAGMA user_version`` holds
  the applied version and ``schema_migrations`` records when each was applied.
  Migrations only add structure; nothing here ever drops user tables.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import config


class DatabaseBusyError(RuntimeError):
    """Raised when the database stays locked longer than the busy timeout."""


MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "core schema: scholarships, multivalued fields, shortlist, applications",
        """
        CREATE TABLE meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE scholarships (
            id                  TEXT PRIMARY KEY,
            name                TEXT NOT NULL,
            provider            TEXT NOT NULL,
            degree_kind         TEXT NOT NULL CHECK (degree_kind IN ('unrestricted','list','unknown')),
            subject_kind        TEXT NOT NULL CHECK (subject_kind IN ('unrestricted','list','unknown')),
            nationality_kind    TEXT NOT NULL CHECK (nationality_kind IN ('unrestricted','list','unknown')),
            exclusion_kind      TEXT NOT NULL CHECK (exclusion_kind IN ('none','list','unknown')),
            min_score           REAL,
            score_scale         TEXT,
            funding_category    TEXT NOT NULL,
            funding_description TEXT NOT NULL DEFAULT '',
            deadline_kind       TEXT NOT NULL CHECK (deadline_kind IN ('dated','rolling','unknown')),
            deadline_date       TEXT,
            deadline_text       TEXT NOT NULL DEFAULT '',
            eligibility_text    TEXT NOT NULL,
            application_url     TEXT NOT NULL,
            source_url          TEXT NOT NULL,
            source_name         TEXT NOT NULL,
            source_key          TEXT NOT NULL,
            award_cycle         TEXT,
            collected_at        TEXT NOT NULL,
            source_fetched_at   TEXT,
            fetch_method        TEXT NOT NULL,
            manual_verified_at  TEXT,
            dataset_origin      TEXT NOT NULL CHECK (dataset_origin IN ('example','real_source')),
            notes               TEXT NOT NULL DEFAULT '',
            source_status       TEXT NOT NULL DEFAULT 'available',
            content_hash        TEXT NOT NULL,
            first_imported_at   TEXT NOT NULL,
            last_imported_at    TEXT NOT NULL,
            CHECK ((deadline_kind = 'dated') = (deadline_date IS NOT NULL)),
            CHECK ((min_score IS NULL) = (score_scale IS NULL)),
            UNIQUE (source_name, source_key)
        );
        CREATE INDEX idx_scholarships_deadline ON scholarships (deadline_kind, deadline_date);
        CREATE INDEX idx_scholarships_funding ON scholarships (funding_category);

        CREATE TABLE scholarship_host_countries (
            scholarship_id TEXT NOT NULL REFERENCES scholarships(id) ON DELETE CASCADE,
            country        TEXT NOT NULL,
            PRIMARY KEY (scholarship_id, country)
        );
        CREATE INDEX idx_host_country ON scholarship_host_countries (country);

        CREATE TABLE scholarship_degrees (
            scholarship_id TEXT NOT NULL REFERENCES scholarships(id) ON DELETE CASCADE,
            degree         TEXT NOT NULL,
            PRIMARY KEY (scholarship_id, degree)
        );
        CREATE INDEX idx_degree ON scholarship_degrees (degree);

        CREATE TABLE scholarship_subjects (
            scholarship_id TEXT NOT NULL REFERENCES scholarships(id) ON DELETE CASCADE,
            subject        TEXT NOT NULL,
            PRIMARY KEY (scholarship_id, subject)
        );
        CREATE INDEX idx_subject ON scholarship_subjects (subject);

        CREATE TABLE scholarship_nationalities (
            scholarship_id TEXT NOT NULL REFERENCES scholarships(id) ON DELETE CASCADE,
            country        TEXT NOT NULL,
            rule           TEXT NOT NULL CHECK (rule IN ('include','exclude')),
            PRIMARY KEY (scholarship_id, country, rule)
        );

        CREATE TABLE scholarship_requirements (
            scholarship_id TEXT NOT NULL REFERENCES scholarships(id) ON DELETE CASCADE,
            position       INTEGER NOT NULL,
            kind           TEXT NOT NULL CHECK (kind IN ('structured','manual_review')),
            category       TEXT NOT NULL,
            text           TEXT NOT NULL,
            PRIMARY KEY (scholarship_id, position)
        );

        -- User data. Scholarships referenced here can never be deleted (RESTRICT).
        CREATE TABLE shortlist (
            scholarship_id TEXT PRIMARY KEY REFERENCES scholarships(id) ON DELETE RESTRICT,
            added_at       TEXT NOT NULL
        );

        CREATE TABLE applications (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scholarship_id  TEXT NOT NULL UNIQUE REFERENCES scholarships(id) ON DELETE RESTRICT,
            status          TEXT NOT NULL CHECK (status IN ('interested','preparing','applied','result_received')),
            target_date     TEXT,
            submitted_date  TEXT,
            outcome         TEXT,
            notes           TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        "application status history and import run log",
        """
        CREATE TABLE application_history (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE RESTRICT,
            changed_at     TEXT NOT NULL,
            status         TEXT NOT NULL,
            target_date    TEXT,
            submitted_date TEXT,
            outcome        TEXT,
            note           TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX idx_history_application ON application_history (application_id, changed_at);

        -- Backfill: give existing applications a starting history row.
        INSERT INTO application_history (application_id, changed_at, status, target_date, submitted_date, outcome, note)
            SELECT id, updated_at, status, target_date, submitted_date, outcome, 'Recorded before history tracking existed'
            FROM applications;

        CREATE TABLE import_runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at  TEXT NOT NULL,
            finished_at TEXT,
            source_file TEXT NOT NULL,
            status      TEXT NOT NULL CHECK (status IN ('success','failed')),
            inserted    INTEGER NOT NULL DEFAULT 0,
            updated     INTEGER NOT NULL DEFAULT 0,
            unchanged   INTEGER NOT NULL DEFAULT 0,
            rejected    INTEGER NOT NULL DEFAULT 0,
            duplicates  INTEGER NOT NULL DEFAULT 0,
            message     TEXT NOT NULL DEFAULT ''
        );
        """,
    ),
]

MIGRATIONS.append((
    3,
    "closing instants: exact closing time, source time zone, stored closing instant, closed-by-source flag",
    """
    ALTER TABLE scholarships ADD COLUMN deadline_at TEXT;
    ALTER TABLE scholarships ADD COLUMN deadline_timezone TEXT;
    ALTER TABLE scholarships ADD COLUMN closes_at TEXT;
    ALTER TABLE scholarships ADD COLUMN closed_by_source INTEGER NOT NULL DEFAULT 0 CHECK (closed_by_source IN (0, 1));
    -- Existing dated rows: end of the deadline day Anywhere on Earth (UTC-12), i.e. 11:59:59 UTC
    -- the next day. The next import recomputes this with the source's own time zone.
    UPDATE scholarships SET closes_at = date(deadline_date, '+1 day') || 'T11:59:59+00:00'
        WHERE deadline_kind = 'dated';
    CREATE INDEX idx_scholarships_closes ON scholarships (closes_at);
    """,
))

LATEST_VERSION = MIGRATIONS[-1][0]


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open a configured connection and always close it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=config.SQLITE_BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {int(config.SQLITE_BUSY_TIMEOUT_MS)}")
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Explicit BEGIN IMMEDIATE ... COMMIT; ROLLBACK on any error."""
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc) or "busy" in str(exc):
            raise DatabaseBusyError(
                "The database is locked by another program or ScholarPath window. "
                "Close it and try again."
            ) from exc
        raise
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(path: Path, target: int = LATEST_VERSION) -> int:
    """Apply pending migrations in order, each in its own transaction."""
    from .config import utc_now_iso

    with connect(path) as conn:
        current = schema_version(conn)
        if current > LATEST_VERSION:
            raise RuntimeError(
                f"Database schema v{current} is newer than this code (v{LATEST_VERSION}). Update ScholarPath."
            )
        for version, description, script in MIGRATIONS:
            if version <= current or version > target:
                continue
            with transaction(conn):
                for statement in _split_sql(script):
                    conn.execute(statement)
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations ("
                    "version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
                    (version, description, utc_now_iso()),
                )
                conn.execute(f"PRAGMA user_version = {int(version)}")
            current = version
        return current


def _split_sql(script: str) -> list[str]:
    """Split a migration script into statements (no semicolons inside literals here)."""
    statements, buffer = [], []
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(buffer))
            buffer = []
    if buffer:
        statements.append("\n".join(buffer))
    return statements


def backup(path: Path, destination: Path) -> Path:
    """Consistent copy using SQLite's online backup API."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    target.close()
    return destination
