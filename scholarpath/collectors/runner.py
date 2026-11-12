"""Run configured collectors and write the real-source JSON dataset safely.

Safety rules:
* An empty run (0 accepted records) is an error and writes nothing.
* A run with failed pages writes to a separate ``*.partial-<timestamp>.json``
  file unless ``allow_partial`` is set.
* The output file is merged by stable ID with what was already collected, so a
  record missing from one run is never dropped (absence is not proof that a
  scholarship disappeared). Pages that answered 404/410 are reported as
  ``unavailable`` so the importer can flag - not delete - those records.
* The file is written atomically (temp file, then replace).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..cleaning import ValidationError, validate_record
from . import cscuk, great
from .base import LiveFetcher, SnapshotFetcher

SOURCES = {
    cscuk.SOURCE_ID: cscuk,
    great.SOURCE_ID: great,
}


class CollectionError(RuntimeError):
    pass


@dataclass
class CollectionReport:
    records: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    duplicates: int = 0
    unavailable_urls: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)

    @property
    def counts(self) -> dict:
        return {
            "accepted": len(self.records),
            "rejected": len(self.rejected),
            "duplicates": self.duplicates,
            "failed": len(self.failed),
        }


def make_fetcher(source_id: str, use_snapshots: bool):
    module = SOURCES[source_id]
    if use_snapshots:
        return SnapshotFetcher(source_id)
    return LiveFetcher(allowed_hosts=set(module.ALLOWED_HOSTS))


def run_collection(source_ids: list[str], use_snapshots: bool, fetcher_factory=make_fetcher,
                   collected_at: str | None = None) -> CollectionReport:
    collected_at = collected_at or config.utc_now_iso()
    report = CollectionReport()
    seen: set[str] = set()
    for source_id in source_ids:
        if source_id not in SOURCES:
            raise CollectionError(f"Unknown source {source_id!r}; configured: {sorted(SOURCES)}")
        module = SOURCES[source_id]
        source_counts = {"source": source_id, "accepted": 0, "rejected": 0, "failed": 0}
        try:
            fetcher = fetcher_factory(source_id, use_snapshots)
        except Exception as exc:
            report.failed.append({"url": source_id, "error": str(exc), "status": None})
            source_counts["failed"] += 1
            report.sources.append(source_counts)
            continue
        for kind, payload in module.collect(fetcher, collected_at):
            if kind == "failed":
                report.failed.append(payload)
                source_counts["failed"] += 1
                if payload.get("status") in (404, 410):
                    report.unavailable_urls.append(payload["url"])
                continue
            try:
                record = validate_record(payload)
            except ValidationError as exc:
                report.rejected.append({"source_url": payload.get("source_url"), "reasons": exc.reasons})
                source_counts["rejected"] += 1
                continue
            if record.id in seen:
                report.duplicates += 1
                continue
            seen.add(record.id)
            report.records.append(record.to_dict())
            source_counts["accepted"] += 1
        report.sources.append(source_counts)
    return report


def _load_existing(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("records", []))


def write_collection(report: CollectionReport, output: Path = config.REAL_DATASET_FILE,
                     allow_partial: bool = False) -> Path:
    if not report.records:
        raise CollectionError(
            "Collection produced 0 valid records; nothing was written. "
            f"Failures: {report.failed[:3]} Rejections: {report.rejected[:3]}"
        )
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    merged = {r["id"]: r for r in _load_existing(output)}
    for record in report.records:
        merged[record["id"]] = record
    payload = {
        "dataset_origin": "real_source",
        "generated_at": config.utc_now_iso(),
        "collection_counts": report.counts,
        "sources": report.sources,
        "failed": report.failed,
        "rejected": report.rejected,
        "unavailable_urls": report.unavailable_urls,
        "records": sorted(merged.values(), key=lambda r: (r["source_name"], r["name"])),
    }
    target = output
    if report.failed and not allow_partial:
        stamp = config.utc_now_iso().replace(":", "").replace("+0000", "Z")
        target = output.with_name(f"{output.stem}.partial-{stamp}.json")
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)
    return target
