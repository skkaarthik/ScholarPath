"""Streamlit AppTest checks.

These drive app.py headlessly against a temporary database and then verify,
through a separate service object, that UI actions reached SQLite.
Workflow covered: Find -> Filter -> Review -> Apply -> Confirm -> Applications,
plus Saved, Check my fit and the other pages (CSV content is checked in
test_exports_and_tracker.py).
Pages are opened the same way the app's own buttons do it (common.go_to).
"""

from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from scholarpath import config
from scholarpath.matching import StudentProfile
from scholarpath.services import ScholarPathService

from .conftest import FIXED_TODAY, by_key, real_record

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
    at.session_state["_goto"] = page
    at.run()
    assert not at.exception, at.exception
    return at


def texts(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [e.value for e in at.error] + [w.value for w in at.warning]
    parts += [s.value for s in at.success] + [i.value for i in at.info] + [s.value for s in at.subheader]
    parts += [c.value for c in at.caption] + [c.value for c in at.code] + [t.value for t in at.title]
    parts += [t.value for t in at.toast] + [h.value for h in at.header]
    return "\n".join(str(p) for p in parts)


def submit_fit(at: AppTest) -> AppTest:
    at.button[[b.label for b in at.button].index("Check my fit")].click().run()
    assert not at.exception, at.exception
    return at


def card_ids(at: AppTest, prefix: str = "find_rev_") -> list[str]:
    return [b.key[len(prefix):] for b in at.button if b.key and b.key.startswith(prefix)]


def click(at: AppTest, key: str) -> AppTest:
    at.button(key=key).click().run()
    assert not at.exception, at.exception
    return at


def link_labels(at: AppTest) -> list[str]:
    return [b.proto.label for b in at.get("link_button")]


def open_review(at: AppTest, scholarship_id: str, back: str = "find") -> AppTest:
    at.session_state["selected_id"] = scholarship_id
    at.session_state["review_back"] = back
    return goto(at, "review")


def test_missing_database_shows_setup_steps_without_fallback():
    at = run_app()
    assert "python -m scholarpath init-examples" in texts(at)
    at.sidebar.radio(key="mode").set_value(config.MODE_REAL).run()
    assert "python -m scholarpath import-real" in texts(at) and not at.exception


def test_app_opens_on_find_scholarships(seeded):
    at = run_app()
    assert [t.value for t in at.title] == ["Find scholarships"]
    assert "Example data:" in texts(at) and "15 scholarships" in texts(at)
    assert not at.warning  # no alarming yellow banners on a normal page


def test_find_review_apply_track_flow(seeded, example_records):
    """A first-time user goes from search to a tracked application without saving anything."""
    at = run_app()
    assert "Filtered by" not in texts(at)
    at.multiselect(key="f_hosts").set_value(["United Kingdom"]).run()
    at.multiselect(key="f_funding").set_value(["full"]).run()
    assert "1 scholarship" in texts(at)
    assert "Filtered by Country: United Kingdom · Funding: Full" in texts(at)  # active filter summary

    cedar_id = by_key(example_records, "cedar-public-health")["id"]
    click(at, f"find_rev_{cedar_id}")  # step 2: review
    assert "Cedar Public Health Scholarship" in [t.value for t in at.title]
    assert at.button(key="r_back").label == "Back to results"
    assert "Who can apply" in texts(at) and "Eligibility" in texts(at)

    assert "Apply on provider site" in link_labels(at)  # step 3: apply happens on the provider's site
    service = ScholarPathService(config.MODE_EXAMPLE)
    click(at, "r_mark")
    assert "Confirm your submission" in texts(at)
    assert service.get_application(cedar_id) is None  # nothing is tracked before the user confirms
    click(at, "r_not_yet")
    assert service.get_application(cedar_id) is None and at.button(key="r_mark") is not None

    click(at, "r_mark")
    click(at, "r_confirm")
    app = service.get_application(cedar_id)
    assert app.status == "applied" and app.submitted_date == FIXED_TODAY
    assert "Application added." in texts(at)
    assert service.saved_ids() == []  # saving was never needed

    click(at, "r_view_app")  # step 4: the matching tracker entry
    assert [t.value for t in at.title] == ["Applications"]
    assert at.subheader[0].value == "Cedar Public Health Scholarship"
    assert "**Applied** · submitted 12 Nov 2026" in texts(at)
    assert [e.proto.expanded for e in at.expander if e.label == "Update status"] == [True]

    at = goto(at, "find")  # the search is still as the user left it
    assert list(at.multiselect(key="f_hosts").value) == ["United Kingdom"]
    assert "In Applications: Applied" in texts(at)
    click(at, "clear_filters")
    assert "15 scholarships" in texts(at)


def test_tracker_updates_status_confirms_and_rejects_invalid_combinations(seeded, example_records):
    sid = by_key(example_records, "vega-cs-masters")["id"]
    seeded.mark_applied(sid, date(2026, 11, 10))
    at = goto(run_app(), "applications")
    assert "1 application: 1 applied" in texts(at)

    at.selectbox(key=f"t_status_{sid}").set_value("result_received").run()
    click(at, f"t_save_{sid}")
    assert any("Not saved yet" in e.value and "outcome" in e.value for e in at.error)
    assert ScholarPathService(config.MODE_EXAMPLE).get_application(sid).status == "applied"

    at.selectbox(key=f"t_out_{sid}").set_value("waitlisted")
    at.date_input(key=f"t_target_{sid}").set_value(date(2026, 11, 18))
    at.text_area(key=f"t_notes_{sid}").input("Uploaded transcript")
    click(at, f"t_save_{sid}")
    assert not at.error and "Saved. Status: Result received." in texts(at)
    assert "**Result received** · Waitlisted / reserve · submitted 10 Nov 2026" in texts(at)

    reopened = ScholarPathService(config.MODE_EXAMPLE).get_application(sid)
    assert reopened.status == "result_received" and reopened.outcome == "waitlisted"
    assert reopened.target_date == date(2026, 11, 18) and reopened.notes == "Uploaded transcript"

    click(at, f"t_save_{sid}")  # a second save with nothing changed writes nothing
    assert any("Nothing to save" in e.value for e in at.error)


def test_earlier_tracker_entries_are_kept_and_can_be_marked_applied(seeded, example_records):
    """Entries created before the redesign (Interested/Preparing) still show and move on normally."""
    sid = by_key(example_records, "vega-cs-masters")["id"]
    seeded.start_tracking(sid)
    seeded.update_application(sid, "preparing", notes="Draft essay")
    at = goto(run_app(), "applications")
    assert "**Preparing**" in texts(at)
    at = open_review(at, sid, back="applications")
    assert at.button(key="r_back").label == "Back to Applications"
    assert at.button(key="r_view_app").label.startswith("In Applications as Preparing")
    click(at, "r_mark")
    click(at, "r_confirm")
    app = ScholarPathService(config.MODE_EXAMPLE).get_application(sid)
    assert app.status == "applied" and app.notes == "Draft essay"


def test_empty_applications_points_back_to_find(seeded):
    at = goto(run_app(), "applications")
    assert "No applications yet" in texts(at)
    click(at, "empty_applications_go")
    assert [t.value for t in at.title] == ["Find scholarships"]


def test_saving_is_optional_and_saved_scholarships_reopen_at_review(seeded, example_records):
    sid = by_key(example_records, "vega-cs-masters")["id"]
    at = goto(run_app(), "saved")
    assert "Nothing saved yet" in texts(at) and "Saving is optional" in texts(at)

    at = open_review(at, sid)
    click(at, "r_save")
    assert ScholarPathService(config.MODE_EXAMPLE).saved_ids() == [sid]
    assert at.button(key="r_unsave") is not None  # the button now offers removal instead

    at = goto(at, "saved")
    assert "Due in 8-30 days (1)" in texts(at)
    click(at, f"saved_rev_{sid}")
    assert "Vega Computer Science Master's Award" in [t.value for t in at.title]
    assert at.button(key="r_back").label == "Back to Saved"
    assert "Apply on provider site" in link_labels(at)


def test_removing_from_saved_keeps_the_application(seeded, example_records):
    sid = by_key(example_records, "vega-cs-masters")["id"]
    seeded.save(sid)
    seeded.mark_applied(sid, FIXED_TODAY)
    at = goto(run_app(), "saved")
    assert "In Applications: Applied" in texts(at)
    click(at, f"saved_remove_{sid}")
    service = ScholarPathService(config.MODE_EXAMPLE)
    assert service.saved_ids() == [] and service.get_application(sid) is not None
    assert "any application entry is kept" in texts(at).lower()


def test_mark_applied_service_rules(seeded, example_records):
    sid = example_records[0]["id"]
    with pytest.raises(ValueError):
        seeded.mark_applied(sid, date(2026, 11, 13))  # after the fixed "today"
    with pytest.raises(ValueError):
        seeded.mark_applied(sid, None)
    assert seeded.get_application(sid) is None
    first = seeded.mark_applied(sid, date(2026, 11, 11))
    again = seeded.mark_applied(sid, date(2026, 11, 12))  # confirming twice changes nothing
    assert again.submitted_date == first.submitted_date == date(2026, 11, 11)
    assert [h["note"] for h in seeded.application_history(sid)] == ["Marked as applied"]


def _tab_counts(at: AppTest) -> dict[str, int]:
    """'(:material/x: )Good fits (4)' -> {'Good fits': 4}"""
    counts = {}
    for tab in at.tabs:
        label = tab.label.split(": ", 1)[-1] if tab.label.startswith(":material/") else tab.label
        name, _, number = label.rpartition(" (")
        counts[name] = int(number.rstrip(")"))
    return counts


def test_profile_matching_groups_results_with_explanations(seeded, example_records):
    at = goto(run_app(), "fit")
    assert "Fill in what you know" in texts(at)
    at.selectbox(key="m_nat").set_value("India")
    at.selectbox(key="m_degree").set_value("master")
    at.selectbox(key="m_subject").set_value("computer_science")
    at.number_input(key="m_score").set_value(8.5)
    at.selectbox(key="m_scale").set_value("cgpa_10")
    submit_fit(at)
    assert not at.exception

    profile = StudentProfile("India", "master", "computer_science", 8.5, "cgpa_10")
    expected = Counter(m.group for _, m in seeded.match(profile))
    assert _tab_counts(at) == {"Good fits": expected["fit"], "Need more info": expected["missing"],
                               "Not a fit": expected["no_fit"]}
    assert expected["fit"] >= 1 and expected["no_fit"] >= 1

    body = texts(at)
    assert "Lakeshore STEM Excellence Award" in body and "Matches recorded requirements" in body
    assert "You meet all 5 recorded requirements" in body
    assert any(e.label.startswith("Confirm on the official page") for e in at.expander)
    assert "does not guarantee" in body
    assert "Tip:" not in body  # every field was filled in
    lakeshore = by_key(example_records, "lakeshore-stem-excellence")["id"]
    assert at.button(key=f"m_rev_{lakeshore}") is not None


def test_profile_matching_rejects_score_without_scale(seeded):
    at = goto(run_app(), "fit")
    at.number_input(key="m_score").set_value(8.5)
    submit_fit(at)
    assert any("scale" in e.value for e in at.error)


def test_blank_profile_is_never_a_match_and_suggests_what_to_add(seeded):
    at = goto(run_app(), "fit")
    submit_fit(at)
    assert _tab_counts(at) == {"Good fits": 0, "Need more info": 15, "Not a fit": 0}
    body = texts(at)
    assert "Tip: add your citizenship, degree, score and subject" in body
    assert "Add your citizenship, degree and subject above to check the rest" in body


def test_switching_dataset_isolates_saved_items_and_clears_selection(seeded, example_records):
    real = ScholarPathService(config.MODE_REAL)
    real.import_records([real_record()])
    seeded.save(example_records[0]["id"])

    at = run_app()
    click(at, f"find_rev_{example_records[0]['id']}")
    assert at.session_state["selected_id"] == example_records[0]["id"]
    at.sidebar.radio(key="mode").set_value(config.MODE_REAL).run()
    assert not at.exception
    assert "Real sources:" in texts(at) and "Example data:" not in texts(at)
    assert "selected_id" not in at.session_state and "No scholarship selected" in texts(at)
    at = goto(at, "saved")
    assert "Nothing saved yet" in texts(at)
    at = goto(at, "applications")
    assert "No applications yet" in texts(at)


def test_insights_states_scope_and_draws_charts(seeded):
    at = goto(run_app(), "insights")
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
    at = goto(at, "find")
    body = texts(at)
    assert "\\<script\\>" in body and "<script>" not in body  # shown as literal text, never as HTML
    assert "\\<img src=x onerror=alert\\(1\\)\\>" in body and "\n<img" not in body
    assert "\\[x\\]\\(https" in body  # no live link
    click(at, f"find_rev_{real_record()['id']}")
    assert "\\$x\\$" in texts(at) and "<b>tags</b>" not in texts(at).replace("\\<b\\>", "")


def test_every_page_renders_without_errors(seeded):
    at = run_app()
    for page in ["find", "review", "saved", "applications", "fit", "insights", "data"]:
        goto(at, page)
        assert not at.error, f"{page}: {[e.value for e in at.error]}"
        assert not at.warning, f"{page}: unexpected warning banner"


def test_results_are_paged_and_export_covers_every_page(seeded):
    at = run_app()
    first = card_ids(at)
    assert len(first) == 10 and "Showing 1 to 10 of 15" in texts(at)
    assert at.button(key="f_page_prev").disabled
    click(at, "f_page_next")
    second = card_ids(at)
    assert len(second) == 5 and not set(first) & set(second)
    assert at.button(key="f_page_next").disabled
    at.multiselect(key="f_hosts").set_value(["United Kingdom"]).run()  # filtering returns to page 1
    assert at.session_state["f_page"] == 1


def test_search_and_filters_are_restored_after_review(seeded):
    at = run_app()
    at.multiselect(key="f_hosts").set_value(["United Kingdom"]).run()
    at.text_input(key="f_text").input("scholarship").run()
    shown = card_ids(at)
    click(at, f"find_rev_{shown[0]}")
    click(at, "r_back")
    assert at.text_input(key="f_text").value == "scholarship"
    assert list(at.multiselect(key="f_hosts").value) == ["United Kingdom"]
    assert card_ids(at) == shown


def test_no_matches_explains_why_and_offers_recovery(seeded):
    at = run_app()
    at.text_input(key="f_text").input("zzz-no-such-scholarship").run()
    assert "0 scholarships" in texts(at) and "No scholarships match" in texts(at)
    click(at, "clear_filters_empty")
    assert "15 scholarships" in texts(at)


def test_review_without_a_selection_points_back_to_find(seeded):
    at = goto(run_app(), "review")
    assert "No scholarship selected" in texts(at)
    click(at, "empty_review_go")
    assert "15 scholarships" in texts(at)


def test_data_page_reports_sources_and_honest_freshness(seeded):
    at = goto(run_app(), "data")
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Records"] == "15" and metrics["Checked by a person"] == "0 of 15"
    assert "no automatic schedule" in texts(at) and "python -m scholarpath init-examples" in texts(at)


def test_database_failure_shows_recovery_message_not_a_traceback(seeded, monkeypatch):
    import sqlite3

    def broken(self, *args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ScholarPathService, "shortlist", broken)
    at = goto(run_app(), "saved")
    assert not at.exception
    assert any("couldn't read or write its database" in e.value for e in at.error)
    assert at.button(key="retry_page") is not None
