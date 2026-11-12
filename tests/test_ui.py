"""Phase 3: Streamlit AppTest checks.

These drive app.py headlessly against a temporary database and then verify,
through a separate service object, that UI actions reached SQLite.
Workflow covered: Explore -> Filter -> Details -> Match -> Save -> Track ->
Dashboard -> Export (CSV content is checked in test_exports_and_tracker.py).
"""

from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from scholarpath import config
from scholarpath.matching import StudentProfile
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
    parts += [c.value for c in at.caption] + [c.value for c in at.code] + [t.value for t in at.title]
    parts += [t.value for t in at.toast]
    return "\n".join(str(p) for p in parts)


def click(at: AppTest, key: str) -> AppTest:
    at.button(key=key).click().run()
    assert not at.exception, at.exception
    return at


def test_missing_database_shows_setup_steps_without_fallback():
    at = run_app()
    assert "python -m scholarpath init-examples" in texts(at)
    at.sidebar.radio(key="mode").set_value(config.MODE_REAL).run()
    assert "python -m scholarpath import-real" in texts(at) and not at.exception


def test_overview_shows_database_counts_and_example_label(seeded):
    at = run_app()
    assert "Example data." in texts(at) and "invented for practice" in texts(at)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Scholarships"] == "15"
    assert metrics["Saved by you"] == "0"
    assert "Closing soon in this dataset" in texts(at)
    assert not at.warning  # no alarming yellow banners on a normal page


def test_explore_filter_details_save_track_dashboard_flow(seeded, example_records):
    at = goto(run_app(), "Explore")
    assert "15 results" in texts(at)

    at.multiselect(key="f_hosts").set_value(["United Kingdom"]).run()
    at.multiselect(key="f_funding").set_value(["full"]).run()
    assert "1 result" in texts(at)

    cedar_id = by_key(example_records, "cedar-public-health")["id"]
    click(at, f"ex_save_{cedar_id}")
    assert "Saved “Cedar Public Health Scholarship”" in texts(at)
    assert ScholarPathService(config.MODE_EXAMPLE).saved_ids() == [cedar_id]  # persisted
    assert at.button(key=f"ex_saved_{cedar_id}").disabled

    click(at, "clear_filters")
    assert "15 results" in texts(at)

    click(at, f"ex_det_{cedar_id}")
    assert at.session_state["page"] == "Scholarship details"
    assert "Cedar Public Health Scholarship" in [h.value for h in at.header]
    assert "Confirm on the official page" in texts(at)

    click(at, "d_track")
    app = ScholarPathService(config.MODE_EXAMPLE).get_application(cedar_id)
    assert app is not None and app.status == "interested"
    assert "Tracking started" in texts(at)

    at = goto(at, "My applications")
    assert "Due today to 7 days (1)" in texts(at) and "Cedar Public Health Scholarship" in texts(at)


def test_tracker_form_persists_and_rejects_invalid_combinations(seeded, example_records):
    sid = by_key(example_records, "vega-cs-masters")["id"]
    seeded.start_tracking(sid)
    at = goto(run_app(), "My applications")

    at.radio(key=f"t_status_{sid}").set_value("applied")
    at.text_area(key=f"t_notes_{sid}").input("Uploaded transcript")
    at.button[[b.label for b in at.button].index("Save changes")].click().run()
    assert any("Not saved yet" in e.value and "submitted" in e.value for e in at.error)
    assert ScholarPathService(config.MODE_EXAMPLE).get_application(sid).status == "interested"

    at.radio(key=f"t_status_{sid}").set_value("preparing")
    at.date_input(key=f"t_target_{sid}").set_value(date(2026, 11, 18))
    at.text_area(key=f"t_notes_{sid}").input("Uploaded transcript")
    at.button[[b.label for b in at.button].index("Save changes")].click().run()
    assert any("Saved" in s.value for s in at.success)

    reopened = ScholarPathService(config.MODE_EXAMPLE).get_application(sid)
    assert reopened.status == "preparing" and reopened.target_date == date(2026, 11, 18)
    assert reopened.notes == "Uploaded transcript"


def test_removing_from_shortlist_keeps_tracker(seeded, example_records):
    sid = by_key(example_records, "vega-cs-masters")["id"]
    seeded.save(sid)
    seeded.start_tracking(sid)
    at = goto(run_app(), "My applications")
    click(at, f"s_remove_{sid}")
    service = ScholarPathService(config.MODE_EXAMPLE)
    assert service.saved_ids() == [] and service.get_application(sid) is not None
    assert "tracker notes and history are kept" in texts(at).lower()


def _tab_counts(at: AppTest) -> dict[str, int]:
    """'(:material/x: )Good fits (4)' -> {'Good fits': 4}"""
    counts = {}
    for tab in at.tabs:
        label = tab.label.split(": ", 1)[-1] if tab.label.startswith(":material/") else tab.label
        name, _, number = label.rpartition(" (")
        counts[name] = int(number.rstrip(")"))
    return counts


def test_profile_matching_groups_results_with_explanations(seeded, example_records):
    at = goto(run_app(), "Profile matching")
    assert "Fill in what you know" in texts(at)
    at.selectbox(key="m_nat").set_value("India")
    at.selectbox(key="m_degree").set_value("master")
    at.selectbox(key="m_subject").set_value("computer_science")
    at.number_input(key="m_score").set_value(8.5)
    at.selectbox(key="m_scale").set_value("cgpa_10")
    at.button[0].click().run()  # the form's submit button
    assert not at.exception

    profile = StudentProfile("India", "master", "computer_science", 8.5, "cgpa_10")
    expected = Counter(m.group for _, m in seeded.match(profile))
    assert _tab_counts(at) == {"Good fits": expected["fit"], "Need more info": expected["missing"],
                               "Not a fit": expected["no_fit"]}
    assert expected["fit"] >= 1 and expected["no_fit"] >= 1

    body = texts(at)
    assert "Lakeshore STEM Excellence Award" in body and "Matches recorded requirements" in body
    assert "You meet all 5 recorded requirements." in body
    assert any(e.label.startswith("Confirm on the official page") for e in at.expander)
    assert "does not guarantee" in body
    assert "Tip:" not in body  # every field was filled in
    lakeshore = by_key(example_records, "lakeshore-stem-excellence")["id"]
    assert at.button(key=f"m_open_{lakeshore}") is not None


def test_profile_matching_rejects_score_without_scale(seeded):
    at = goto(run_app(), "Profile matching")
    at.number_input(key="m_score").set_value(8.5)
    at.button[0].click().run()
    assert any("scale" in e.value for e in at.error)


def test_blank_profile_is_never_a_match_and_suggests_what_to_add(seeded):
    at = goto(run_app(), "Profile matching")
    at.button[0].click().run()
    assert _tab_counts(at) == {"Good fits": 0, "Need more info": 15, "Not a fit": 0}
    body = texts(at)
    assert "Tip: add your citizenship, degree, score and subject" in body
    assert "Add your citizenship, degree and subject above to check the rest." in body


def test_switching_dataset_isolates_saved_items_and_clears_selection(seeded, example_records):
    real = ScholarPathService(config.MODE_REAL)
    real.import_records([real_record()])
    seeded.save(example_records[0]["id"])

    at = goto(run_app(), "Scholarship details")
    at.selectbox(key="selected_id").set_value(example_records[0]["id"]).run()
    at.sidebar.radio(key="mode").set_value(config.MODE_REAL).run()
    assert not at.exception
    assert "Real sources." in texts(at) and "Example data." not in texts(at)
    assert at.session_state["selected_id"] == real_record()["id"]
    at = goto(at, "My applications")
    assert "Your shortlist is empty" in texts(at)


def test_insights_states_scope_and_draws_charts(seeded):
    at = goto(run_app(), "Insights")
    assert "15 scholarships" in texts(at) and "no filters" in texts(at)
    assert "counts once in each" in texts(at)
    assert len(at.get("vega_lite_chart")) == 3


def test_untrusted_text_is_escaped_not_rendered(tmp_path, clock):
    real = ScholarPathService(config.MODE_REAL)
    real.import_records([real_record(name="<script>alert(1)</script> **Bold** [x](https://evil.example)",
                                     provider="<img src=x onerror=alert(1)>",
                                     eligibility_text="$x$ and <b>tags</b>")])
    at = run_app()
    at.sidebar.radio(key="mode").set_value(config.MODE_REAL).run()
    at = goto(at, "Explore")
    html_blocks = " ".join(m.value for m in at.markdown if "sp-card-title" in m.value)
    assert "&lt;script&gt;" in html_blocks and "<script>" not in html_blocks
    assert "&lt;img src=x onerror=alert(1)&gt;" in html_blocks
    at = goto(at, "Scholarship details")
    assert "\\$x\\$" in texts(at) and "<b>tags</b>" not in texts(at).replace("\\<b\\>", "")


def test_every_page_renders_without_errors(seeded):
    at = run_app()
    for page in ["Overview", "Explore", "Profile matching", "Scholarship details", "My applications", "Insights"]:
        goto(at, page)
        assert not at.error, f"{page}: {[e.value for e in at.error]}"
        assert not at.warning, f"{page}: unexpected warning banner"
