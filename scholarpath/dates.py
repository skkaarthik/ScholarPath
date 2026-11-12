"""Deadline status and dashboard grouping (pure functions; 'today' is injected).

Date basis: published deadlines are calendar dates. A date-only deadline is
treated as open through the end of that calendar day in the application
timezone (Asia/Kolkata by default). Official closing times and timezones vary,
so the UI always links to the official source for exact details.
"""

from __future__ import annotations

from datetime import date

STATUS_LABELS = {
    "open": "Open",
    "expired": "Expired",
    "rolling": "Rolling",
    "unknown": "Unknown",
}

GROUPS = {
    "due_7": "Due today to 7 days",
    "due_30": "Due in 8-30 days",
    "later": "More than 30 days away",
    "expired": "Expired",
    "rolling": "Rolling deadline",
    "unknown": "Deadline unknown",
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
        return "Rolling - applications reviewed as received (check source)"
    if status == "unknown":
        return "Unknown - not published in a structured form"
    assert deadline is not None and days_left is not None
    stamp = deadline.strftime("%d %b %Y")
    if days_left == 0:
        return f"{stamp} - closes today"
    if days_left > 0:
        return f"{stamp} - {days_left} day{'s' if days_left != 1 else ''} left"
    return f"{stamp} - expired {-days_left} day{'s' if days_left != -1 else ''} ago"
