"""Deadline status and dashboard grouping (pure functions; 'today' and 'now' are injected).

When an opportunity closes (``closes_at``), in order of precedence:

1. The official page says applications are closed (``closed_by_source``): closed now,
   whatever date was recorded.
2. The source states an exact closing time with a zone, e.g. "16:00 GMT on 8 December
   2026" (``deadline_at``): closed from that instant.
3. A date without a time: open through the END of that calendar day in the source's
   time zone (``deadline_timezone``, e.g. Europe/London for UK sources). Fictional
   example records use the app time zone (Asia/Kolkata).
4. A date without a known zone: open through the end of that day "Anywhere on Earth"
   (UTC-12), the latest the day ends anywhere, so nothing is hidden early.
5. Rolling or missing/ambiguous deadlines never count as closed; they are labelled
   "Rolling" or "Date not confirmed".

Closed opportunities leave active discovery (search, counts, exports) the moment they
close, even between data refreshes, because status is computed from 'now' on every read.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ANYWHERE_ON_EARTH = timezone(timedelta(hours=-12), "AoE")


def closes_at(kind: str, deadline: date | None, deadline_at: str | None = None,
              tz_name: str | None = None) -> datetime | None:
    """The UTC instant applications close, or None when there is no reliable date."""
    if kind != "dated" or deadline is None:
        return None
    if deadline_at:
        return datetime.fromisoformat(deadline_at).astimezone(timezone.utc)
    zone = ZoneInfo(tz_name) if tz_name else ANYWHERE_ON_EARTH
    end_of_day = datetime.combine(deadline + timedelta(days=1), time(0), tzinfo=zone)
    return (end_of_day - timedelta(seconds=1)).astimezone(timezone.utc)


def is_closed(kind: str, deadline: date | None, now: datetime, deadline_at: str | None = None,
              tz_name: str | None = None, closed_by_source: bool = False) -> bool:
    if closed_by_source:
        return True
    moment = closes_at(kind, deadline, deadline_at, tz_name)
    return moment is not None and now >= moment


def record_closed(rec, now: datetime) -> bool:
    return is_closed(rec.deadline_kind, rec.deadline_date, now, rec.deadline_at, rec.deadline_timezone,
                     rec.closed_by_source)


def closes_at_iso(rec) -> str | None:
    """Stored in the database so SQL filters and Python agree (UTC, second precision)."""
    moment = closes_at(rec.deadline_kind, rec.deadline_date, rec.deadline_at, rec.deadline_timezone)
    return moment.replace(microsecond=0).isoformat() if moment else None


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


def deadline_status(kind: str, deadline: date | None, today: date,
                    closed: bool | None = None) -> tuple[str, int | None]:
    """Return (status, days_left). days_left is None unless the deadline is dated.

    ``closed`` is the result of ``is_closed`` (time-zone aware). Without it, the
    calendar date alone decides, as before (used where no clock is available)."""
    days_left = (deadline - today).days if kind == "dated" and deadline is not None else None
    if closed:
        return "expired", days_left
    if kind == "rolling":
        return "rolling", None
    if kind != "dated" or deadline is None:
        return "unknown", None
    if closed is False:
        return "open", max(days_left, 0)
    return ("open" if days_left >= 0 else "expired"), days_left


def dashboard_group(kind: str, deadline: date | None, today: date, closed: bool | None = None) -> str:
    """Non-overlapping groups: 0-7, 8-30, >30 days, expired, rolling, unknown."""
    status, days_left = deadline_status(kind, deadline, today, closed)
    if status != "open":
        return status
    assert days_left is not None
    if days_left <= 7:
        return "due_7"
    if days_left <= 30:
        return "due_30"
    return "later"


def describe_deadline(kind: str, deadline: date | None, today: date, closed: bool | None = None) -> str:
    status, days_left = deadline_status(kind, deadline, today, closed)
    if status == "expired" and (kind != "dated" or deadline is None):
        return "Closed: the official page says applications are closed (no closing date recorded)"
    if status == "rolling":
        return "Rolling: no fixed closing date, applications are reviewed as they arrive"
    if status == "unknown":
        return "No exact closing date is recorded"
    assert deadline is not None and days_left is not None
    if status == "expired" and days_left >= 0:
        return f"{deadline.day} {deadline.strftime('%b %Y')} - closed"
    stamp = f"{deadline.day} {deadline.strftime('%b %Y')}"
    if days_left == 0:
        return f"{stamp} - closes today"
    if days_left > 0:
        return f"{stamp} - {days_left} day{'s' if days_left != 1 else ''} left"
    return f"{stamp} - closed {-days_left} day{'s' if days_left != -1 else ''} ago"
