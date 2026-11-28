"""Facts read from a job posting (pure functions; shared by every internship adapter).

ScholarPath keeps facts only, never an employer's description text (the same choice as
for DAAD). Each helper looks for an explicit statement and returns "unknown" when there
is none: a stipend, duration, degree or year of study is never guessed.

Disciplines are the one reading ScholarPath makes itself: they come from the role title
and the team name (for example "Data Analyst Intern" -> Data & analytics). The Review page
says so.
"""

from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup

INTERN_WORDS = re.compile(r"\b(intern|interns|internship|internships|trainee|apprentice|apprenticeship)\b", re.I)

DISCIPLINE_WORDS = {
    "data": ("data", "analytics", "analyst", "machine learning", " ml ", "ml/", "ai ", "business intelligence"),
    "engineering": ("engineer", "engineering", "developer", "software", "sde", "backend", "frontend", "front-end",
                    "full stack", "full-stack", "devops", "embedded", "mechanical", "electrical", "electronics",
                    "civil", "qa ", "quality assurance", "test", "security", "cloud", "platform", "technical",
                    "technology", "it support", "programmer", "mobile", "android", "ios"),
    "design": ("design", "designer", "ux", "ui/", "ui ", "graphic", "visual", "illustrat", "animation"),
    "product": ("product manager", "product management", "product intern", "product analyst", "apm"),
    "business": ("business", "operations", "strategy", "sales", "customer", "account", "partnership",
                 "supply chain", "procurement", "consult", "onboarding", "support", "growth", "management trainee"),
    "finance": ("finance", "financial", "accounting", "accountant", "audit", "tax", "treasury", "ca ", "articleship",
                "investment", "credit", "risk"),
    "marketing": ("marketing", "content", "social media", "brand", "seo", "copywrit", "communications", "pr ",
                  "public relations", "community", "digital marketing"),
    "research": ("research", "scientist", "science", "lab", "r&d", "biology", "chemistry", "physics"),
    "people": ("hr", "human resources", "people", "talent", "recruit"),
    "legal": ("legal", "law", "compliance", "paralegal"),
}

DEGREE_PATTERNS = {
    "diploma": r"\bdiploma\b",
    "bachelor": r"\b(b\.?\s?tech|b\.?\s?e\b|bachelor'?s?|b\.?\s?sc|b\.?\s?com|bba|bca|b\.?\s?a\b|b\.?\s?des|undergraduate)",
    "master": r"\b(m\.?\s?tech|m\.?\s?e\b|master'?s?|m\.?\s?sc|mba|mca|pgdm|m\.?\s?com|m\.?\s?des|postgraduate)",
    "phd": r"\b(ph\.?\s?d|doctoral|doctorate)\b",
}
YEAR_PATTERNS = {
    "final": r"\b(final[- ]year|final semester|graduating in|(?:20\d\d) (?:graduates?|batch|pass[- ]?outs?))\b",
    "graduate": r"\b(recent(?:ly)? graduat\w*|fresh graduates?|freshers?|graduated|pass[- ]?outs?)\b",
    "1": r"\b(1st|first)[- ]year\b", "2": r"\b(2nd|second)[- ]year\b", "3": r"\b(3rd|third|pre[- ]final)[- ]year\b",
    "4": r"\b(4th|fourth)[- ]year\b", "5": r"\b(5th|fifth)[- ]year\b",
}
WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "eleven": 11, "twelve": 12}


def plain_text(markup: str) -> str:
    """Posting HTML (Greenhouse sends it HTML-escaped) as plain text, for reading facts only."""
    if not markup:
        return ""
    text = BeautifulSoup(html.unescape(markup), "html.parser").get_text(" ")
    return " ".join(text.split())


def is_internship(title: str, commitment: str = "") -> bool:
    """An internship by its title, or by the job board's own work type (Lever's "Intern").
    Word boundaries keep "Internal Auditor" and "International Sales" out."""
    return bool(INTERN_WORDS.search(title or "") or re.search(r"\bintern(ship)?\b", commitment or "", re.I))


def disciplines(title: str, team: str = "") -> dict:
    """ScholarPath's reading of the role title and team name; "unknown" when nothing matches."""
    text = f" {(title or '').lower()} {(team or '').lower()} "
    found = sorted(key for key, words in DISCIPLINE_WORDS.items() if any(w in text for w in words))
    if "product" in found and "engineering" in found and "engineer" not in text:
        found.remove("engineering")
    return {"kind": "list", "values": found} if found else {"kind": "unknown", "values": []}


def _amount(text: str) -> int | None:
    text = text.replace(",", "").strip().lower()
    match = re.match(r"(\d+(?:\.\d+)?)\s*(k|lakh|lakhs|lac|l)?\b", text)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    if unit == "k":
        value *= 1000
    elif unit in ("lakh", "lakhs", "lac", "l"):
        value *= 100000
    return int(round(value))


STIPEND = re.compile(
    r"(?:stipend|salary|pay|compensation)[^.\n]{0,60}?(?:inr|rs\.?|₹)\s*([\d,]+(?:\.\d+)?\s*(?:k|lakh|lakhs|lac)?)"
    r"(?:\s*(?:-|to|–)\s*(?:inr|rs\.?|₹)?\s*([\d,]+(?:\.\d+)?\s*(?:k|lakh|lakhs|lac)?))?"
    r"\s*(?:/|per|a|each)?\s*(month|mo|pm|p\.m\.|week|year|annum|total)?",
    re.I,
)


def stipend(text: str, salary_range: dict | None = None) -> dict:
    """{"stipend_kind", "stipend_min", "stipend_max", "stipend_text"} in rupees per month.

    Only an amount in rupees with a monthly period (or a structured monthly INR range) is
    stored. "Unpaid" must be said in so many words. "Paid"/"stipend" without an amount is
    "paid_unstated"."""
    empty = {"stipend_kind": "unknown", "stipend_min": None, "stipend_max": None, "stipend_text": ""}
    if salary_range and str(salary_range.get("currency", "")).upper() == "INR":
        interval = str(salary_range.get("interval", "")).lower()
        low, high = salary_range.get("min"), salary_range.get("max")
        if "month" in interval and isinstance(low, (int, float)):
            return {"stipend_kind": "paid", "stipend_min": int(low),
                    "stipend_max": int(high) if isinstance(high, (int, float)) else None,
                    "stipend_text": "Monthly range published by the employer"}
    text = text or ""
    match = STIPEND.search(text)
    if match:
        period = (match.group(3) or "").lower()
        low = _amount(match.group(1))
        high = _amount(match.group(2)) if match.group(2) else None
        if low and period in ("month", "mo", "pm", "p.m."):
            return {"stipend_kind": "paid", "stipend_min": low, "stipend_max": high if high and high >= low else None,
                    "stipend_text": "Monthly amount stated in the posting"}
        if low:
            return {**empty, "stipend_kind": "paid_unstated",
                    "stipend_text": "An amount is stated, but not as a monthly stipend; see the posting"}
    if re.search(r"\bunpaid\b", text, re.I):
        return {**empty, "stipend_kind": "unpaid", "stipend_text": "The posting says the internship is unpaid"}
    if re.search(r"\b(paid internship|stipend)\b", text, re.I):
        return {**empty, "stipend_kind": "paid_unstated", "stipend_text": "The posting mentions a stipend without an amount"}
    return empty


DURATION = re.compile(r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
                      r"(?:\s*(?:-|to|–)\s*(\d{1,2}))?\s*[- ]?\s*(months?|weeks?)\b", re.I)


def duration(text: str) -> tuple[float | None, str]:
    """(months, wording) from the first "N months" / "N-M months" / "N weeks" near the word
    internship or duration; (None, "") when the posting states none."""
    for match in DURATION.finditer(text or ""):
        window = (text[max(0, match.start() - 80): match.end() + 40]).lower()
        if not re.search(r"intern|duration|tenure|period|program", window):
            continue
        first = match.group(1).lower()
        low = WORD_NUMBERS.get(first) or int(first)
        high = int(match.group(2)) if match.group(2) else None
        unit = match.group(3).lower()
        months = (high or low) / (4.345 if unit.startswith("week") else 1)
        if 0 < months <= 24:
            shown = f"{low}{'-' + str(high) if high else ''} {'weeks' if unit.startswith('week') else 'months'}"
            return round(months, 1), shown
    return None, ""


def degrees(text: str) -> dict:
    found = sorted(k for k, pattern in DEGREE_PATTERNS.items() if re.search(pattern, text or "", re.I))
    return {"kind": "list", "values": found} if found else {"kind": "unknown", "values": []}


def study_years(text: str) -> dict:
    found = sorted(k for k, pattern in YEAR_PATTERNS.items() if re.search(pattern, text or "", re.I))
    return {"kind": "list", "values": found} if found else {"kind": "unknown", "values": []}


def experience(text: str) -> str:
    """A short fact about experience in ScholarPath's own words, or ""."""
    text = text or ""
    if re.search(r"\bno (prior |previous )?(work )?experience (is )?(required|needed)\b", text, re.I):
        return "No prior experience required (stated in the posting)."
    match = re.search(r"\b(\d)\s*(?:-|to|–)\s*(\d)\s*years? (?:of )?(?:work )?experience\b", text, re.I)
    if match:
        return f"Asks for {match.group(1)}-{match.group(2)} years of experience."
    match = re.search(r"\b(\d)\+?\s*years? (?:of )?(?:relevant |work |professional )?experience\b", text, re.I)
    if match:
        return f"Asks for {match.group(1)}+ years of experience."
    return ""


def facts_summary(degree: dict, years: dict, exp: str) -> str:
    """The eligibility facts in one short line written by ScholarPath (never copied text)."""
    from ..models import INTERN_DEGREES, STUDY_YEARS

    parts = []
    if degree["kind"] == "list":
        parts.append("Degrees mentioned: " + ", ".join(INTERN_DEGREES[d].split(" (")[0] for d in degree["values"]))
    if years["kind"] == "list":
        parts.append("Year of study mentioned: " + ", ".join(STUDY_YEARS[y] for y in years["values"]))
    if exp:
        parts.append(exp.rstrip("."))
    return ". ".join(parts) + ("." if parts else "")
