"""Command-line interface: ``python -m scholarpath <command>``.

Commands
  init-examples   Build the fictional example dataset and import it (example DB).
  collect         Run real-source collectors (live HTTP, or saved snapshots) -> JSON.
  import-real     Import the collected real-source JSON into the real DB.
  status          Show database locations, schema versions and counts.
  backup          Copy a database with SQLite's backup API.
  migrate         Apply pending schema migrations (never deletes data).

Real-data collection is always an explicit command; the Streamlit app never
scrapes on startup or rerun.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from . import config
from .collectors.runner import SOURCES, CollectionError, run_collection, write_collection
from .database import backup
from .examples import write_example_dataset
from .services import ImportFailed, ScholarPathService


def _print_report(report) -> None:
    print(f"  {report.summary()}")
    for item in report.rejected[:10]:
        print(f"  rejected: {item.get('name')}: {'; '.join(item['reasons'])}")


def cmd_init_examples(args) -> int:
    anchor = date.fromisoformat(args.anchor_date) if args.anchor_date else config.Clock().today()
    path = write_example_dataset(anchor)
    service = ScholarPathService(config.MODE_EXAMPLE)
    service.ensure_schema()
    print(f"Example dataset (FICTIONAL) generated with deadlines relative to {anchor}: {path}")
    report = service.import_file(path)
    print(f"Imported into {service.db_path}")
    _print_report(report)
    return 0


def cmd_collect(args) -> int:
    sources = args.sources or list(SOURCES)
    mode = "saved browser snapshots" if args.from_snapshots else "live HTTP"
    print(f"Collecting {sources} from {mode} ...")
    report = run_collection(sources, use_snapshots=args.from_snapshots)
    print(f"  counts: {report.counts}")
    for src in report.sources:
        print(f"  {src}")
    for failure in report.failed:
        print(f"  FAILED {failure['url']}: {failure['error']}")
    for rejection in report.rejected:
        print(f"  REJECTED {rejection['source_url']}: {'; '.join(rejection['reasons'])}")
    try:
        target = write_collection(report, Path(args.output), allow_partial=args.allow_partial)
    except CollectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if target != Path(args.output):
        print(f"Some pages failed, so results were written to {target} and {args.output} was left unchanged.")
        print("Re-run later, or pass --allow-partial to merge the successful records anyway.")
        return 1
    print(f"Wrote {target} (merged by stable ID with previously collected records).")
    print("Next: python -m scholarpath import-real")
    return 0


def cmd_import_real(args) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"ERROR: {path} not found. Run `python -m scholarpath collect` first.", file=sys.stderr)
        return 2
    service = ScholarPathService(config.MODE_REAL)
    service.ensure_schema()
    try:
        report = service.import_file(path)
    except ImportFailed as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"Imported real-source records into {service.db_path}")
    _print_report(report)
    return 0


def cmd_status(_args) -> int:
    for mode in config.MODES:
        service = ScholarPathService(mode)
        print(f"[{config.MODE_LABELS[mode]}] {service.db_path}")
        if not service.database_exists():
            print("  not initialised")
            continue
        service.ensure_schema()
        info = service.overview()
        print(f"  schema v{service.schema_version()} | scholarships={info['scholarships']} "
              f"saved={info['saved']} tracked={info['tracked']}")
        if info["last_import"]:
            print(f"  last import: {info['last_import']['finished_at']} from {info['last_import']['source_file']}")
    return 0


def cmd_backup(args) -> int:
    source = config.db_path(args.mode)
    if not source.exists():
        print(f"ERROR: {source} does not exist.", file=sys.stderr)
        return 2
    stamp = config.utc_now_iso().replace(":", "").replace("+0000", "Z")
    destination = config.PROJECT_ROOT / "backups" / f"{source.stem}-{stamp}.sqlite3"
    backup(source, destination)
    print(f"Backed up {source} -> {destination}")
    return 0


def cmd_migrate(args) -> int:
    service = ScholarPathService(args.mode)
    print(f"{service.db_path}: schema v{service.ensure_schema()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scholarpath", description="ScholarPath data commands")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-examples", help="generate and import the fictional example dataset")
    p.add_argument("--anchor-date", help="ISO date the example deadlines are relative to (default: today)")
    p.set_defaults(func=cmd_init_examples)

    p = sub.add_parser("collect", help="collect real scholarship pages into JSON")
    p.add_argument("--sources", nargs="+", choices=sorted(SOURCES), help="default: all configured sources")
    p.add_argument("--from-snapshots", action="store_true", help="parse saved snapshots instead of live HTTP")
    p.add_argument("--allow-partial", action="store_true", help="merge results even if some pages failed")
    p.add_argument("--output", default=str(config.REAL_DATASET_FILE))
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("import-real", help="import collected real-source JSON")
    p.add_argument("--file", default=str(config.REAL_DATASET_FILE))
    p.set_defaults(func=cmd_import_real)

    p = sub.add_parser("status", help="show databases and counts")
    p.set_defaults(func=cmd_status)

    for name, func, help_text in (("backup", cmd_backup, "back up a database"),
                                  ("migrate", cmd_migrate, "apply schema migrations")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--mode", choices=config.MODES, default=config.MODE_EXAMPLE)
        p.set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
