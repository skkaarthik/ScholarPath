"""Phase 2: explainable, conservative eligibility rules."""

import pytest

from scholarpath.cleaning import validate_record
from scholarpath.matching import (
    FAILED,
    OVERALL_FAIL,
    OVERALL_MANUAL,
    OVERALL_MATCH,
    SATISFIED,
    UNKNOWN,
    StudentProfile,
    evaluate,
    validate_profile,
)
from scholarpath.repository import SearchFilters

from .conftest import by_key

INDIAN_CS = StudentProfile(nationality="India", degree="master", subject="computer_science",
                           score=8.5, score_scale="cgpa_10")


@pytest.fixture
def recs(example_records):
    return {r["source_key"]: validate_record(r) for r in example_records}


def rule(result, name):
    return next(r for r in result.rules if r.rule == name)


def test_full_match_only_when_every_rule_is_satisfied(recs):
    result = evaluate(INDIAN_CS, recs["lakeshore-stem-excellence"])
    assert result.overall == OVERALL_MATCH
    assert all(r.status == SATISFIED for r in result.rules)
    assert rule(result, "Academic score").student_value.startswith("8.5")


def test_explicit_nationality_failure(recs):
    result = evaluate(StudentProfile(nationality="India", degree="master", subject="medicine_health"),
                      recs["cedar-public-health"])
    assert result.overall == OVERALL_FAIL
    assert rule(result, "Nationality").status == FAILED


def test_exclusions_are_evaluated_separately(recs):
    result = evaluate(StudentProfile(nationality="Ireland", degree="master", subject="computer_science",
                                     score=9, score_scale="cgpa_10"), recs["vega-cs-masters"])
    assert rule(result, "Nationality").status == SATISFIED  # unrestricted...
    assert rule(result, "Nationality exclusions").status == FAILED  # ...but excluded
    assert result.overall == OVERALL_FAIL


def test_unknown_criteria_are_never_treated_as_satisfied(recs):
    result = evaluate(StudentProfile(nationality="India", degree="phd", subject="natural_sciences"),
                      recs["meridian-doctoral-fellowship"])
    assert rule(result, "Nationality").status == UNKNOWN
    assert rule(result, "Nationality exclusions").status == UNKNOWN
    assert result.overall == OVERALL_MANUAL


def test_explicitly_unrestricted_criteria_are_satisfied(recs):
    result = evaluate(StudentProfile(nationality="Kenya", degree="master", subject="law",
                                     score=80, score_scale="percent_100"), recs["aurora-global-masters-northbridge"])
    assert rule(result, "Subject").status == SATISFIED
    assert rule(result, "Nationality").status == SATISFIED
    assert result.overall == OVERALL_MANUAL  # IELTS still needs manual review


def test_same_maximum_different_scale_is_unknown_not_compared(recs):
    profile = StudentProfile(nationality="India", degree="master", subject="law", score=3.9, score_scale="gpa_4_us")
    result = evaluate(profile, recs["delta-law-policy"])  # requirement is gpa_4_other
    assert rule(result, "Academic score").status == UNKNOWN
    assert "does not convert" in rule(result, "Academic score").reason
    assert result.overall == OVERALL_MANUAL


def test_gpa_is_never_converted_to_percentage(recs):
    profile = StudentProfile(nationality="India", degree="master", subject="humanities", score=3.9, score_scale="gpa_4_us")
    assert rule(evaluate(profile, recs["lumen-humanities"]), "Academic score").status == UNKNOWN


def test_score_below_minimum_on_same_scale_fails(recs):
    profile = StudentProfile(nationality="India", degree="master", subject="computer_science",
                             score=7.9, score_scale="cgpa_10")
    assert rule(evaluate(profile, recs["lakeshore-stem-excellence"]), "Academic score").status == FAILED


def test_missing_student_input_makes_that_rule_unknown(recs):
    result = evaluate(StudentProfile(degree="master", subject="computer_science"), recs["lakeshore-stem-excellence"])
    assert rule(result, "Nationality").status == UNKNOWN
    assert rule(result, "Academic score").status == UNKNOWN
    assert result.overall == OVERALL_MANUAL


def test_subjects_are_matched_exactly_not_fuzzily(recs):
    result = evaluate(StudentProfile(nationality="India", degree="master", subject="economics",
                                     score=9, score_scale="cgpa_10"), recs["lakeshore-stem-excellence"])
    assert rule(result, "Subject").status == FAILED


def test_nationality_comparison_ignores_case_only(recs):
    result = evaluate(StudentProfile(nationality="india"), recs["lakeshore-stem-excellence"])
    assert rule(result, "Nationality").status == SATISFIED
    result = evaluate(StudentProfile(nationality="Indian"), recs["lakeshore-stem-excellence"])
    assert rule(result, "Nationality").status == FAILED


def test_manual_review_items_are_visible_rules(recs):
    result = evaluate(INDIAN_CS, recs["sakura-research-scholarship"])
    manual = [r for r in result.rules if r.rule.startswith("Manual review")]
    assert {r.rule for r in manual} == {"Manual review (age)", "Manual review (admission)"}
    assert all(r.status == UNKNOWN for r in manual)


def test_every_rule_explains_itself(recs):
    for rec in recs.values():
        for r in evaluate(INDIAN_CS, rec).rules:
            assert r.rule and r.requirement and r.reason and r.status in (SATISFIED, FAILED, UNKNOWN)


def test_profile_validation():
    assert validate_profile(StudentProfile(score=11, score_scale="cgpa_10"))
    assert validate_profile(StudentProfile(score=8.0))
    assert validate_profile(StudentProfile(score_scale="cgpa_10"))
    assert validate_profile(INDIAN_CS) == []


def test_preferred_destination_filters_but_is_not_a_rule(example_service, example_records):
    profile = StudentProfile(nationality="India", degree="master", subject="computer_science",
                             score=8.5, score_scale="cgpa_10", preferred_destination="Germany")
    results = example_service.match(profile)
    assert [v.record.name for v, _ in results] == ["Lakeshore STEM Excellence Award"]
    assert not any("destination" in r.rule.lower() for r in results[0][1].rules)


def test_match_results_put_matches_first(example_service):
    results = example_service.match(INDIAN_CS, SearchFilters())
    overall = [m.overall for _, m in results]
    order = [OVERALL_MATCH, OVERALL_MANUAL, OVERALL_FAIL]
    assert overall == sorted(overall, key=order.index)
    assert overall[0] == OVERALL_MATCH
