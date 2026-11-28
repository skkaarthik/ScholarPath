"""The live internship finder: read every board, normalise, deduplicate, publish safely.

* Each board is fetched with the polite LiveFetcher: allow-listed hosts, robots.txt,
  a timeout per request, a pause between requests and bounded retries with backoff.
* A board that fails does not stop the run. Its last successfully collected records are
  carried over unchanged from the previous dataset, with that board's last success time,
  and the failure is recorded in the dataset's ``sources`` list.
* Duplicates are merged within and across boards by the stable internship ID (employer,
  role and place). The listing from the earlier board in ``BOARDS`` stays the main one;
  the others are kept as "also listed on" links.
* Every record is validated before anything is written. A run in which no board could
  be read writes nothing. The dataset file is replaced atomically (temp file, then rename).
* Only live answers reach this file. Tests pass their own fetcher and output path.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..cleaning import ValidationError, validate_internship
from .base import FetchError, LiveFetcher
from .internship_sources import BOARDS, HOSTS, PARSERS, Board


class InternshipCollectionError(RuntimeError):
    pass


@dataclass
class InternshipRun:
    records: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    duplicates_merged: int = 0
    generated_at: str = ""

    @property
    def succeeded(self) -> list[dict]:
        return [s for s in self.sources if s["status"] == "ok"]

    @property
    def failed(self) -> list[dict]:
        return [s for s in self.sources if s["status"] == "failed"]


def load_previous(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"records": [], "sources": []}


def _merge(records: list[dict], order: dict[str, int]) -> tuple[list[dict], int]:
    """One record per internship ID. The main listing is the one from the earliest board;
    every other listing of the same internship becomes an "also listed on" link."""
    by_id: dict[str, dict] = {}
    merged = 0
    for rec in sorted(records, key=lambda r: (order.get(r["source_name"], len(order)), r["source_key"])):
        kept = by_id.get(rec["id"])
        if kept is None:
            by_id[rec["id"]] = {**rec, "also_listed": list(rec.get("also_listed") or [])}
            continue
        merged += 1
        links = kept["also_listed"]
        known = {kept["application_url"]} | {link["url"] for link in links}
        for link in [{"source_name": rec["source_name"], "url": rec["application_url"]}, *(rec.get("also_listed") or [])]:
            if link["url"] not in known:
                links.append(link)
                known.add(link["url"])
        # Fill a gap from the other listing; never overwrite what the main listing states.
        if kept.get("stipend_kind") == "unknown" and rec.get("stipend_kind") != "unknown":
            for key in ("stipend_kind", "stipend_min", "stipend_max", "stipend_text"):
                kept[key] = rec.get(key)
        if kept.get("duration_months") is None and rec.get("duration_months") is not None:
            kept["duration_months"], kept["duration_text"] = rec["duration_months"], rec.get("duration_text", "")
    return list(by_id.values()), merged


def collect(boards: tuple[Board, ...] = BOARDS, fetcher=None, previous: dict | None = None) -> InternshipRun:
    """Read every board once. ``fetcher`` needs a ``get(url)`` returning an object with ``html`` and
    ``fetched_at`` (base.LiveFetcher by default)."""
    fetcher = fetcher or LiveFetcher(set(HOSTS.values()))
    previous = previous or {"records": [], "sources": []}
    before = {s["source_name"]: s for s in previous.get("sources") or []}
    run = InternshipRun(generated_at=config.utc_now_iso())
    collected: list[dict] = []
    for board in boards:
        status = {"source_name": board.source_name, "platform": board.platform, "board": board.token,
                  "url": board.api_url.split("?")[0], "focus": board.focus,
                  "last_success_at": before.get(board.source_name, {}).get("last_success_at")}
        try:
            page = fetcher.get(board.api_url)
            records, listed = PARSERS[board.platform](board, page.html, page.fetched_at)
        except (FetchError, ValueError, KeyError, TypeError) as exc:
            kept = [r for r in previous.get("records") or [] if r.get("source_name") == board.source_name]
            collected += kept
            status.update({"status": "failed", "error": str(exc)[:300], "listed": None, "internships": len(kept),
                           "carried_over": len(kept)})
            run.sources.append(status)
            continue
        valid = []
        for raw in records:
            try:
                validate_internship(raw)
            except ValidationError as exc:
                run.rejected.append({"source_name": board.source_name, "title": raw.get("title"), "reasons": exc.reasons})
                continue
            valid.append(raw)
        collected += valid
        status.update({"status": "ok", "error": "", "listed": listed, "internships": len(valid), "carried_over": 0,
                       "last_success_at": page.fetched_at})
        run.sources.append(status)
    order = {b.source_name: i for i, b in enumerate(boards)}
    run.records, run.duplicates_merged = _merge(collected, order)
    return run


def coverage(records: list[dict]) -> dict[str, int]:
    """Unique internships in Chennai, Bengaluru, the rest of India and remote (one record can count
    in several places)."""
    return {
        "unique": len(records),
        "chennai": sum(1 for r in records if "Chennai" in r["cities"]),
        "bengaluru": sum(1 for r in records if "Bengaluru" in r["cities"]),
        "rest_of_india": sum(1 for r in records if any(c not in ("Chennai", "Bengaluru") for c in r["cities"])
                             or (not r["cities"] and r["work_arrangement"] != "remote")),
        "remote": sum(1 for r in records if r["work_arrangement"] == "remote"),
    }


def write_dataset(run: InternshipRun, path: Path = config.REAL_INTERNSHIPS_FILE) -> Path:
    """Publish atomically. Refuses a run in which no board could be read."""
    if not run.succeeded:
        raise InternshipCollectionError("No internship source could be read; the previous dataset was kept unchanged.")
    payload = {
        "dataset": "internships", "dataset_origin": "real_source", "dataset_version": run.generated_at,
        "generated_at": run.generated_at, "coverage": coverage(run.records), "sources": run.sources,
        "duplicates_merged": run.duplicates_merged, "rejected": run.rejected,
        "records": sorted(run.records, key=lambda r: r["id"]),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, path)
    return path
