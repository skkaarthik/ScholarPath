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

1. **Overview (30 s)** - point to the *Example data* banner (every record is invented), the
   hero quick actions and the database-backed counts. Hover a card: it lifts and outlines in teal.
2. **Explore (60 s)** - filter Host country = *United Kingdom*, Funding = *Full* → 1 result
   (Cedar Public Health). Clear filters. Filter Subject = *Computer science*: the Atlas short
   course disappears (subject *unknown*), Aurora appears (*explicitly unrestricted*).
   Download the CSV and mention provenance columns and formula-injection protection.
3. **Details (45 s)** - open *Cedar Public Health Scholarship*: requirements table, manual-review
   items, original wording, provenance. Click **Save to shortlist** and **Start tracking**
   (a confirmation pops up in the corner).
4. **Profile matching (75 s)** - use the profiles below. Results are grouped into *Good fits*
   (every automatic check passed; anything left is a short checklist), *Need more info* and
   *Not a fit*. The overall verdict wording on each card is unchanged.
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
| India · Master's · Computer science · 8.5 on *CGPA 10-point* | Lakeshore STEM Excellence Award | **Good fits** - ✅ *Matches recorded requirements* (all 5 rules met). Vega and Sakura also land in Good fits with a short checklist |
| India · Master's · Medicine & health | Cedar Public Health Scholarship | **Not a fit** - India is not on the nationality list |
| India · PhD · Natural sciences | Meridian Doctoral Fellowship | **Need more info** - the source doesn't list eligible countries |
| India · Master's · Law · 3.9 on *US 4.0 GPA* | Delta Law & Policy Scholarship | **Need more info** - the requirement uses a different 4-point scale; no conversion |
| Ireland · Master's · Computer science · 9 on CGPA | Vega Computer Science Master's Award | **Not a fit** - nationality allowed in general but explicitly excluded |
| (leave everything blank) | any | All 15 in **Need more info**, with a tip naming the fields to add - blanks are never treated as matches |

## Real dataset profile

India · Master's (other fields blank):
- Commonwealth Master's / Shared → **Need more info** (citizenship and degree met; add a subject;
  residence, the 2:1 degree and other clauses form the confirm-yourself checklist).
- Commonwealth PhD → **Not a fit** - India is not on the PhD eligible-country list.

## Offline fallback

Everything above works without internet: the example data is generated locally and the real
dataset is imported from the committed JSON (`data/collected/real_scholarships.json`). If the
real database is missing, the app says so and shows the command - it never silently shows
example data instead. If Streamlit fails entirely, run `python -m scholarpath status` and
`python -m pytest -k "flow or persistence"` to demonstrate the backend.
