"""Build the fictional example dataset from its template.

Dated example deadlines are stored as day offsets so a live demo always has a
mix of upcoming, near and expired deadlines. The anchor date is recorded in the
generated file and in the database so the UI can state it. This never touches
real-source records.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from . import config
from .models import stable_id

EXAMPLE_NOTE = "FICTIONAL EXAMPLE - invented for demonstration; not a real scholarship."


def build_example_records(anchor: date, template_path: Path = config.EXAMPLE_TEMPLATE, collected_at: str | None = None) -> dict:
    template = json.loads(Path(template_path).read_text(encoding="utf-8"))
    source_name = template["source_name"]
    collected_at = collected_at or config.utc_now_iso()
    records = []
    for item in template["records"]:
        record = dict(item)
        offset = record.pop("deadline_offset_days", None)
        if record.get("deadline_kind") == "dated":
            record["deadline_date"] = (anchor + timedelta(days=int(offset))).isoformat()
            # Fictional deadlines close at the end of the day in the app's time zone.
            record["deadline_timezone"] = config.APP_TIMEZONE_NAME
        else:
            record["deadline_date"] = None
        key = record["source_key"]
        record.update(
            {
                "id": stable_id(source_name, key),
                "source_name": source_name,
                "source_url": f"https://example.org/scholarpath-fictional/{key}",
                "application_url": f"https://example.org/scholarpath-fictional/{key}/apply",
                "collected_at": collected_at,
                "source_fetched_at": None,
                "fetch_method": "fictional",
                "manual_verified_at": None,
                "dataset_origin": "example",
                "notes": EXAMPLE_NOTE,
                "source_status": "available",
            }
        )
        records.append(record)
    return {
        "dataset_origin": "example",
        "example_anchor_date": anchor.isoformat(),
        "generated_at": collected_at,
        "records": records,
    }


def write_example_dataset(anchor: date, out_dir: Path = config.EXAMPLE_BUILD_DIR) -> Path:
    payload = build_example_records(anchor)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "example_scholarships.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path
