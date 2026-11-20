"""Phase 1: validation, normalisation and stable identity."""

import math

import pytest

from scholarpath.cleaning import ValidationError, content_hash, validate_many, validate_record
from scholarpath.models import stable_id

from .conftest import by_key, real_record


def reasons(raw) -> str:
    with pytest.raises(ValidationError) as info:
        validate_record(raw)
    return " | ".join(info.value.reasons)


def test_all_example_records_are_valid_and_labelled_fictional(example_records):
    valid, rejected, duplicates = validate_many(example_records)
    assert rejected == [] and duplicates == 0
    assert len(valid) == 15
    for rec in valid:
        assert rec.dataset_origin == "example" and rec.fetch_method == "fictional"
        assert "FICTIONAL" in rec.notes and "(fictional)" in rec.provider


def test_dated_deadline_requires_a_date():
    assert "deadline_date: required" in reasons(real_record(deadline_date=None))


def test_rolling_deadline_must_not_have_a_date():
    assert "must be empty" in reasons(real_record(deadline_kind="rolling"))


def test_empty_list_is_not_a_synonym_for_unknown_or_unrestricted():
    assert "needs at least one value" in reasons(real_record(nationalities={"kind": "list", "values": []}))
    assert "must not carry values" in reasons(real_record(nationalities={"kind": "unrestricted", "values": ["India"]}))


def test_country_cannot_be_both_allowed_and_excluded():
    raw = real_record(nationality_exclusions={"kind": "list", "values": ["India"]})
    assert "both allowed and excluded" in reasons(raw)


@pytest.mark.parametrize("score, scale, expected", [
    (math.inf, "percent_100", "finite"),
    (75, None, "explicit scale"),
    (11, "cgpa_10", "outside"),
    ("75", "percent_100", "must be a number"),
])
def test_scores_need_finite_values_and_explicit_scales(score, scale, expected):
    assert expected in reasons(real_record(min_score=score, score_scale=scale))


def test_urls_must_be_http_or_https():
    assert "application_url" in reasons(real_record(application_url="javascript:alert(1)"))
    assert "source_url" in reasons(real_record(source_url="ftp://example.org/x"))


def test_timestamps_must_be_timezone_aware_and_are_normalised_to_utc():
    assert "timezone" in reasons(real_record(collected_at="2026-11-12T10:00:00"))
    rec = validate_record(real_record(collected_at="2026-11-12T15:30:00+05:30"))
    assert rec.collected_at == "2026-11-12T10:00:00+00:00"


def test_real_records_need_fetch_timestamp_and_cannot_claim_fictional():
    assert "source_fetched_at" in reasons(real_record(source_fetched_at=None))
    assert "fictional" in reasons(real_record(fetch_method="fictional"))


def test_unknown_controlled_labels_are_rejected():
    assert "unknown labels" in reasons(real_record(subjects={"kind": "list", "values": ["AI stuff"]}))
    assert "funding_category" in reasons(real_record(funding_category="lots"))


def test_stable_id_is_deterministic_and_ignores_changing_content():
    first = validate_record(real_record())
    changed = validate_record(real_record(deadline_date="2027-01-31", eligibility_text="Rewritten text."))
    assert first.id == changed.id == stable_id("Test Source", "page")
    assert first.id == "sp-" + __import__("hashlib").sha256(b"test source|page").hexdigest()[:16]
    assert content_hash(first) != content_hash(changed)


def test_tampered_id_is_rejected():
    raw = real_record()
    raw["id"] = "sp-0000000000000000"
    assert "stable ID" in reasons(raw)


def test_similarly_named_awards_from_different_institutions_stay_separate(example_records):
    a = by_key(example_records, "aurora-global-masters-northbridge")
    b = by_key(example_records, "aurora-global-masters-southgate")
    assert a["name"] == b["name"] and a["id"] != b["id"]


def test_duplicates_in_one_batch_are_counted_not_imported_twice():
    valid, rejected, duplicates = validate_many([real_record(), real_record(), {"name": "broken"}])
    assert len(valid) == 1 and duplicates == 1 and len(rejected) == 1
    assert rejected[0]["reasons"]


def test_whitespace_is_normalised_but_wording_preserved():
    rec = validate_record(real_record(eligibility_text="  Citizens of   India \n only. "))
    assert rec.eligibility_text == "Citizens of India only."


def test_volatile_timestamps_do_not_change_content_hash():
    a = validate_record(real_record())
    b = validate_record(real_record(collected_at="2027-01-01T00:00:00+00:00",
                                    source_fetched_at="2027-01-01T00:00:00+00:00"))
    assert content_hash(a) == content_hash(b)
