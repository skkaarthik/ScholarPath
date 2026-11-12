# ScholarPath

ScholarPath is a **single-user, local** Streamlit app for discovering international
scholarships and planning applications:

**Find a scholarship → understand its requirements → save it → track your preparation and deadlines.**

It is a college semester project. It does not submit applications, predict who wins,
generate essays, send emails, store documents or convert currencies.

## Features

- **Two isolated datasets**, each with its own SQLite database, shortlist and tracker:
  - *Example data (fictional)* - 15 invented scholarships for offline demos. Always labelled.
  - *Real sources (collected)* - 16 records parsed from official pages of the
    Commonwealth Scholarship Commission in the UK and British Council GREAT Scholarships (India).
- **Explore**: text search plus host country, degree, subject, funding and deadline-status filters
  (OR within a filter, AND across filters), sorting, and **CSV export of the filtered results**.
- **Scholarship details**: funding, structured requirements, *original eligibility wording*,
  manual-review items, official links and provenance (source, fetch time, verification status).
- **Profile matching**: explainable rule-by-rule results - *satisfied / failed / unknown* - with an
  overall verdict of "Matches recorded requirements", "Needs manual verification" or
  "Does not match recorded requirements". Results are grouped into *Good fits*, *Need more info*
  and *Not a fit*; things only you can confirm become a short checklist. Missing information is
  never treated as a match.
- **My applications**: shortlist, tracker (Interested → Preparing → Applied → Result received)
  with personal target dates, notes, corrections and change history, plus a deadline dashboard.
- **Insights**: counts by host country, funding category and known deadline month.

## Architecture (short)

```
Streamlit UI (app.py, scholarpath/ui)  →  services.py  →  repository.py (SQL)  →  database.py  →  SQLite
Collectors: fetch (live or snapshot) → parse → validate → data/collected/*.json → import service → SQLite
```

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Field definitions:
[docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md). Sources: [docs/SOURCES.md](docs/SOURCES.md).

## Prerequisites

- Python **3.11 or newer** (`python --version`)
- Git (to clone)
- Internet only for installing packages and for optional live collection

## Setup

All commands run from the repository root (the folder containing `app.py`).

### Windows (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

`requirements.txt` holds runtime packages; `requirements-dev.txt` adds pytest.

## Initialise data and launch

```bash
python -m scholarpath init-examples   # fictional example DB (deadlines relative to today)
python -m scholarpath import-real     # real-source DB from data/collected/real_scholarships.json
python -m streamlit run app.py        # opens http://localhost:8501
```

Choose the dataset in the sidebar. Both datasets work **offline**.

`init-examples --anchor-date 2026-11-12` makes the example deadlines reproducible
(they are stored as day offsets and converted relative to the anchor date).

## Real-source collection (optional, explicit)

The app never scrapes on startup. Collection is a separate command:

```bash
python -m scholarpath collect --from-snapshots   # re-parse saved snapshots in data/snapshots/ (offline)
python -m scholarpath collect --live             # fetch the official pages over HTTP (polite, robots-aware)
python -m scholarpath import-real                # then import the JSON into the real DB
```

`collect` prints accepted / rejected / duplicate / failed counts. An empty run writes nothing;
a run with failed pages writes a separate `*.partial-*.json` file unless you pass
`--allow-partial`. Records are merged by stable ID, so nothing is dropped because it was
missing from one run. **Live collection has not been verified from the development
environment** (see [docs/SOURCES.md](docs/SOURCES.md)).

## Tests

```bash
python -m pytest
```

Tests run offline with temporary databases, local HTML fixtures and the fixed date
**2026-11-12**. They include Streamlit `AppTest` UI checks.

## Database locations, backup and reset

| Dataset | File |
|---|---|
| Example (fictional) | `data/db/scholarpath_example.sqlite3` |
| Real sources | `data/db/scholarpath_real.sqlite3` |

- `python -m scholarpath status` - paths, schema version, counts, last import.
- `python -m scholarpath backup --mode example` (or `--mode real_source`) - copy to `backups/`.
- Re-running `init-examples` / `import-real` **updates** records in place and keeps your
  shortlist and tracker. Nothing resets automatically.
- To reset a dataset completely, close the app, back it up, then delete that one `.sqlite3`
  file yourself and run the init/import command again. This deletes your saved items and
  tracker entries for that dataset.
- Set `SCHOLARPATH_DATA_DIR` to keep the databases elsewhere.

Generated databases, backups and the generated example JSON are ignored by Git.

## Dataset distinctions

| | Example | Real sources |
|---|---|---|
| Content | Invented; URLs on `example.org` | Parsed from official pages |
| Deadlines | Generated relative to an anchor date | Exactly as published; never shifted |
| Purpose | Reliable demo of every rule and edge case | Honest sample of real data |
| Verified? | Not applicable | Parsed, **not manually verified** |

## Limitations

- Single user on one computer. No accounts, no user isolation, not for shared hosting.
- Real data covers 16 UK-hosted awards from two sources and is a snapshot from 2026-11-12;
  most GREAT deadlines in it have already passed.
- Matching only uses structured data. Language tests, residence, age, experience and similar
  clauses are shown as manual-review items.
- A recorded match never guarantees eligibility, selection or funding.

## Troubleshooting

| Problem | Fix |
|---|---|
| "database has no scholarships yet" | Run the command shown in the message from the repository root. |
| `ModuleNotFoundError: scholarpath` | Run commands from the repository root with the venv active. |
| `ZoneInfoNotFoundError` on Windows | `python -m pip install -r requirements.txt` (installs `tzdata`). |
| "database is locked" | Close other ScholarPath windows or DB browsers, then retry. |
| `streamlit` not found | Use `python -m streamlit run app.py`. |
| Live collection fails | Check internet access; the saved snapshots still work offline. |

## Documentation

[Architecture](docs/ARCHITECTURE.md) · [Data dictionary](docs/DATA_DICTIONARY.md) ·
[Sources](docs/SOURCES.md) · [Demo guide](docs/DEMO_GUIDE.md) ·
[Viva preparation](docs/VIVA_PREPARATION.md) · [Implementation status](docs/IMPLEMENTATION_STATUS.md) ·
[Contributions](docs/CONTRIBUTIONS.md) · [AI assistance](docs/AI_ASSISTANCE.md)
