"""CSV export of the currently filtered results.

Untrusted text is protected against spreadsheet formula injection: a cell whose
first non-whitespace character is one of = + - @ (or a tab/carriage return)
is prefixed with an apostrophe so spreadsheet apps treat it as text.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

from .dates import STATUS_LABELS, deadline_status, record_closed
from .models import DEGREES, FUNDING_CATEGORIES, SCORE_SCALES, SUBJECTS, ScholarshipRecord

FORMULA_PREFIXES = ("=", "+", "-", "@")
CONTROL_PREFIXES = ("\t", "\r", "\n")

COLUMNS = [
    "id", "name", "provider", "host_countries", "degrees", "subjects", "nationality_rule",
    "nationality_exclusions", "minimum_score", "funding_category", "funding_description",
    "deadline_kind", "deadline_date", "deadline_status", "days_until_deadline", "deadline_text",
    "award_cycle", "manual_review_items", "application_url", "source_name", "source_url",
    "collected_at", "source_fetched_at", "fetch_method", "manual_verified_at", "source_status",
    "dataset_origin",
]


def safe_cell(value) -> str:
    if value is None:
        return ""
    text = str(value)
    # Check after stripping leading whitespace: "  =cmd()" is just as dangerous.
    if text.lstrip().startswith(FORMULA_PREFIXES) or text.startswith(CONTROL_PREFIXES):
        return "'" + text
    return text


def _restriction_text(kind: str, values: list[str], labels: dict | None = None) -> str:
    if kind == "unrestricted":
        return "Unrestricted"
    if kind == "unknown":
        return "Unknown"
    return "; ".join(labels.get(v, v) if labels else v for v in values)


def record_row(rec: ScholarshipRecord, today: date, now: datetime | None = None) -> dict:
    closed = record_closed(rec, now) if now is not None else None
    status, days_left = deadline_status(rec.deadline_kind, rec.deadline_date, today, closed)
    exc = rec.nationality_exclusions
    exclusions = {"none": "None recorded", "unknown": "Unknown"}.get(exc.kind, "; ".join(exc.values))
    score = (f"{rec.min_score:g} ({SCORE_SCALES[rec.score_scale]['label']})" if rec.min_score is not None else "")
    return {
        "id": rec.id,
        "name": rec.name,
        "provider": rec.provider,
        "host_countries": "; ".join(rec.host_countries),
        "degrees": _restriction_text(rec.degrees.kind, rec.degrees.values, DEGREES),
        "subjects": _restriction_text(rec.subjects.kind, rec.subjects.values, SUBJECTS),
        "nationality_rule": _restriction_text(rec.nationalities.kind, rec.nationalities.values),
        "nationality_exclusions": exclusions,
        "minimum_score": score,
        "funding_category": FUNDING_CATEGORIES.get(rec.funding_category, rec.funding_category),
        "funding_description": rec.funding_description,
        "deadline_kind": rec.deadline_kind,
        "deadline_date": rec.deadline_date.isoformat() if rec.deadline_date else "",
        "deadline_status": STATUS_LABELS[status],
        "days_until_deadline": "" if days_left is None else days_left,
        "deadline_text": rec.deadline_text,
        "award_cycle": rec.award_cycle or "",
        "manual_review_items": " | ".join(r.text for r in rec.manual_review_items),
        "application_url": rec.application_url,
        "source_name": rec.source_name,
        "source_url": rec.source_url,
        "collected_at": rec.collected_at,
        "source_fetched_at": rec.source_fetched_at or "",
        "fetch_method": rec.fetch_method,
        "manual_verified_at": rec.manual_verified_at or "Not manually verified",
        "source_status": rec.source_status,
        "dataset_origin": rec.dataset_origin,
    }


def to_csv(records: list[ScholarshipRecord], today: date, now: datetime | None = None) -> str:
    """CSV of the given records. Pass ``now`` so the status uses the same closing rule as the app."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for rec in records:
        row = record_row(rec, today, now)
        writer.writerow({k: safe_cell(v) if isinstance(v, str) else v for k, v in row.items()})
    return buffer.getvalue()


# --- internships (v2): the same protections, internship columns ------------------------------

INTERNSHIP_COLUMNS = [
    "id", "title", "employer", "cities", "states", "location_text", "work_arrangement", "disciplines", "degrees",
    "study_years", "experience", "eligibility_facts", "stipend_kind", "stipend_min_inr_per_month",
    "stipend_max_inr_per_month", "duration_months", "duration_text", "deadline_kind", "deadline_date",
    "deadline_status", "days_until_deadline", "deadline_text", "application_url", "also_listed_on", "source_name",
    "source_url", "collected_at", "last_checked_at", "fetch_method", "manual_verified_at", "source_status",
    "dataset_origin",
]


def internship_row(rec, today: date, now: datetime | None = None) -> dict:
    from .models import DISCIPLINES, INTERN_DEGREES, STIPEND_KINDS, STUDY_YEARS, WORK_ARRANGEMENTS

    closed = record_closed(rec, now) if now is not None else None
    status, days_left = deadline_status(rec.deadline_kind, rec.deadline_date, today, closed)
    return {
        "id": rec.id, "title": rec.title, "employer": rec.employer, "cities": "; ".join(rec.cities),
        "states": "; ".join(rec.states), "location_text": rec.location_text,
        "work_arrangement": WORK_ARRANGEMENTS.get(rec.work_arrangement, rec.work_arrangement),
        "disciplines": _restriction_text(rec.disciplines.kind, rec.disciplines.values, DISCIPLINES),
        "degrees": _restriction_text(rec.degrees.kind, rec.degrees.values, INTERN_DEGREES),
        "study_years": _restriction_text(rec.study_years.kind, rec.study_years.values, STUDY_YEARS),
        "experience": rec.experience_text, "eligibility_facts": rec.eligibility_text,
        "stipend_kind": STIPEND_KINDS.get(rec.stipend_kind, rec.stipend_kind),
        "stipend_min_inr_per_month": "" if rec.stipend_min is None else rec.stipend_min,
        "stipend_max_inr_per_month": "" if rec.stipend_max is None else rec.stipend_max,
        "duration_months": "" if rec.duration_months is None else f"{rec.duration_months:g}",
        "duration_text": rec.duration_text, "deadline_kind": rec.deadline_kind,
        "deadline_date": rec.deadline_date.isoformat() if rec.deadline_date else "",
        "deadline_status": STATUS_LABELS[status], "days_until_deadline": "" if days_left is None else days_left,
        "deadline_text": rec.deadline_text, "application_url": rec.application_url,
        "also_listed_on": " | ".join(f"{link.source_name}: {link.url}" for link in rec.also_listed),
        "source_name": rec.source_name, "source_url": rec.source_url, "collected_at": rec.collected_at,
        "last_checked_at": rec.source_fetched_at or "", "fetch_method": rec.fetch_method,
        "manual_verified_at": rec.manual_verified_at or "Not manually verified", "source_status": rec.source_status,
        "dataset_origin": rec.dataset_origin,
    }


def internships_to_csv(records: list, today: date, now: datetime | None = None) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=INTERNSHIP_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for rec in records:
        row = internship_row(rec, today, now)
        writer.writerow({k: safe_cell(v) if isinstance(v, str) else v for k, v in row.items()})
    return buffer.getvalue()
