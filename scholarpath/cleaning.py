"""Validation and normalisation of canonical scholarship records.

``validate_record`` turns an untrusted dict (from JSON or a parser) into a
``ScholarshipRecord`` or returns human-readable rejection reasons. Nothing is
written anywhere until a record passes validation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import (
    DATASET_ORIGINS,
    DEADLINE_KINDS,
    DEGREES,
    EXCLUSION_KINDS,
    FETCH_METHODS,
    FUNDING_CATEGORIES,
    REQUIREMENT_CATEGORIES,
    REQUIREMENT_KINDS,
    RESTRICTION_KINDS,
    SCORE_SCALES,
    SOURCE_STATUSES,
    SUBJECTS,
    Exclusions,
    Requirement,
    Restriction,
    ScholarshipRecord,
    stable_id,
)

_WS = re.compile(r"\s+")


class ValidationError(ValueError):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def clean_text(value: Any) -> str:
    """Normalise unicode and collapse whitespace; keeps the original wording."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value)).replace(" ", " ")
    return _WS.sub(" ", text).strip()


def clean_country(value: Any) -> str:
    return clean_text(value)


def is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc) and " " not in value


def normalise_utc_timestamp(value: Any, field_name: str, errors: list[str]) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field_name}: not an ISO timestamp ({value!r})")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{field_name}: timestamp must include a timezone")
        return None
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _restriction(raw: Any, field_name: str, errors: list[str], vocab: dict | None) -> Restriction:
    if not isinstance(raw, dict):
        errors.append(f"{field_name}: must be an object with 'kind' and 'values'")
        return Restriction("unknown")
    kind = raw.get("kind")
    values = [clean_text(v) for v in raw.get("values") or [] if clean_text(v)]
    values = sorted(set(values), key=str.casefold)
    if kind not in RESTRICTION_KINDS:
        errors.append(f"{field_name}.kind must be one of {RESTRICTION_KINDS}, got {kind!r}")
        return Restriction("unknown")
    if kind == "list" and not values:
        errors.append(f"{field_name}: kind 'list' needs at least one value")
    if kind != "list" and values:
        errors.append(f"{field_name}: kind {kind!r} must not carry values")
    if vocab is not None:
        bad = [v for v in values if v not in vocab]
        if bad:
            errors.append(f"{field_name}: unknown labels {bad}")
    return Restriction(kind, values if kind == "list" else [])


def _exclusions(raw: Any, errors: list[str]) -> Exclusions:
    if not isinstance(raw, dict):
        errors.append("nationality_exclusions: must be an object with 'kind' and 'values'")
        return Exclusions("unknown")
    kind = raw.get("kind")
    values = sorted({clean_text(v) for v in raw.get("values") or [] if clean_text(v)}, key=str.casefold)
    if kind not in EXCLUSION_KINDS:
        errors.append(f"nationality_exclusions.kind must be one of {EXCLUSION_KINDS}, got {kind!r}")
        return Exclusions("unknown")
    if kind == "list" and not values:
        errors.append("nationality_exclusions: kind 'list' needs at least one value")
    if kind != "list" and values:
        errors.append(f"nationality_exclusions: kind {kind!r} must not carry values")
    return Exclusions(kind, values if kind == "list" else [])


def validate_record(raw: dict[str, Any]) -> ScholarshipRecord:
    """Validate and normalise one record. Raises ValidationError with all reasons."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        raise ValidationError(["record is not an object"])

    name = clean_text(raw.get("name"))
    provider = clean_text(raw.get("provider"))
    source_name = clean_text(raw.get("source_name"))
    source_key = clean_text(raw.get("source_key"))
    for label, value in (("name", name), ("provider", provider), ("source_name", source_name), ("source_key", source_key)):
        if not value:
            errors.append(f"{label}: required")

    expected_id = stable_id(source_name, source_key) if source_name and source_key else None
    record_id = clean_text(raw.get("id")) or expected_id
    if expected_id and record_id != expected_id:
        errors.append("id: does not match the stable ID derived from source_name and source_key")

    host_countries = sorted({clean_country(c) for c in raw.get("host_countries") or [] if clean_country(c)}, key=str.casefold)
    if not host_countries:
        errors.append("host_countries: at least one host country is required")

    degrees = _restriction(raw.get("degrees"), "degrees", errors, DEGREES)
    subjects = _restriction(raw.get("subjects"), "subjects", errors, SUBJECTS)
    nationalities = _restriction(raw.get("nationalities"), "nationalities", errors, None)
    exclusions = _exclusions(raw.get("nationality_exclusions"), errors)
    overlap = set(nationalities.values) & set(exclusions.values)
    if overlap:
        errors.append(f"nationalities: {sorted(overlap)} are both allowed and excluded")

    # Academic threshold: only with an explicit, finite score and a known scale.
    min_score = raw.get("min_score")
    score_scale = raw.get("score_scale") or None
    if min_score is None and score_scale is not None:
        errors.append("score_scale: given without min_score")
    if min_score is not None:
        if isinstance(min_score, bool) or not isinstance(min_score, (int, float)):
            errors.append("min_score: must be a number")
            min_score = None
        elif not math.isfinite(float(min_score)):
            errors.append("min_score: must be finite")
            min_score = None
        elif score_scale not in SCORE_SCALES:
            errors.append(f"score_scale: required explicit scale, one of {list(SCORE_SCALES)}")
        else:
            scale = SCORE_SCALES[score_scale]
            if not scale["min"] <= float(min_score) <= scale["max"]:
                errors.append(f"min_score: {min_score} outside {score_scale} range")
            min_score = float(min_score)

    funding_category = raw.get("funding_category")
    if funding_category not in FUNDING_CATEGORIES:
        errors.append(f"funding_category: must be one of {list(FUNDING_CATEGORIES)}")
    funding_description = clean_text(raw.get("funding_description"))

    deadline_kind = raw.get("deadline_kind")
    deadline_raw = raw.get("deadline_date")
    deadline_date: date | None = None
    if deadline_kind not in DEADLINE_KINDS:
        errors.append(f"deadline_kind: must be one of {DEADLINE_KINDS}")
    if deadline_raw not in (None, ""):
        try:
            deadline_date = date.fromisoformat(str(deadline_raw))
        except ValueError:
            errors.append(f"deadline_date: not an ISO date ({deadline_raw!r})")
    if deadline_kind == "dated" and deadline_date is None:
        errors.append("deadline_date: required when deadline_kind is 'dated'")
    if deadline_kind in ("rolling", "unknown") and deadline_raw not in (None, ""):
        errors.append(f"deadline_date: must be empty when deadline_kind is {deadline_kind!r}")
        deadline_date = None

    requirements: list[Requirement] = []
    for i, req in enumerate(raw.get("requirements") or []):
        if not isinstance(req, dict):
            errors.append(f"requirements[{i}]: must be an object")
            continue
        kind, category, text = req.get("kind"), req.get("category"), clean_text(req.get("text"))
        if kind not in REQUIREMENT_KINDS or category not in REQUIREMENT_CATEGORIES or not text:
            errors.append(f"requirements[{i}]: needs kind {REQUIREMENT_KINDS}, a known category and text")
            continue
        requirements.append(Requirement(kind, category, text))

    application_url = clean_text(raw.get("application_url"))
    source_url = clean_text(raw.get("source_url"))
    if not is_http_url(application_url):
        errors.append("application_url: must be an http(s) URL")
    if not is_http_url(source_url):
        errors.append("source_url: must be an http(s) URL")

    dataset_origin = raw.get("dataset_origin")
    fetch_method = raw.get("fetch_method")
    if dataset_origin not in DATASET_ORIGINS:
        errors.append(f"dataset_origin: must be one of {DATASET_ORIGINS}")
    if fetch_method not in FETCH_METHODS:
        errors.append(f"fetch_method: must be one of {FETCH_METHODS}")
    if (dataset_origin == "example") != (fetch_method == "fictional"):
        errors.append("fetch_method 'fictional' is required for, and only for, example records")

    collected_at = normalise_utc_timestamp(raw.get("collected_at"), "collected_at", errors)
    if raw.get("collected_at") in (None, ""):
        errors.append("collected_at: required")
    source_fetched_at = normalise_utc_timestamp(raw.get("source_fetched_at"), "source_fetched_at", errors)
    manual_verified_at = normalise_utc_timestamp(raw.get("manual_verified_at"), "manual_verified_at", errors)
    if dataset_origin == "real_source" and source_fetched_at is None:
        errors.append("source_fetched_at: required for real-source records")

    source_status = raw.get("source_status", "available")
    if source_status not in SOURCE_STATUSES:
        errors.append(f"source_status: must be one of {SOURCE_STATUSES}")

    deadline_at = normalise_utc_timestamp(raw.get("deadline_at"), "deadline_at", errors)
    if deadline_at and deadline_kind != "dated":
        errors.append("deadline_at: an exact closing time needs deadline_kind 'dated'")
    if deadline_at and deadline_date and datetime.fromisoformat(deadline_at).date() not in (
            deadline_date, date.fromordinal(deadline_date.toordinal() + 1),
            date.fromordinal(deadline_date.toordinal() - 1)):
        errors.append("deadline_at: does not match deadline_date")
    deadline_timezone = clean_text(raw.get("deadline_timezone")) or None
    if deadline_timezone:
        try:
            ZoneInfo(deadline_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            errors.append(f"deadline_timezone: unknown IANA time zone {deadline_timezone!r}")
    closed_by_source = raw.get("closed_by_source", False)
    if not isinstance(closed_by_source, bool):
        errors.append("closed_by_source: must be true or false")

    award_cycle = clean_text(raw.get("award_cycle")) or None
    eligibility_text = clean_text(raw.get("eligibility_text"))
    if not eligibility_text:
        errors.append("eligibility_text: original eligibility wording is required")

    if errors:
        raise ValidationError(errors)

    return ScholarshipRecord(
        id=record_id,
        name=name,
        provider=provider,
        host_countries=host_countries,
        degrees=degrees,
        subjects=subjects,
        nationalities=nationalities,
        nationality_exclusions=exclusions,
        min_score=min_score,
        score_scale=score_scale if min_score is not None else None,
        funding_category=funding_category,
        funding_description=funding_description,
        deadline_kind=deadline_kind,
        deadline_date=deadline_date,
        deadline_text=clean_text(raw.get("deadline_text")),
        eligibility_text=eligibility_text,
        requirements=requirements,
        application_url=application_url,
        source_url=source_url,
        source_name=source_name,
        source_key=source_key,
        award_cycle=award_cycle,
        collected_at=collected_at or "",
        source_fetched_at=source_fetched_at,
        fetch_method=fetch_method,
        manual_verified_at=manual_verified_at,
        dataset_origin=dataset_origin,
        notes=clean_text(raw.get("notes")),
        source_status=source_status,
        deadline_at=deadline_at,
        deadline_timezone=deadline_timezone,
        closed_by_source=bool(closed_by_source),
    )


# Fields that change on every collection run and must not make a record look "updated".
VOLATILE_FIELDS = ("collected_at", "source_fetched_at", "manual_verified_at", "source_status")


def content_hash(record: ScholarshipRecord) -> str:
    data = record.to_dict()
    for key in VOLATILE_FIELDS:
        data.pop(key, None)
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_many(raw_records: list[Any]) -> tuple[list[ScholarshipRecord], list[dict], int]:
    """Validate a batch. Returns (valid, rejected, duplicate_count).

    Duplicates (same stable ID within the batch) keep the first occurrence.
    """
    valid: list[ScholarshipRecord] = []
    rejected: list[dict] = []
    seen: set[str] = set()
    duplicates = 0
    for index, raw in enumerate(raw_records):
        try:
            record = validate_record(raw)
        except ValidationError as exc:
            label = raw.get("name") if isinstance(raw, dict) else None
            rejected.append({"index": index, "name": label, "reasons": exc.reasons})
            continue
        if record.id in seen:
            duplicates += 1
            continue
        seen.add(record.id)
        valid.append(record)
    return valid, rejected, duplicates
