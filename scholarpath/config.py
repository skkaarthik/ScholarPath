"""Central configuration.

Paths are resolved from the project location (not the shell's working directory),
so commands behave the same from any folder. Two environment variables exist for
tests and demonstrations:

* ``SCHOLARPATH_DATA_DIR`` - put the SQLite databases somewhere else (tests use a temp dir).
* ``SCHOLARPATH_TODAY``    - pin "today" (ISO date) so date logic is reproducible.
* ``SCHOLARPATH_NOW``      - pin the exact instant (ISO timestamp with zone), for deadline-time tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EXAMPLES_DIR = DATA_DIR / "examples"
EXAMPLE_TEMPLATE = EXAMPLES_DIR / "example_scholarships.template.json"
EXAMPLE_BUILD_DIR = EXAMPLES_DIR / "build"
COLLECTED_DIR = DATA_DIR / "collected"
REAL_DATASET_FILE = COLLECTED_DIR / "real_scholarships.json"
SNAPSHOT_DIR = DATA_DIR / "snapshots"

APP_TIMEZONE_NAME = os.environ.get("SCHOLARPATH_TIMEZONE", "Asia/Kolkata")
APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)

# Dataset modes. Each mode has its own database file so saved items, tracker
# entries and counts never mix between fictional and real data.
MODE_EXAMPLE = "example"
MODE_REAL = "real_source"
MODES = (MODE_EXAMPLE, MODE_REAL)
MODE_LABELS = {
    MODE_EXAMPLE: "Example data (fictional)",
    MODE_REAL: "Real sources (collected)",
}

# Polite collection defaults.
HTTP_TIMEOUT_SECONDS = 20
HTTP_MAX_RETRIES = 3
HTTP_DELAY_SECONDS = 2.0
HTTP_USER_AGENT = "ScholarPath-student-project/1.0 (educational, low-rate; single-user local tool)"

SQLITE_BUSY_TIMEOUT_MS = 5000


def db_dir() -> Path:
    override = os.environ.get("SCHOLARPATH_DATA_DIR")
    base = Path(override).expanduser().resolve() if override else DATA_DIR / "db"
    return base


def db_path(mode: str) -> Path:
    if mode not in MODES:
        raise ValueError(f"Unknown dataset mode: {mode!r}")
    name = "scholarpath_example.sqlite3" if mode == MODE_EXAMPLE else "scholarpath_real.sqlite3"
    return db_dir() / name


@dataclass(frozen=True)
class Clock:
    """Injectable source of 'today' and 'now' so date logic is testable."""

    fixed_today: date | None = None

    def today(self) -> date:
        if self.fixed_today is not None:
            return self.fixed_today
        instant = os.environ.get("SCHOLARPATH_NOW")
        if instant:   # a pinned instant decides the date too, so the two never disagree
            return datetime.fromisoformat(instant.replace("Z", "+00:00")).astimezone(APP_TIMEZONE).date()
        override = os.environ.get("SCHOLARPATH_TODAY")
        if override:
            return date.fromisoformat(override)
        return datetime.now(APP_TIMEZONE).date()

    def now(self) -> datetime:
        """The current instant (UTC). When 'today' is pinned (tests, demonstrations), "now" is
        noon of that day in the app timezone, so the date and the instant always agree."""
        override = os.environ.get("SCHOLARPATH_NOW")
        if override and self.fixed_today is None:
            return datetime.fromisoformat(override.replace("Z", "+00:00")).astimezone(timezone.utc)
        if self.fixed_today is not None or os.environ.get("SCHOLARPATH_TODAY"):
            day = self.today()
            return datetime(day.year, day.month, day.day, 12, tzinfo=APP_TIMEZONE).astimezone(timezone.utc)
        return datetime.now(timezone.utc).replace(microsecond=0)

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc).replace(microsecond=0)


def utc_now_iso() -> str:
    return Clock.now_utc().isoformat()
