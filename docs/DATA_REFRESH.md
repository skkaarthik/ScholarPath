# Automatic data refresh

How ScholarPath keeps its real-source dataset current, what closes a scholarship, how a
refresh reaches the website, and what to do when something goes wrong.

## In one paragraph

A GitHub Actions workflow runs every day. It calls `python -m scholarpath refresh`, which does
real work only when **15 days have elapsed since the last successful refresh** (or when forced).
It collects every enabled source live, validates the whole collection, and only if everything
passes publishes `data/collected/real_scholarships.json` atomically and records the result in
`data/refresh/state.json`. The workflow commits those two files when they changed. The app
imports a newly published version the next time it runs. Closed scholarships leave Find
Scholarships the moment their deadline passes, even between refreshes.

## Sources

| Source | Status | Checked |
|---|---|---|
| Commonwealth Scholarship Commission UK (`cscuk`) | **Enabled** | robots.txt allows all (19 Nov 2026). Parser run on today's live pages read in a browser: 3/3 records, exact closing time and "now closed" read correctly. |
| British Council GREAT Scholarships, India (`great_india`) | **Enabled** | robots.txt blocks only two thank-you pages (19 Nov 2026). Parser run on today's live pages: 13/13 records. |
| DAAD scholarship database (`daad`) | **Disabled** | www2.daad.de has no robots.txt (no restrictions). Not yet checked: DAAD's terms of use (www.daad.de did not load on 19 Nov 2026), and a live run from Python. DAAD pages publish no deadlines, so every DAAD record would show "Date not confirmed". |
| Erasmus Mundus | Not added | Decision: leave out for now (catalogue gives no deadlines). |

"Parser run on live pages" means the HTML was read in a browser and parsed in a test
environment. **No live request from Python (or from GitHub's servers) has been made yet**; the
first workflow run is that test.

## When a scholarship closes (`scholarpath/dates.py`)

1. The official page says applications are closed (`closed_by_source`): closed now.
2. An exact time with a zone is published ("16:00 GMT on 8 December 2026", `deadline_at`):
   closed from that instant.
3. A date only: open through the **end of that day in the source's time zone**
   (`deadline_timezone`; Europe/London for CSC and GREAT; Asia/Kolkata for fictional examples).
4. A date with no known zone: open through the end of that day **Anywhere on Earth** (UTC−12),
   so nothing is hidden early.
5. Rolling, missing or ambiguous deadlines are never treated as closed; they are labelled
   "Rolling" or "Date not confirmed". A date without a year is recorded as unknown.

Closed scholarships are hidden from Find, its CSV export, Insights, Check my fit, the
assistant's suggestions and the "open" counts. They are **never deleted**: saved ones stay in
Saved under "Closed", tracked ones stay in Applications with their history, and their Review
page still opens.

## Annual cycles

A record keeps its ID while it stays in the same award cycle, or while nobody saved or tracked
it. When a new cycle (e.g. 2027/28 after 2026/27) arrives for a record the user saved or applied
to, the new cycle becomes a separate record (`source_key#cycle`), so the old application keeps
its original cycle and deadline. A scholarship that disappears from a source page is kept as it
was; absence is not proof that it expired.

## Validation (`refresh.Thresholds`)

A refresh publishes nothing if any of these happen:

| Check | Limit |
|---|---|
| Pages that could not be read (any enabled source) | 0 |
| Records rejected by validation (malformed) | 0 |
| Duplicate stable IDs | 0 |
| Records from an enabled source | at least 1 |
| Drop in a source's records vs. published (once it has 4+) | at most 25 % |
| Deadline year | from 3 years ago to 5 years ahead |

## Activating the schedule (you need to do this once)

GitHub only runs scheduled workflows from the repository's **default branch** (`main`).

1. Add the workflow file. The remote tools are not allowed to write `.github/workflows/`, so
   copy `refresh-data.yml` (sent with this work) into the repository:
   ```
   mkdir -p .github/workflows
   cp ~/Downloads/refresh-data.yml .github/workflows/refresh-data.yml
   git add .github/workflows/refresh-data.yml
   git commit -m "Add the daily GitHub Actions refresh workflow"
   ```
2. Push `feature/scholarpath-v1`, open the pull request into `main` and merge it.
3. On GitHub: **Settings → Actions → General → Workflow permissions**: choose "Read and write
   permissions" (the workflow commits the refreshed data). If `main` has branch protection that
   blocks direct pushes, allow GitHub Actions to push, or the commit step will fail.
4. **Actions tab → Refresh scholarship data → Run workflow** with "dry run" ticked. This is the
   first real live test of the sources from GitHub's servers. Then run it once with "force".

Scheduling is best-effort: GitHub may start scheduled runs late (busy times, especially the top
of the hour) and may disable schedules in repositories without recent activity. The 15-day rule
is measured from the last successful refresh, so a late or skipped day only delays the refresh.

## Manual refresh

- On GitHub: Actions → Refresh scholarship data → Run workflow (tick **force** to refresh before
  it is due; tick **dry run** to check sources without changing anything).
- On your computer: `python -m scholarpath refresh --force`, or `--dry-run` to only check.
  Then commit `data/collected/real_scholarships.json` and `data/refresh/state.json` if they changed.

The app has no Refresh button on purpose: collection never runs from the website.

## When a refresh fails

Nothing is lost: the previous dataset stays published and in use, `last_success_at` does not
move, and the next daily run tries again. Data & sources shows "The latest refresh attempt
failed" with the reasons; the GitHub run's summary lists them too.

- **A page could not be read / timed out**: often temporary. Wait for the next daily run, or
  run the workflow manually. If it keeps failing, open the page in a browser to see whether it
  moved (the parser's URL list is at the top of each collector).
- **Layout changed (StructureError) or malformed records**: repair the collector (below).
- **Large drop in records**: check the source page. If the drop is real (a programme ended),
  run `python -m scholarpath refresh --force` locally after confirming, or temporarily raise
  `max_drop_fraction` in `scholarpath/refresh.py` with a comment explaining why.
- **Stuck lock** ("Another refresh is running"): a lock older than 3 hours is ignored
  automatically; locally you can delete `data/refresh/refresh.lock`.

## Adding or repairing a collector

1. Save the current page(s) in a browser into `data/snapshots/<source>/` with a `manifest.json`
   (see the existing ones), or as a small fixture in `tests/fixtures/`.
2. Write or fix `scholarpath/collectors/<source>.py`: `SOURCE_ID`, `SOURCE_NAME`,
   `ALLOWED_HOSTS`, `TIMEZONE`, `ENABLED`, and `collect(fetcher, collected_at)` yielding
   `("record", dict)` or `("failed", {url, error, status})`. Never guess a deadline, year,
   amount or eligibility; use `unknown` and a `manual_review` requirement instead.
3. Register it in `SOURCES` in `scholarpath/collectors/runner.py` with `ENABLED = False`.
4. Add fixture tests in `tests/test_collectors.py` (including pagination and a broken layout).
5. Check robots.txt and the site's terms; then `python -m scholarpath refresh --dry-run --sources <id>`.
6. Only then set `ENABLED = True`.

Enabling DAAD: confirm DAAD's terms allow automated collection, run
`python -m scholarpath refresh --dry-run --sources daad` (expect about 147 records), then set
`ENABLED = True` in `scholarpath/collectors/daad.py`. Note that all DAAD records will show
"Date not confirmed".

## How a refresh reaches the website

- **On your computer**: the app checks the published file's version on every run (cached by
  file modification time) and imports a new version once, in one transaction, then clears all
  cached reads so every open browser tab sees it on its next rerun. Saved items, applications
  and history are separate tables and are never touched by an import.
- **Hosting**: none is configured yet. On Streamlit Community Cloud, the app follows the
  repository: a commit to `main` by the workflow is picked up automatically, and the same
  version check imports it.

### Persistence warning for Streamlit Community Cloud

Community Cloud does not guarantee that local files survive restarts or redeploys. The real
scholarship data is safe (it is rebuilt from the committed dataset), but **saved items,
applications and their history live in SQLite and can be lost** there. Before relying on the
hosted app for those, move user data to an external database (for example a hosted Postgres),
which needs an account, a connection string in the app's Secrets, and a storage adapter in
`database.py`/`repository.py`. That work is not done. Until then, treat the hosted version as a
demo, and the example dataset must be rebuilt there with `python -m scholarpath init-examples`
or left empty.
