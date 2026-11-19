"""Persistence: every SQL statement in ScholarPath lives in this module.

All statements are parameterized. Functions take an open connection so the
service layer decides transaction boundaries.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from .models import Exclusions, Requirement, Restriction, ScholarshipRecord

# Deadline status computed in SQL so filters and sorting agree with dates.py.
STATUS_SQL = (
    "CASE WHEN s.deadline_kind = 'rolling' THEN 'rolling' "
    "WHEN s.deadline_kind = 'unknown' THEN 'unknown' "
    "WHEN s.deadline_date >= :today THEN 'open' ELSE 'expired' END"
)

# Deadline sort order (documented in docs/ARCHITECTURE.md): open dated deadlines
# soonest first, then rolling, then unknown, then expired (most recent first).
SORTS = {
    "deadline": (
        "CASE WHEN s.deadline_kind = 'dated' AND s.deadline_date >= :today THEN 0 "
        "WHEN s.deadline_kind = 'rolling' THEN 1 "
        "WHEN s.deadline_kind = 'unknown' THEN 2 ELSE 3 END, "
        "CASE WHEN s.deadline_date >= :today THEN s.deadline_date END ASC, "
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
        "SELECT id, content_hash, manual_verified_at FROM scholarships WHERE id = ?", (scholarship_id,)
    ).fetchone()


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
            first_imported_at, last_imported_at
        ) VALUES (
            :id, :name, :provider, :degree_kind, :subject_kind, :nationality_kind, :exclusion_kind,
            :min_score, :score_scale, :funding_category, :funding_description, :deadline_kind,
            :deadline_date, :deadline_text, :eligibility_text, :application_url, :source_url,
            :source_name, :source_key, :award_cycle, :collected_at, :source_fetched_at, :fetch_method,
            :manual_verified_at, :dataset_origin, :notes, :source_status, :content_hash,
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

def search_ids(conn: sqlite3.Connection, filters: SearchFilters, today: date, sort: str = "deadline") -> list[str]:
    """Combined filters: OR within a category, AND across categories.

    Unknown criteria never satisfy a precise filter; explicitly unrestricted
    degree/subject criteria do.
    """
    params: dict = {"today": today.isoformat()}
    where = ["1 = 1"]
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
        ))
    return records


def count_scholarships(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM scholarships").fetchone()[0])


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


# --- shortlist ------------------------------------------------------------------

def shortlist_add(conn: sqlite3.Connection, scholarship_id: str, now: str) -> bool:
    cur = conn.execute(
        "INSERT INTO shortlist (scholarship_id, added_at) VALUES (?, ?) ON CONFLICT(scholarship_id) DO NOTHING",
        (scholarship_id, now),
    )
    return cur.rowcount == 1


def shortlist_remove(conn: sqlite3.Connection, scholarship_id: str) -> bool:
    return conn.execute("DELETE FROM shortlist WHERE scholarship_id = ?", (scholarship_id,)).rowcount == 1


def shortlist_ids(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT scholarship_id FROM shortlist ORDER BY added_at, scholarship_id")]


def scholarship_exists(conn: sqlite3.Connection, scholarship_id: str) -> bool:
    return conn.execute("SELECT 1 FROM scholarships WHERE id = ?", (scholarship_id,)).fetchone() is not None


# --- applications ----------------------------------------------------------------

def application_for(conn: sqlite3.Connection, scholarship_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM applications WHERE scholarship_id = ?", (scholarship_id,)).fetchone()


def application_insert(conn: sqlite3.Connection, scholarship_id: str, status: str, now: str) -> int:
    cur = conn.execute(
        "INSERT INTO applications (scholarship_id, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (scholarship_id, status, now, now),
    )
    return int(cur.lastrowid)


def application_update(conn: sqlite3.Connection, application_id: int, values: dict, now: str) -> None:
    conn.execute(
        """
        UPDATE applications SET status = :status, target_date = :target_date,
            submitted_date = :submitted_date, outcome = :outcome, notes = :notes, updated_at = :now
        WHERE id = :id
        """,
        {**values, "now": now, "id": application_id},
    )


def history_insert(conn: sqlite3.Connection, application_id: int, values: dict, note: str, now: str) -> None:
    conn.execute(
        """
        INSERT INTO application_history (application_id, changed_at, status, target_date,
                                         submitted_date, outcome, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (application_id, now, values["status"], values.get("target_date"), values.get("submitted_date"),
         values.get("outcome"), note),
    )


def application_delete(conn: sqlite3.Connection, application_id: int) -> None:
    """Delete one tracker entry and its history (history first: its foreign key is ON DELETE RESTRICT)."""
    conn.execute("DELETE FROM application_history WHERE application_id = ?", (application_id,))
    conn.execute("DELETE FROM applications WHERE id = ?", (application_id,))


def application_list(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM applications ORDER BY updated_at DESC, id DESC"))


def history_for(conn: sqlite3.Connection, application_id: int) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT * FROM application_history WHERE application_id = ? ORDER BY id DESC", (application_id,)
    ))
