"""Seed a disposable data folder: example scholarships + internships, one existing scholarship save
and one scholarship application (the "existing v1 data" the journey must return to)."""
import os, sys
from datetime import date
from pathlib import Path
os.environ["SCHOLARPATH_DATA_DIR"] = sys.argv[1]
os.environ["SCHOLARPATH_TODAY"] = "2026-11-12"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scholarpath import config, examples
from scholarpath.services import InternshipService, ScholarPathService
build = Path(sys.argv[1]) / "build"
s = ScholarPathService(config.MODE_EXAMPLE)
s.import_file(examples.write_example_dataset(date(2026, 11, 12), out_dir=build))
i = InternshipService(config.MODE_EXAMPLE)
i.import_file(examples.write_example_internships(date(2026, 11, 12), out_dir=build))
views = s.search()
s.save(views[0].record.id)
s.mark_applied(views[1].record.id, date(2026, 11, 1))
print(views[0].record.name, "|", views[1].record.name)
