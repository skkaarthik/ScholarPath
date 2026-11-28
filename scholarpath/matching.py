"""Explainable eligibility matching (pure functions, no I/O).

Each rule returns the student's value, the recorded requirement, a status
(satisfied / failed / unknown) and a reason. Rules only decide when structured
source data supports a decision:

* missing criteria are never treated as satisfied;
* nationality is never inferred from residence;
* subjects and nationalities are compared by exact label (case-insensitive),
  never fuzzily;
* scores are compared only on the same scale ID - GPA is never converted to a
  percentage and two scales with the same maximum are not assumed equivalent;
* unsupported requirements (language tests, age, experience, admission...) are
  listed as manual-review items with status "unknown".

Preferred destination is a filter applied by the service, not an eligibility
rule. Deadline status is reported separately from matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import DEGREES, DISCIPLINES, INTERN_DEGREES, SCORE_SCALES, STUDY_YEARS, SUBJECTS, ScholarshipRecord

SATISFIED, FAILED, UNKNOWN = "satisfied", "failed", "unknown"

OVERALL_FAIL = "Does not match recorded requirements"
OVERALL_MANUAL = "Needs manual verification"
OVERALL_MATCH = "Matches recorded requirements"

DISCLAIMER = (
    "A recorded match only compares your answers with the requirements ScholarPath recorded from the source. "
    "It does not guarantee official eligibility, selection or funding. Always confirm on the official page."
)


@dataclass
class StudentProfile:
    nationality: str | None = None
    degree: str | None = None
    subject: str | None = None
    score: float | None = None
    score_scale: str | None = None
    preferred_destination: str | None = None  # filter preference only


@dataclass
class RuleResult:
    rule: str
    student_value: str
    requirement: str
    status: str
    reason: str
    kind: str = "automatic"       # "automatic" (structured rule) or "manual" (checklist item)
    missing_input: bool = False   # unknown only because the student left this blank


@dataclass
class MatchResult:
    scholarship_id: str
    overall: str
    rules: list[RuleResult] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        return {s: sum(1 for r in self.rules if r.status == s) for s in (SATISFIED, FAILED, UNKNOWN)}

    @property
    def automatic(self) -> list[RuleResult]:
        return [r for r in self.rules if r.kind == "automatic"]

    @property
    def manual(self) -> list[RuleResult]:
        return [r for r in self.rules if r.kind == "manual"]

    @property
    def missing_inputs(self) -> list[RuleResult]:
        return [r for r in self.automatic if r.missing_input]

    @property
    def group(self) -> str:
        """Display group (the overall verdict is unchanged):

        * "fit"     - every automatic check passed; only checklist items may remain
        * "missing" - nothing failed, but some automatic checks could not run
        * "no_fit"  - at least one recorded requirement failed
        """
        if self.overall == OVERALL_FAIL:
            return "no_fit"
        if any(r.status == UNKNOWN for r in self.automatic):
            return "missing"
        return "fit"


def _same(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _missing(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _show(value, labels: dict | None = None) -> str:
    if _missing(value):
        return "(not provided)"
    return labels.get(value, value) if labels else str(value)


def validate_profile(profile: StudentProfile) -> list[str]:
    """Input problems the UI should show before matching."""
    errors = []
    if profile.degree and profile.degree not in DEGREES:
        errors.append("Unknown degree level.")
    if profile.subject and profile.subject not in SUBJECTS:
        errors.append("Unknown subject.")
    if profile.score is not None:
        if profile.score_scale not in SCORE_SCALES:
            errors.append("Choose the scale your score is measured on.")
        else:
            scale = SCORE_SCALES[profile.score_scale]
            if not scale["min"] <= profile.score <= scale["max"]:
                errors.append(f"Score must be between {scale['min']:g} and {scale['max']:g} on this scale.")
    elif profile.score_scale:
        errors.append("Enter a score for the selected scale, or clear the scale.")
    return errors


def rule_nationality(profile: StudentProfile, rec: ScholarshipRecord) -> RuleResult:
    req = rec.nationalities
    shown = {"unrestricted": "Open to all nationalities", "unknown": "Not recorded in structured form"}.get(
        req.kind, "Citizens of: " + ", ".join(req.values))
    student = _show(profile.nationality)
    if _missing(profile.nationality):
        return RuleResult("Nationality", student, shown, UNKNOWN, "You didn't enter a citizenship, so this can't be checked.",
                          missing_input=True)
    if req.kind == "unknown":
        return RuleResult("Nationality", student, shown, UNKNOWN,
                          "The source doesn't list eligible countries in a form ScholarPath can check.")
    if req.kind == "unrestricted":
        return RuleResult("Nationality", student, shown, SATISFIED, "Open to every nationality.")
    if any(_same(profile.nationality, v) for v in req.values):
        return RuleResult("Nationality", student, shown, SATISFIED, f"{profile.nationality} is on the list of eligible countries.")
    return RuleResult("Nationality", student, shown, FAILED, f"{profile.nationality} is not on the list of eligible countries.")


def rule_exclusions(profile: StudentProfile, rec: ScholarshipRecord) -> RuleResult:
    exc = rec.nationality_exclusions
    shown = {"none": "No exclusions recorded", "unknown": "Exclusions not recorded"}.get(
        exc.kind, "Not open to citizens of: " + ", ".join(exc.values))
    student = _show(profile.nationality)
    if _missing(profile.nationality):
        return RuleResult("Nationality exclusions", student, shown, UNKNOWN, "You didn't enter a citizenship, so this can't be checked.",
                          missing_input=True)
    if exc.kind == "unknown":
        return RuleResult("Nationality exclusions", student, shown, UNKNOWN,
                          "The source doesn't say whether any nationalities are excluded.")
    if exc.kind == "list" and any(_same(profile.nationality, v) for v in exc.values):
        return RuleResult("Nationality exclusions", student, shown, FAILED,
                          f"The source says citizens of {profile.nationality} can't apply.")
    return RuleResult("Nationality exclusions", student, shown, SATISFIED,
                      "Your citizenship isn't excluded.")


def _list_rule(name: str, student_value, req, labels: dict) -> RuleResult:
    shown = {"unrestricted": "Any (explicitly unrestricted)", "unknown": "Not recorded in structured form"}.get(
        req.kind, ", ".join(labels.get(v, v) for v in req.values))
    student = _show(student_value, labels)
    if _missing(student_value):
        return RuleResult(name, student, shown, UNKNOWN, f"You didn't choose a {name.lower()}, so this can't be checked.",
                          missing_input=True)
    if req.kind == "unknown":
        return RuleResult(name, student, shown, UNKNOWN, f"The source doesn't list {name.lower()} options in a form ScholarPath can check.")
    if req.kind == "unrestricted":
        return RuleResult(name, student, shown, SATISFIED, f"Open to any {name.lower()}.")
    if student_value in req.values:
        return RuleResult(name, student, shown, SATISFIED, f"{labels.get(student_value, student_value)} is accepted.")
    return RuleResult(name, student, shown, FAILED,
                      f"{labels.get(student_value, student_value)} is not one of the accepted options.")


def rule_score(profile: StudentProfile, rec: ScholarshipRecord) -> RuleResult | None:
    if rec.min_score is None:
        return None  # no structured threshold; any academic wording appears as a manual-review item
    scale_label = SCORE_SCALES[rec.score_scale]["label"]
    shown = f"At least {rec.min_score:g} ({scale_label})"
    if profile.score is None:
        return RuleResult("Academic score", "(not provided)", shown, UNKNOWN, "You didn't enter a score, so this can't be checked.",
                          missing_input=True)
    student = f"{profile.score:g} ({SCORE_SCALES.get(profile.score_scale, {}).get('label', profile.score_scale)})"
    if profile.score_scale != rec.score_scale:
        return RuleResult("Academic score", student, shown, UNKNOWN,
                          "Your score is on a different grading scale. ScholarPath does not convert between "
                          "scales, so check the provider's own conversion rules.")
    if profile.score >= rec.min_score:
        return RuleResult("Academic score", student, shown, SATISFIED, "Meets the minimum on the same scale.")
    return RuleResult("Academic score", student, shown, FAILED, "Below the minimum on the same scale.")


def evaluate(profile: StudentProfile, rec: ScholarshipRecord) -> MatchResult:
    rules = [
        rule_nationality(profile, rec),
        rule_exclusions(profile, rec),
        _list_rule("Degree", profile.degree, rec.degrees, DEGREES),
        _list_rule("Subject", profile.subject, rec.subjects, SUBJECTS),
    ]
    score_rule = rule_score(profile, rec)
    if score_rule:
        rules.append(score_rule)
    for item in rec.manual_review_items:
        rules.append(RuleResult(
            f"Manual review ({item.category.replace('_', ' ')})", "-", item.text, UNKNOWN,
            "Confirm this yourself on the official page.",
            kind="manual",
        ))
    statuses = {r.status for r in rules}
    if FAILED in statuses:
        overall = OVERALL_FAIL
    elif UNKNOWN in statuses:
        overall = OVERALL_MANUAL
    else:
        overall = OVERALL_MATCH
    return MatchResult(rec.id, overall, rules)


# --- internships (same verdicts, same grouping, same honesty rules) -----------------------

@dataclass
class InternshipProfile:
    degree: str | None = None            # INTERN_DEGREES
    year: str | None = None              # "1".."5" or "graduate"
    final_year: bool = False             # the student's current year is the last of the course
    discipline: str | None = None        # DISCIPLINES
    preferred_place: str | None = None   # a city, "remote" or None; narrows the list only


def validate_internship_profile(profile: InternshipProfile) -> list[str]:
    errors = []
    if profile.degree and profile.degree not in INTERN_DEGREES:
        errors.append("Unknown degree.")
    if profile.year and profile.year not in STUDY_YEARS:
        errors.append("Unknown year of study.")
    if profile.final_year and profile.year == "graduate":
        errors.append("A recent graduate is not in a final year. Choose one or the other.")
    if profile.final_year and not profile.year:
        errors.append("Choose your year of study as well, or untick final year.")
    if profile.discipline and profile.discipline not in DISCIPLINES:
        errors.append("Unknown discipline.")
    return errors


def rule_study_year(profile: InternshipProfile, req) -> RuleResult:
    """Numbered years, "final year" and "recent graduate" are compared without guessing course length:
    a 3rd-year student meets "final year" only when they said this is their final year."""
    shown = {"unrestricted": "Any year (stated)", "unknown": "Not recorded in structured form"}.get(
        req.kind, ", ".join(STUDY_YEARS.get(v, v) for v in req.values))
    if not profile.year:
        return RuleResult("Year of study", "(not provided)", shown, UNKNOWN,
                          "You didn't choose a year of study, so this can't be checked.", missing_input=True)
    student = STUDY_YEARS[profile.year] + (" (final year)" if profile.final_year else "")
    if req.kind == "unknown":
        return RuleResult("Year of study", student, shown, UNKNOWN,
                          "The employer doesn't state a year of study in a form ScholarPath can check.")
    if req.kind == "unrestricted" or profile.year in req.values or (profile.final_year and "final" in req.values):
        return RuleResult("Year of study", student, shown, SATISFIED, f"{student} is accepted.")
    return RuleResult("Year of study", student, shown, FAILED, f"{student} is not one of the years asked for.")


def evaluate_internship(profile: InternshipProfile, rec) -> MatchResult:
    rules = [
        _list_rule("Degree", profile.degree, rec.degrees, INTERN_DEGREES),
        rule_study_year(profile, rec.study_years),
        _list_rule("Discipline", profile.discipline, rec.disciplines, DISCIPLINES),
    ]
    if rec.experience_text:
        rules.append(RuleResult("Manual review (experience)", "-", rec.experience_text, UNKNOWN,
                                "Confirm this yourself on the employer's page.", kind="manual"))
    rules.append(RuleResult("Manual review (full requirements)", "-",
                            "Skills, documents and other conditions in the employer's posting", UNKNOWN,
                            "ScholarPath keeps facts only; read the full posting before applying.", kind="manual"))
    statuses = {r.status for r in rules}
    overall = OVERALL_FAIL if FAILED in statuses else OVERALL_MANUAL if UNKNOWN in statuses else OVERALL_MATCH
    return MatchResult(rec.id, overall, rules)
