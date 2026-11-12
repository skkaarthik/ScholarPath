# Architecture

## Layers

```mermaid
flowchart LR
    UI["Streamlit UI<br/>app.py + scholarpath/ui/*"] --> SVC["Application services<br/>services.py"]
    SVC --> MATCH["Matching & dates<br/>matching.py, dates.py (pure)"]
    SVC --> REPO["Repository<br/>repository.py (all SQL)"]
    REPO --> DB["database.py<br/>connections, transactions, migrations"]
    DB --> SQLITE[("SQLite<br/>one file per dataset mode")]
    SVC --> EXP["exports.py (CSV)"]
```

| Module | Responsibility | Not allowed |
|---|---|---|
| `ui/*.py` | Navigation, forms, display, temporary selections in `st.session_state` | SQL, HTTP, reading JSON files, storing business data in session state |
| `services.py` | Operations used by UI and CLI; validation; transaction boundaries | Streamlit calls |
| `repository.py` | Parameterized SQL only | Business rules |
| `database.py` | Connections, foreign keys, busy timeout, transactions, migrations | Data-specific logic |
| `matching.py`, `dates.py` | Pure rules with injected `today` | I/O |
| `collectors/*` | Fetching (base.py) and source-specific parsing | Writing to the database |

## Collection and import pipeline

```mermaid
flowchart LR
    A["Fetch<br/>LiveFetcher (HTTP) or SnapshotFetcher (saved HTML)"] --> B["Parse<br/>cscuk.py / great.py"]
    B --> C["Validate & normalise<br/>cleaning.validate_record"]
    C --> D["JSON<br/>data/collected/real_scholarships.json<br/>(merged by stable ID)"]
    D --> E["Import service<br/>validate → one transaction"]
    E --> F[("scholarpath_real.sqlite3")]
    T["Example template + anchor date<br/>examples.py"] --> E2["Import service"] --> G[("scholarpath_example.sqlite3")]
```

Collection is only ever triggered by the CLI (`python -m scholarpath collect ...`).
The Streamlit app never fetches web pages.

## Database

```mermaid
erDiagram
    scholarships ||--o{ scholarship_host_countries : "hosted in"
    scholarships ||--o{ scholarship_degrees : "for degree"
    scholarships ||--o{ scholarship_subjects : "for subject"
    scholarships ||--o{ scholarship_nationalities : "include / exclude"
    scholarships ||--o{ scholarship_requirements : "has"
    scholarships ||--o| shortlist : "saved as"
    scholarships ||--o| applications : "tracked as"
    applications ||--o{ application_history : "changes"
    scholarships {
        text id PK
        text name
        text provider
        text degree_kind
        text subject_kind
        text nationality_kind
        text exclusion_kind
        text deadline_kind
        text deadline_date
        text source_url
        text content_hash
    }
    applications {
        int id PK
        text scholarship_id FK
        text status
        text target_date
        text submitted_date
        text outcome
    }
```

Also: `meta` (dataset mode, example anchor date, last import), `import_runs`, `schema_migrations`.

Key decisions:

- **Normalized multivalued fields** (countries, degrees, subjects, nationalities) so filters are
  indexed `EXISTS` sub-queries, not string matching.
- **`*_kind` columns** keep "unrestricted", "list" and "unknown" distinct.
- **`ON DELETE RESTRICT`** from `shortlist` and `applications` to `scholarships`: a scholarship
  that the user saved or tracked cannot be deleted. Child rows of a scholarship use `CASCADE`
  because only the scholarship owns them.
- **CHECK constraints** enforce "dated ⇔ has date" and "score ⇔ scale" at the database level too.
- **Separate database per mode** (`config.db_path(mode)`); a `meta.dataset_mode` row stops a file
  being opened in the wrong mode. Each mode only accepts records with the matching `dataset_origin`.

## Transactions and imports

- `database.connect()` opens a connection per operation, enables `PRAGMA foreign_keys`, sets a busy
  timeout and always closes it. There is no shared global connection.
- `database.transaction()` runs `BEGIN IMMEDIATE` … `COMMIT`, or `ROLLBACK` on any exception.
  A lock that outlasts the timeout raises `DatabaseBusyError` with a readable message.
- **Import policy:** every record is validated before anything is written. Invalid records are
  rejected individually with reasons. All valid records are then written in **one** transaction;
  any database error rolls back the whole batch. Zero valid records → refused, nothing changes.
- Records are upserted by stable ID: insert, `UPDATE` in place (if the content hash changed) or
  "unchanged". Rows are never deleted and re-inserted, so saved items and tracker entries keep
  pointing at them. Each run is logged in `import_runs`.

## Migrations

`database.MIGRATIONS` is an ordered list `(version, description, sql)`. `migrate()` applies each
pending version in its own transaction, records it in `schema_migrations` and sets
`PRAGMA user_version`. Migrations only add structure (v2 added `application_history`, with a
backfill row per existing application, and `import_runs`). A test builds a v1 database with user
data, migrates it and checks that nothing was lost.

## Caching (Streamlit)

Read-heavy calls (search, overview, filter options) use `st.cache_data`, keyed by the
**database path** and today's date, so the two modes can never share cached results. After every
successful write the UI calls `st.cache_data.clear()`. Switching the dataset clears temporary
selections (selected scholarship, match results, filters).

## Matching

`matching.evaluate(profile, record)` runs fixed rules: nationality, exclusions, degree, subject,
academic score (only if the record has a numeric threshold) and one "manual review" rule per
unresolved requirement. Each returns *student value, recorded requirement, status, reason*.
Overall: any failed → "Does not match recorded requirements"; else any unknown →
"Needs manual verification"; else "Matches recorded requirements". Preferred destination is
applied as a host-country filter before matching, and deadline status is shown separately.

## Dates

`Clock` provides "today" in `Asia/Kolkata` (configurable with `SCHOLARPATH_TIMEZONE`;
`SCHOLARPATH_TODAY` pins it for demos/tests). Status is computed at read time in SQL for
filters/sorting (`repository.STATUS_SQL`) and in Python (`dates.deadline_status`) for display;
tests check both agree on the boundaries.
