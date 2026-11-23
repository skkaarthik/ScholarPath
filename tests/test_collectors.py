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


def test_live_fetcher_says_when_the_site_refused_robots_txt_instead_of_blaming_robots_rules():
    session = FakeSession({"https://example.org/robots.txt": [FakeResponse(403)]})
    with pytest.raises(FetchError, match=r"refused access \(robots.txt answered HTTP 403\)") as info:
        fetcher(session).get("https://example.org/page")
    assert info.value.status == 403 and "disallowed by robots.txt" not in str(info.value)
    assert session.calls == ["https://example.org/robots.txt"]               # the page itself is never fetched


def test_live_fetcher_reports_404_status_for_unavailable_pages():
    session = FakeSession({
        "https://example.org/robots.txt": [FakeResponse(404)],
        "https://example.org/gone": [FakeResponse(404)],
    })
    with pytest.raises(FetchError) as info:
        fetcher(session).get("https://example.org/gone")
    assert info.value.status == 404


def test_cscuk_reads_exact_closing_times_and_pages_that_say_closed():
    """Fixture-based (saved pages of 12 Nov 2026; the live pages read through a browser on
    19 Nov 2026 said the same). An exact time with its zone becomes deadline_at; "now closed"
    marks the record closed without inventing a date."""
    from scholarpath.collectors.runner import make_fetcher

    report = run_collection(["cscuk"], use_snapshots=True, fetcher_factory=make_fetcher)
    by_name = {r["name"]: r for r in report.records}
    shared = by_name["Commonwealth Shared Scholarships"]
    assert (shared["deadline_date"], shared["deadline_at"]) == ("2026-12-08", "2026-12-08T16:00:00+00:00")
    assert shared["closed_by_source"] is False and shared["deadline_timezone"] == "Europe/London"
    masters = by_name["Commonwealth Master’s Scholarships"]
    assert masters["closed_by_source"] is True
    assert masters["deadline_kind"] == "unknown" and masters["deadline_at"] is None   # "20 October" has no year


@pytest.mark.parametrize("sentence, day, expected", [
    ("The closing date is 16:00 GMT on Tuesday 8 December 2026.", "2026-12-08", "2026-12-08T16:00:00+00:00"),
    ("Closes 16:00 BST on 20 October 2026.", "2026-10-20", "2026-10-20T15:00:00+00:00"),
    ("Deadline: 23:59 (CET), 15 January 2027.", "2027-01-15", "2027-01-15T22:59:00+00:00"),
    ("Deadline 5pm GMT 1 March 2027", "2027-03-01", "2027-03-01T17:00:00+00:00"),
    ("The closing date is 8 December 2026.", "2026-12-08", None),                   # no time: date-only rule
    ("Closes at 16:00 on 8 December 2026.", "2026-12-08", None),                    # no zone: not guessed
    ("16:00 GMT on Tuesday 20 October.", None, None),                                # no year: unknown
])
def test_closing_times_are_read_only_when_time_zone_and_full_date_are_stated(sentence, day, expected):
    from datetime import date

    from scholarpath.collectors.htmltools import parse_closing_time

    assert parse_closing_time(sentence, date.fromisoformat(day) if day else None) == expected


# --- DAAD (fixture-based: one entry copied verbatim from the live listing of 19 Nov 2026) ----

class _Pages:
    """Serves given HTML per listing page number; records which pages were asked for."""

    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def get(self, url):
        number = int(url.split("&page=")[1].split("&")[0])
        self.asked.append(number)
        return FetchedPage(url, self.pages[number], "2026-11-19T10:00:00+00:00", "browser_snapshot")


def _daad_fixture():
    return (FIXTURES / "daad_listing_one_entry.html").read_text(encoding="utf-8")


def test_daad_listing_entry_becomes_a_cautious_valid_record():
    from scholarpath.collectors import daad

    items = list(daad.collect(_Pages({1: _daad_fixture()}), "2026-11-19T10:00:00+00:00"))
    assert [kind for kind, _ in items] == ["record"]
    record = validate_record(items[0][1])
    assert record.name == "Study Scholarships - Master Studies for All Academic Disciplines"
    assert record.provider == "DAAD" and record.host_countries == ["Germany"]
    assert (record.degrees.kind, record.degrees.values) == ("list", ["master"])          # "Graduates"
    assert record.subjects.kind == "unrestricted"                                         # all 7 subject groups
    assert record.nationalities.kind == "unknown"                                          # "Only specified"
    assert record.deadline_kind == "unknown" and record.deadline_date is None             # never guessed
    assert record.source_url.startswith("https://www2.daad.de/") and "detail=50026200" in record.source_url
    assert record.source_key == "50026200" and record.manual_verified_at is None


def test_daad_records_keep_facts_only_and_never_copy_daads_description_text():
    from scholarpath.collectors import daad

    items = list(daad.collect(_Pages({1: _daad_fixture()}), "2026-11-19T10:00:00+00:00"))
    record = items[0][1]
    stored = repr(record)
    assert "wishing to continue their academic training" not in stored                   # DAAD's summary text
    assert record["eligibility_text"].startswith("DAAD programme for: Graduates.")
    assert "Country rule on DAAD: Only specified." in record["eligibility_text"]


def test_daad_follows_pages_until_the_stated_total_and_never_imports_a_partial_list():
    from scholarpath.collectors import daad

    one = _daad_fixture()
    two_total = one.replace("1 Scholarship options", "2 Scholarship options")
    second = two_total.replace("detail=50026200", "detail=57742121").replace(
        "Study Scholarships - Master Studies for All Academic Disciplines", "Research Grants in Germany")
    pages = _Pages({1: two_total, 2: second})
    items = list(daad.collect(pages, "2026-11-19T10:00:00+00:00"))
    assert pages.asked == [1, 2] and [k for k, _ in items] == ["record", "record"]
    stuck = _Pages({1: two_total, 2: two_total})                                            # page 2 adds nothing
    items = list(daad.collect(stuck, "2026-11-19T10:00:00+00:00"))
    assert [k for k, _ in items] == ["failed"] and "Only 1 of 2" in items[0][1]["error"]


def test_daad_is_configured_but_not_enabled_until_verified_live():
    from scholarpath.collectors import daad
    from scholarpath.collectors.runner import SOURCES, enabled_source_ids

    assert "daad" in SOURCES and daad.ENABLED is False
    assert enabled_source_ids() == ["cscuk", "great_india"]
