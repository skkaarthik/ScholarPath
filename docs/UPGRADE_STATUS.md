# Upgrade status

## Interface redesign (2026-11-14) - done

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
