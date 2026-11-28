"""v2 internships below the UI: locations, validation, migration from v1, isolation from
scholarships, filters, the live finder's adapters, deduplication and partial failures.

Everything runs offline: job-board answers come from tests/fixtures/*.json through a fake
fetcher, and every database and output file lives in a temporary folder.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date

import pytest

from scholarpath import config, database, locations
from scholarpath.cleaning import ValidationError, validate_internship
from scholarpath.collectors import internship_facts as facts
from scholarpath.collectors import internship_runner as finder
from scholarpath.collectors.base import FetchError
from scholarpath.collectors.internship_sources import Board, parse_greenhouse, parse_lever
from scholarpath.examples import build_example_internships
from scholarpath.exports import internships_to_csv
from scholarpath.matching import InternshipProfile, evaluate_internship
from scholarpath.models import internship_id
from scholarpath.repository import InternshipFilters, SearchFilters
from scholarpath.services import InternshipService, ScholarPathService, ServiceError

from .conftest import FIXED_TODAY, FIXTURES

GH = Board("greenhouse", "fourkites", "FourKites", "Chennai")
LV = Board("lever", "fampay", "FamPay", "Bengaluru")
FETCHED = "2026-11-12T06:00:00+00:00"


@pytest.fixture
def interns(clock, tmp_path):
    svc = InternshipService(config.MODE_EXAMPLE, db_path=tmp_path / "example.sqlite3", clock=clock)
    svc.import_payload(build_example_internships(FIXED_TODAY, collected_at="2026-11-12T00:00:00+00:00"), "test")
    return svc


def titles(views) -> list[str]:
    return [v.record.title for v in views]


def real(**overrides) -> dict:
    """A minimal valid real internship record."""
    rec = {"title": "Data Analyst Intern", "employer": "Acme", "cities": ["Chennai"], "states": ["Tamil Nadu"],
           "location_text": "Chennai, India", "work_arrangement": "onsite",
           "disciplines": {"kind": "list", "values": ["data"]}, "degrees": {"kind": "unknown", "values": []},
           "study_years": {"kind": "unknown", "values": []}, "stipend_kind": "unknown", "deadline_kind": "unknown",
           "deadline_date": None, "application_url": "https://jobs.example.com/1", "source_url": "https://jobs.example.com",
           "source_name": "Acme (Lever job board)", "source_key": "lever:acme:1", "collected_at": FETCHED,
           "source_fetched_at": FETCHED, "fetch_method": "live_http", "dataset_origin": "real_source"}
    rec.update(overrides)
    rec["id"] = internship_id(rec["employer"], rec["title"], rec["cities"], rec["work_arrangement"])
    return rec


# --- locations ------------------------------------------------------------------------

@pytest.mark.parametrize("text,city,state", [
    ("Bangalore", "Bengaluru", "Karnataka"), ("Bengaluru Urban, KA", "Bengaluru", "Karnataka"),
    ("Madras", "Chennai", "Tamil Nadu"), ("Chennai - India", "Chennai", "Tamil Nadu"),
    ("Gurgaon, Haryana, India", "Delhi NCR", "Haryana"), ("Noida, Uttar Pradesh", "Delhi NCR", "Uttar Pradesh"),
    ("Bombay", "Mumbai", "Maharashtra"), ("Cochin", "Kochi", "Kerala"), ("Kovai", "Coimbatore", "Tamil Nadu"),
    ("Hyderabad, Telangana", "Hyderabad", "Telangana"), ("Kolkata", "Kolkata", "West Bengal"),
    ("Ahmedabad", "Ahmedabad", "Gujarat"), ("Pune", "Pune", "Maharashtra"),
])
def test_place_names_are_normalised(text, city, state):
    place = locations.parse_location(text)
    assert place["cities"] == [city] and state in place["states"] and place["india"]


def test_chennai_then_bengaluru_lead_every_list_of_places():
    assert locations.order_places(["Pune", "Bengaluru", "Ahmedabad", "Chennai"]) == ["Chennai", "Bengaluru",
                                                                                    "Ahmedabad", "Pune"]
    assert locations.order_states(["Kerala", "Karnataka", "Tamil Nadu"]) == ["Tamil Nadu", "Karnataka", "Kerala"]


def test_unknown_places_are_ignored_and_arrangements_read_only_when_stated():
    assert locations.parse_location("Singapore")["india"] is False
    assert locations.parse_location("Remote - India") == {"cities": [], "states": [], "india": True,
                                                         "arrangement": "remote"}
    assert locations.parse_location("Chennai")["arrangement"] == "unknown"
    assert locations.parse_location("Chennai (Hybrid)")["arrangement"] == "hybrid"


# --- validation and identity ----------------------------------------------------------------

def test_a_valid_internship_and_its_display_slots():
    rec = validate_internship(real())
    assert (rec.name, rec.provider) == ("Data Analyst Intern", "Acme")       # role and employer fill the slots


@pytest.mark.parametrize("change,reason", [
    ({"stipend_kind": "paid"}, "needs a stated amount"),
    ({"stipend_min": 5000}, "need stipend_kind 'paid'"),
    ({"work_arrangement": "office"}, "work_arrangement"),
    ({"deadline_kind": "dated"}, "deadline_date: required"),
    ({"application_url": "javascript:alert(1)"}, "application_url"),
    ({"fetch_method": "fictional"}, "fictional"),
])
def test_invalid_internships_are_rejected_with_a_reason(change, reason):
    with pytest.raises(ValidationError) as err:
        validate_internship(real(**change))
    assert any(reason in r for r in err.value.reasons)


def test_the_same_internship_has_the_same_id_whichever_board_lists_it():
    a = internship_id("FourKites", "Product Support - Intern", ["Chennai"], "onsite")
    assert a == internship_id("fourkites", "Product Support – Intern", ["Chennai"], "hybrid")
    assert a != internship_id("FourKites", "Product Support - Intern", ["Bengaluru"], "onsite")


# --- migration from a v1 database ----------------------------------------------------------

def test_a_v1_database_upgrades_without_touching_scholarship_data(tmp_path, clock, example_records):
    path = tmp_path / "v1.sqlite3"
    database.migrate(path, target=3)                                      # the schema v1 shipped with
    v1 = ScholarPathService(config.MODE_EXAMPLE, db_path=path, clock=clock)
    with database.connect(path) as conn:                                  # v1 code never stored this meta row
        assert database.schema_version(conn) == 3
    v1.import_records(example_records, source_file="v1")
    first, second = example_records[0]["id"], example_records[1]["id"]
    v1.save(first)
    v1.mark_applied(second, date(2026, 11, 10))
    v1.update_application(second, "result_received", submitted_date=date(2026, 11, 10), outcome="awarded",
                          notes="kept", history_note="Heard back")

    def snapshot():
        with sqlite3.connect(path) as conn:
            return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
                    for t in ("scholarships", "shortlist", "applications", "application_history")}

    before = snapshot()
    assert database.migrate(path) == 4
    assert snapshot() == before                                           # every v1 row unchanged
    after = ScholarPathService(config.MODE_EXAMPLE, db_path=path, clock=clock)
    assert after.saved_ids() == [first] and after.get_application(second).outcome == "awarded"
    assert [h["note"] for h in after.application_history(second)] == ["Heard back", "Marked as applied"]
    interns = InternshipService(config.MODE_EXAMPLE, db_path=path, clock=clock)
    assert interns.saved_ids() == [] and interns.applications() == []
    with sqlite3.connect(path) as conn:
        assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2, 3, 4]
    assert database.migrate(path) == 4                                    # running it again changes nothing
    assert snapshot() == before


# --- isolation --------------------------------------------------------------------------------

def test_saved_items_and_applications_never_mix_between_types(interns, clock, example_records):
    scholarships = ScholarPathService(config.MODE_EXAMPLE, db_path=interns.db_path, clock=clock)
    scholarships.import_records(example_records, source_file="test")
    internship = interns.search()[0].record.id
    scholarship = scholarships.search()[0].record.id
    interns.save(internship)
    interns.mark_applied(internship, FIXED_TODAY)
    scholarships.save(scholarship)
    assert interns.saved_ids() == [internship] and scholarships.saved_ids() == [scholarship]
    assert [a.item_id for a in interns.applications()] == [internship]
    assert scholarships.applications() == []
    with pytest.raises(ServiceError):
        interns.save(scholarship)                                         # a scholarship ID is not an internship
    with pytest.raises(ServiceError):
        scholarships.mark_applied(internship, FIXED_TODAY)
    assert interns.overview()["saved"] == 1 and scholarships.overview()["saved"] == 1


def test_example_and_real_internships_stay_apart(interns, clock, tmp_path):
    real_svc = InternshipService(config.MODE_REAL, db_path=tmp_path / "real.sqlite3", clock=clock)
    with pytest.raises(Exception):
        real_svc.import_payload(build_example_internships(FIXED_TODAY), "wrong dataset")
    real_svc.import_records([real()])
    assert titles(real_svc.search()) == ["Data Analyst Intern"]
    assert "Acme" not in {v.record.employer for v in interns.search(InternshipFilters(include_closed=True))}


def test_mark_applied_returns_an_existing_applied_entry_before_validating(interns):
    rec = interns.search()[0].record.id
    first = interns.mark_applied(rec, FIXED_TODAY)
    again = interns.mark_applied(rec, date(2099, 1, 1))                  # invalid date, but already applied
    assert again.id == first.id and again.submitted_date == FIXED_TODAY
    assert len(interns.application_history(rec)) == 1
    with pytest.raises(ServiceError):
        interns.mark_applied(interns.search()[1].record.id, date(2099, 1, 1))


def test_unsave_keeps_the_application_and_remove_keeps_the_record(interns):
    rec = interns.search()[0].record.id
    interns.save(rec)
    interns.mark_applied(rec, FIXED_TODAY)
    assert interns.unsave(rec) and interns.get_application(rec) is not None
    assert interns.remove_application(rec) and interns.get(rec) is not None
    assert not interns.remove_application(rec)


# --- filters --------------------------------------------------------------------------------

def test_quick_places_respect_the_choice(interns):
    chennai = interns.search(InternshipFilters(place="chennai"))
    assert chennai and all("Chennai" in v.record.cities for v in chennai)
    bengaluru = interns.search(InternshipFilters(place="bengaluru"))
    assert bengaluru and all("Bengaluru" in v.record.cities for v in bengaluru)
    remote = interns.search(InternshipFilters(place="remote"))
    assert remote and all(v.record.work_arrangement == "remote" for v in remote)
    assert len(interns.search(InternshipFilters(place="all_india"))) == len(interns.search())
    assert "Research Intern, Materials Lab" not in titles(chennai)        # closed ones never in Find


def test_city_state_arrangement_discipline_stipend_and_deadline_filters(interns):
    assert titles(interns.search(InternshipFilters(cities=["Coimbatore"]))) == ["Mechanical Design Intern"]
    tamil_nadu = interns.search(InternshipFilters(states=["Tamil Nadu"]))
    assert {"Mechanical Design Intern", "Data Analyst Intern"} <= set(titles(tamil_nadu))
    assert all(v.record.work_arrangement == "hybrid" for v in interns.search(InternshipFilters(arrangements=["hybrid"])))
    legal = interns.search(InternshipFilters(disciplines=["legal"]))
    assert titles(legal) == ["Legal Intern"]
    unpaid = interns.search(InternshipFilters(stipends=["unpaid"]))
    assert unpaid and all(v.record.stipend_kind == "unpaid" for v in unpaid)
    rolling = interns.search(InternshipFilters(deadline_statuses=["rolling"]))
    assert rolling and all(v.status == "rolling" for v in rolling)
    both = interns.search(InternshipFilters(place="chennai", disciplines=["data"]))
    assert titles(both) == ["Data Analyst Intern"]                        # AND across filters
    assert titles(interns.search(InternshipFilters(text="kaveri"))) == ["Embedded Systems Intern"]


def test_an_unstated_discipline_never_matches_a_discipline_filter(interns, clock, tmp_path):
    svc = InternshipService(config.MODE_REAL, db_path=tmp_path / "r.sqlite3", clock=clock)
    svc.import_records([real(disciplines={"kind": "unknown", "values": []})])
    assert svc.search(InternshipFilters(disciplines=["data"])) == []
    assert len(svc.search()) == 1


def test_sorting_by_deadline_and_by_stipend(interns):
    by_deadline = interns.search(sort="deadline")
    dated = [v.record.deadline_date for v in by_deadline if v.status == "open"]
    assert dated == sorted(dated)
    stipends = [v.record.stipend_max or v.record.stipend_min for v in interns.search(sort="stipend")]
    stated = [s for s in stipends if s is not None]
    assert stated == sorted(stated, reverse=True) and stipends[: len(stated)] == stated


# --- Check my fit ------------------------------------------------------------------------------

def test_internship_fit_never_counts_unknown_as_met(interns):
    rec = next(v.record for v in interns.search() if v.record.title == "Data Analyst Intern")
    result = evaluate_internship(InternshipProfile(degree="bachelor", year="4", final_year=True,
                                                   discipline="data"), rec)
    assert result.group == "fit"
    assert evaluate_internship(InternshipProfile(degree="phd"), rec).group == "no_fit"
    assert evaluate_internship(InternshipProfile(), rec).group == "missing"
    third = evaluate_internship(InternshipProfile(year="3"), rec)
    assert next(r for r in third.rules if r.rule == "Year of study").status == "satisfied"
    two = evaluate_internship(InternshipProfile(year="2"), rec)
    assert next(r for r in two.rules if r.rule == "Year of study").status == "failed"


def test_preferred_place_only_narrows_the_list(interns):
    results = interns.match(InternshipProfile(preferred_place="Chennai"))
    assert results and all("Chennai" in v.record.cities for v, _ in results)


# --- facts read from postings --------------------------------------------------------------------

def test_facts_are_read_only_when_stated():
    assert facts.stipend("Stipend of Rs. 15k per month")["stipend_min"] == 15000
    assert facts.stipend("salary INR 3 lakh per annum")["stipend_kind"] == "paid_unstated"   # not monthly
    assert facts.stipend("This is an unpaid internship")["stipend_kind"] == "unpaid"
    assert facts.stipend("Great team, free snacks")["stipend_kind"] == "unknown"
    assert facts.duration("The internship duration is 3-6 months") == (6.0, "3-6 months")
    assert facts.duration("We have 5 months of runway") == (None, "")                       # not about the internship
    assert facts.is_internship("Summer Internship 2027") and not facts.is_internship("International Sales Manager")
    assert facts.disciplines("UX Design Intern")["values"] == ["design"]
    assert facts.disciplines("Intern")["kind"] == "unknown"


# --- adapters --------------------------------------------------------------------------------

def test_greenhouse_adapter_keeps_internships_in_india_only():
    records, listed = parse_greenhouse(GH, (FIXTURES / "greenhouse_jobs.json").read_text(), FETCHED)
    assert listed == 5
    assert [r["title"] for r in records] == ["Product Support - Intern", "Software Engineering Intern"]
    support, engineering = records
    assert support["cities"] == ["Chennai"] and support["stipend_min"] == 20000 and support["duration_months"] == 6
    assert support["study_years"]["values"] == ["final"] and "bachelor" in support["degrees"]["values"]
    assert support["experience_text"].startswith("No prior experience")
    assert engineering["cities"] == ["Bengaluru"] and engineering["work_arrangement"] == "hybrid"
    assert (engineering["deadline_kind"], engineering["deadline_date"]) == ("dated", "2026-12-15")
    for rec in records:
        validate_internship(rec)
        assert rec["fetch_method"] == "live_http" and rec["dataset_origin"] == "real_source"
    assert "Final year" in support["eligibility_text"]                  # facts in ScholarPath's words
    assert "tenure" not in support["eligibility_text"]                  # never the employer's text


def test_lever_adapter_reads_work_type_salary_range_and_country():
    records, listed = parse_lever(LV, (FIXTURES / "lever_postings.json").read_text(), FETCHED)
    assert listed == 5
    by_title = {r["title"]: r for r in records}
    assert set(by_title) == {"Backend Engineering Intern", "People Operations Associate", "Data Analyst Intern"}
    assert by_title["People Operations Associate"]["stipend_kind"] == "unpaid"        # Lever's "Intern" work type
    assert by_title["Data Analyst Intern"]["work_arrangement"] == "remote"
    assert (by_title["Data Analyst Intern"]["stipend_min"], by_title["Data Analyst Intern"]["stipend_max"]) == (25000, 30000)
    assert by_title["Backend Engineering Intern"]["stipend_kind"] == "paid_unstated"
    assert by_title["People Operations Associate"]["cities"] == ["Bengaluru"]        # "Bangalore" normalised


# --- the finder: dedupe, partial failure, stable identity ---------------------------------------

@dataclass
class Page:
    html: str
    fetched_at: str = FETCHED


class FakeFetcher:
    def __init__(self, answers: dict):
        self.answers = answers

    def get(self, url):
        answer = self.answers[url]
        if isinstance(answer, Exception):
            raise answer
        return Page(answer)


def gh_answer(*jobs) -> str:
    return json.dumps({"jobs": list(jobs)})


def job(job_id, title="Data Analyst Intern", location="Chennai, India", company="Acme", deadline=None):
    return {"id": job_id, "title": title, "company_name": company, "location": {"name": location},
            "absolute_url": f"https://boards.example/{job_id}", "content": "", "application_deadline": deadline}


A = Board("greenhouse", "acme", "Acme", "Chennai")
B = Board("lever", "acme", "Acme", "Chennai")          # the same employer on a second platform


def lv_answer(*posts) -> str:
    return json.dumps(list(posts))


def post(post_id, title="Data Analyst Intern", location="Chennai"):
    return {"id": post_id, "text": title, "country": "IN", "workplaceType": "onsite",
            "categories": {"location": location, "commitment": "Intern"},
            "hostedUrl": f"https://lever.example/{post_id}", "descriptionPlain": "", "lists": []}


def test_duplicates_merge_within_and_across_sources_keeping_every_link():
    fetcher = FakeFetcher({A.api_url: gh_answer(job(1), job(2)), B.api_url: lv_answer(post(9))})
    run = finder.collect((A, B), fetcher)
    assert len(run.records) == 1 and run.duplicates_merged == 2
    rec = run.records[0]
    assert rec["source_name"] == A.source_name                           # the earlier board stays the main listing
    assert {link["url"] for link in rec["also_listed"]} == {"https://boards.example/2", "https://lever.example/9"}
    validate_internship(rec)


def test_a_failed_source_keeps_its_last_records_and_the_others_still_refresh(tmp_path):
    out = tmp_path / "real_internships.json"
    first = finder.collect((A, B), FakeFetcher({A.api_url: gh_answer(job(1)),
                                                B.api_url: lv_answer(post(5, "UX Design Intern"))}))
    finder.write_dataset(first, out)
    previous = finder.load_previous(out)
    second = finder.collect((A, B), FakeFetcher({A.api_url: gh_answer(job(1), job(3, "Finance Intern", "Pune")),
                                                 B.api_url: FetchError("timed out after 3 attempts")}),
                            previous=previous)
    assert [s["status"] for s in second.sources] == ["ok", "failed"]
    failed = second.sources[1]
    assert failed["carried_over"] == 1 and failed["last_success_at"] == FETCHED and "timed out" in failed["error"]
    assert {r["title"] for r in second.records} == {"Data Analyst Intern", "Finance Intern", "UX Design Intern"}
    finder.write_dataset(second, out)
    assert finder.coverage(second.records) == {"unique": 3, "chennai": 2, "bengaluru": 0, "rest_of_india": 1, "remote": 0}


def test_nothing_is_written_when_no_source_could_be_read(tmp_path):
    out = tmp_path / "real_internships.json"
    out.write_text('{"records": [], "sources": [], "dataset_version": "old"}')
    run = finder.collect((A,), FakeFetcher({A.api_url: FetchError("HTTP 503")}))
    with pytest.raises(finder.InternshipCollectionError):
        finder.write_dataset(run, out)
    assert json.loads(out.read_text())["dataset_version"] == "old"


def test_invalid_postings_are_rejected_without_stopping_the_board():
    bad = job(7)
    bad["absolute_url"] = "not a link"
    run = finder.collect((A,), FakeFetcher({A.api_url: gh_answer(job(1, "Design Intern"), bad)}))
    assert [r["title"] for r in run.records] == ["Design Intern"] and len(run.rejected) == 1


def test_repeat_refreshes_keep_saves_and_close_postings_that_are_gone(tmp_path, clock):
    svc = InternshipService(config.MODE_REAL, db_path=tmp_path / "real.sqlite3", clock=clock)
    out = tmp_path / "real_internships.json"
    finder.write_dataset(finder.collect((A, B), FakeFetcher({A.api_url: gh_answer(job(1), job(2, "Finance Intern")),
                                                             B.api_url: lv_answer(post(5, "UX Design Intern"))})), out)
    assert svc.sync_published(out) == "imported" and svc.sync_published(out) == "current"
    analyst = next(v.record.id for v in svc.search() if v.record.title == "Data Analyst Intern")
    ux = next(v.record.id for v in svc.search() if v.record.title == "UX Design Intern")
    svc.save(analyst)
    svc.mark_applied(analyst, FIXED_TODAY)
    svc.save(ux)

    # Next day: board A no longer lists the analyst role; board B is down.
    second = finder.collect((A, B), FakeFetcher({A.api_url: gh_answer(job(2, "Finance Intern")),
                                                 B.api_url: FetchError("HTTP 503")}),
                            previous=finder.load_previous(out))
    second.generated_at = "2026-11-13T06:00:00+00:00"
    finder.write_dataset(second, out)
    assert svc.sync_published(out) == "imported"
    assert svc.saved_ids() == [analyst, ux]                               # same IDs: saves kept
    assert svc.get_application(analyst).status == "applied"
    assert svc.get(analyst).status == "expired"                           # gone from a board that answered
    assert svc.get(ux).status != "expired"                                # its board failed: left as it was
    assert set(titles(svc.search())) == {"Finance Intern", "UX Design Intern"}
    assert svc.overview()["sources"][1]["status"] == "failed"


def test_test_fixtures_never_reach_the_real_published_dataset(isolated_data_dir):
    run = finder.collect((A,), FakeFetcher({A.api_url: gh_answer(job(1))}))
    written = finder.write_dataset(run)                                   # default path, as the command uses
    assert written == config.REAL_INTERNSHIPS_FILE
    assert str(written).startswith(str(isolated_data_dir))                # conftest's temporary folder
    assert written != config.PROJECT_ROOT / "data" / "collected" / "real_internships.json"


# --- exports and assistant ---------------------------------------------------------------------------

def test_internship_csv_protects_against_formula_injection(interns, clock, tmp_path):
    svc = InternshipService(config.MODE_REAL, db_path=tmp_path / "r.sqlite3", clock=clock)
    svc.import_records([real(title="=HYPERLINK(1) Intern")])
    text = internships_to_csv([v.record for v in svc.search()], FIXED_TODAY, svc.now())
    assert "'=HYPERLINK(1) Intern" in text and "deadline_status" in text.splitlines()[0]


def test_the_assistant_answers_from_internship_records_in_demo_mode(interns):
    reply = interns.chat("Which internships close soonest?", [])
    assert reply.demo and "Internships in ScholarPath" in reply.text
    assert all(hasattr(ref.view.record, "employer") for ref in reply.references)
    progress = interns.chat("Where do my applications stand?", [])
    assert "no applications recorded" in progress.text and "internship's Review page" in progress.text
