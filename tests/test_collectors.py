"""Phase 1: collectors - parsing saved HTML, structure errors, safe writes, polite fetching."""

import json

import pytest
import requests

from scholarpath.cleaning import validate_record
from scholarpath.collectors import cscuk, great
from scholarpath.collectors.base import FetchedPage, FetchError, LiveFetcher, StructureError
from scholarpath.collectors.runner import CollectionError, CollectionReport, run_collection, write_collection

from .conftest import FIXTURES, real_record

NOW = "2026-11-12T10:00:00+00:00"


def page(name: str, url: str) -> FetchedPage:
    return FetchedPage(url=url, html=(FIXTURES / name).read_text(encoding="utf-8"), fetched_at=NOW,
                       method="browser_snapshot")


# --- CSC parser -----------------------------------------------------------------

def test_cscuk_parses_structured_fields_and_keeps_original_wording():
    raw = cscuk.parse_page(page("cscuk_minimal.html", "https://cscuk.fcdo.gov.uk/scholarships/example/"), NOW)
    rec = validate_record(raw)
    assert rec.nationalities.kind == "list"
    assert rec.nationalities.values == ["Bangladesh", "India", "Saint Vincent and The Grenadines", "The Gambia"]
    assert rec.degrees.values == ["master"]
    assert rec.subjects.kind == "unknown"  # not published as a structured list
    assert rec.deadline_kind == "dated" and rec.deadline_date.isoformat() == "2026-12-08"
    assert "16:00 GMT" in rec.deadline_text  # time kept as published text, not invented
    assert rec.award_cycle == "2027/28"
    assert rec.funding_category == "full"
    assert "permanently resident" in rec.eligibility_text
    categories = {(r.kind, r.category) for r in rec.requirements}
    assert ("structured", "nationality") in categories
    assert ("manual_review", "residence") in categories  # residence never becomes nationality
    assert ("manual_review", "academic") in categories
    assert not any("no age limit" in r.text.lower() for r in rec.requirements)


def test_cscuk_date_without_year_is_unknown_not_guessed():
    raw = cscuk.parse_page(page("cscuk_no_year.html", "https://cscuk.fcdo.gov.uk/scholarships/phd/"), NOW)
    rec = validate_record(raw)
    assert rec.deadline_kind == "unknown" and rec.deadline_date is None
    assert "20 October" in rec.deadline_text
    assert "no year" in rec.notes and "now closed" in rec.notes
    assert rec.degrees.values == ["phd"]
    assert rec.funding_category == "tuition_full"


def test_cscuk_missing_section_gives_useful_error():
    with pytest.raises(StructureError, match="countries"):
        cscuk.parse_page(page("cscuk_missing_section.html", "https://cscuk.fcdo.gov.uk/x/"), NOW)


# --- GREAT parser ---------------------------------------------------------------

LISTING_URL = "https://study-uk.britishcouncil.org/scholarships-funding/great-scholarships/india"


def test_great_listing_follows_only_allowed_detail_links_and_reads_shared_criteria():
    listing = great.parse_listing(page("great_listing_minimal.html", LISTING_URL))
    assert listing["country"] == "India"
    assert [u["name"] for u in listing["universities"]] == ["Example University", "Course List College"]
    assert all(u["url"].startswith("https://study-uk.britishcouncil.org/") for u in listing["universities"])
    assert len(listing["criteria"]) == 2


def test_great_detail_all_courses_is_unrestricted_and_ignores_marketing_and_footer():
    listing = great.parse_listing(page("great_listing_minimal.html", LISTING_URL))
    url = "https://study-uk.britishcouncil.org/scholarships-funding/great-scholarships/example-university"
    rec = validate_record(great.parse_detail(page("great_detail_all_courses.html", url), listing, NOW))
    assert rec.provider == "Example University"
    assert rec.nationalities.values == ["India", "Thailand"]
    assert rec.subjects.kind == "unrestricted"
    assert rec.deadline_date.isoformat() == "2026-04-24"  # not 1999 (marketing) or 2020 (footer)
    assert rec.application_url == "https://example.ac.uk/great"
    assert rec.award_cycle == "2026-27" and "£13,000" in rec.funding_description
    assert rec.funding_category == "partial"
    assert any(r.category == "language" for r in rec.manual_review_items)


def test_great_course_list_stays_unknown_and_unsafe_link_is_not_used():
    listing = great.parse_listing(page("great_listing_minimal.html", LISTING_URL))
    url = "https://study-uk.britishcouncil.org/scholarships-funding/great-scholarships/course-list-college"
    rec = validate_record(great.parse_detail(page("great_detail_course_list.html", url), listing, NOW))
    assert rec.subjects.kind == "unknown"
    assert any("LLM Law and Technology" in r.text for r in rec.manual_review_items)
    assert rec.deadline_kind == "unknown"
    assert rec.application_url == url  # javascript: link rejected, falls back to the official page


def test_great_broken_layout_raises_structure_error():
    with pytest.raises(StructureError):
        great.parse_detail(page("great_detail_broken.html", "https://study-uk.britishcouncil.org/x"), {}, NOW)


def test_saved_snapshots_parse_into_sixteen_valid_real_records():
    report = run_collection(["cscuk", "great_india"], use_snapshots=True, collected_at=NOW)
    assert report.counts == {"accepted": 16, "rejected": 0, "duplicates": 0, "failed": 0}
    shared = next(r for r in report.records if r["name"] == "Commonwealth Shared Scholarships")
    assert shared["deadline_date"] == "2026-12-08" and shared["degrees"]["values"] == ["master"]
    assert all(r["dataset_origin"] == "real_source" for r in report.records)
    assert all(r["fetch_method"] == "browser_snapshot" for r in report.records)


# --- safe writing ------------------------------------------------------------------

def test_empty_scrape_is_an_error_and_does_not_touch_existing_file(tmp_path):
    out = tmp_path / "real.json"
    out.write_text(json.dumps({"records": [real_record()]}), encoding="utf-8")
    before = out.read_text(encoding="utf-8")
    with pytest.raises(CollectionError, match="0 valid records"):
        write_collection(CollectionReport(failed=[{"url": "x", "error": "boom"}]), out)
    assert out.read_text(encoding="utf-8") == before


def test_partial_scrape_goes_to_separate_file_and_merge_keeps_absent_records(tmp_path):
    out = tmp_path / "real.json"
    old = real_record(source_key="old-page", name="Old Scholarship")
    out.write_text(json.dumps({"records": [old]}), encoding="utf-8")
    new = real_record(source_key="new-page", name="New Scholarship")
    partial = CollectionReport(records=[new], failed=[{"url": "y", "error": "timeout", "status": None}])
    target = write_collection(partial, out)
    assert target != out and ".partial-" in target.name
    assert json.loads(out.read_text())["records"] == [old]  # main file unchanged

    complete = CollectionReport(records=[new])
    assert write_collection(complete, out) == out
    names = {r["name"] for r in json.loads(out.read_text())["records"]}
    assert names == {"Old Scholarship", "New Scholarship"}  # absence is not deletion


# --- polite live fetching (no network: fake session) -----------------------------

class FakeResponse:
    def __init__(self, status: int, text: str = ""):
        self.status_code, self.text = status, text


class FakeSession:
    def __init__(self, responses: dict[str, list]):
        self.responses = responses
        self.headers: dict = {}
        self.calls: list[str] = []

    def get(self, url, timeout):
        self.calls.append(url)
        item = self.responses[url].pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def fetcher(session) -> LiveFetcher:
    return LiveFetcher({"example.org"}, session=session, delay_seconds=0, sleep=lambda s: None)


def test_live_fetcher_retries_transient_errors_then_succeeds():
    session = FakeSession({
        "https://example.org/robots.txt": [FakeResponse(404)],
        "https://example.org/page": [requests.ConnectionError("reset"), FakeResponse(503), FakeResponse(200, "<p>ok</p>")],
    })
    result = fetcher(session).get("https://example.org/page")
    assert result.html == "<p>ok</p>" and result.method == "live_http"
    assert session.calls.count("https://example.org/page") == 3


def test_live_fetcher_gives_up_after_bounded_retries():
    session = FakeSession({
        "https://example.org/robots.txt": [FakeResponse(404)],
        "https://example.org/page": [FakeResponse(503)] * 3,
    })
    with pytest.raises(FetchError, match="gave up after 3"):
        fetcher(session).get("https://example.org/page")


def test_live_fetcher_respects_robots_and_host_allow_list():
    session = FakeSession({"https://example.org/robots.txt": [FakeResponse(200, "User-agent: *\nDisallow: /private")]})
    with pytest.raises(FetchError, match="robots"):
        fetcher(session).get("https://example.org/private/page")
    with pytest.raises(FetchError, match="allow-list"):
        fetcher(session).get("https://evil.example.com/page")


def test_live_fetcher_reports_404_status_for_unavailable_pages():
    session = FakeSession({
        "https://example.org/robots.txt": [FakeResponse(404)],
        "https://example.org/gone": [FakeResponse(404)],
    })
    with pytest.raises(FetchError) as info:
        fetcher(session).get("https://example.org/gone")
    assert info.value.status == 404
