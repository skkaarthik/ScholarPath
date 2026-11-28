"""Internship sources: two adapters (Greenhouse and Lever job-board APIs) and the boards they read.

Why these sources (checked November 2026, details in docs/SOURCES.md):

* Greenhouse's Job Board API (``boards-api.greenhouse.io``) and Lever's Postings API
  (``api.lever.co/v0/postings``) are official, documented, public, read-only APIs that
  employers publish so their openings can be listed elsewhere. No login, no key, and
  robots.txt allows them. Each employer has its own board, and many companies hiring
  interns in Chennai and Bengaluru publish on one of the two.
* Not used: the AICTE Internship Portal (its listings load from /api/, which robots.txt
  disallows), Internshala (robots.txt disallows search and detail pages for all crawlers),
  National Career Service (search needs an account), SmartRecruiters (robots.txt disallows
  its API), and aggregator sites without a published API.

Each board is one *source* in the collection status (its own success, failure, counts and
last success), so one employer's board being down never hides another's postings.
Boards are listed Chennai-first, then Bengaluru, then elsewhere; the same order decides
which listing is kept as the main one when two boards list the same internship.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from ..locations import parse_location
from . import internship_facts as facts

PLATFORMS = {"greenhouse": "Greenhouse job board", "lever": "Lever job board"}
HOSTS = {"greenhouse": "boards-api.greenhouse.io", "lever": "api.lever.co"}


@dataclass(frozen=True)
class Board:
    platform: str          # "greenhouse" | "lever"
    token: str             # the employer's board name on that platform
    employer: str          # the employer's name on every board (dedup across platforms relies on it)
    focus: str             # why it is listed: the city where it posts interns (documentation only)

    @property
    def source_name(self) -> str:
        return f"{self.employer} ({PLATFORMS[self.platform]})"

    @property
    def api_url(self) -> str:
        if self.platform == "greenhouse":
            return f"https://boards-api.greenhouse.io/v1/boards/{self.token}/jobs?content=true"
        return f"https://api.lever.co/v0/postings/{self.token}?mode=json"


# Chennai first, Bengaluru second, then the rest of India. Each board was found publishing an
# internship (or roles) in that city in November 2026; whether it has one open today is what
# a live run reports.
BOARDS = (
    Board("greenhouse", "fourkites", "FourKites", "Chennai"),
    Board("greenhouse", "toast", "Toast", "Chennai"),
    Board("greenhouse", "episodesix", "Episode Six", "Chennai"),
    Board("greenhouse", "zuora", "Zuora", "Chennai, Bengaluru"),
    Board("lever", "portcast", "Portcast", "Chennai, Bengaluru (remote)"),
    Board("lever", "shopback-2", "ShopBack", "Chennai, Bengaluru"),
    Board("lever", "paytm", "Paytm", "Chennai, Noida"),
    Board("lever", "paytmpayments", "Paytm Payments Services", "Chennai, Bengaluru, Delhi NCR"),
    Board("lever", "dnb", "Dun & Bradstreet", "Chennai"),
    Board("greenhouse", "devrev", "DevRev", "Bengaluru"),
    Board("greenhouse", "commerceiq", "CommerceIQ", "Bengaluru"),
    Board("greenhouse", "enterpret", "Enterpret", "Bengaluru"),
    Board("greenhouse", "karya", "Karya", "Bengaluru"),
    Board("greenhouse", "hackerrank", "HackerRank", "Bengaluru"),
    Board("lever", "fampay", "FamPay", "Bengaluru"),
    Board("lever", "epifi", "Fi (epiFi)", "Bengaluru"),
    Board("lever", "zeta", "Zeta", "Bengaluru"),
    Board("lever", "Sprinto", "Sprinto", "Bengaluru (remote)"),
    Board("lever", "stable-money1", "Stable Money", "Bengaluru"),
)


def _iso_ms(value) -> str | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).replace(microsecond=0).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _record(board: Board, *, posting_id: str, title: str, employer: str, location: str, arrangement: str,
            team: str, body: str, url: str, fetched_at: str, deadline: str | None = None,
            salary_range: dict | None = None, country: str | None = None, extra_places: list[str] = ()) -> dict | None:
    """One internship as a canonical-record dict, or None when it is not an internship in India."""
    from ..models import internship_id

    place = parse_location(" / ".join([location, *extra_places]))
    india = place["india"] or (country or "").upper() == "IN"
    if not india:
        return None
    arrangement = arrangement if arrangement in ("onsite", "hybrid", "remote") else place["arrangement"]
    degree, years, exp = facts.degrees(body), facts.study_years(body), facts.experience(body)
    months, months_text = facts.duration(body)
    record = {
        "title": title, "employer": employer, "cities": place["cities"], "states": place["states"],
        "location_text": location, "work_arrangement": arrangement,
        "disciplines": facts.disciplines(title, team), "degrees": degree, "study_years": years,
        "experience_text": exp, "eligibility_text": facts.facts_summary(degree, years, exp),
        **facts.stipend(body, salary_range), "duration_months": months, "duration_text": months_text,
        "deadline_kind": "unknown", "deadline_date": None, "deadline_text": "",
        "application_url": url, "source_url": board.api_url.split("?")[0], "source_name": board.source_name,
        "source_key": f"{board.platform}:{board.token}:{posting_id}", "collected_at": fetched_at,
        "source_fetched_at": fetched_at, "fetch_method": "live_http", "manual_verified_at": None,
        "dataset_origin": "real_source", "notes": "", "source_status": "available",
    }
    if deadline:   # Greenhouse's optional application_deadline (an ISO date or timestamp)
        record.update({"deadline_kind": "dated", "deadline_date": deadline[:10], "deadline_timezone": "Asia/Kolkata",
                       "deadline_text": "Application deadline published on the employer's job board"})
    record["id"] = internship_id(employer, title, record["cities"], arrangement)
    return record


def parse_greenhouse(board: Board, payload: str, fetched_at: str) -> tuple[list[dict], int]:
    """(internship records in India, number of postings on the board)."""
    data = json.loads(payload)
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("Greenhouse answer has no 'jobs' list")
    records = []
    for job in jobs:
        title = (job.get("title") or "").strip()
        if not title or not facts.is_internship(title):
            continue
        location = ((job.get("location") or {}).get("name") or "").strip()
        offices = [o.get("name", "") for o in job.get("offices") or [] if isinstance(o, dict)]
        team = " ".join(d.get("name", "") for d in job.get("departments") or [] if isinstance(d, dict))
        body = facts.plain_text(job.get("content") or "")
        record = _record(board, posting_id=str(job.get("id")), title=title,
                         employer=board.employer, location=location,   # one name per employer on every board
                         arrangement=parse_location(location + " " + body[:300])["arrangement"], team=team,
                         body=body, url=job.get("absolute_url") or "", fetched_at=fetched_at,
                         deadline=job.get("application_deadline") or None, extra_places=offices)
        if record:
            records.append(record)
    return records, len(jobs)


def parse_lever(board: Board, payload: str, fetched_at: str) -> tuple[list[dict], int]:
    data = json.loads(payload)
    if not isinstance(data, list):
        raise ValueError("Lever answer is not a list of postings")
    records = []
    for post in data:
        title = (post.get("text") or "").strip()
        categories = post.get("categories") or {}
        if not title or not facts.is_internship(title, categories.get("commitment") or ""):
            continue
        location = (categories.get("location") or "").strip()
        others = [p for p in categories.get("allLocations") or [] if isinstance(p, str)]
        body = " ".join(filter(None, [post.get("descriptionPlain"), post.get("additionalPlain"),
                                      " ".join(facts.plain_text(item.get("content", ""))
                                               for item in post.get("lists") or [] if isinstance(item, dict))]))
        workplace = (post.get("workplaceType") or "").lower()
        record = _record(board, posting_id=str(post.get("id")), title=title, employer=board.employer,
                         location=location, arrangement="onsite" if workplace == "on-site" else workplace,
                         team=" ".join(filter(None, [categories.get("team"), categories.get("department")])),
                         body=body, url=post.get("hostedUrl") or post.get("applyUrl") or "",
                         fetched_at=fetched_at, salary_range=post.get("salaryRange"), country=post.get("country"),
                         extra_places=others)
        if record:
            record["start_text"] = ""
            records.append(record)
    return records, len(data)


PARSERS = {"greenhouse": parse_greenhouse, "lever": parse_lever}
