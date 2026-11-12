"""Phase 3: Streamlit AppTest checks.

These drive app.py headlessly against a temporary database and then verify,
through a separate service object, that UI actions reached SQLite.
Workflow covered: Explore -> Filter -> Details -> Match -> Save -> Track ->
Dashboard -> Export (CSV content is checked in test_exports_and_tracker.py).
"""

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from scholarpath import config
from scholarpath.services import ScholarPathService

from .conftest import by_key, real_record

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def seeded(example_records):
    service = ScholarPathService(config.MODE_EXAMPLE)  # temp DB via SCHOLARPATH_DATA_DIR
    service.import_records(example_records, source_file="test")
    return service


def run_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def goto(at: AppTest, page: str) -> AppTest:
    at.sidebar.radio(key="page").set_value(page).run()
    assert not at.exception, at.exception
    return at


def texts(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [e.value for e in at.error] + [w.value for w in at.warning]
    parts += [s.value for s in at.success] + [i.value for i in at.info] + [s.value for s in at.subheader]
    return "\n".join(str(p) for p in parts)


def test_missing_database_shows_clear_message_without_fallback():
    at = run_app()
    assert "init-examples" in texts(at)
    at.sidebar.radio(key="mode").set_value(config.MODE_REAL).run()
    assert "import-real" in texts(at) and not at.exception


def test_overview_shows_database_counts_and_example_label(seeded):
    at = run_app()
    assert "EXAMPLE DATA" in texts(at)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Scholarships in dataset"] == "15"
    assert metrics["Saved"] == "0"


def test_explore_filter_details_save_track_dashboard_flow(seeded, example_records):
    at = goto(run_app(), "Explore")
    assert "15 results" in texts(at)

    at.multiselect(key="f_hosts").set_value(["United Kingdom"]).run()
    at.multiselect(key="f_funding").set_value(["full"]).run()
    assert "1 result" in texts(at)

    at.button(key="explore_save").click().run()
    assert "Saved to your shortlist" in texts(at)
    cedar_id = by_key(example_records, "cedar-public-health")["id"]
    assert ScholarPathService(config.MODE_EXAMPLE).saved_ids() == [cedar_id]  # persisted

    at.button(key="clear_filters").click().run()
    assert "15 results" in texts(at)

    at.selectbox(key="explore_open_id").set_value(cedar_id).run()
    at.button(key="explore_details").click().run()
    assert at.session_state["page"] == "Scholarship details"
    assert "Cedar Public Health Scholarship" in [h.value for h in at.header]
    assert "Manual-review items" in texts(at)

    at.button(key="d_track").click().run()
    app = ScholarPathService(config.MODE_EXAMPLE).get_application(cedar_id)
    assert app is not None and app.status == "interested"

    at = goto(at, "My applications")
    assert "Due today to 7 days" in texts(at) and "Cedar Public Health Scholarship" in texts(at)


def test_tracker_form_persists_and_rejects_invalid_combinations(seeded, example_records):
    sid = by_key(example_records, "vega-cs-masters")["id"]
    seeded.start_tracking(sid)
    at = goto(run_app(), "My applications")

    at.selectbox(key=f"t_status_{sid}").set_value("applied")
    at.text_area(key=f"t_notes_{sid}").input("Uploaded transcript")
    at.button[[b.label for b in at.button].index("Save changes")].click().run()
    assert any("Not saved" in e.value and "submitted" in e.value for e in at.error)
    assert ScholarPathService(config.MODE_EXAMPLE).get_application(sid).status == "interested"

    at.selectbox(key=f"t_status_{sid}").set_value("preparing")
    at.date_input(key=f"t_target_{sid}").set_value(date(2026, 11, 18))
    at.text_area(key=f"t_notes_{sid}").input("Uploaded transcript")
    at.button[[b.label for b in at.button].index("Save changes")].click().run()
    assert any("Saved" in s.value for s in at.success)

    reopened = ScholarPathService(config.MODE_EXAMPLE).get_application(sid)
    assert reopened.status == "preparing" and reopened.target_date == date(2026, 11, 18)
    assert reopened.notes == "Uploaded transcript"


def test_profile_matching_form_shows_rule_explanations(seeded):
    at = goto(run_app(), "Profile matching")
    assert "Fill in what you know" in texts(at)
    at.selectbox(key="m_nat").set_value("India")
    at.selectbox(key="m_degree").set_value("master")
    at.selectbox(key="m_subject").set_value("computer_science")
    at.number_input(key="m_score").set_value(8.5)
    at.selectbox(key="m_scale").set_value("cgpa_10")
    at.button[0].click().run()  # the form's submit button
    assert not at.exception
    labels = [e.label for e in at.expander]
    assert labels[0].startswith("✅ Matches recorded requirements") and "Lakeshore" in labels[0]
    assert any(label.startswith("❌") for label in labels) and any(label.startswith("⚠️") for label in labels)
    assert "does not guarantee" in texts(at)


def test_profile_matching_rejects_score_without_scale(seeded):
    at = goto(run_app(), "Profile matching")
    at.number_input(key="m_score").set_value(8.5)
    at.button[0].click().run()
    assert any("scale" in e.value for e in at.error)


def test_switching_dataset_isolates_saved_items_and_clears_selection(seeded, example_records, clock):
    real = ScholarPathService(config.MODE_REAL)
    real.import_records([real_record()])
    seeded.save(example_records[0]["id"])

    at = goto(run_app(), "Scholarship details")
    at.selectbox(key="selected_id").set_value(example_records[0]["id"]).run()
    at.sidebar.radio(key="mode").set_value(config.MODE_REAL).run()
    assert not at.exception
    assert "Real-source data" in texts(at) and "EXAMPLE DATA" not in texts(at)
    assert at.session_state["selected_id"] == real_record()["id"]
    at = goto(at, "My applications")
    assert "Your shortlist is empty" in texts(at)


def test_insights_states_scope_and_draws_charts(seeded):
    at = goto(run_app(), "Insights")
    assert "Scope:" in texts(at) and "15 scholarships" in texts(at)
    assert "counts once in each" in " ".join(c.value for c in at.caption)
    assert len(at.get("vega_lite_chart")) == 3


def test_every_page_renders_without_errors(seeded):
    at = run_app()
    for page in ["Overview", "Explore", "Profile matching", "Scholarship details", "My applications", "Insights"]:
        goto(at, page)
        assert not at.error, f"{page}: {[e.value for e in at.error]}"
