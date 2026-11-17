# Upgrade status

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
