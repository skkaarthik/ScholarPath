"""Shared fixtures.

All tests use temporary databases, local HTML fixtures and a FIXED date, so
they never touch the network or the user's real databases.
"""

from __future__ import annotations

import copy
from datetime import date
from pathlib import Path

import pytest

from scholarpath import config
from scholarpath.config import Clock
from scholarpath.examples import build_example_records

FIXED_TODAY = date(2026, 11, 12)  # documented test date
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Point every database at a temp folder and pin 'today'."""
    monkeypatch.setenv("SCHOLARPATH_DATA_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("SCHOLARPATH_TODAY", FIXED_TODAY.isoformat())
    return tmp_path


@pytest.fixture
def clock() -> Clock:
    return Clock(fixed_today=FIXED_TODAY)


@pytest.fixture
def example_payload() -> dict:
    return build_example_records(FIXED_TODAY, collected_at="2026-11-12T00:00:00+00:00")


@pytest.fixture
def example_records(example_payload) -> list[dict]:
    return copy.deepcopy(example_payload["records"])


@pytest.fixture
def example_service(tmp_path, clock, example_records):
    from scholarpath.services import ScholarPathService

    service = ScholarPathService(config.MODE_EXAMPLE, db_path=tmp_path / "example.sqlite3", clock=clock)
    service.import_records(example_records, source_file="test")
    return service


def by_key(records: list[dict], key: str) -> dict:
    return next(r for r in records if r["source_key"] == key)


def real_record(**overrides) -> dict:
    """A minimal valid real-source record for persistence tests."""
    from scholarpath.models import stable_id

    record = {
        "name": "Test Real Scholarship",
        "provider": "Test Provider",
        "host_countries": ["United Kingdom"],
        "degrees": {"kind": "list", "values": ["master"]},
        "subjects": {"kind": "unknown", "values": []},
        "nationalities": {"kind": "list", "values": ["India"]},
        "nationality_exclusions": {"kind": "none", "values": []},
        "min_score": None,
        "score_scale": None,
        "funding_category": "partial",
        "funding_description": "GBP 10,000 towards tuition.",
        "deadline_kind": "dated",
        "deadline_date": "2026-12-08",
        "deadline_text": "The deadline is 8 December 2026.",
        "eligibility_text": "Citizens of India.",
        "requirements": [],
        "application_url": "https://example.ac.uk/apply",
        "source_url": "https://example.ac.uk/page",
        "source_name": "Test Source",
        "source_key": "page",
        "award_cycle": "2027/28",
        "collected_at": "2026-11-12T10:00:00+00:00",
        "source_fetched_at": "2026-11-12T10:00:00+00:00",
        "fetch_method": "browser_snapshot",
        "manual_verified_at": None,
        "dataset_origin": "real_source",
        "notes": "",
        "source_status": "available",
    }
    record.update(overrides)
    record["id"] = stable_id(record["source_name"], record["source_key"])
    return record
