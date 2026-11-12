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

## Phase 3 - UI and complete workflow: see below

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
- Compare up to three scholarships, document checklists, calendar export.
