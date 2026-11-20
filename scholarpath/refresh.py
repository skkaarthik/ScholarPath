"""Scheduled refresh of the published real-source dataset.

``python -m scholarpath refresh`` is what the GitHub Actions workflow runs once a day.
It does real work only when a refresh is due:

* **Due** = at least ``REFRESH_INTERVAL`` (15 days) has elapsed since the last
  *successful* refresh, or ``--force`` was given. A failed attempt never moves the
  last-success time, so the next daily run simply tries again.
* **Lock**: a lock file stops two refreshes overlapping on one machine (the workflow
  also has a concurrency group).
* **Staging**: every enabled source is collected live into memory, then validated as a
  whole. If ANY enabled source fails, or validation sees malformed records, duplicate IDs,
  impossible dates, an empty source or a large unexplained drop in records, nothing is
  published: the previous dataset stays exactly as it was and the attempt is recorded as
  failed (this version is all-or-nothing on purpose).
* **Publish**: the validated dataset is written to a temporary file in the same folder,
  read back and re-validated, then swapped in with ``os.replace`` (atomic). It is only
  rewritten when its content changed in a meaningful way (collection timestamps alone do
  not count), so Git sees a commit only for real changes.
* **Never delete**: a record missing from a new collection is kept as it was; absence
  from a page is not proof that a scholarship expired (closing is decided by dates.py).

Refresh metadata lives in ``data/refresh/state.json`` (committed; no personal data).
Nothing here runs from the website: the app only *reads* the published files.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config
from .cleaning import VOLATILE_FIELDS, validate_many
from .collectors import runner

REFRESH_INTERVAL = timedelta(days=15)
STATE_FILE = config.DATA_DIR / "refresh" / "state.json"
LOCK_FILE = config.DATA_DIR / "refresh" / "refresh.lock"     # git-ignored
STALE_LOCK = timedelta(hours=3)                               # a crashed run's lock is ignored after this
STATE_VERSION = 1


@dataclass(frozen=True)
class Thresholds:
    """Validation limits. A refresh that breaks any of them publishes nothing."""

    max_failed_pages: int = 0          # every page of every enabled source must be read
    max_rejected_records: int = 0      # every collected record must pass validation
    max_duplicate_ids: int = 0         # two records may never claim the same stable ID
    min_records_per_source: int = 1    # an enabled source that returns nothing is broken, not empty
    max_drop_fraction: float = 0.25    # a source may lose at most 25 % of its published records...
    drop_check_min_records: int = 4    # ...once it has at least this many (small sources vary a lot)
    max_years_ahead: int = 5           # a deadline more than 5 years away is a parsing error
    max_years_back: int = 3            # so is one more than 3 years in the past


DEFAULT_THRESHOLDS = Thresholds()


class RefreshLocked(RuntimeError):
    pass


@dataclass
class RefreshResult:
    outcome: str                        # "not_due" | "published" | "unchanged" | "failed" | "dry_run"
    message: str
    problems: list[str] = field(default_factory=list)
    next_due_at: str | None = None
    dataset_changed: bool = False
    state_changed: bool = False

    @property
    def exit_code(self) -> int:
        return 1 if self.outcome == "failed" else 0


# --- state -----------------------------------------------------------------------------

def load_state(path: Path = STATE_FILE) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": STATE_VERSION, "last_success_at": None, "latest_attempt": None, "sources": {}}


def _atomic_write(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save_state(state: dict, path: Path = STATE_FILE) -> None:
    _atomic_write(path, json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def _parse(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts) if ts else None


def next_due(state: dict, interval: timedelta = REFRESH_INTERVAL) -> datetime | None:
    """When the next refresh is due; None means "now" (no successful refresh yet)."""
    last = _parse(state.get("last_success_at"))
    return last + interval if last else None


def is_due(state: dict, now: datetime, interval: timedelta = REFRESH_INTERVAL) -> bool:
    due = next_due(state, interval)
    return due is None or now >= due


# --- lock ------------------------------------------------------------------------------

class refresh_lock:
    """Exclusive lock file (O_EXCL). A lock older than STALE_LOCK is from a crashed run."""

    def __init__(self, path: Path = LOCK_FILE, now: datetime | None = None):
        self.path, self.now = Path(path), now or datetime.now(timezone.utc)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            started = datetime.fromtimestamp(self.path.stat().st_mtime, timezone.utc)
            if self.now - started < STALE_LOCK:
                raise RefreshLocked(f"Another refresh is running (lock file {self.path}).")
            self.path.unlink()
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, self.now.isoformat().encode())
        os.close(fd)
        return self

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)
        return False


# --- dataset ---------------------------------------------------------------------------

def dataset_version(records: list[dict]) -> str:
    """Content fingerprint of a dataset. Collection timestamps and source status are left
    out, so re-reading unchanged pages gives the same version (and no commit)."""
    canonical = sorted(({k: v for k, v in r.items() if k not in VOLATILE_FIELDS} for r in records),
                       key=lambda r: r["id"])
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def load_published(path: Path = config.REAL_DATASET_FILE) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"records": []}
    payload.setdefault("dataset_version", dataset_version(payload.get("records", [])))
    return payload


def validate_collection(report: runner.CollectionReport, previous: list[dict], source_ids: list[str],
                        today: date, thresholds: Thresholds = DEFAULT_THRESHOLDS) -> list[str]:
    """Everything that makes a collection unsafe to publish (empty list = safe)."""
    problems = []
    if len(report.failed) > thresholds.max_failed_pages:
        problems += [f"Page could not be read: {f['url']} ({f['error'][:160]})" for f in report.failed]
    if len(report.rejected) > thresholds.max_rejected_records:
        problems += [f"Malformed record from {r.get('source_url')}: {'; '.join(r['reasons'])[:200]}"
                     for r in report.rejected]
    if report.duplicates > thresholds.max_duplicate_ids:
        problems.append(f"{report.duplicates} records had a duplicate ID")
    for rec in report.records:
        if rec.get("deadline_date"):
            day = date.fromisoformat(rec["deadline_date"])
            if not (today.year - thresholds.max_years_back <= day.year <= today.year + thresholds.max_years_ahead):
                problems.append(f"Implausible deadline {day} for {rec['name']!r}")
    for source_id in source_ids:
        name = runner.SOURCES[source_id].SOURCE_NAME
        new = sum(1 for r in report.records if r["source_name"] == name)
        old = sum(1 for r in previous if r["source_name"] == name)
        if new < thresholds.min_records_per_source:
            problems.append(f"{name}: no records collected")
        elif old >= thresholds.drop_check_min_records and new < old * (1 - thresholds.max_drop_fraction):
            problems.append(f"{name}: only {new} records collected, {old} are published "
                            f"(more than {thresholds.max_drop_fraction:.0%} fewer)")
    return problems


def merge(previous: list[dict], fresh: list[dict]) -> list[dict]:
    """New records replace old ones with the same ID; old ones not seen again are kept."""
    merged = {r["id"]: r for r in previous}
    merged.update({r["id"]: r for r in fresh})
    return sorted(merged.values(), key=lambda r: (r["source_name"], r["name"], r["id"]))


def publish(records: list[dict], report: runner.CollectionReport, path: Path, now: datetime) -> str:
    """Write the dataset atomically after re-validating what was written. Returns its version."""
    version = dataset_version(records)
    payload = {
        "dataset_origin": "real_source",
        "dataset_version": version,
        "generated_at": now.isoformat(),
        "collection_counts": report.counts,
        "sources": report.sources,
        "failed": report.failed,
        "rejected": report.rejected,
        "unavailable_urls": report.unavailable_urls,
        "records": records,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.staging")
    staging.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written = json.loads(staging.read_text(encoding="utf-8"))
    valid, rejected, duplicates = validate_many(written["records"])
    if rejected or duplicates or len(valid) != len(records):
        staging.unlink()
        raise RuntimeError("The staged dataset failed re-validation; nothing was published.")
    os.replace(staging, path)
    return version


# --- the refresh -----------------------------------------------------------------------

def enabled_sources() -> list[str]:
    return runner.enabled_source_ids()


def run_refresh(now: datetime | None = None, force: bool = False, dry_run: bool = False,
                source_ids: list[str] | None = None, dataset_path: Path = config.REAL_DATASET_FILE,
                state_path: Path = STATE_FILE, lock_path: Path = LOCK_FILE,
                fetcher_factory=runner.make_fetcher, thresholds: Thresholds = DEFAULT_THRESHOLDS,
                interval: timedelta = REFRESH_INTERVAL) -> RefreshResult:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    state = load_state(state_path)
    if not (force or dry_run) and not is_due(state, now, interval):
        due = next_due(state, interval)
        return RefreshResult("not_due", f"Not due: last successful refresh {state['last_success_at']}, "
                                        f"next due {due.isoformat()}.", next_due_at=due.isoformat())
    sources = source_ids or enabled_sources()
    with refresh_lock(lock_path, now):
        previous_payload = load_published(dataset_path)
        previous = previous_payload.get("records", [])
        report = runner.run_collection(sources, use_snapshots=False, fetcher_factory=fetcher_factory,
                                       collected_at=now.isoformat())
        problems = validate_collection(report, previous, sources, now.date(), thresholds)
        per_source = {s["source"]: {"accepted": s["accepted"], "rejected": s["rejected"], "failed": s["failed"],
                                    "status": "ok" if not s["failed"] and not s["rejected"] and s["accepted"]
                                    else "failed"} for s in report.sources}
        if dry_run:
            return RefreshResult("dry_run", f"Dry run: {report.counts}; nothing was written.", problems)
        if problems:
            changed = _record_failure(state, problems, per_source, now, state_path)
            return RefreshResult("failed", "Refresh failed; the previous dataset is still published.",
                                 problems, state_changed=changed)

        merged = merge(previous, report.records)
        version = dataset_version(merged)
        dataset_changed = version != previous_payload.get("dataset_version")
        if dataset_changed:
            publish(merged, report, dataset_path, now)
        for source_id, info in per_source.items():
            info["last_success_at"] = now.isoformat()
        state.update({
            "version": STATE_VERSION,
            "last_success_at": now.isoformat(),
            "dataset_version": version,
            "records": len(merged),
            "latest_attempt": {"status": "success", "at": now.isoformat(), "problems": []},
            "sources": {**state.get("sources", {}), **per_source},
        })
        save_state(state, state_path)
        outcome = "published" if dataset_changed else "unchanged"
        return RefreshResult(outcome, f"Refresh succeeded ({report.counts}); dataset "
                                      f"{'updated' if dataset_changed else 'unchanged'}.",
                             next_due_at=(now + interval).isoformat(), dataset_changed=dataset_changed,
                             state_changed=True)


def _record_failure(state: dict, problems: list[str], per_source: dict, now: datetime, path: Path) -> bool:
    """Record a failed attempt without touching last_success_at. The file is rewritten only
    when the failure is new or different, so a daily retry of the same failure makes no commit."""
    previous = state.get("latest_attempt") or {}
    if previous.get("status") == "failed" and previous.get("problems") == problems[:20]:
        return False
    state["latest_attempt"] = {"status": "failed", "at": now.isoformat(), "problems": problems[:20]}
    for source_id, info in per_source.items():
        old = state.setdefault("sources", {}).get(source_id, {})
        state["sources"][source_id] = {**info, "last_success_at": old.get("last_success_at")}
    save_state(state, path)
    return True
