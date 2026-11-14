# Viva preparation

Short answers grounded in the code as implemented. File names point to where to show each answer.

## Overview

**What does the project do?** Find scholarships, explain recorded requirements, save them and
track applications and deadlines - a single-user local Streamlit app backed by SQLite.

**Why two datasets?** Fictional examples (`data/examples/…template.json`) make every rule and
edge case demonstrable offline; real records (`data/collected/real_scholarships.json`) show the
pipeline on official pages. Separate database files keep counts, saved items and the tracker
from mixing (`config.db_path`, `services.ensure_schema` mode guard, `dataset_origin` check).

## Scraping and data quality

- **Which sources and why?** CSC UK and British Council GREAT Scholarships: official bodies,
  robots.txt allows the pages, stable server-rendered HTML. (`docs/SOURCES.md`)
- **How is fetching separated from parsing?** `collectors/base.py` fetches (`LiveFetcher`,
  `SnapshotFetcher`); `cscuk.py` and `great.py` only turn HTML into dicts. Parsers are tested on
  local fixtures, so tests never need the internet.
- **Politeness?** robots.txt check, host allow-list, 20 s timeout, 2 s delay, at most 3 attempts with
  back-off for transient errors (429/5xx/connection errors), a descriptive User-Agent, no logins.
- **What if the layout changes?** The parser raises `StructureError` naming the missing section;
  the page is reported as *failed*. Zero accepted records → error, nothing written. Failed pages →
  results go to a separate partial file. Previous records are merged, never dropped.
- **Why snapshots?** The development environment could not reach the sites, so pages were captured
  in a browser and parsed offline by the same code. Live fetching is implemented but unverified.
- **Why is the CSC Master's deadline "unknown"?** The page says "Tuesday 20 October" with no year.
  We never infer years or times (`htmltools.parse_full_date` requires a year).
- **"Verified"?** Three separate facts: fetched (`source_fetched_at`), parsed/validated (in the
  dataset), manually checked (`manual_verified_at`, empty for all records).

## Data model and validation

- **Unknown vs unrestricted?** `{"kind": "unrestricted"|"list"|"unknown", "values": []}` - an
  empty list never carries meaning (`cleaning._restriction`).
- **Stable IDs?** `sha256(source_name|source_key)`; editing a description or deadline doesn't
  change the ID, so updates hit the same row. Python `hash()` is randomised per process, so it
  would break identity between runs.
- **What does validation reject?** Dated deadline without date, values on unknown/unrestricted,
  non-finite or out-of-range scores, scores without a scale, non-http URLs, naive timestamps,
  unknown vocabulary labels, a country both allowed and excluded, tampered IDs.

## SQL and transactions

- **Schema?** `scholarships` plus child tables for multivalued fields; `shortlist`, `applications`,
  `application_history`, `import_runs`, `meta`. (`database.MIGRATIONS`)
- **Why child tables instead of comma-separated text?** Correct OR/AND filters with indexed
  `EXISTS` sub-queries; no partial-string false matches.
- **SQL injection?** Every statement is parameterized (`repository.py`); `IN (...)` lists are
  built from named placeholders; LIKE wildcards in user text are escaped.
- **Transactions?** `database.transaction()` = `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK`.
  Imports, saves, tracker edits (application row + history row) are each one transaction.
  Tests force a failure mid-way and check nothing changed (`test_failed_batch_rolls_back_completely`,
  `test_multi_step_tracker_write_rolls_back_on_error`).
- **Idempotent import?** Content hash per record → insert / update in place / unchanged. Repeat
  import = 0 inserted, 15 unchanged.
- **Protecting user data?** `ON DELETE RESTRICT` from shortlist/applications; imports never delete;
  removing from the shortlist leaves the application and its history.
- **Migrations?** Ordered list, `PRAGMA user_version`, each in a transaction, additive only;
  v2 backfills history rows. Test: v1 DB with data → migrate → data intact.
- **Foreign keys?** SQLite disables them by default, so `connect()` enables them on every connection.

## Matching

- **How is eligibility decided?** Deterministic rules; each returns student value, requirement,
  status and reason (`matching.py`). Overall verdict: any failed → does not match; any unknown →
  needs manual verification; else matches.
- **Why not convert GPA to percentage?** Conversions differ by institution and country; two
  4-point scales are not equivalent. Different scale → *unknown* with an explanation.
- **Missing answer?** That rule is *unknown*, never satisfied; it is flagged `missing_input` so the
  UI can say which field to add.
- **Why three result groups?** Real sources contain clauses no program can check (residence,
  language). Showing each as a warning buried every result in caution. The verdict is unchanged,
  but results whose automatic checks all pass are grouped as *Good fits* with a checklist, separate
  from results where information is genuinely missing (`MatchResult.group`).
- **Language tests, age, residence?** Manual-review items shown as *unknown* rules.
- **Why no fuzzy matching or AI?** Eligibility errors are costly; exact, explainable rules are
  auditable and testable.
- **Preferred destination?** A host-country filter applied before matching, not a rule.

## Dates

- **Timezone?** `Asia/Kolkata` by default. A date-only deadline is open through that calendar day.
  The UI states this basis and links to the official page for exact closing times.
- **Testable?** `Clock` is injected; tests pin 2026-11-12 and check 0/7/8/30/31/-1 day boundaries.

## UI and caching

- **How does the UI reach the database?** Only through `ScholarPathService`; no SQL in `ui/`.
- **Caching?** `st.cache_data` on reads, keyed by database path and date; cleared after writes;
  temporary selections cleared when switching datasets.
- **Unsafe content?** Source text is markdown-escaped; HTML is never rendered; links are shown
  only if they are http/https.
- **CSV injection?** Cells starting (after whitespace) with `= + - @`, or with tab/CR, get a
  leading apostrophe (`exports.safe_cell`).

## Testing

- `pytest` (133 tests, ~5 s): validation, parsers on fixtures and snapshots, safe writes, polite
  fetcher with fake HTTP, persistence across reopen, idempotency, rollback, migration, isolation,
  filters, sorting, boundaries, matching, CSV content and escaping, tracker rules, and Streamlit
  `AppTest` UI flows that check the database afterwards.
- A headless-browser smoke test (Discover → Save → Details → Track → Saved & applications → Insights →
  Matching) was also run during development (see `docs/IMPLEMENTATION_STATUS.md`).

## Honest limitations

Live scraping unverified; 16 real UK-hosted records; most real deadlines already passed; no
manual verification yet; single user only; subject categories are coarse.
