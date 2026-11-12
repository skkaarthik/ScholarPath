# Five-minute demonstration

## Before the demo (once)

```bash
python -m scholarpath init-examples --anchor-date 2026-11-12
python -m scholarpath import-real
python -m pytest                      # optional: show the suite passing
```

For identical deadline labels to this guide, pin today's date when launching:

```bash
# macOS/Linux
SCHOLARPATH_TODAY=2026-11-12 python -m streamlit run app.py
# Windows PowerShell
$env:SCHOLARPATH_TODAY="2026-11-12"; python -m streamlit run app.py
```

Without it, example deadlines are relative to the anchor date and real ones to the real today.

## Script (≈5 minutes)

1. **Overview (30 s)** - point to the yellow *EXAMPLE DATA - fictional* banner and the
   database-backed counts.
2. **Explore (60 s)** - filter Host country = *United Kingdom*, Funding = *Full* → 1 result
   (Cedar Public Health). Clear filters. Filter Subject = *Computer science*: the Atlas short
   course disappears (subject *unknown*), Aurora appears (*explicitly unrestricted*).
   Download the CSV and mention provenance columns and formula-injection protection.
3. **Details (45 s)** - open *Cedar Public Health Scholarship*: requirements table, manual-review
   items, original wording, provenance. Click **Save to shortlist** and **Start tracking**.
4. **Profile matching (75 s)** - use the profiles below.
5. **My applications (45 s)** - Tracker: set status *Applied* without a date → validation error;
   set *Preparing* with a target date → saved. Show the history. Deadlines tab: Cedar sits in
   "Due today to 7 days".
6. **Real data (30 s)** - switch the sidebar to *Real sources*: banner changes, the shortlist is
   empty (isolated database). Open *Commonwealth Shared Scholarships* (deadline 8 Dec 2026,
   from the official page) and *Commonwealth Master's Scholarships* (deadline unknown because
   the page gives no year).
7. **Restart proof (15 s)** - stop and restart Streamlit; saved and tracked items are still there.

## Example profiles (example dataset)

| Profile | Scholarship to open | Expected result |
|---|---|---|
| India · Master's · Computer science · 8.5 on *CGPA 10-point* | Lakeshore STEM Excellence Award | ✅ **Matches recorded requirements** (all rules satisfied) |
| India · Master's · Medicine & health | Cedar Public Health Scholarship | ❌ **Does not match** - India is not on the nationality list |
| India · PhD · Natural sciences | Meridian Doctoral Fellowship | ⚠️ **Needs manual verification** - nationality rules unknown |
| India · Master's · Law · 3.9 on *US 4.0 GPA* | Delta Law & Policy Scholarship | ⚠️ score rule unknown - requirement uses a different 4-point scale; no conversion |
| Ireland · Master's · Computer science · 9 on CGPA | Vega Computer Science Master's Award | ❌ nationality allowed but explicitly **excluded** |
| (leave everything blank) | any | ⚠️ every record needs manual verification - blanks are never treated as matches |

## Real dataset profile

India · Master's (other fields blank):
- Commonwealth Master's / Shared → ⚠️ needs manual verification (nationality satisfied; residence,
  2:1 degree and other clauses are manual review).
- Commonwealth PhD → ❌ India is not on the PhD eligible-country list.

## Offline fallback

Everything above works without internet: the example data is generated locally and the real
dataset is imported from the committed JSON (`data/collected/real_scholarships.json`). If the
real database is missing, the app says so and shows the command - it never silently shows
example data instead. If Streamlit fails entirely, run `python -m scholarpath status` and
`python -m pytest -k "flow or persistence"` to demonstrate the backend.
