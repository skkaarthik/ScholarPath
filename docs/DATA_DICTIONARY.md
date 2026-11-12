# Data dictionary

One canonical record shape is used by the example template, collector output
(`data/collected/real_scholarships.json`), the import service, the database and the CSV export.
Defined in `scholarpath/models.py`; validated by `scholarpath/cleaning.py`.

## Scholarship record

| Field | Type | Meaning |
|---|---|---|
| `id` | text | `sp-` + first 16 hex chars of `sha256("<source_name lowercased>|<source_key>")`. Deterministic; never Python `hash()`. |
| `source_name` | text | Source identity, e.g. `Commonwealth Scholarship Commission in the UK`. |
| `source_key` | text | Stable key within the source (URL path or slug). Name, wording or deadline changes do **not** change it. |
| `name` | text | Scholarship name as published. |
| `provider` | text | Institution/provider. Same-named awards from different providers have different keys → different IDs. |
| `host_countries` | list of text | Countries where study happens. At least one is required. A multi-country record counts in each country in charts. |
| `degrees` | criterion | Degree levels (vocabulary below). |
| `subjects` | criterion | Fields of study (vocabulary below). |
| `nationalities` | criterion | Citizenships accepted. |
| `nationality_exclusions` | exclusions | Citizenships explicitly excluded (evaluated separately). |
| `min_score`, `score_scale` | number, text | Minimum academic score **only when explicitly published**, always with an explicit scale. Both empty otherwise. |
| `funding_category` | enum | `full`, `tuition_full`, `partial`, `living_only`, `unknown`. |
| `funding_description` | text | Original funding wording. |
| `deadline_kind` | enum | `dated`, `rolling`, `unknown`. |
| `deadline_date` | ISO date | Required if and only if `deadline_kind = dated`. |
| `deadline_text` | text | Original deadline wording (keeps published times such as "16:00 GMT"). |
| `eligibility_text` | text | Original eligibility wording (required). |
| `requirements` | list | Each `{kind, category, text}`; `kind` is `structured` (represented in the fields above) or `manual_review` (cannot be checked automatically). |
| `application_url` | URL | Official application/info page. http/https only. |
| `source_url` | URL | Page the record was parsed from. http/https only. |
| `award_cycle` | text or null | e.g. `2027/28`, only when the source states it. |
| `collected_at` | UTC timestamp | When the record was produced by the collector/generator. |
| `source_fetched_at` | UTC timestamp or null | When the source page was fetched or captured. Required for real records. |
| `fetch_method` | enum | `fictional`, `live_http`, `browser_snapshot`. |
| `manual_verified_at` | UTC timestamp or null | Set only after a person checked the record against the official page. Scraping is **not** verification. Re-imports never erase it. |
| `dataset_origin` | enum | `example` or `real_source`; each can only be imported into its own database. |
| `source_status` | enum | `available`, `unavailable` (source answered 404/410), `unknown`. Unavailable records are kept and flagged, never deleted. |
| `notes` | text | Collector notes (e.g. "date has no year, recorded as unknown"). |

All timestamps are ISO 8601 with timezone and are normalised to UTC.

### Provenance stages (tracked separately)

1. **Source fetched** - `source_fetched_at`, `fetch_method`.
2. **Parsed and validated** - the record exists in the dataset (invalid records are rejected with reasons).
3. **Manually checked** - `manual_verified_at` (currently empty for every real record).

## Criterion semantics

`{"kind": ..., "values": [...]}`

| kind | values | Meaning | Matching | Filters |
|---|---|---|---|---|
| `unrestricted` | must be empty | Source explicitly allows any value | satisfied | matches any selection |
| `list` | at least one | Only the listed values | satisfied if listed, else failed | matches if any listed value is selected |
| `unknown` | must be empty | Not published in structured form | unknown | never matches a precise filter |

An empty list therefore never means "unknown" or "unrestricted".

Exclusions: `{"kind": "none" | "list" | "unknown", "values": [...]}`. `none` means the
source structure leaves no exclusions (for example an explicit allow-list of countries).

## Vocabularies

- **Degrees:** `bachelor`, `master`, `phd`, `postdoc`, `non_degree`.
- **Subjects:** `agriculture_environment`, `arts_design`, `business_management`, `computer_science`,
  `economics`, `education`, `engineering`, `humanities`, `law`, `medicine_health`,
  `music_performing_arts`, `natural_sciences`, `public_policy`, `social_sciences`.
  Matched exactly; no two labels are treated as equivalent.
- **Score scales** (identified by ID, not by maximum): `percent_100` (0-100), `cgpa_10` (0-10),
  `gpa_4_us` (US 4.0), `gpa_4_other` (4-point, non-US system). Scores on different scales are
  never compared or converted.
- **Requirement categories:** nationality, degree, subject, academic, language, residence, age,
  experience, admission, financial_need, documents, other.

## Deadline status (computed, never stored)

Using today's date in the app timezone (default Asia/Kolkata):

| Status | Rule |
|---|---|
| open | dated and `deadline_date >= today` (a date-only deadline is open through that day) |
| expired | dated and `deadline_date < today` |
| rolling | `deadline_kind = rolling` |
| unknown | `deadline_kind = unknown` |

Dashboard groups (non-overlapping): 0-7 days, 8-30 days, more than 30 days, expired, rolling, unknown.

Deadline sort order: open (soonest first) → rolling → unknown → expired (most recent first);
ties broken by name, then ID.

## User data tables

| Table | Fields |
|---|---|
| `shortlist` | `scholarship_id` (PK, FK), `added_at` |
| `applications` | `id`, `scholarship_id` (unique, FK), `status`, `target_date`, `submitted_date`, `outcome`, `notes`, `created_at`, `updated_at` |
| `application_history` | one row per change: status, dates, outcome, note, `changed_at` |
| `import_runs` | each import: counts, status (`success`/`failed`), message |

### Tracker status rules

| Status | Submission date | Outcome |
|---|---|---|
| `interested` | must be empty | must be empty |
| `preparing` | must be empty | must be empty |
| `applied` | **required** (the date *you* submitted) | must be empty |
| `result_received` | **required** | **required** (`awarded`, `not_selected`, `waitlisted`, `withdrawn`, `other`) |

- Submission date cannot be in the future. The personal target date is optional for every status
  and is never confused with the official deadline.
- ScholarPath never submits anything; "Applied" only records what you did yourself.
- Entries can be corrected (including moving back to an earlier status); every change adds a
  history row. Removing a shortlist item never deletes the application or its history.
