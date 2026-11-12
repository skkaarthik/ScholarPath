# Implementation status

Last updated: 2026-11-12. Branch: `feature/scholarpath-v1`.

## Phase 1 - Data collection and quality: DONE
- Canonical record + controlled vocabularies (`models.py`), validation (`cleaning.py`).
- Fictional example template (15 records) + generator anchored to a date (`examples.py`).
- Collectors: CSC UK (3 records) and British Council GREAT Scholarships for India (13 records),
  live fetcher (robots, allow-list, timeouts, delay, bounded retries) and snapshot fetcher.
- Safe JSON writes: empty run = error, partial run = separate file, merge by stable ID.
- Checks: `pytest tests/test_cleaning.py tests/test_collectors.py` - passing.

## Phase 2 - Storage and application services: DONE
- `database.py`: per-operation connections, foreign keys, busy timeout, explicit
  transactions, ordered migrations (v1 core, v2 history + import log) tracked by `user_version`.
- `repository.py`: all parameterized SQL; normalized multivalued tables; combined filters.
- `services.py`: validated idempotent imports (insert/update/unchanged/rejected), mode guard,
  search, details, shortlist, tracker with status/date rules and history, dashboard, matching.
- `matching.py`: deterministic per-rule explanations; `exports.py`: CSV with formula protection.
- CLI: `python -m scholarpath init-examples | collect | import-real | status | backup | migrate`.
- Checks: full `pytest` suite - passing (persistence, rollback, migration, isolation,
  filters, boundaries, matching, CSV, tracker rules).

## Phase 3 - UI and complete workflow: DONE
- `app.py` + `scholarpath/ui/`: Overview, Explore (filters, results, save, details, filtered CSV),
  Profile matching (submitted form, validation, per-rule tables, separate deadline status),
  Scholarship details (requirements, original wording, manual review, links, provenance,
  save/track), My applications (deadline groups, shortlist, tracker form + history), Insights
  (3 single-series charts, stated scope, table view).
- Docs: README, DATA_DICTIONARY, SOURCES, ARCHITECTURE, DEMO_GUIDE, VIVA_PREPARATION,
  CONTRIBUTIONS (template), AI_ASSISTANCE (template).

## Verification performed (2026-11-12, Linux, Python 3.11.18, Streamlit 1.67.0)
- `python -m pytest`: 121 passed (includes 9 Streamlit AppTest UI checks).
- Clean-copy smoke test: deleted DBs → `init-examples` (15 inserted) → `import-real`
  (16 inserted) → `streamlit run app.py` → `/_stcore/health` returned `ok`.
- Headless Chrome (Playwright) against the running server: Overview → Explore → Save →
  View details → Start tracking → My applications → Insights → Profile matching; afterwards
  `python -m scholarpath status` showed saved=1, tracked=1 (writes reached SQLite).
  Screenshots were reviewed; chart label truncation and low-contrast icons were fixed.
- Repeat imports: 0 inserted / 15 and 16 unchanged.
- Demo-guide profiles checked against `ScholarPathService.match` output.
- Not performed: Windows/macOS runs, live HTTP collection, a browser test on the user's machine.

## Blockers and limitations
- **Live HTTP collection not verified.** The build environment's network allow-list
  blocked the scholarship sites. Pages were captured with a browser on 2026-11-12,
  saved as trimmed snapshots in `data/snapshots/`, and parsed by the same parsers.
  `python -m scholarpath collect --live` is implemented and unit-tested with fake
  HTTP responses only.
- Snapshot `captured_at` times are approximate (within about 15 minutes).
- No record has been manually verified (`manual_verified_at` is empty for all).
- No GitHub remote exists for this repository; pushes not possible (see final report).

## Deferred (optional) work
Not started, and not shown in the UI: compare up to three scholarships, application document
checklists, calendar (.ics) export. The required workflow was prioritised.
