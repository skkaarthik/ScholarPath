# Upgrade status

## v2: internships beside scholarships (2026-11-28), branch `scholarpath-v2`

Base: `feature/scholarpath-v1` at `9eccf26` (checked on the Mac: local branch = origin, clean tree;
the 17 Nov handoff hashes `66ac267`/`312034c` survive only on the backup branches after the history
rewrite; the polish pass is `79389c5`). `main` and `feature/scholarpath-v1` are untouched.

### What changed
1. **First screen** (`ui/choose.py`, the only new screen): *Find internships* or *Find scholarships*;
   the choice opens that Find page at once and is kept for the session and in the address
   (`?for=internships`), so a reload does not ask again.
2. **Switching** (`app.py`, `common.switch_kind`): a labelled *Looking for: Internships | Scholarships*
   switch under the menu on every width, the same switch in the More menu and the sidebar. The four
   menu entries (and the phone bottom bar, <= 40rem) are unchanged. Each type keeps its own search,
   filters, sort, page and Check my fit answers (separate widget keys); its open selections (record on
   Review, unfinished confirmation, assistant conversation, removal undo) are put aside and restored.
3. **Data** (migration v4, additive): `internships` with cities, states, criteria and other listings,
   and its own `internship_saved`, `internship_applications`, `internship_application_history`.
   Scholarship tables are not touched. Same database file per dataset (Example/Real).
4. **Services**: `InternshipService(ScholarPathService)` inherits saving, Mark as applied (an
   existing Applied entry is still returned before validation), updates, removal and history; the
   repository functions take the table set. UI -> services.py -> repository.py -> database.py kept.
5. **Shared screens**: Find, Review, Saved, Applications, Check my fit, Insights, Data & sources and
   the assistant serve both types from the same templates and components. Role and employer fill the
   title and provider slots; stipend, duration, work arrangement, place, degree, year of study,
   experience and deadline fill the fact slots. Missing facts are written out ("Stipend not stated",
   "Duration not stated", "Not listed in a structured form", "No deadline published").
6. **India locations** (`locations.py`): canonical cities and states/UTs, aliases (Bangalore,
   Madras, Bombay, Gurgaon/Noida -> Delhi NCR, Cochin ...), Chennai then Bengaluru first in every list.
   Quick choices Chennai, Bengaluru, All India, Remote; filters for city, state/UT, arrangement,
   discipline, stipend, deadline.
7. **Live finder** (`collectors/internship_*.py`, `python -m scholarpath find-internships [--import]`):
   Greenhouse and Lever job-board APIs, one adapter per platform, each employer board its own source;
   polite LiveFetcher (robots.txt, allow-listed hosts, timeouts, bounded retries); a failed board
   keeps its last records and last success; duplicates merge by stable ID (employer, role, place)
   with the other listings kept as links; facts only (no description text, as for DAAD); atomic
   publish; nothing written when no board answers. The app imports a new version by itself; the
   daily GitHub workflow now also runs the finder (once the workflow is activated).

### Feature-parity checklist (v1 inventory -> internship equivalent)
Every item was checked in both modes by AppTest and/or the browser run below.

| v1 scholarship feature or state | Internship equivalent | Evidence |
|---|---|---|
| Menu: Find / Saved / Applications / More (Check my fit, Insights, Data & sources); highlight; Review highlights its origin; phone bottom bar with 4 entries | Same entries; "Find Internships" label; switch added under the menu and inside More | browser (menu order, highlight, 4 columns at 390/360), `test_v2_ui` |
| Dataset switch (sidebar and Data & sources), isolation Example/Real | Same; clears both types' filters | `test_a_dataset_switch_clears_both_types_filters`, `test_example_and_real_internships_stay_apart` |
| Empty dataset set-up card; create example data in the app | Same card; example data creates both types; real: `find-internships --import` | `test_v2_ui`, v1 tests |
| Find: search, filters behind one control with count, deadline pills, summary line, clear, sort, page reset, pager, "Showing x to y", progress note (Saved / In Applications), table view, CSV of all filtered rows, no-results card | All of these; plus quick location choice and stipend sort | `test_internship_filters_table_csv_and_empty_state`, browser |
| Review: back label by origin, Save / Remove from Saved, four facts, Apply states (not applied, confirm with date, future date refused, Yes / Not yet, Application added, View application), closed info, missing/none selected cards, eligibility, manual items, original wording, deadline, funding, source and freshness | Same; facts: Who can apply (degree, year, discipline), Where (place, arrangement), Stipend (amount, duration); "Facts recorded from the posting"; "Also listed on" links; "Last checked" | browser (double click -> one application), `test_find_review_save_unsave_apply_and_track_a_chennai_internship` |
| Saved: grouped by deadline, Review, Remove with Undo, empty state | Same | browser, `test_v2_ui` |
| Applications: counts, next step per status, Update status (status, date, outcome, target, notes, what changed), history table, Remove with confirmation, messages inside the entry | Same (employer wording) | `test_application_status_updates_keep_history_for_internships`, browser |
| Check my fit: optional form, validation, three result groups, rule table, manual checklist, how it works | Degree, year of study (+ final-year tick), discipline, preferred place | `test_internship_fit_never_counts_unknown_as_met`, `test_check_my_fit_insights_and_data_pages_for_internships` |
| Insights: scope toggle, charts with numbers, tables | By city (Chennai, Bengaluru first), stipend, arrangement, deadline month | same test, browser |
| Data & sources: metrics, refresh status, sources table, every record, trust, technical commands | Live finder table per board (read/failed, postings, internships, last success, problem), coverage metrics | `test_check_my_fit_insights_and_data_pages_for_internships`, live check |
| Ask ScholarPath assistant (demo and live), starters, context, references | Internship records, prompt, starters, demo answers | `test_the_assistant_answers_from_internship_records_in_demo_mode`, `test_the_assistant_talks_about_internships` |
| Deadline vocabulary (`dates.STATUS_LABELS`, `common.deadline_state`), closing rules | Same functions (same deadline fields) | shared code |
| Loading (spinners), storage-error card, inline feedback, no toasts | Same code paths | shared code |

Differences are limited to content and the controls the type needs: the quick location choice,
internship filters and sort, internship facts, and the type switch.

### Tests (cloud Linux container, Python 3.12.3, Streamlit 1.67.0)
- `python -m pytest`: **297 passed**. The v1 base itself has **238** tests (the 158 in the 17 Nov
  handoff predates the data-refresh work); all 238 still pass. Two v1 tests changed only to start as a
  student who already chose scholarships. **59 new** in `tests/test_v2_internships.py` and
  `tests/test_v2_ui.py`: mode selection and switching, kept state, data isolation (types and
  datasets), v1 data preservation, internship filters, adapters, cross-source dedup, partial
  failure, stable IDs across refreshes, closing postings a board drops, CSV safety, assistant.
- **Migration evidence**: `test_a_v1_database_upgrades_without_touching_scholarship_data` builds a
  schema-v3 (v1) database with a saved scholarship and an application with two history rows,
  migrates to v4, and compares every row of `scholarships`, `shortlist`, `applications`,
  `application_history` before and after (identical); re-running the migration changes nothing.

### Browser checks (Playwright + headless Chrome, disposable databases; `docs/evidence/browser_checks.py`)
**516 of 516 passed** (102 per desktop/tablet width, 105 per phone width) at 1440, 1280, 768, 390
and 360 px: first-visit choice; Find internships; menu entries and order; bottom bar on phones with
the switch outside it; Chennai quick choice; Review with four facts and menu highlight; Save (SQLite:
one internship save, scholarship saves unchanged); Saved -> Remove -> Undo -> Remove; Find kept the
search; Mark as applied writes nothing; double click on Yes -> exactly one application and one
history row; View application; Check my fit, Insights, Data & sources; switch to scholarships ->
existing scholarship save, application and history shown; switch back keeps the internship search;
reload keeps the type; no horizontal overflow on any page. **Side-by-side comparison**: computed
styles (font, size, weight, colour, background, border, radius) of headings, menu, switch, cards,
buttons, inputs and the four-fact panel are identical between the two types on Find, Review, Saved,
Applications, Check my fit, Insights and Data & sources, and the menu and heading have the same
position and width. Screenshots were also compared by eye (chooser cards were made equal height).

### Live sources (actual run, 28 Nov 2026 ~18:55 IST)
Neither the cloud container nor the Mac's Linux VM can reach the job boards (egress allowlists), so
the 20 board APIs were fetched once through the built-in browser on Kaarthik's Mac. The captured
facts (`docs/evidence/live_capture_2026-11-28.json`) were run through the finder's adapters,
validation, dedup, the database and the app (`docs/evidence/live_capture_check.py --app`; output in
`live_capture_report.txt`).

| Result | Boards |
|---|---|
| Read (19) | FourKites, Toast, Episode Six, Zuora, DevRev, CommerceIQ, Enterpret, Karya, HackerRank (Greenhouse); Portcast, ShopBack, Paytm, Paytm Payments Services, Dun & Bradstreet, FamPay, Fi, Zeta, Sprinto, Stable Money (Lever) |
| Failed (1) | Interview Kickstart (Greenhouse, HTTP 404: board removed; dropped from the list afterwards) |
| Internships in India found | Paytm 9, Paytm Payments 6, FamPay 3, Enterpret 2, Karya 2, HackerRank 2, Dun & Bradstreet 2, Sprinto 2, Stable Money 2, FourKites 1, Episode Six 1, Portcast 1, Zeta 1; the rest 0 today |

**34 unique internships: Chennai 2, Bengaluru 17, rest of India 16 (Delhi NCR 11, Mumbai 2, Pune 1,
city not stated 1, plus Portcast's remote role that lists six cities including Chennai and
Bengaluru), remote 3.** An internship in several places counts in each. Find Internships showed the same counts for Chennai, Bengaluru,
Remote and All India. No duplicates across boards occurred in this run (dedup is covered by tests).

### Gaps and unverified checks (release criteria not yet met are marked)
- **Chennai coverage is thin (2 of 34).** Chennai employers checked: Freshworks (SmartRecruiters:
  robots.txt disallows its API), Zoho (own site, no public API), AICTE Internship Portal (listings
  load from `/api/`, disallowed by robots.txt), Internshala (robots.txt disallows search and detail
  pages), National Career Service (account needed). More Chennai boards can be added to
  `BOARDS` in `collectors/internship_sources.py` as they are found.
- **The finder's own HTTP client has not run against the live boards** (both available machines are
  blocked). Run on the Mac: `python -m scholarpath find-internships --dry-run`, then `--import`.
- Stipend, duration, degree and year extraction was tested on fixtures shaped like real answers, not
  on the live capture (descriptions were not captured).
- Not run on the Mac: `python -m pytest`, a click-through, and the browser checks.
- Known v1 limits still apply (no screen-reader test, small Streamlit sub-controls, reload resets
  Review). Discipline is ScholarPath's reading of the role title and team; most job boards publish no
  deadline, so most internships show "No deadline published".

## Polish pass: navigation, design system, repaired interactions (2026-11-17) - done

### What changed and why
1. **Menu** (`app.py`, `ui/style.py`, `common.menu_item`): one menu drawn from `st.page_link` and
   `st.popover` inside containers we key, so the highlighted entry is reliable on every page and
   rerun (before: "Find" never highlighted on phones; nothing highlighted on Review or More pages).
   Review highlights the page it came from. On phones the four entries form a bottom bar, which
   replaces the duplicated `mobile_nav` row and the sidebar-arrow route to More pages.
2. **Design system** (`.streamlit/config.toml`, `style.py`, `common.py`, `docs/DESIGN_SYSTEM.md`):
   semantic badge/message colours, input borders at 3:1+, white cards on paper with a hairline,
   one date format, one deadline vocabulary, 44 px touch targets, one focus ring, reduced motion.
3. **Repaired or clarified interactions**
   - Deadlines: two Commonwealth records showed "Deadline not published" although the provider
     published wording without a year; now "Date not confirmed" with the provider's wording.
     Closed / rolling / no deadline published are told apart everywhere (cards, table, CSV).
   - Clearing filters and switching datasets now also clear the browser's copy of each widget
     (before, the old search came back on the next click).
   - Sorting is visible next to the result count; any search, filter or sort change returns to page 1.
   - Apply: a repeated "Yes, add to Applications" returns the existing entry instead of an error;
     a future submission date is refused next to the field and the button is disabled (before, the
     browser silently kept the previous date). Leaving Review drops a half-finished confirmation.
   - Missing records explain themselves; closed scholarships say so and can still be recorded.
   - The More menu is drawn fresh after a choice (before, an open menu swallowed the next click).
   - Saved: "Remove" with Undo; Applications: next step per status, "Nothing to save" is info,
     not an error. Toasts removed: on phones they covered buttons and the menu bar.
   - Check my fit: "Another country" without a name is refused; the limits are explained.
   - Data & sources: dataset switch on the page (phones), per-source read dates, every record's
     source link, honest wording on verification and live collection. App icon no longer fetched
     from the internet.

### Evidence (cloud Linux container, Python 3.12.3, Streamlit 1.67.0, headless Chrome; not the Mac)
- `python -m pytest`: **158 passed** (was 136; 22 new UI regression tests for the menu highlight,
  Review context and Back, state kept across Review, page reset, filter clearing, CSV scope,
  deadline states, mark-as-applied without confirming, duplicate confirmation, future dates,
  save/unsave persistence, undo, fit validation, Insights counts against SQL, dataset isolation).
- Browser journeys on disposable databases (`init-examples`, `import-real` into a temp folder),
  checking SQLite after each write: **57 checks at 1440, 1280, 768, 390 and 360 px, all passing** -
  search → filter (Open or Rolling) → sort → page 2 → Review → Back (filters, sort, page kept);
  CSV = every filtered row (not just the page); table view; empty results and reset; save →
  Saved → reopen → remove → undo; provider link (stored URL, new tab) creates nothing; Mark as
  applied alone creates nothing; Not yet cancels; future date refused; double click on Yes →
  exactly one application and one history row, scholarship not saved; reload adds nothing; View
  application opens that entry; Result received without outcome refused; status saved and history
  in order after reload; fit validation and results; Insights; Example/Real isolation both ways.
- Menu checks: **34 at 1440/1280/768 px, 32 at 390/360 px, all passing** (order, 44 px targets,
  colours, highlight on every page and on Review, More menu inside the screen and closing, Back,
  Tab order, visible focus ring, Enter and Escape, hover).
- No page-level horizontal overflow on any page at any of the five widths.

### Limits
- Not run on the Mac; please run `python -m pytest` and click through once there.
- No screen-reader session; accessibility was checked with keyboard, contrast arithmetic and
  DOM inspection only.
- Streamlit's own small sub-controls (number-input steppers, "?" help icons, chart menus, the
  clear icon in multiselects) stay below 44 px; each has a larger alternative.
- A browser reload starts a new Streamlit session, so Review then shows "No scholarship selected"
  (with a route back); filters also reset on reload.
- Live HTTP collection is still unverified and no record has been checked by a person.

## Find → Review → Apply → Track (2026-11-17) - done

### Why
Too many elements competed for attention: six menu items, a Home page that repeated other
pages, filters always open, badges on every card, two or three buttons per result, and a
tracker split across tabs with a table that duplicated the entries below it.

### What was delivered
1. **One sequence**: Find scholarships → Review → Apply → Track the application.
2. **Menu**: Find Scholarships (opening page), Saved, Applications, plus a "More" group
   (Check my fit, Insights, Data & sources) using `st.navigation(position="top")`. Home is removed.
3. **Find** (`ui/find.py`): search field first; filters and sorting behind one control with a
   count of filters in use; one Review button per result; table view and CSV behind one control.
4. **Review** (`ui/review.py`): deadline, who can apply, where and funding at the top; then the
   Apply section; then eligibility, deadline, funding; wording and source behind controls.
5. **Apply**: "Apply on provider site" opens the provider's page in a new tab. "Mark as
   applied" asks for the date and a confirmation. Only "Yes, add to Applications" writes
   (`services.mark_applied`, one transaction, history note "Marked as applied"). Then
   "Application added" and "View application", which opens that entry in Applications.
6. **Saved** (`ui/saved.py`): optional; grouped by deadline; each row reopens Review.
7. **Applications** (`ui/applications.py`): scholarship, provider and status per entry; "Update
   status" inside the entry; "Saved. Status: ..." confirmation; empty state leads to Find.
8. **Data kept**: no schema change. Existing saved items and tracker entries (including
   Interested/Preparing entries made with the old "Start tracking" button) still appear and can
   be edited or marked as applied. New entries are created only by confirming a submission.

### Evidence (Linux container, Python 3.13, Streamlit 1.67.0, headless Chrome - not the Mac)
- `python -m pytest`: **136 passed** (22 Streamlit AppTest UI checks), fixed date 2026-11-12.
- Fresh databases (`init-examples`, `import-real`), browser walkthrough at **1280 px (real
  data)** and **390 px (example data)**: search → open filters → Review → Back to results
  (search text and result count restored) → Review → Apply link checked (provider URL, opens
  in a new tab) → Mark as applied (SQLite: still no application) → Yes, add to Applications
  (SQLite: one row, status applied, submitted today; saved list still empty) → "Application
  added" shown → View application (that entry first, opened) → status changed to Result
  received / Awarded → saved (SQLite updated, confirmation shown).
- No horizontal overflow at 390 px on those screens.

### Limits (honest)
- Not run on the Mac itself. No screen-reader session or axe scan.
- While a scholarship is open on Review, no menu item is highlighted (Review is not a menu
  page); the Back button names where the user came from.
- On phone widths Streamlit folds the menu into the sidebar; the three main links are repeated
  at the top of the page, and "More" pages are reached through the sidebar arrow.
- ScholarPath cannot know whether the provider's page was opened or the form submitted; the
  user's confirmation is the only signal.
- Earlier limits below still apply (input border contrast, reload after a CLI import, live
  collection unverified, no record checked by a person).

## Interface redesign (2026-11-14) - done, partly superseded by the section above

### Assessment before the change (from the code and screenshots of all six pages)
- Navigation was a sidebar radio restyled into a menu with CSS that depended on Streamlit's
  internal test IDs and hid the radio dots; "Scholarship details" was a menu page with a
  select box, so reading a scholarship took a page switch plus a selection, with no way back.
- About 190 lines of custom CSS/HTML (hero, tiles, card titles, banners), hover-lift
  animations and a font downloaded from Google Fonts on every load.
- Filters were hidden in an expander, with no summary of active filters and no paging.
- The tracker needed a select box to pick an application; its table went stale after saving.
- Filter and form values were lost whenever another page was opened.
- Backend (services, repository, migrations, 126 tests) was sound and is unchanged apart from
  one exported tuple (`services.STORAGE_ERRORS`).

### What was delivered
1. **Design system** (`docs/DESIGN_SYSTEM.md`): theme in `.streamlit/config.toml`, four CSS
   rules, shared components in `ui/common.py`, system fonts only.
2. **Navigation**: Streamlit's built-in `st.navigation` menu (Home, Discover, Check my fit,
   Saved & applications, Insights, Data & sources). Details is a hidden page opened from any
   card, with **Back to ...** returning to the page it was opened from.
3. **Every page rebuilt** on the shared components: Home (replaces Overview), Discover
   (replaces Explore; visible filters, "Filtered by ..." summary, Clear all, 10 per page,
   table switch, CSV of all filtered results), Details (single scroll: dates, funding, source
   and freshness; requirements, items to confirm, how to apply, original wording), Check my
   fit, Saved & applications (deadline board with all six groups, saved list, tracker with one
   edit form per application), Insights, and a new Data & sources page.
4. **States**: every empty list explains why and offers the next step; no-match search offers
   Clear all; missing dataset shows the setup command and **Check again**; database errors show
   a message and **Try again** instead of a traceback; the fit check shows a spinner; writes
   confirm with a toast only after the commit, failures stay on the page.
5. **Fewer steps**: details one click from any card; filters, page and fit answers survive
   visiting other pages; saved cards can be removed in place; tracker forms open directly.

### Verification (Linux container, Python 3.13.18, Streamlit 1.67.0, headless Chrome)
- `python -m pytest`: **133 passed** (19 Streamlit AppTest UI checks; 7 new: paging, filter
  persistence across Details, no-match recovery, remove from card, details without selection,
  Data page, database-failure message).
- Clean start: databases deleted → `init-examples` (15 inserted) → `import-real` (16 inserted)
  → `streamlit run app.py` → `/_stcore/health` = `ok`.
- Real-source walkthrough in the browser, checking SQLite directly after each step:
  Discover (16 results) → search "Commonwealth" (3 results, summary shown) → CSV download
  (3 rows, all Commonwealth) → Details → Save (shortlist = 1 row) → Start tracking
  (application = interested) → Back (filters kept) → **new browser session** → Saved &
  applications shows the scholarship → Tracker: Preparing + note saved (application row and
  2 history rows) → Applied without a date refused, row unchanged.
  `python -m scholarpath status` afterwards: real saved=1 tracked=1, example saved=0.
- Keyboard: Tab reaches "Skip to main content", then the menu links; Enter opens Discover;
  focused link shows the 3 px ring.
- Headings: one h1, then h2 sections, then h3 card titles (checked on Discover).
- Contrast, measured from computed styles on all seven pages: lowest enabled text is 4.67:1
  (captions and input icons); body text and badges are 5.5:1 or higher. Disabled buttons are
  2.6:1 (exempt under WCAG).
- Layout: screenshots reviewed at 1280 px for every page (Deadlines and Tracker tabs
  included) and at 390 px for Discover, Details and Check my fit; no horizontal overflow at
  390 px on Discover and Details.

### Not done / limits (honest)
- **Not run on the Mac itself** (the session could edit files there but not start the app in
  a browser on it). Heading font on macOS will be Iowan Old Style; it was reviewed with a
  Linux fallback serif.
- No screen-reader session and no automated axe scan were run. WCAG 2.2 AA is the target,
  not a claim of conformance.
- Streamlit limits: on a phone-width screen the filter panel is a full screen tall before
  results, and the menu stays open after choosing a page until it is closed; widget borders
  (`#A8A397`, about 2.4:1 on paper) are below the 3:1 non-text guideline, though inputs are
  also filled; dataframes are keyboard-reachable but not ideal for screen readers.
- Cached reads are cleared after in-app writes only. After running a CLI import while the
  app is open, reload the page.
- Live HTTP collection is still unverified and no record has been checked by a person
  (unchanged by this work; shown on the Data & sources page).

### Next (not started)
1. Stage A of the wider upgrade: opportunity types, freshness policy, a second independent
   source, refresh dry-run and outcome log.
2. Compare (up to three), per-application checklists, calendar export, saved searches.
3. Fill in `docs/CONTRIBUTIONS.md` and `docs/AI_ASSISTANCE.md`.
