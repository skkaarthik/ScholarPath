"""British Council Study UK - GREAT Scholarships (study-uk.britishcouncil.org).

GREAT Scholarships are a UK government (British Council) campaign delivered
with UK universities. robots.txt (checked 2026-11-12) only disallows two
thank-you pages. The collector starts from the configured country listing
page (India), follows the per-university pages it links to, and builds one
record per university page. Each university page lists the nationalities it
accepts, the award value, eligible courses and (usually) a deadline.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from ..models import stable_id
from .base import FetchedPage, StructureError
from .htmltools import blocks, parse_full_date, sentence_containing, soup_of

SOURCE_ID = "great_india"
SOURCE_NAME = "British Council Study UK - GREAT Scholarships"
ALLOWED_HOSTS = {"study-uk.britishcouncil.org"}
LISTING_URL = "https://study-uk.britishcouncil.org/scholarships-funding/great-scholarships/india"
DETAIL_PREFIX = "/scholarships-funding/great-scholarships/"

_STOP_HEADINGS = re.compile(r"^(see also|sign up to our newsletter)", re.I)
_SKIP_SECTIONS = re.compile(r"^(why |key subjects)", re.I)


def _main(page: FetchedPage):
    soup = soup_of(page.html)
    return soup.find("main") or soup.body or soup


def _flat(page: FetchedPage) -> list:
    """Ordered blocks of the main content, minus marketing sections and footer."""
    main = _main(page)
    out = []
    skipping = False
    for block in blocks(main, ("h1", "h2", "h3", "p", "li", "a")):
        if block.tag == "a" and "find out more" not in block.text.lower():
            continue  # only the official "Find out more" link is kept as its own block
        if block.tag in ("h1", "h2", "h3"):
            if _STOP_HEADINGS.match(block.text):
                break
            skipping = bool(_SKIP_SECTIONS.match(block.text))
        if not skipping:
            out.append(block)
    return out


def parse_listing(page: FetchedPage) -> dict:
    main = _main(page)
    heading = main.find(["h1"])
    if heading is None or not main.find(string=re.compile("UK universities offering GREAT Scholarships", re.I)):
        raise StructureError(f"{page.url}: expected the 'UK universities offering GREAT Scholarships' section")
    universities = []
    for anchor in main.find_all("a", href=True):
        h3 = anchor.find("h3")
        if h3 is None:
            continue
        url = urljoin(page.url, anchor["href"])
        if urlparse(url).netloc in ALLOWED_HOSTS and urlparse(url).path.startswith(DETAIL_PREFIX):
            universities.append({"name": h3.get_text(" ", strip=True), "url": url})
    if not universities:
        raise StructureError(f"{page.url}: no university links found (page layout changed?)")

    flat = blocks(main, ("h2", "h3", "p", "li"))
    criteria: list[str] = []
    award_sentence = ""
    collecting = False
    for block in flat:
        if block.tag == "p" and "£" in block.text and not award_sentence:
            award_sentence = block.text
        if block.tag in ("h2", "h3"):
            collecting = "looking for" in block.text.lower()
            continue
        if collecting and block.tag == "li":
            criteria.append(block.text)
    return {
        "country": heading.get_text(" ", strip=True),
        "award_sentence": award_sentence,
        "universities": universities,
        "criteria": criteria,
    }


def _criterion_category(text: str) -> str:
    lowered = text.lower()
    if "resident" in lowered or "passport" in lowered:
        return "residence"
    if "english language" in lowered:
        return "language"
    if "degree" in lowered:
        return "academic"
    return "other"


def parse_detail(page: FetchedPage, listing: dict, collected_at: str) -> dict:
    flat = _flat(page)
    h1 = next((b for b in flat if b.tag == "h1"), None)
    if h1 is None:
        raise StructureError(f"{page.url}: no <h1> heading")
    match = re.match(r"GREAT Scholarships? at (?:the )?(.+)$", h1.text, re.I)
    if not match:
        raise StructureError(f"{page.url}: heading {h1.text!r} is not 'GREAT Scholarships at <university>'")
    provider = match.group(1).strip()

    offer = next((b.text for b in flat if b.tag == "p" and "academic year" in b.text and "worth" in b.text), None)
    if offer is None:
        raise StructureError(f"{page.url}: missing the 'offering GREAT Scholarships ... each worth' sentence")
    cycle = re.search(r"for the (\d{4}-\d{2}) academic year", offer)

    nationalities: list[str] = []
    eligibility_parts: list[str] = []
    course_groups: list[str] = []
    all_courses_open = False
    index = 0
    while index < len(flat):
        block = flat[index]
        lowered = block.text.lower()
        if block.tag == "p" and "available for students from" in lowered:
            eligibility_parts.append(block.text)
            index += 1
            while index < len(flat) and flat[index].tag == "li":
                nationalities.append(flat[index].text)
                index += 1
            continue
        if block.tag == "p" and "following subjects" in lowered:
            courses = []
            index += 1
            while index < len(flat) and flat[index].tag == "li":
                courses.append(flat[index].text)
                index += 1
            course_groups.append(f"{block.text} {'; '.join(courses)}")
            eligibility_parts.append(course_groups[-1])
            continue
        if block.tag == "p" and "available for all full-time postgraduate taught master" in lowered:
            eligibility_parts.append(block.text)
            if lowered.startswith("the scholarships for "):
                course_groups.append(block.text)  # country-specific rule
            else:
                all_courses_open = True
        index += 1
    if not nationalities:
        raise StructureError(f"{page.url}: missing 'Scholarships are available for students from' list")

    if all_courses_open and not course_groups:
        subjects = {"kind": "unrestricted", "values": []}
    else:
        subjects = {"kind": "unknown", "values": []}
    taught_master = any("master" in part.lower() for part in eligibility_parts)

    text_all = " ".join(b.text for b in flat if b.tag == "p")
    deadline_sentence = sentence_containing(text_all, "deadline for applications") or ""
    deadline_date = parse_full_date(deadline_sentence)

    apply_link = next((b.element.get("href") for b in flat if b.tag == "a"), None)
    application_url = urljoin(page.url, apply_link) if apply_link else page.url
    if urlparse(application_url).scheme not in ("http", "https"):
        application_url = page.url

    requirements = [{
        "kind": "structured",
        "category": "nationality",
        "text": "Scholarships are available for students from: " + ", ".join(nationalities) + ".",
    }]
    for group in course_groups:
        requirements.append({"kind": "manual_review", "category": "subject", "text": group})
    country = listing.get("country", "")
    for criterion in listing.get("criteria", []):
        requirements.append({
            "kind": "manual_review",
            "category": _criterion_category(criterion),
            "text": f"British Council {country} page: GREAT scholars must {criterion}",
        })

    funding = offer
    if listing.get("award_sentence"):
        funding += " " + listing["award_sentence"]
    eligibility_text = " ".join(eligibility_parts)
    if listing.get("criteria"):
        eligibility_text += f" British Council {country} page - GREAT scholars must: " + "; ".join(listing["criteria"])

    notes = ["Award amount is paid towards tuition fees; check the university page for course and application details."]
    if deadline_sentence and not deadline_date:
        notes.append("A deadline is mentioned without a full date; recorded as unknown.")
    if not deadline_sentence:
        notes.append("No deadline is given on the British Council page; see the university's website.")

    key = "great/" + urlparse(page.url).path.rstrip("/").split("/")[-1]
    return {
        "id": stable_id(SOURCE_NAME, key),
        "name": f"GREAT Scholarship - {provider}",
        "provider": provider,
        "host_countries": ["United Kingdom"],
        "degrees": {"kind": "list", "values": ["master"]} if taught_master else {"kind": "unknown", "values": []},
        "subjects": subjects,
        "nationalities": {"kind": "list", "values": nationalities},
        "nationality_exclusions": {"kind": "none", "values": []},
        "min_score": None,
        "score_scale": None,
        "funding_category": "partial",
        "funding_description": funding,
        "deadline_kind": "dated" if deadline_date else "unknown",
        "deadline_date": deadline_date.isoformat() if deadline_date else None,
        "deadline_text": deadline_sentence,
        "eligibility_text": eligibility_text,
        "requirements": requirements,
        "application_url": application_url,
        "source_url": page.url,
        "source_name": SOURCE_NAME,
        "source_key": key,
        "award_cycle": cycle.group(1) if cycle else None,
        "collected_at": collected_at,
        "source_fetched_at": page.fetched_at,
        "fetch_method": page.method,
        "manual_verified_at": None,
        "dataset_origin": "real_source",
        "notes": " ".join(notes),
        "source_status": "available",
    }


def collect(fetcher, collected_at: str):
    """Yield ('record', dict) or ('failed', {url, error, status}) items."""
    try:
        listing = parse_listing(fetcher.get(LISTING_URL))
    except Exception as exc:
        yield "failed", {"url": LISTING_URL, "error": str(exc), "status": getattr(exc, "status", None)}
        return
    for university in listing["universities"]:
        try:
            page = fetcher.get(university["url"])
            yield "record", parse_detail(page, listing, collected_at)
        except Exception as exc:
            yield "failed", {"url": university["url"], "error": str(exc), "status": getattr(exc, "status", None)}
