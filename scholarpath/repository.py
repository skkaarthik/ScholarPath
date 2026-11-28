"""Persistence: every SQL statement in ScholarPath lives in this module.

All statements are parameterized. Functions take an open connection so the
service layer decides transaction boundaries.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from .dates import closes_at_iso
from .models import Exclusions, InternshipRecord, Requirement, Restriction, ScholarshipRecord, SourceLink


@dataclass(frozen=True)
class UserTables:
    """Where one opportunity type keeps the student's own data. Scholarships and internships
    have tables of the same shape, so one set of functions serves both; the names below are
    fixed constants (never user input), which is why they may appear inside the SQL text."""

    records: str
    saved: str
    applications: str
    history: str
    column: str       # the column that points at the opportunity


SCHOLARSHIP_TABLES = UserTables("scholarships", "shortlist", "applications", "application_history", "scholarship_id")
INTERNSHIP_TABLES = UserTables("internships", "internship_saved", "internship_applications",
                               "internship_application_history", "internship_id")

# Closed = the source says so, or the stored closing instant (dates.closes_at) has passed.
# ``:now`` is a UTC ISO timestamp; ``closes_at`` is stored in the same format, so the text
# comparison is a time comparison. Filters, sorting, counts and dates.py all agree.
CLOSED_SQL = "(s.closed_by_source = 1 OR (s.closes_at IS NOT NULL AND s.closes_at <= :now))"
STATUS_SQL = (
    f"CASE WHEN {CLOSED_SQL} THEN 'expired' "
    "WHEN s.deadline_kind = 'rolling' THEN 'rolling' "
    "WHEN s.deadline_kind = 'unknown' THEN 'unknown' ELSE 'open' END"
)

# Deadline sort order (documented in docs/ARCHITECTURE.md): open dated deadlines
# soonest first, then rolling, then unknown, then expired (most recent first).
SORTS = {
    "deadline": (
        f"CASE WHEN {CLOSED_SQL} THEN 3 WHEN s.deadline_kind = 'dated' THEN 0 "
        "WHEN s.deadline_kind = 'rolling' THEN 1 ELSE 2 END, "
        f"CASE WHEN NOT {CLOSED_SQL} THEN s.closes_at END ASC, "
        "s.deadline_date DESC, s.name COLLATE NOCASE, s.id"
    ),
    "name": "s.name COLLATE NOCASE, s.provider COLLATE NOCASE, s.id",
    "provider": "s.provider COLLATE NOCASE, s.name COLLATE NOCASE, s.id",
}


@dataclass
class SearchFilters:
    text: str = ""
    host_countries: list[str] = field(default_factory=list)
    degrees: list[str] = field(default_factory=list)
    subjects: list[str] = field(default_factory=list)
    funding: list[str] = field(default_factory=list)
    deadline_statuses: list[str] = field(default_factory=list)
    # Active discovery never shows closed opportunities. Only pages that must reach closed
    # records on purpose (Data & sources, a saved/tracked record's own page) set this.
    include_closed: bool = False

    def is_empty(self) -> bool:
        return not (self.text.strip() or self.host_countries or self.degrees or self.subjects
                    or self.funding or self.deadline_statuses)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _in_clause(prefix: str, values: list[str], params: dict) -> str:
    names = []
    for i, value in enumerate(values):
        key = f"{prefix}{i}"
        params[key] = value
        names.append(f":{key}")
    return ", ".join(names)


# --- meta -------------------------------------------------------------------

def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# --- scholarship writes -----------------------------------------------------

def existing_state(conn: sqlite3.Connection, scholarship_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, content_hash, manual_verified_at, award_cycle FROM scholarships WHERE id = ?", (scholarship_id,)
    ).fetchone()


def is_referenced(conn: sqlite3.Connection, scholarship_id: str) -> bool:
    """True if the user saved it or has an application entry for it."""
    return conn.execute(
        "SELECT EXISTS (SELECT 1 FROM shortlist WHERE scholarship_id = :id) "
        "OR EXISTS (SELECT 1 FROM applications WHERE scholarship_id = :id)", {"id": scholarship_id},
    ).fetchone()[0] == 1


def _scholarship_params(rec: ScholarshipRecord, content_hash: str, now: str) -> dict:
    return {
        "id": rec.id, "name": rec.name, "provider": rec.provider,
        "degree_kind": rec.degrees.kind, "subject_kind": rec.subjects.kind,
        "nationality_kind": rec.nationalities.kind, "exclusion_kind": rec.nationality_exclusions.kind,
        "min_score": rec.min_score, "score_scale": rec.score_scale,
        "funding_category": rec.funding_category, "funding_description": rec.funding_description,
        "deadline_kind": rec.deadline_kind,
        "deadline_date": rec.deadline_date.isoformat() if rec.deadline_date else None,
        "deadline_text": rec.deadline_text, "eligibility_text": rec.eligibility_text,
        "application_url": rec.application_url, "source_url": rec.source_url,
        "source_name": rec.source_name, "source_key": rec.source_key, "award_cycle": rec.award_cycle,
        "collected_at": rec.collected_at, "source_fetched_at": rec.source_fetched_at,
        "fetch_method": rec.fetch_method, "manual_verified_at": rec.manual_verified_at,
        "dataset_origin": rec.dataset_origin, "notes": rec.notes, "source_status": rec.source_status,
        "deadline_at": rec.deadline_at, "deadline_timezone": rec.deadline_timezone,
        "closes_at": closes_at_iso(rec), "closed_by_source": int(rec.closed_by_source),
        "content_hash": content_hash, "now": now,
    }


def insert_scholarship(conn: sqlite3.Connection, rec: ScholarshipRecord, content_hash: str, now: str) -> None:
    conn.execute(
        """
        INSERT INTO scholarships (
            id, name, provider, degree_kind, subject_kind, nationality_kind, exclusion_kind,
            min_score, score_scale, funding_category, funding_description, deadline_kind,
            deadline_date, deadline_text, eligibility_text, application_url, source_url,
            source_name, source_key, award_cycle, collected_at, source_fetched_at, fetch_method,
            manual_verified_at, dataset_origin, notes, source_status, content_hash,
            deadline_at, deadline_timezone, closes_at, closed_by_source,
            first_imported_at, last_imported_at
        ) VALUES (
            :id, :name, :provider, :degree_kind, :subject_kind, :nationality_kind, :exclusion_kind,
            :min_score, :score_scale, :funding_category, :funding_description, :deadline_kind,
            :deadline_date, :deadline_text, :eligibility_text, :application_url, :source_url,
            :source_name, :source_key, :award_cycle, :collected_at, :source_fetched_at, :fetch_method,
            :manual_verified_at, :dataset_origin, :notes, :source_status, :content_hash,
            :deadline_at, :deadline_timezone, :closes_at, :closed_by_source,
            :now, :now
        )
        """,
        _scholarship_params(rec, content_hash, now),
    )
    replace_children(conn, rec)


def update_scholarship(conn: sqlite3.Connection, rec: ScholarshipRecord, content_hash: str, now: str) -> None:
    """Update in place (never delete/re-insert the referenced row).

    A manual verification timestamp already in the database is kept when the
    incoming record has none.
    """
    conn.execute(
        """
        UPDATE scholarships SET
            name = :name, provider = :provider, degree_kind = :degree_kind,
            subject_kind = :subject_kind, nationality_kind = :nationality_kind,
            exclusion_kind = :exclusion_kind, min_score = :min_score, score_scale = :score_scale,
            funding_category = :funding_category, funding_description = :funding_description,
            deadline_kind = :deadline_kind, deadline_date = :deadline_date,
            deadline_text = :deadline_text, eligibility_text = :eligibility_text,
            application_url = :application_url, source_url = :source_url,
            award_cycle = :award_cycle, collected_at = :collected_at,
            source_fetched_at = :source_fetched_at, fetch_method = :fetch_method,
            manual_verified_at = COALESCE(:manual_verified_at, manual_verified_at),
            notes = :notes, source_status = :source_status, content_hash = :content_hash,
            deadline_at = :deadline_at, deadline_timezone = :deadline_timezone,
            closes_at = :closes_at, closed_by_source = :closed_by_source,
            last_imported_at = :now
        WHERE id = :id
        """,
        _scholarship_params(rec, content_hash, now),
    )
    replace_children(conn, rec)


def touch_unchanged(conn: sqlite3.Connection, rec: ScholarshipRecord, now: str) -> None:
    conn.execute(
        """
        UPDATE scholarships SET collected_at = ?, source_fetched_at = ?, source_status = ?,
            last_imported_at = ?
        WHERE id = ?
        """,
        (rec.collected_at, rec.source_fetched_at, rec.source_status, now, rec.id),
    )


def replace_children(conn: sqlite3.Connection, rec: ScholarshipRecord) -> None:
    """Multivalued fields are owned by the scholarship and never referenced by user data."""
    for table in ("scholarship_host_countries", "scholarship_degrees", "scholarship_subjects",
                  "scholarship_nationalities", "scholarship_requirements"):
        conn.execute(f"DELETE FROM {table} WHERE scholarship_id = ?", (rec.id,))
    conn.executemany("INSERT INTO scholarship_host_countries VALUES (?, ?)",
                     [(rec.id, c) for c in rec.host_countries])
    conn.executemany("INSERT INTO scholarship_degrees VALUES (?, ?)", [(rec.id, d) for d in rec.degrees.values])
    conn.executemany("INSERT INTO scholarship_subjects VALUES (?, ?)", [(rec.id, s) for s in rec.subjects.values])
    conn.executemany("INSERT INTO scholarship_nationalities VALUES (?, ?, 'include')",
                     [(rec.id, c) for c in rec.nationalities.values])
    conn.executemany("INSERT INTO scholarship_nationalities VALUES (?, ?, 'exclude')",
                     [(rec.id, c) for c in rec.nationality_exclusions.values])
    conn.executemany("INSERT INTO scholarship_requirements VALUES (?, ?, ?, ?, ?)",
                     [(rec.id, i, r.kind, r.category, r.text) for i, r in enumerate(rec.requirements)])


def mark_unavailable(conn: sqlite3.Connection, source_urls: Iterable[str]) -> int:
    count = 0
    for url in source_urls:
        count += conn.execute(
            "UPDATE scholarships SET source_status = 'unavailable' WHERE source_url = ?", (url,)
        ).rowcount
    return count


def record_import_run(conn: sqlite3.Connection, run: dict) -> None:
    conn.execute(
        """
        INSERT INTO import_runs (started_at, finished_at, source_file, status, inserted, updated,
                                 unchanged, rejected, duplicates, message)
        VALUES (:started_at, :finished_at, :source_file, :status, :inserted, :updated,
                :unchanged, :rejected, :duplicates, :message)
        """,
        run,
    )


def latest_import_run(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM import_runs WHERE status = 'success' ORDER BY id DESC LIMIT 1"
    ).fetchone()


# --- scholarship reads --------------------------------------------------------

def search_ids(conn: sqlite3.Connection, filters: SearchFilters, today: date, sort: str = "deadline",
               now: str | None = None) -> list[str]:
    """Combined filters: OR within a category, AND across categories.

    Unknown criteria never satisfy a precise filter; explicitly unrestricted
    degree/subject criteria do.
    """
    params: dict = {"today": today.isoformat(), "now": now or f"{today.isoformat()}T12:00:00+00:00"}
    where = ["1 = 1"] if filters.include_closed else [f"NOT {CLOSED_SQL}"]
    if filters.text.strip():
        params["text"] = f"%{_escape_like(filters.text.strip())}%"
        where.append("(s.name LIKE :text ESCAPE '\\' OR s.provider LIKE :text ESCAPE '\\')")
    if filters.host_countries:
        where.append(
            "EXISTS (SELECT 1 FROM scholarship_host_countries h WHERE h.scholarship_id = s.id "
            f"AND h.country IN ({_in_clause('host', filters.host_countries, params)}))"
        )
    if filters.degrees:
        where.append(
            "(s.degree_kind = 'unrestricted' OR EXISTS (SELECT 1 FROM scholarship_degrees d "
            f"WHERE d.scholarship_id = s.id AND d.degree IN ({_in_clause('deg', filters.degrees, params)})))"
        )
    if filters.subjects:
        where.append(
            "(s.subject_kind = 'unrestricted' OR EXISTS (SELECT 1 FROM scholarship_subjects x "
            f"WHERE x.scholarship_id = s.id AND x.subject IN ({_in_clause('sub', filters.subjects, params)})))"
        )
    if filters.funding:
        where.append(f"s.funding_category IN ({_in_clause('fund', filters.funding, params)})")
    if filters.deadline_statuses:
        where.append(f"{STATUS_SQL} IN ({_in_clause('st', filters.deadline_statuses, params)})")
    order = SORTS.get(sort, SORTS["deadline"])
    sql = f"SELECT s.id FROM scholarships s WHERE {' AND '.join(where)} ORDER BY {order}"
    return [row["id"] for row in conn.execute(sql, params)]


def load_records(conn: sqlite3.Connection, ids: list[str]) -> list[ScholarshipRecord]:
    """Hydrate full records (with multivalued fields) preserving the order of ``ids``."""
    if not ids:
        return []
    params: dict = {}
    placeholders = _in_clause("id", ids, params)
    rows = {r["id"]: r for r in conn.execute(f"SELECT * FROM scholarships WHERE id IN ({placeholders})", params)}
    children: dict[str, dict] = {i: {"host": [], "deg": [], "sub": [], "inc": [], "exc": [], "req": []} for i in rows}
    for r in conn.execute(f"SELECT * FROM scholarship_host_countries WHERE scholarship_id IN ({placeholders}) ORDER BY country", params):
        children[r["scholarship_id"]]["host"].append(r["country"])
    for r in conn.execute(f"SELECT * FROM scholarship_degrees WHERE scholarship_id IN ({placeholders}) ORDER BY degree", params):
        children[r["scholarship_id"]]["deg"].append(r["degree"])
    for r in conn.execute(f"SELECT * FROM scholarship_subjects WHERE scholarship_id IN ({placeholders}) ORDER BY subject", params):
        children[r["scholarship_id"]]["sub"].append(r["subject"])
    for r in conn.execute(f"SELECT * FROM scholarship_nationalities WHERE scholarship_id IN ({placeholders}) ORDER BY country", params):
        children[r["scholarship_id"]]["inc" if r["rule"] == "include" else "exc"].append(r["country"])
    for r in conn.execute(f"SELECT * FROM scholarship_requirements WHERE scholarship_id IN ({placeholders}) ORDER BY position", params):
        children[r["scholarship_id"]]["req"].append(Requirement(r["kind"], r["category"], r["text"]))

    records = []
    for scholarship_id in ids:
        row = rows.get(scholarship_id)
        if row is None:
            continue
        c = children[scholarship_id]
        records.append(ScholarshipRecord(
            id=row["id"], name=row["name"], provider=row["provider"], host_countries=c["host"],
            degrees=Restriction(row["degree_kind"], c["deg"]),
            subjects=Restriction(row["subject_kind"], c["sub"]),
            nationalities=Restriction(row["nationality_kind"], c["inc"]),
            nationality_exclusions=Exclusions(row["exclusion_kind"], c["exc"]),
            min_score=row["min_score"], score_scale=row["score_scale"],
            funding_category=row["funding_category"], funding_description=row["funding_description"],
            deadline_kind=row["deadline_kind"],
            deadline_date=date.fromisoformat(row["deadline_date"]) if row["deadline_date"] else None,
            deadline_text=row["deadline_text"], eligibility_text=row["eligibility_text"],
            requirements=c["req"], application_url=row["application_url"], source_url=row["source_url"],
            source_name=row["source_name"], source_key=row["source_key"], award_cycle=row["award_cycle"],
            collected_at=row["collected_at"], source_fetched_at=row["source_fetched_at"],
            fetch_method=row["fetch_method"], manual_verified_at=row["manual_verified_at"],
            dataset_origin=row["dataset_origin"], notes=row["notes"], source_status=row["source_status"],
            deadline_at=row["deadline_at"], deadline_timezone=row["deadline_timezone"],
            closed_by_source=bool(row["closed_by_source"]),
        ))
    return records


def count_scholarships(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM scholarships").fetchone()[0])


def count_active(conn: sqlite3.Connection, now: str) -> int:
    """Opportunities shown in discovery: not closed (rolling and unknown deadlines count)."""
    return int(conn.execute(f"SELECT COUNT(*) FROM scholarships s WHERE NOT {CLOSED_SQL}", {"now": now}).fetchone()[0])


def distinct_values(conn: sqlite3.Connection) -> dict[str, list[str]]:
    return {
        "host_countries": [r[0] for r in conn.execute(
            "SELECT DISTINCT country FROM scholarship_host_countries ORDER BY country COLLATE NOCASE")],
        "nationalities": [r[0] for r in conn.execute(
            "SELECT DISTINCT country FROM scholarship_nationalities ORDER BY country COLLATE NOCASE")],
    }


def freshness(conn: sqlite3.Connection) -> sqlite3.Row:
    return conn.execute(
        """
        SELECT MIN(collected_at) AS oldest_collected, MAX(collected_at) AS newest_collected,
               MIN(source_fetched_at) AS oldest_fetched, MAX(source_fetched_at) AS newest_fetched,
               SUM(manual_verified_at IS NOT NULL) AS verified_count,
               SUM(source_status = 'unavailable') AS unavailable_count
        FROM scholarships
        """
    ).fetchone()


# --- saved list (both opportunity types) ------------------------------------------

def shortlist_add(conn: sqlite3.Connection, scholarship_id: str, now: str, t: UserTables = SCHOLARSHIP_TABLES) -> bool:
    cur = conn.execute(
        f"INSERT INTO {t.saved} ({t.column}, added_at) VALUES (?, ?) ON CONFLICT({t.column}) DO NOTHING",
        (scholarship_id, now),
    )
    return cur.rowcount == 1


def shortlist_remove(conn: sqlite3.Connection, scholarship_id: str, t: UserTables = SCHOLARSHIP_TABLES) -> bool:
    return conn.execute(f"DELETE FROM {t.saved} WHERE {t.column} = ?", (scholarship_id,)).rowcount == 1


def shortlist_ids(conn: sqlite3.Connection, t: UserTables = SCHOLARSHIP_TABLES) -> list[str]:
    return [r[0] for r in conn.execute(f"SELECT {t.column} FROM {t.saved} ORDER BY added_at, {t.column}")]


def scholarship_exists(conn: sqlite3.Connection, scholarship_id: str, t: UserTables = SCHOLARSHIP_TABLES) -> bool:
    return conn.execute(f"SELECT 1 FROM {t.records} WHERE id = ?", (scholarship_id,)).fetchone() is not None


# --- applications (both opportunity types) -------------------------------------------
# Rows carry the opportunity's ID as "item_id" whichever table they come from.

def application_for(conn: sqlite3.Connection, scholarship_id: str, t: UserTables = SCHOLARSHIP_TABLES) -> sqlite3.Row | None:
    return conn.execute(f"SELECT *, {t.column} AS item_id FROM {t.applications} WHERE {t.column} = ?",
                        (scholarship_id,)).fetchone()


def application_insert(conn: sqlite3.Connection, scholarship_id: str, status: str, now: str,
                       t: UserTables = SCHOLARSHIP_TABLES) -> int:
    cur = conn.execute(
        f"INSERT INTO {t.applications} ({t.column}, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (scholarship_id, status, now, now),
    )
    return int(cur.lastrowid)


def application_update(conn: sqlite3.Connection, application_id: int, values: dict, now: str,
                       t: UserTables = SCHOLARSHIP_TABLES) -> None:
    conn.execute(
        f"""
        UPDATE {t.applications} SET status = :status, target_date = :target_date,
            submitted_date = :submitted_date, outcome = :outcome, notes = :notes, updated_at = :now
        WHERE id = :id
        """,
        {**values, "now": now, "id": application_id},
    )


def history_insert(conn: sqlite3.Connection, application_id: int, values: dict, note: str, now: str,
                   t: UserTables = SCHOLARSHIP_TABLES) -> None:
    conn.execute(
        f"""
        INSERT INTO {t.history} (application_id, changed_at, status, target_date,
                                 submitted_date, outcome, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (application_id, now, values["status"], values.get("target_date"), values.get("submitted_date"),
         values.get("outcome"), note),
    )


def application_delete(conn: sqlite3.Connection, application_id: int, t: UserTables = SCHOLARSHIP_TABLES) -> None:
    """Delete one tracker entry and its history (history first: its foreign key is ON DELETE RESTRICT)."""
    conn.execute(f"DELETE FROM {t.history} WHERE application_id = ?", (application_id,))
    conn.execute(f"DELETE FROM {t.applications} WHERE id = ?", (application_id,))


def application_list(conn: sqlite3.Connection, t: UserTables = SCHOLARSHIP_TABLES) -> list[sqlite3.Row]:
    return list(conn.execute(f"SELECT *, {t.column} AS item_id FROM {t.applications} ORDER BY updated_at DESC, id DESC"))


def history_for(conn: sqlite3.Connection, application_id: int, t: UserTables = SCHOLARSHIP_TABLES) -> list[sqlite3.Row]:
    return list(conn.execute(
        f"SELECT * FROM {t.history} WHERE application_id = ? ORDER BY id DESC", (application_id,)
    ))


# --- internships: records ----------------------------------------------------------
# Same rules as scholarships: parameterized statements, updates in place, user data in
# separate tables, and the closing instant stored so SQL and dates.py agree.

I_CLOSED_SQL = "(i.closed_by_source = 1 OR (i.closes_at IS NOT NULL AND i.closes_at <= :now))"
I_STATUS_SQL = (
    f"CASE WHEN {I_CLOSED_SQL} THEN 'expired' "
    "WHEN i.deadline_kind = 'rolling' THEN 'rolling' "
    "WHEN i.deadline_kind = 'unknown' THEN 'unknown' ELSE 'open' END"
)
I_SORTS = {
    "deadline": (
        f"CASE WHEN {I_CLOSED_SQL} THEN 3 WHEN i.deadline_kind = 'dated' THEN 0 "
        "WHEN i.deadline_kind = 'rolling' THEN 1 ELSE 2 END, "
        f"CASE WHEN NOT {I_CLOSED_SQL} THEN i.closes_at END ASC, "
        "i.deadline_date DESC, i.title COLLATE NOCASE, i.id"
    ),
    "name": "i.title COLLATE NOCASE, i.employer COLLATE NOCASE, i.id",
    "provider": "i.employer COLLATE NOCASE, i.title COLLATE NOCASE, i.id",
    # Highest stated monthly stipend first; internships without an amount come last.
    "stipend": "COALESCE(i.stipend_max, i.stipend_min) IS NULL, COALESCE(i.stipend_max, i.stipend_min) DESC, "
               "i.title COLLATE NOCASE, i.id",
}


@dataclass
class InternshipFilters:
    text: str = ""
    place: str = "all_india"                       # locations.QUICK_PLACES
    cities: list[str] = field(default_factory=list)
    states: list[str] = field(default_factory=list)
    arrangements: list[str] = field(default_factory=list)
    disciplines: list[str] = field(default_factory=list)
    stipends: list[str] = field(default_factory=list)
    deadline_statuses: list[str] = field(default_factory=list)
    include_closed: bool = False

    def is_empty(self) -> bool:
        return not (self.text.strip() or self.place not in ("", "all_india") or self.cities or self.states
                    or self.arrangements or self.disciplines or self.stipends or self.deadline_statuses)


def internship_state(conn: sqlite3.Connection, internship_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT id, content_hash, manual_verified_at FROM internships WHERE id = ?",
                        (internship_id,)).fetchone()


def _internship_params(rec: InternshipRecord, content_hash: str, now: str) -> dict:
    return {
        "id": rec.id, "title": rec.title, "employer": rec.employer, "location_text": rec.location_text,
        "work_arrangement": rec.work_arrangement, "discipline_kind": rec.disciplines.kind,
        "degree_kind": rec.degrees.kind, "year_kind": rec.study_years.kind, "experience_text": rec.experience_text,
        "eligibility_text": rec.eligibility_text, "stipend_kind": rec.stipend_kind, "stipend_min": rec.stipend_min,
        "stipend_max": rec.stipend_max, "stipend_text": rec.stipend_text, "duration_months": rec.duration_months,
        "duration_text": rec.duration_text, "start_text": rec.start_text, "deadline_kind": rec.deadline_kind,
        "deadline_date": rec.deadline_date.isoformat() if rec.deadline_date else None,
        "deadline_text": rec.deadline_text, "deadline_at": rec.deadline_at, "deadline_timezone": rec.deadline_timezone,
        "closes_at": closes_at_iso(rec), "closed_by_source": int(rec.closed_by_source),
        "application_url": rec.application_url, "source_url": rec.source_url, "source_name": rec.source_name,
        "source_key": rec.source_key, "collected_at": rec.collected_at, "source_fetched_at": rec.source_fetched_at,
        "fetch_method": rec.fetch_method, "manual_verified_at": rec.manual_verified_at,
        "dataset_origin": rec.dataset_origin, "notes": rec.notes, "source_status": rec.source_status,
        "content_hash": content_hash, "now": now,
    }


_I_COLUMNS = ("id, title, employer, location_text, work_arrangement, discipline_kind, degree_kind, year_kind, "
              "experience_text, eligibility_text, stipend_kind, stipend_min, stipend_max, stipend_text, "
              "duration_months, duration_text, start_text, deadline_kind, deadline_date, deadline_text, deadline_at, "
              "deadline_timezone, closes_at, closed_by_source, application_url, source_url, source_name, source_key, "
              "collected_at, source_fetched_at, fetch_method, manual_verified_at, dataset_origin, notes, "
              "source_status, content_hash")


def insert_internship(conn: sqlite3.Connection, rec: InternshipRecord, content_hash: str, now: str) -> None:
    values = ", ".join(f":{c.strip()}" for c in _I_COLUMNS.split(","))
    conn.execute(f"INSERT INTO internships ({_I_COLUMNS}, first_imported_at, last_imported_at) "
                 f"VALUES ({values}, :now, :now)", _internship_params(rec, content_hash, now))
    _replace_internship_children(conn, rec)


def update_internship(conn: sqlite3.Connection, rec: InternshipRecord, content_hash: str, now: str) -> None:
    """Update in place; a stored manual check is kept when the incoming record has none."""
    columns = [c.strip() for c in _I_COLUMNS.split(",") if c.strip() != "id"]
    sets = ", ".join("manual_verified_at = COALESCE(:manual_verified_at, manual_verified_at)"
                     if c == "manual_verified_at" else f"{c} = :{c}" for c in columns)
    conn.execute(f"UPDATE internships SET {sets}, last_imported_at = :now WHERE id = :id",
                 _internship_params(rec, content_hash, now))
    _replace_internship_children(conn, rec)


def touch_internship(conn: sqlite3.Connection, rec: InternshipRecord, now: str) -> None:
    conn.execute("UPDATE internships SET collected_at = ?, source_fetched_at = ?, source_status = ?, "
                 "last_imported_at = ? WHERE id = ?",
                 (rec.collected_at, rec.source_fetched_at, rec.source_status, now, rec.id))


def _replace_internship_children(conn: sqlite3.Connection, rec: InternshipRecord) -> None:
    for table in ("internship_cities", "internship_states", "internship_criteria", "internship_listings"):
        conn.execute(f"DELETE FROM {table} WHERE internship_id = ?", (rec.id,))
    conn.executemany("INSERT INTO internship_cities VALUES (?, ?)", [(rec.id, c) for c in rec.cities])
    conn.executemany("INSERT INTO internship_states VALUES (?, ?)", [(rec.id, s) for s in rec.states])
    for field_name, restriction in (("discipline", rec.disciplines), ("degree", rec.degrees),
                                    ("year", rec.study_years)):
        conn.executemany("INSERT INTO internship_criteria VALUES (?, ?, ?)",
                         [(rec.id, field_name, v) for v in restriction.values])
    conn.executemany("INSERT INTO internship_listings VALUES (?, ?, ?, ?)",
                     [(rec.id, i, link.source_name, link.url) for i, link in enumerate(rec.also_listed)])


def close_missing_internships(conn: sqlite3.Connection, source_name: str, seen_ids: set[str]) -> int:
    """A job board that answered but no longer lists a posting has closed it. Mark (never delete)
    those records, but only for sources that were read successfully in this run."""
    rows = conn.execute("SELECT id FROM internships WHERE source_name = ? AND closed_by_source = 0",
                        (source_name,)).fetchall()
    gone = [r["id"] for r in rows if r["id"] not in seen_ids]
    conn.executemany("UPDATE internships SET closed_by_source = 1, source_status = 'unavailable' WHERE id = ?",
                     [(i,) for i in gone])
    return len(gone)


def search_internship_ids(conn: sqlite3.Connection, filters: InternshipFilters, sort: str = "deadline",
                          now: str = "") -> list[str]:
    """OR within a filter, AND across filters. Unknown criteria never satisfy a precise filter."""
    params: dict = {"now": now}
    where = ["1 = 1"] if filters.include_closed else [f"NOT {I_CLOSED_SQL}"]
    if filters.text.strip():
        params["text"] = f"%{_escape_like(filters.text.strip())}%"
        where.append("(i.title LIKE :text ESCAPE '\\' OR i.employer LIKE :text ESCAPE '\\')")
    if filters.place == "remote":
        where.append("i.work_arrangement = 'remote'")
    elif filters.place in ("chennai", "bengaluru"):
        params["quick_city"] = filters.place.capitalize()
        where.append("EXISTS (SELECT 1 FROM internship_cities c WHERE c.internship_id = i.id AND c.city = :quick_city)")
    if filters.cities:
        where.append("EXISTS (SELECT 1 FROM internship_cities c WHERE c.internship_id = i.id "
                     f"AND c.city IN ({_in_clause('city', filters.cities, params)}))")
    if filters.states:
        where.append("EXISTS (SELECT 1 FROM internship_states s WHERE s.internship_id = i.id "
                     f"AND s.state IN ({_in_clause('state', filters.states, params)}))")
    if filters.arrangements:
        where.append(f"i.work_arrangement IN ({_in_clause('arr', filters.arrangements, params)})")
    if filters.disciplines:
        where.append("(i.discipline_kind = 'unrestricted' OR EXISTS (SELECT 1 FROM internship_criteria x "
                     "WHERE x.internship_id = i.id AND x.field = 'discipline' "
                     f"AND x.value IN ({_in_clause('dis', filters.disciplines, params)})))")
    if filters.stipends:
        where.append(f"i.stipend_kind IN ({_in_clause('stp', filters.stipends, params)})")
    if filters.deadline_statuses:
        where.append(f"{I_STATUS_SQL} IN ({_in_clause('st', filters.deadline_statuses, params)})")
    order = I_SORTS.get(sort, I_SORTS["deadline"])
    sql = f"SELECT i.id FROM internships i WHERE {' AND '.join(where)} ORDER BY {order}"
    return [row["id"] for row in conn.execute(sql, params)]


def load_internships(conn: sqlite3.Connection, ids: list[str]) -> list[InternshipRecord]:
    """Hydrate full internship records preserving the order of ``ids``."""
    if not ids:
        return []
    params: dict = {}
    placeholders = _in_clause("id", ids, params)
    rows = {r["id"]: r for r in conn.execute(f"SELECT * FROM internships WHERE id IN ({placeholders})", params)}
    kids: dict[str, dict] = {i: {"city": [], "state": [], "discipline": [], "degree": [], "year": [], "links": []}
                             for i in rows}
    for r in conn.execute(f"SELECT * FROM internship_cities WHERE internship_id IN ({placeholders})", params):
        kids[r["internship_id"]]["city"].append(r["city"])
    for r in conn.execute(f"SELECT * FROM internship_states WHERE internship_id IN ({placeholders})", params):
        kids[r["internship_id"]]["state"].append(r["state"])
    for r in conn.execute(f"SELECT * FROM internship_criteria WHERE internship_id IN ({placeholders}) "
                          "ORDER BY value", params):
        kids[r["internship_id"]][r["field"]].append(r["value"])
    for r in conn.execute(f"SELECT * FROM internship_listings WHERE internship_id IN ({placeholders}) "
                          "ORDER BY position", params):
        kids[r["internship_id"]]["links"].append(SourceLink(r["source_name"], r["url"]))

    from .locations import order_places, order_states

    records = []
    for internship_id in ids:
        row = rows.get(internship_id)
        if row is None:
            continue
        k = kids[internship_id]
        records.append(InternshipRecord(
            id=row["id"], title=row["title"], employer=row["employer"], cities=order_places(k["city"]),
            states=order_states(k["state"]), location_text=row["location_text"],
            work_arrangement=row["work_arrangement"],
            disciplines=Restriction(row["discipline_kind"], k["discipline"]),
            degrees=Restriction(row["degree_kind"], k["degree"]),
            study_years=Restriction(row["year_kind"], k["year"]),
            experience_text=row["experience_text"], eligibility_text=row["eligibility_text"],
            stipend_kind=row["stipend_kind"], stipend_min=row["stipend_min"], stipend_max=row["stipend_max"],
            stipend_text=row["stipend_text"], duration_months=row["duration_months"],
            duration_text=row["duration_text"], deadline_kind=row["deadline_kind"],
            deadline_date=date.fromisoformat(row["deadline_date"]) if row["deadline_date"] else None,
            deadline_text=row["deadline_text"], application_url=row["application_url"],
            source_url=row["source_url"], source_name=row["source_name"], source_key=row["source_key"],
            collected_at=row["collected_at"], source_fetched_at=row["source_fetched_at"],
            fetch_method=row["fetch_method"], manual_verified_at=row["manual_verified_at"],
            dataset_origin=row["dataset_origin"], also_listed=k["links"], notes=row["notes"],
            source_status=row["source_status"], deadline_at=row["deadline_at"],
            deadline_timezone=row["deadline_timezone"], closed_by_source=bool(row["closed_by_source"]),
            start_text=row["start_text"],
        ))
    return records


def count_internships(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM internships").fetchone()[0])


def count_active_internships(conn: sqlite3.Connection, now: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM internships i WHERE NOT {I_CLOSED_SQL}", {"now": now}).fetchone()[0])


def internship_values(conn: sqlite3.Connection) -> dict[str, list[str]]:
    return {
        "cities": [r[0] for r in conn.execute("SELECT DISTINCT city FROM internship_cities")],
        "states": [r[0] for r in conn.execute("SELECT DISTINCT state FROM internship_states")],
    }


def internship_freshness(conn: sqlite3.Connection) -> sqlite3.Row:
    return conn.execute(
        """
        SELECT MIN(collected_at) AS oldest_collected, MAX(collected_at) AS newest_collected,
               MIN(source_fetched_at) AS oldest_fetched, MAX(source_fetched_at) AS newest_fetched,
               SUM(manual_verified_at IS NOT NULL) AS verified_count,
               SUM(source_status = 'unavailable') AS unavailable_count
        FROM internships
        """
    ).fetchone()
