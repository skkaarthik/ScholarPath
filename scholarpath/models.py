"""Canonical scholarship record and controlled vocabularies.

The canonical record is the single shape used by the example dataset, the
collectors' JSON output, the import service and the CSV export. Field meanings
are documented in docs/DATA_DICTIONARY.md.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import date

# --- Controlled vocabularies (internal label -> display label) -------------

DEGREES = {
    "bachelor": "Bachelor's",
    "master": "Master's",
    "phd": "PhD / Doctorate",
    "postdoc": "Postdoctoral",
    "non_degree": "Short course / non-degree",
}

FUNDING_CATEGORIES = {
    "full": "Full (tuition + living costs)",
    "tuition_full": "Full tuition only",
    "partial": "Partial / fixed amount",
    "living_only": "Living costs only",
    "unknown": "Not stated",
}

# Subject labels are deliberately coarse and are matched exactly. ScholarPath
# never treats two different labels as equivalent.
SUBJECTS = {
    "agriculture_environment": "Agriculture & environment",
    "arts_design": "Art & design",
    "business_management": "Business & management",
    "computer_science": "Computer science",
    "economics": "Economics",
    "education": "Education",
    "engineering": "Engineering",
    "humanities": "Humanities",
    "law": "Law",
    "medicine_health": "Medicine & health",
    "music_performing_arts": "Music & performing arts",
    "natural_sciences": "Natural sciences",
    "public_policy": "Public policy & development",
    "social_sciences": "Social sciences",
}

# Score scales are identified by ID, never by maximum value: two 4-point scales
# from different systems are NOT comparable.
SCORE_SCALES = {
    "percent_100": {"label": "Percentage (0-100)", "min": 0.0, "max": 100.0},
    "cgpa_10": {"label": "CGPA on a 10-point scale", "min": 0.0, "max": 10.0},
    "gpa_4_us": {"label": "GPA on the US 4.0 scale", "min": 0.0, "max": 4.0},
    "gpa_4_other": {"label": "4-point scale (non-US system)", "min": 0.0, "max": 4.0},
}

RESTRICTION_KINDS = ("unrestricted", "list", "unknown")
EXCLUSION_KINDS = ("none", "list", "unknown")
DEADLINE_KINDS = ("dated", "rolling", "unknown")
DATASET_ORIGINS = ("example", "real_source")
FETCH_METHODS = ("fictional", "live_http", "browser_snapshot")
SOURCE_STATUSES = ("available", "unavailable", "unknown")
REQUIREMENT_KINDS = ("structured", "manual_review")
REQUIREMENT_CATEGORIES = (
    "nationality",
    "degree",
    "subject",
    "academic",
    "language",
    "residence",
    "age",
    "experience",
    "admission",
    "financial_need",
    "documents",
    "other",
)

TRACKER_STATUSES = {
    "interested": "Interested",
    "preparing": "Preparing",
    "applied": "Applied (recorded by you)",
    "result_received": "Result received",
}
TRACKER_OUTCOMES = {
    "awarded": "Awarded",
    "not_selected": "Not selected",
    "waitlisted": "Waitlisted / reserve",
    "withdrawn": "Withdrawn by me",
    "other": "Other",
}


@dataclass
class Restriction:
    """A criterion that may be explicitly unrestricted, an explicit list, or unknown."""

    kind: str
    values: list[str] = field(default_factory=list)


@dataclass
class Exclusions:
    """Explicit nationality exclusions: 'none' (source structure leaves none), 'list', or 'unknown'."""

    kind: str
    values: list[str] = field(default_factory=list)


@dataclass
class Requirement:
    kind: str  # structured | manual_review
    category: str
    text: str


@dataclass
class ScholarshipRecord:
    id: str
    name: str
    provider: str
    host_countries: list[str]
    degrees: Restriction
    subjects: Restriction
    nationalities: Restriction
    nationality_exclusions: Exclusions
    min_score: float | None
    score_scale: str | None
    funding_category: str
    funding_description: str
    deadline_kind: str
    deadline_date: date | None
    deadline_text: str
    eligibility_text: str
    requirements: list[Requirement]
    application_url: str
    source_url: str
    source_name: str
    source_key: str
    award_cycle: str | None
    collected_at: str
    source_fetched_at: str | None
    fetch_method: str
    manual_verified_at: str | None
    dataset_origin: str
    notes: str = ""
    source_status: str = "available"
    # When applications close (see dates.closes_at for the rules):
    deadline_at: str | None = None          # exact closing instant (UTC ISO) when the source states a time
    deadline_timezone: str | None = None    # IANA zone of the source, used for date-only deadlines
    closed_by_source: bool = False          # the official page says applications are closed

    @property
    def manual_review_items(self) -> list[Requirement]:
        return [r for r in self.requirements if r.kind == "manual_review"]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["deadline_date"] = self.deadline_date.isoformat() if self.deadline_date else None
        return data


def stable_id(source_name: str, source_key: str) -> str:
    """Deterministic ID from stable source identity (never Python's hash()).

    Descriptions and deadlines are not part of the identity, so edits on the
    source page update the same record instead of creating a new one.
    """
    raw = f"{source_name.strip().lower()}|{source_key.strip()}".encode("utf-8")
    return "sp-" + hashlib.sha256(raw).hexdigest()[:16]


# --- Internships (v2) -----------------------------------------------------------
# An internship record uses the same deadline fields as a scholarship (deadline_kind,
# deadline_date, deadline_at, deadline_timezone, closed_by_source), so dates.py, the
# deadline badges and the closing rules work unchanged for both opportunity types.

OPPORTUNITY_KINDS = ("scholarship", "internship")

INTERN_DEGREES = {
    "diploma": "Diploma",
    "bachelor": "Bachelor's (B.E., B.Tech, B.Sc., B.Com, BBA, B.A. ...)",
    "master": "Master's (M.Tech, M.Sc., MBA, M.A. ...)",
    "phd": "PhD",
}
# Year of study the employer asks for. "final" and "graduate" are kept apart from the
# numbered years: a final-year student is in year 3, 4 or 5 depending on the course.
STUDY_YEARS = {
    "1": "1st year", "2": "2nd year", "3": "3rd year", "4": "4th year", "5": "5th year",
    "final": "Final year", "graduate": "Recent graduate",
}
DISCIPLINES = {
    "engineering": "Engineering & software",
    "data": "Data & analytics",
    "design": "Design",
    "product": "Product management",
    "business": "Business & operations",
    "finance": "Finance & accounting",
    "marketing": "Marketing & content",
    "research": "Research & science",
    "people": "People & HR",
    "legal": "Legal",
}
WORK_ARRANGEMENTS = {"onsite": "On-site", "hybrid": "Hybrid", "remote": "Remote", "unknown": "Not stated"}
STIPEND_KINDS = {"paid": "Paid (amount stated)", "paid_unstated": "Paid (amount not stated)",
                 "unpaid": "Unpaid", "unknown": "Not stated"}


@dataclass
class SourceLink:
    """Where else the same internship is listed (kept when duplicates are merged)."""

    source_name: str
    url: str


@dataclass
class InternshipRecord:
    id: str
    title: str
    employer: str
    cities: list[str]                  # canonical city names (locations.canonical_city)
    states: list[str]                  # states / union territories of those cities
    location_text: str                 # the location as the source wrote it
    work_arrangement: str              # WORK_ARRANGEMENTS
    disciplines: Restriction           # DISCIPLINES; "unknown" when the role says nothing usable
    degrees: Restriction               # INTERN_DEGREES
    study_years: Restriction           # STUDY_YEARS
    experience_text: str               # e.g. "No prior experience required"; "" when not stated
    eligibility_text: str              # short facts only (never the employer's description text)
    stipend_kind: str                  # STIPEND_KINDS
    stipend_min: int | None            # rupees per month
    stipend_max: int | None
    stipend_text: str
    duration_months: float | None
    duration_text: str
    deadline_kind: str
    deadline_date: date | None
    deadline_text: str
    application_url: str
    source_url: str
    source_name: str
    source_key: str
    collected_at: str
    source_fetched_at: str | None
    fetch_method: str
    manual_verified_at: str | None
    dataset_origin: str
    also_listed: list[SourceLink] = field(default_factory=list)
    notes: str = ""
    source_status: str = "available"
    deadline_at: str | None = None
    deadline_timezone: str | None = None
    closed_by_source: bool = False
    start_text: str = ""

    # The shared screens show every opportunity as "title by provider". For an internship the
    # role fills the title slot and the employer the provider slot.
    @property
    def name(self) -> str:
        return self.title

    @property
    def provider(self) -> str:
        return self.employer

    @property
    def requirements(self) -> list:
        return []

    @property
    def manual_review_items(self) -> list:
        return []

    @property
    def award_cycle(self) -> None:
        return None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["deadline_date"] = self.deadline_date.isoformat() if self.deadline_date else None
        return data


def internship_id(employer: str, title: str, cities: list[str], arrangement: str) -> str:
    """Stable identity of an internship across sources and refreshes.

    The same role at the same employer in the same place is one internship, whichever job
    board lists it, so a repeat refresh (or a second source) updates the record a student
    saved instead of creating a new one. Descriptions, stipends and deadlines are not part
    of the identity.
    """
    def norm(text: str) -> str:
        return " ".join("".join(ch if ch.isalnum() else " " for ch in text.casefold()).split())

    place = ",".join(sorted(norm(c) for c in cities)) or ("remote" if arrangement == "remote" else "india")
    raw = f"internship|{norm(employer)}|{norm(title)}|{place}".encode("utf-8")
    return "in-" + hashlib.sha256(raw).hexdigest()[:16]
