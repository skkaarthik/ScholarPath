"""DAAD scholarship database (www2.daad.de), study and research in Germany.

What was checked (19 Nov 2026, in a browser on the project owner's computer):

* www2.daad.de has no robots.txt (HTTP 404), which under the robots standard means no
  crawling restrictions. DAAD's terms of use / imprint on www.daad.de could not be loaded
  that day, so a text-and-data-mining reservation has NOT been ruled out.
* The listing page shows every programme on one page (147 entries, matching its own
  "147 Scholarship options" line), as server-rendered ``li.entry`` items.
* Programme pages do NOT state an application deadline: they say deadlines are updated
  annually and depend on the applicant's status and country. So every DAAD record has an
  unknown deadline ("Date not confirmed"); nothing is guessed.

Only the listing is read (one polite request). Each record keeps the programme's DAAD page
as source and application link. The collector is DISABLED (``ENABLED = False``) until a
live dry run succeeds and the terms are checked; see docs/DATA_REFRESH.md.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

from ..models import stable_id
from .base import FetchedPage, StructureError
from .htmltools import soup_of

SOURCE_ID = "daad"
SOURCE_NAME = "DAAD scholarship database"
ENABLED = False          # see the module docstring: verify live access and terms first
ALLOWED_HOSTS = {"www2.daad.de"}
TIMEZONE = "Europe/Berlin"
LISTING_URL = ("https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/"
               "?status=&origin=&subjectGrps=&daad=&intention=&q=&page={page}&lang=en")
MAX_PAGES = 20

# DAAD "Status" wording -> ScholarPath degree codes. Anything else is left out, and a record
# with no recognised status gets an "unknown" degree rule rather than a guess.
STATUS_TO_DEGREE = {
    "undergraduates": "bachelor",
    "graduates": "master",
    "doctoral candidates/phd students": "phd",
    "postdoctoral researchers": "postdoc",
}
SUBJECT_GROUPS = 7       # DAAD's subject filter has seven groups; all seven listed = every subject
TOTAL = re.compile(r"(\d+)\s+Scholarship options", re.I)


def _dd(entry, label: str):
    for dt in entry.select("dt"):
        if dt.get_text(" ", strip=True).lower().startswith(label):
            return dt.find_next_sibling("dd")
    return None


def parse_listing(page: FetchedPage) -> tuple[int, list[dict]]:
    """(stated total, entries). Raises StructureError when the page is not what we expect."""
    soup = soup_of(page.html)
    match = TOTAL.search(soup.get_text(" "))
    entries = soup.select("li.entry")
    if not match or not entries:
        raise StructureError(f"{page.url}: expected 'N Scholarship options' and li.entry items (layout changed?)")
    out = []
    for entry in entries:
        link = entry.select_one("h2 a[href]")
        if link is None:
            raise StructureError(f"{page.url}: an entry has no programme link")
        url = urljoin(page.url, link["href"])
        detail = parse_qs(urlparse(url).query).get("detail", [""])[0]
        if urlparse(url).netloc not in ALLOWED_HOSTS or not detail.isdigit():
            continue
        provider_el = link.find("span")
        provider = provider_el.get_text(" ", strip=True).lstrip("•").strip() if provider_el else ""
        if provider_el:
            provider_el.extract()
        status = _dd(entry, "status")
        country = _dd(entry, "country")
        subject = _dd(entry, "subject")
        # DAAD's own description text (.entry-detail) is deliberately not read: DAAD's imprint
        # allows its text for personal, private, non-commercial use only, and this app may be
        # hosted publicly. Only facts (title, provider, status, country rule, subjects, link) are kept.
        out.append({
            "detail": detail,
            "url": url,
            "name": link.get_text(" ", strip=True),
            "provider": provider or "DAAD",
            "statuses": [s.strip() for s in (status.get_text(" ", strip=True) if status else "").split(",")
                         if s.strip()],
            "country": (country.contents[0].get_text(" ", strip=True) if hasattr(country.contents[0], "get_text")
                        else str(country.contents[0]).strip()) if country and country.contents else "",
            "subject_groups": [li.get_text(" ", strip=True) for li in subject.select("li")] if subject else [],
        })
    return int(match.group(1)), out


def eligibility_text(item: dict) -> str:
    """A plain sentence built only from listed facts, never from DAAD's description text."""
    who = ", ".join(item["statuses"]) if item["statuses"] else "not shown"
    return (f"DAAD programme for: {who}. Country rule on DAAD: {item['country'] or 'not shown'}. "
            "Full conditions, funding and the deadline for your country are on the DAAD programme page.")


def to_record(item: dict, page: FetchedPage, collected_at: str) -> dict:
    degrees = sorted({STATUS_TO_DEGREE[s.lower()] for s in item["statuses"] if s.lower() in STATUS_TO_DEGREE})
    all_subjects = len(item["subject_groups"]) >= SUBJECT_GROUPS
    requirements = [
        {"kind": "manual_review", "category": "nationality",
         "text": f"Country rule on DAAD: {item['country'] or 'not shown'}. Check the programme page for which "
                 "countries are eligible."},
        {"kind": "manual_review", "category": "other",
         "text": "DAAD shows the application deadline only after you choose your status and country on the "
                 "programme page; it is not recorded here."},
    ]
    if item["subject_groups"] and not all_subjects:
        requirements.append({"kind": "manual_review", "category": "subject",
                             "text": "Subject groups listed by DAAD: " + "; ".join(item["subject_groups"])})
    return {
        "id": stable_id(SOURCE_NAME, item["detail"]),
        "name": item["name"],
        "provider": item["provider"],
        "host_countries": ["Germany"],
        "degrees": {"kind": "list", "values": degrees} if degrees else {"kind": "unknown", "values": []},
        "subjects": {"kind": "unrestricted", "values": []} if all_subjects else {"kind": "unknown", "values": []},
        "nationalities": {"kind": "unknown", "values": []},
        "nationality_exclusions": {"kind": "unknown", "values": []},
        "min_score": None,
        "score_scale": None,
        "funding_category": "unknown",
        "funding_description": "",
        "deadline_kind": "unknown",
        "deadline_date": None,
        "deadline_timezone": TIMEZONE,
        "deadline_text": "",
        "eligibility_text": eligibility_text(item),
        "requirements": requirements,
        "application_url": item["url"],
        "source_url": item["url"],
        "source_name": SOURCE_NAME,
        "source_key": item["detail"],
        "award_cycle": None,
        "collected_at": collected_at,
        "source_fetched_at": page.fetched_at,
        "fetch_method": page.method,
        "manual_verified_at": None,
        "dataset_origin": "real_source",
        "notes": "Facts from the DAAD scholarship database listing (DAAD's own description is not copied); full "
                 "conditions, value and the deadline for your country are on the programme page.",
        "source_status": "available",
    }


def collect(fetcher, collected_at: str):
    """Read listing pages until every stated programme is seen (handles pagination). A run
    that cannot reach the stated total is a failure, never a silently partial import."""
    seen: dict[str, tuple[dict, FetchedPage]] = {}
    total = None
    for number in range(1, MAX_PAGES + 1):
        url = LISTING_URL.format(page=number)
        try:
            page = fetcher.get(url)
            total, items = parse_listing(page)
        except Exception as exc:
            yield "failed", {"url": url, "error": str(exc), "status": getattr(exc, "status", None)}
            return
        new = [i for i in items if i["detail"] not in seen]
        for item in new:
            seen[item["detail"]] = (item, page)
        if len(seen) >= total or not new:
            break
    if total is None or len(seen) < total:
        yield "failed", {"url": LISTING_URL.format(page=1), "status": None,
                         "error": f"Only {len(seen)} of {total} programmes found across the listing pages"}
        return
    for item, page in seen.values():
        yield "record", to_record(item, page, collected_at)
