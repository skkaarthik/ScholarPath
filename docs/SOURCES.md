# Sources

Only sources that are actually implemented are listed. Both are official bodies.

## 1. Commonwealth Scholarship Commission in the UK (`cscuk`)

- **Site:** https://cscuk.fcdo.gov.uk/scholarships/ (UK government-funded scholarship body)
- **Collector:** `scholarpath/collectors/cscuk.py`
- **Pages configured (3):** Commonwealth Master's Scholarships, Commonwealth Shared Scholarships,
  Commonwealth PhD Scholarships.
- **Excluded on purpose:** Commonwealth Fellowships and Startup Fellowships (professional
  fellowships, not degree study) and the page for UK host organisations.
- **robots.txt (checked 2026-11-12):** `User-agent: *` with an empty `Disallow` - crawling allowed.
- **Structure parsed:** `h1.entry-title`, then `<h1>` sections inside `.entry-content`:
  Overview, How to apply, Applicant/Candidate eligibility, Eligible countries
  (`<br>`-separated list), Financial assistance. A missing section raises a `StructureError`.
- **What becomes structured:** eligible citizenship list, degree level (title or first overview
  paragraph), funding category (tuition + stipend → full), award cycle ("2027/28"), and the
  deadline **only when a full date with a year is published**.
- **Limitations:**
  - The Master's and PhD pages say the closing date "was 16:00 BST on Tuesday 20 October" with
    no year, so their deadlines are stored as **unknown**, with the wording and a note.
  - Subjects are not published as a structured list → subject = unknown + manual-review item.
  - The 2:1 degree requirement uses UK classifications, not a numeric score → manual review.
  - Residence, financial need, documents and prior-study rules → manual review.

## 2. British Council Study UK - GREAT Scholarships, India page (`great_india`)

- **Site:** https://study-uk.britishcouncil.org/scholarships-funding/great-scholarships/india
- **Collector:** `scholarpath/collectors/great.py`
- **Records:** one per UK university linked from the India page (13 for 2026-27).
- **robots.txt (checked 2026-11-12):** only `/contact-us/thank-you` and `/newsletter/thank-you`
  are disallowed.
- **Structure parsed:** listing page: links that wrap an `<h3>` university name, plus the
  "What are we looking for in a GREAT scholar?" list. University pages: `<h1>` "GREAT Scholarships
  at ...", the "offering ... for the 2026-27 academic year, each worth £X" sentence, the
  "available for students from" list, course paragraphs, the "deadline for applications is ..."
  sentence and the "Find out more" link (official university page). "Why ...?" and
  "Key subjects" marketing sections and everything after "See also" are ignored.
- **What becomes structured:** accepted nationalities, master's level, award cycle, deadline date,
  funding = partial (fixed amount towards tuition), subject = unrestricted only when the page
  says all full-time taught master's programmes qualify.
- **Limitations:**
  - When eligible courses are a named list (or differ by nationality) the subject is
    **unknown** and the course list is a manual-review item. Course names are not mapped to
    subject categories.
  - Trinity Laban's page gives no deadline → unknown.
  - The India page's shared criteria (Indian passport and residence, undergraduate degree,
    English requirement) are manual-review items labelled as coming from the India page.
  - All 2026-27 deadlines on these pages fell between April and August 2026, so they show as
    **expired** on 2026-11-12. They are kept because the data is real; the app never shifts real
    deadlines.

## 3. DAAD scholarship database (`daad`), disabled

- Listing: https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/
  (all programmes on one page; 147 on 19 Nov 2026, matching the page's own count).
- robots.txt: none on www2.daad.de (HTTP 404, 19 Nov 2026), so no crawling restrictions.
  DAAD's terms of use on www.daad.de could not be loaded that day and are not yet checked.
- Programme pages publish **no application deadline** (it depends on the applicant's status and
  country), so records have an unknown deadline. Country rules are "Only specified" and are
  recorded as unknown with a manual-review note. Only the listing page is read.
- Disabled (`ENABLED = False`) until the terms are checked and a live dry run succeeds; see
  docs/DATA_REFRESH.md.

## Live checks on 19 Nov 2026 (browser, not Python)

Today's CSC and GREAT pages were read in a browser on the project owner's computer and parsed
in a test environment: CSC 3/3 records (Master's and PhD 2027/28 "now closed"; Shared Scholarships
close 16:00 GMT on 8 December 2026), GREAT 13/13 records (2026-27 cycle, 12 dated deadlines
between April and August 2026, all passed; Trinity Laban has no date). No request was made from
Python or from GitHub's servers.

## How the current real dataset was collected (2026-11-12)

The development environment's network allow-list blocked both sites, so `--live` collection
**could not be run or verified**. Instead:

1. The pages were opened in a web browser and their HTML was captured.
2. Each page was trimmed to the sections the parser reads (wording unchanged) and saved under
   `data/snapshots/<source>/` with a `manifest.json` (URL, approximate capture time, robots note).
3. `python -m scholarpath collect --from-snapshots` ran the same parsers over these files:
   **16 accepted, 0 rejected, 0 duplicates, 0 failed**.

Records are marked `fetch_method = browser_snapshot`. None has been manually verified
(`manual_verified_at` is empty). Capture times are approximate (within about 15 minutes).

The live fetcher (`collectors/base.py`) is implemented with robots.txt checks, a host
allow-list, a 20-second timeout, a 2-second delay between requests and up to 3 attempts
for transient errors. It is tested with fake HTTP responses only. Running
`python -m scholarpath collect --live` on a machine with normal internet access is the way to
check it; if the site layout has changed, the parser reports which section is missing.
