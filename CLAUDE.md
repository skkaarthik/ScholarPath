# ScholarPath - implementation conventions

Single-user, local Streamlit app for finding international scholarships and
tracking applications. College semester project; code must be easy to explain.

## Layers (no shortcuts across them)
`app.py` / `scholarpath/ui/*` (Streamlit only) → `scholarpath/services.py` →
`scholarpath/repository.py` (all SQL) → `scholarpath/database.py` (connections,
transactions, migrations) → SQLite.

Collection: `collectors/<source>.py` parse HTML → `collectors/runner.py`
validates and writes `data/collected/real_scholarships.json` → `import-real`
→ service → SQLite.

- No SQL, HTTP or JSON-file reads in UI modules.
- Matching (`matching.py`) and date logic (`dates.py`) are pure; inject `today`.
- Never scrape from the UI. Real data changes only via explicit commands (`refresh`, `collect`,
  `import-real`); the app may only *import* the published, validated dataset file when its
  version changes (no network). See docs/DATA_REFRESH.md.
- Closing is decided by `dates.closes_at`/`is_closed` (source time zone; Anywhere on Earth when
  unknown). Closed records leave discovery but are never deleted.

## Data rules
- Canonical record: `models.ScholarshipRecord`; validate with `cleaning.validate_record`.
- Criteria use `{"kind": "unrestricted"|"list"|"unknown", "values": [...]}`.
  An empty list never means "unknown" or "unrestricted".
- IDs: `models.stable_id(source_name, source_key)` (sha256). Never `hash()`.
- Never invent deadlines, years, times or award cycles. A date without a year is `unknown`.
- `manual_verified_at` is only set by a human check; scraping is not verification.
- Example data is fictional and lives only in the example database.

## Database
- One SQLite file per mode (`data/db/`); `PRAGMA foreign_keys=ON` on every connection.
- Multi-step writes inside `database.transaction()`.
- Schema changes = append a new entry to `database.MIGRATIONS`. Never edit or drop old ones.
- Imports upsert in place; scholarships referenced by user data are never deleted.

## Commands
```
python -m pytest                       # all tests (offline, temp DBs, fixed date 2026-11-12)
python -m scholarpath init-examples    # fictional data -> example DB
python -m scholarpath collect --from-snapshots | --live
python -m scholarpath import-real
streamlit run app.py
```

## Git
Work on a feature branch; stage explicit files; never commit `data/db/`,
`data/examples/build/`, backups or personal notes.
