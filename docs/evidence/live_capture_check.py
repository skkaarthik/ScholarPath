"""Run the 28 Nov 2026 live capture through the finder's own code (adapters, India test, place
normalisation, validation, deduplication, coverage). Facts only; no descriptions were captured, so
stipend, duration, degree and year cannot be checked from this capture.

    python docs/evidence/live_capture_check.py
"""
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scholarpath.collectors import internship_runner as finder          # noqa: E402
from scholarpath.collectors.internship_sources import BOARDS            # noqa: E402

capture = json.loads((Path(__file__).with_name("live_capture_2026-11-28.json")).read_text())
FETCHED = "2026-11-28T13:25:00+00:00"


@dataclass
class Page:
    html: str
    fetched_at: str = FETCHED


class CaptureFetcher:
    def get(self, url):
        board = next(b for b in BOARDS if b.api_url == url)
        listed = capture[board.platform]["listed"][board.token]
        if not isinstance(listed, int):
            raise finder.FetchError(f"{url}: {listed}")
        rows = [r for r in capture[board.platform]["rows"] if r[0] == board.token]
        if board.platform == "greenhouse":
            jobs = [{"id": f"{board.token}-{i}", "title": r[1], "location": {"name": r[2]},
                     "offices": [{"name": r[3]}], "absolute_url": f"https://job-boards.greenhouse.io/{board.token}/jobs/{i}",
                     "content": ""} for i, r in enumerate(rows)]
            jobs += [{"id": f"other-{i}", "title": "Senior Engineer", "location": {"name": "Chennai"},
                      "absolute_url": "https://example.org/x", "content": ""} for i in range(listed - len(rows))]
            return Page(json.dumps({"jobs": jobs}))
        posts = [{"id": f"{board.token}-{i}", "text": r[1], "country": r[5], "workplaceType": r[4],
                  "categories": {"location": r[2], "allLocations": r[3].split("/"), "commitment": r[6]},
                  "hostedUrl": f"https://jobs.lever.co/{board.token}/{i}", "lists": []} for i, r in enumerate(rows)]
        posts += [{"id": f"other-{i}", "text": "Senior Engineer", "categories": {"commitment": "Full-time"},
                   "hostedUrl": "https://example.org/x", "lists": []} for i in range(listed - len(rows))]
        return Page(json.dumps(posts))


run = finder.collect(fetcher=CaptureFetcher())
for s in run.sources:
    print(f"{s['status']:6} {s['source_name']:45} listed={s['listed']!s:5} internships_in_india={s['internships']}"
          + (f"  ({s['error']})" if s["error"] else ""))
print("duplicates merged:", run.duplicates_merged, "| rejected:", len(run.rejected))
print("coverage:", finder.coverage(run.records))
for r in sorted(run.records, key=lambda r: (r["cities"][:1] or ["~"], r["title"])):
    print(f"  {', '.join(r['cities']) or ('Remote' if r['work_arrangement'] == 'remote' else 'India')}: "
          f"{r['title']} - {r['employer']} [{r['work_arrangement']}]")

# --- storage, filtering and display: the same records through the database and the app --------
if "--app" in sys.argv:
    import os
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    os.environ["SCHOLARPATH_DATA_DIR"] = str(tmp / "db")
    from streamlit.testing.v1 import AppTest

    from scholarpath import config
    from scholarpath.services import InternshipService

    published = finder.write_dataset(run, tmp / "real_internships.json")
    config.REAL_INTERNSHIPS_FILE = published
    svc = InternshipService(config.MODE_REAL)
    print("import:", svc.sync_published(published), "| stored coverage:", svc.coverage())
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state["kind"], at.session_state["mode"] = "internship", config.MODE_REAL
    at.run()
    for place in ("chennai", "bengaluru", "remote", "all_india"):
        at.segmented_control(key="i_place").set_value(place).run()
        print(f"Find Internships, {place}: {at.header[0].value}; first: {[s.value for s in at.subheader][:2]}")
    at.session_state["_goto"] = "data"
    at.run()
    print("Data & sources metrics:", {m.label: m.value for m in at.metric})
    assert not at.exception, at.exception
