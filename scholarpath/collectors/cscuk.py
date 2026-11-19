"""Commonwealth Scholarship Commission in the UK (cscuk.fcdo.gov.uk).

Official UK government scholarship body. robots.txt (checked 2026-11-12)
disallows nothing. Each configured page is a WordPress post whose
``.entry-content`` is split into sections by ``<h1>`` headings such as
"Applicant eligibility", "Eligible countries" and "Financial assistance".

Only the three degree-study programmes are configured. The listing also holds
professional fellowships and a page for UK host organisations, which are not
degree scholarships for students, so they are deliberately excluded.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..models import stable_id
from .base import FetchedPage, StructureError
from .htmltools import blocks, parse_closing_time, parse_full_date, sentence_containing, soup_of

SOURCE_ID = "cscuk"
SOURCE_NAME = "Commonwealth Scholarship Commission in the UK"
ALLOWED_HOSTS = {"cscuk.fcdo.gov.uk"}
TIMEZONE = "Europe/London"   # CSC deadlines are UK times ("16:00 GMT/BST")
CLOSED = re.compile(r"\bapplications\b[^.]*\b(?:are|is)\s+now\s+closed\b", re.I)
PAGE_URLS = [
    "https://cscuk.fcdo.gov.uk/scholarships/commonwealth-masters-scholarships/",
    "https://cscuk.fcdo.gov.uk/scholarships/commonwealth-shared-scholarships-applications/",
    "https://cscuk.fcdo.gov.uk/scholarships/commonwealth-phd-scholarships-for-least-developed-countries-and-vulnerable-states/",
]

REQUIRED_SECTIONS = {
    "overview": ("overview",),
    "apply": ("how to apply",),
    "eligibility": ("applicant eligibility", "candidate eligibility"),
    "countries": ("eligible countries",),
    "funding": ("financial assistance",),
}


def _sections(page: FetchedPage) -> tuple[str, dict[str, list[str]]]:
    soup = soup_of(page.html)
    title_el = soup.select_one("h1.entry-title")
    content = soup.select_one(".entry-content")
    if title_el is None or content is None:
        raise StructureError(f"{page.url}: expected 'h1.entry-title' and '.entry-content' (page layout changed?)")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for block in blocks(content, ("h1", "p", "li")):
        if block.tag == "h1":
            heading = block.text.lower()
            current = next((key for key, names in REQUIRED_SECTIONS.items() if heading in names), None)
            if current:
                sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(block.text)
    missing = [key for key in REQUIRED_SECTIONS if not sections.get(key)]
    if missing:
        raise StructureError(f"{page.url}: missing or empty sections {missing} (page layout changed?)")
    return title_el.get_text(" ", strip=True), sections


def _countries(lines: list[str]) -> list[str]:
    countries: list[str] = []
    for block in lines:
        for line in block.split("\n"):
            line = line.strip()
            if not line or len(line) > 45 or line.endswith(".") or line.lower().startswith(("please", "in line")):
                continue
            countries.append(line)
    return countries


def _classify(item: str) -> tuple[str, str]:
    text = item.lower()
    if "citizen" in text:
        return "structured", "nationality"
    if "high income country" in text:
        return "manual_review", "experience"
    if "resident" in text:
        return "manual_review", "residence"
    if "degree" in text or "registered for a phd" in text:
        return "manual_review", "academic"
    if "afford" in text:
        return "manual_review", "financial_need"
    if "documentation" in text:
        return "manual_review", "documents"
    if "studied or worked" in text:
        return "manual_review", "experience"
    return "manual_review", "other"


def parse_page(page: FetchedPage, collected_at: str) -> dict:
    title, sections = _sections(page)

    countries = _countries(sections["countries"])
    if not countries:
        raise StructureError(f"{page.url}: 'Eligible countries' section has no country lines")

    # Degree level comes from the title, or failing that the first overview
    # paragraph (e.g. "one of three Master's programmes").
    degrees = {"kind": "unknown", "values": []}
    for text in (title, sections["overview"][0]):
        if re.search(r"\bph\.?d\b|doctoral", text, re.I):
            degrees = {"kind": "list", "values": ["phd"]}
            break
        if re.search(r"\bmaster", text, re.I):
            degrees = {"kind": "list", "values": ["master"]}
            break

    apply_text = " ".join(sections["apply"])
    deadline_sentence = sentence_containing(apply_text, "closing date") or ""
    deadline_date = parse_full_date(deadline_sentence)
    cycle_match = re.search(r"for the (\d{4}/\d{2}) academic year", apply_text)
    status_sentence = sentence_containing(apply_text, "are now") or ""
    closed_by_source = bool(CLOSED.search(apply_text))   # e.g. "... for the 2027/28 academic year are now closed."

    requirements = []
    eligibility_items = sections["eligibility"]
    for item in eligibility_items:
        if item.endswith(":") or len(item) > 400:
            continue
        kind, category = _classify(item)
        if category == "other" and not item.lower().startswith(("be ", "not ", "have ", "by ")):
            continue  # narrative paragraphs stay in eligibility_text only
        requirements.append({"kind": kind, "category": category, "text": item})
    requirements.append({
        "kind": "manual_review",
        "category": "other",
        "text": "Explanatory paragraphs in the original eligibility wording (for example prior-study rules "
                "and conditions after the award) are not itemised here; read the full wording before applying.",
    })
    requirements.append({
        "kind": "manual_review",
        "category": "subject",
        "text": "Subject eligibility is not published as a structured list on this page; "
                "check the course/development-theme guidance on the source page.",
    })

    funding_text = " ".join(sections["funding"])
    lowered = funding_text.lower()
    if "tuition fees" in lowered and "stipend" in lowered:
        funding_category = "full"
    elif "tuition fees" in lowered:
        funding_category = "tuition_full"
    else:
        funding_category = "unknown"

    notes = []
    if status_sentence:
        notes.append(f"Source status at collection: {status_sentence}")
    if deadline_sentence and deadline_date is None:
        notes.append("The published closing date has no year, so it is recorded as unknown rather than guessed.")
    notes.append("Applications are made through the CSC's own application system as described on the source page.")

    key = urlparse(page.url).path.strip("/")
    return {
        "id": stable_id(SOURCE_NAME, key),
        "name": title,
        "provider": SOURCE_NAME,
        "host_countries": ["United Kingdom"],
        "degrees": degrees,
        "subjects": {"kind": "unknown", "values": []},
        "nationalities": {"kind": "list", "values": countries},
        # The page gives an explicit allow-list, so no separate exclusions apply.
        "nationality_exclusions": {"kind": "none", "values": []},
        "min_score": None,
        "score_scale": None,
        "funding_category": funding_category,
        "funding_description": funding_text,
        "deadline_kind": "dated" if deadline_date else "unknown",
        "deadline_date": deadline_date.isoformat() if deadline_date else None,
        "deadline_at": parse_closing_time(deadline_sentence, deadline_date),
        "deadline_timezone": TIMEZONE,
        "closed_by_source": closed_by_source,
        "deadline_text": deadline_sentence,
        "eligibility_text": " ".join(eligibility_items),
        "requirements": requirements,
        "application_url": page.url,
        "source_url": page.url,
        "source_name": SOURCE_NAME,
        "source_key": key,
        "award_cycle": cycle_match.group(1) if cycle_match else None,
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
    for url in PAGE_URLS:
        try:
            page = fetcher.get(url)
            yield "record", parse_page(page, collected_at)
        except Exception as exc:  # report every page failure, keep going
            yield "failed", {"url": url, "error": str(exc), "status": getattr(exc, "status", None)}
