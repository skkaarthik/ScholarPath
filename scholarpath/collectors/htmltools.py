"""Small HTML helpers shared by parsers. Text is extracted, never rendered."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

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


def sentence_containing(text: str, needle: str) -> str | None:
    """Return the sentence of ``text`` that contains ``needle`` (case-insensitive)."""
    for sentence in re.split(r"(?<=[.!?])\s+", text.replace("\n", " ")):
        if needle.lower() in sentence.lower():
            return sentence.strip()
    return None
