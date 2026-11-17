"""Deadline status and dashboard grouping (pure functions; 'today' is injected).

Date basis: published deadlines are calendar dates. A date-only deadline is
treated as open through the end of that calendar day in the application
timezone (Asia/Kolkata by default). Official closing times and timezones vary,
so the UI always links to the official source for exact details.
"""

from __future__ import annotations

from datetime import date

# One vocabulary for the whole app (pages, filters and the CSV export).
STATUS_LABELS = {
    "open": "Open",
    "expired": "Closed",
    "rolling": "Rolling",
    "unknown": "Date not confirmed",
}

GROUPS = {
    "due_7": "Closing within 7 days",
    "due_30": "Closing in 8 to 30 days",
    "later": "More than 30 days away",
    "expired": "Closed",
    "rolling": "Rolling deadline",
    "unknown": "Closing date not confirmed",
}
GROUP_ORDER = list(GROUPS)


def deadline_status(kind: str, deadline: date | None, today: date) -> tuple[str, int | None]:
    """Return (status, days_left). days_left is None unless the deadline is dated."""
    if kind == "rolling":
        return "rolling", None
    if kind != "dated" or deadline is None:
        return "unknown", None
    days_left = (deadline - today).days
    return ("open" if days_left >= 0 else "expired"), days_left


def dashboard_group(kind: str, deadline: date | None, today: date) -> str:
    """Non-overlapping groups: 0-7, 8-30, >30 days, expired, rolling, unknown."""
    status, days_left = deadline_status(kind, deadline, today)
    if status != "open":
        return status
    assert days_left is not None
    if days_left <= 7:
        return "due_7"
    if days_left <= 30:
        return "due_30"
    return "later"


def describe_deadline(kind: str, deadline: date | None, today: date) -> str:
    status, days_left = deadline_status(kind, deadline, today)
    if status == "rolling":
        return "Rolling: no fixed closing date, applications are reviewed as they arrive"
    if status == "unknown":
        return "No exact closing date is recorded"
    assert deadline is not None and days_left is not None
    stamp = f"{deadline.day} {deadline.strftime('%b %Y')}"
    if days_left == 0:
        return f"{stamp} - closes today"
    if days_left > 0:
        return f"{stamp} - {days_left} day{'s' if days_left != 1 else ''} left"
    return f"{stamp} - closed {-days_left} day{'s' if days_left != -1 else ''} ago"
