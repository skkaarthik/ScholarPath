"""Small HTML helpers shared by parsers. Text is extracted, never rendered."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from bs4 import BeautifulSoup, Tag

from ..cleaning import clean_text

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
FULL_DATE = re.compile(rf"\b(\d{{1,2}})\s+({MONTHS})\s+(\d{{4}})\b")


@dataclass
class Block:
    tag: str
    text: str
    element: Tag


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def blocks(container: Tag, tags: tuple[str, ...]) -> list[Block]:
    """Flatten a container into ordered text blocks.

    ``<p>`` inside ``<li>`` is skipped (the list item already holds its text).
    ``<br>`` is kept as a newline so line-separated lists stay splittable.
    """
    out: list[Block] = []
    for element in container.find_all(list(tags)):
        if element.name == "p" and element.find_parent("li"):
            continue
        text = element.get_text("\n") if element.name in ("p", "li") else element.get_text(" ")
        lines = [clean_text(line) for line in text.split("\n")]
        text = "\n".join(line for line in lines if line)
        if text:
            out.append(Block(element.name, text, element))
    return out


def parse_full_date(text: str) -> date | None:
    """Parse '8 December 2026' style dates. Returns None when no year is given."""
    match = FULL_DATE.search(text)
    if not match:
        return None
    day, month, year = match.groups()
    return datetime.strptime(f"{day} {month} {year}", "%d %B %Y").date()


# Zone abbreviations that official UK and German pages use next to a closing time.
ZONE_OFFSETS = {"GMT": 0, "UTC": 0, "BST": 1, "CET": 1, "CEST": 2}
CLOCK_TIME = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\s*\(?(GMT|UTC|BST|CET|CEST)\b\)?", re.I)


def parse_closing_time(text: str, day: date | None) -> str | None:
    """'16:00 GMT on Tuesday 8 December 2026' -> '2026-12-08T16:00:00+00:00' (UTC).

    Only when the same sentence gives a full date (``day``), a clock time and an explicit
    zone; anything less returns None and the date-only rule applies instead."""
    if day is None:
        return None
    match = CLOCK_TIME.search(text)
    if not match:
        return None
    if match[2] is None and match[3] is None:
        return None   # a bare number next to a zone ("2026 GMT") is not a time
    hour, minute, meridiem, zone = int(match[1]), int(match[2] or 0), (match[3] or "").lower(), match[4].upper()
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone(timedelta(hours=ZONE_OFFSETS[zone])))
    return local.astimezone(timezone.utc).isoformat()


def sentence_containing(text: str, needle: str) -> str | None:
    """Return the sentence of ``text`` that contains ``needle`` (case-insensitive)."""
    for sentence in re.split(r"(?<=[.!?])\s+", text.replace("\n", " ")):
        if needle.lower() in sentence.lower():
            return sentence.strip()
    return None
