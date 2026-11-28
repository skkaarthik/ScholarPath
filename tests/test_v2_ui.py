"""v2 UI checks (Streamlit AppTest): the first-visit choice, switching between internships and
scholarships, kept state, and the internship journey Find -> Review -> Save -> Apply -> Track,
with every result verified through a separate service object (i.e. in SQLite).
"""

from __future__ import annotations

from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from scholarpath import config
from scholarpath.examples import build_example_internships
from scholarpath.services import InternshipService, ScholarPathService

from .conftest import FIXED_TODAY
from .test_ui import APP, click, goto, highlighted, menu_keys, texts


@pytest.fixture
def seeded(example_records):
    scholarships = ScholarPathService(config.MODE_EXAMPLE)
    scholarships.import_records(example_records, source_file="test")
    interns = InternshipService(config.MODE_EXAMPLE)
    interns.import_payload(build_example_internships(FIXED_TODAY, collected_at="2026-11-12T00:00:00+00:00"), "test")
    return scholarships, interns


def fresh() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def choose(at: AppTest, kind: str) -> AppTest:
    return click(at, f"choose_{kind}")


def headers(at: AppTest) -> list[str]:
    return [h.value for h in at.header]


def find_ids(at: AppTest) -> list[str]:
    return [b.key[len("find_rev_"):] for b in at.button if b.key and b.key.startswith("find_rev_")]


def switch(at: AppTest, kind: str) -> AppTest:
    at.segmented_control(key="kind_pick").set_value(kind).run()
    assert not at.exception, at.exception
    return at


# --- first screen -------------------------------------------------------------------------

def test_first_visit_shows_only_the_two_choices(seeded):
    at = fresh()
    assert [t.value for t in at.title] == ["What are you looking for?"]
    assert {b.key for b in at.button} == {"choose_internship", "choose_scholarship"}
    assert [b.label for b in at.button] == ["Find internships", "Find scholarships"]
    assert menu_keys(at) == [] and not at.sidebar.radio                     # nothing else is drawn yet


def test_choosing_internships_opens_find_internships_at_once(seeded):
    at = choose(fresh(), "internship")
    assert [t.value for t in at.title] == ["Find internships"]
    assert headers(at)[0] == "15 internships"
    assert at.session_state["kind"] == "internship" and at.query_params.get("for") == "internships"


def test_choosing_scholarships_opens_the_v1_find_page(seeded):
    at = choose(fresh(), "scholarship")
    assert [t.value for t in at.title] == ["Find scholarships"] and "13 scholarships" in texts(at)


def test_a_reload_keeps_the_choice_from_the_address(seeded):
    at = AppTest.from_file(APP, default_timeout=30)
    at.query_params["for"] = "internships"
    at.run()
    assert [t.value for t in at.title] == ["Find internships"]


# --- menu and switching ---------------------------------------------------------------------

def test_the_menu_keeps_its_four_entries_and_labels_follow_the_type(seeded):
    at = choose(fresh(), "internship")
    assert [k.replace("_current", "") for k in menu_keys(at)][:4] == ["nav_find", "nav_saved", "nav_applications",
                                                                       "nav_more"]
    labels = [link.proto.label for link in at.get("page_link")]
    assert labels[:3] == ["Find Internships", "Saved", "Applications"]
    assert highlighted(at) == ["find"]
    assert at.segmented_control(key="kind_pick").value == "internship"
    assert any(b.label == "Switch to scholarships" for b in at.button)       # also inside More


def test_switching_keeps_each_types_search_and_filters(seeded):
    at = choose(fresh(), "internship")
    at.segmented_control(key="i_place").set_value("chennai").run()
    assert headers(at)[0] == "4 internships"
    switch(at, "scholarship")
    assert [t.value for t in at.title] == ["Find scholarships"] and "13 scholarships" in texts(at)
    at.multiselect(key="f_hosts").set_value(["United Kingdom"]).run()
    narrowed = headers(at)[0]
    switch(at, "internship")
    assert headers(at)[0] == "4 internships" and "Filtered by Location: Chennai" in texts(at)
    switch(at, "scholarship")
    assert headers(at)[0] == narrowed and at.multiselect(key="f_hosts").value == ["United Kingdom"]


def test_switching_brings_back_the_record_open_on_review(seeded):
    scholarships, interns = seeded
    at = choose(fresh(), "internship")
    click(at, f"find_rev_{find_ids(at)[0]}")
    role = at.title[0].value
    switch(at, "scholarship")
    goto(at, "find")
    click(at, f"find_rev_{find_ids(at)[0]}")
    scholarship = at.title[0].value
    switch(at, "internship")
    goto(at, "review")
    assert at.title[0].value == role
    switch(at, "scholarship")
    goto(at, "review")
    assert at.title[0].value == scholarship


def test_the_more_menu_switch_changes_type(seeded):
    at = choose(fresh(), "scholarship")
    click(at, "nav_switch_find")
    assert at.session_state["kind"] == "internship"
    assert [t.value for t in at.title] == ["Find internships"]


def test_a_dataset_switch_clears_both_types_filters(seeded):
    at = choose(fresh(), "internship")
    at.segmented_control(key="i_place").set_value("remote").run()
    at.sidebar.radio(key="mode").set_value(config.MODE_REAL).run()
    assert at.session_state["i_place"] == "all_india"
    assert "python -m scholarpath find-internships --import" in texts(at)   # real internships: terminal only


# --- the Chennai internship journey -------------------------------------------------------------

def test_find_review_save_unsave_apply_and_track_a_chennai_internship(seeded, example_records):
    scholarships, interns = seeded
    scholarship = example_records[0]["id"]
    scholarships.save(scholarship)                                          # existing scholarship data
    scholarships.mark_applied(example_records[1]["id"], date(2026, 11, 1))

    at = choose(fresh(), "internship")
    at.segmented_control(key="i_place").set_value("chennai").run()
    target = next(v for v in interns.search() if v.record.title == "Data Analyst Intern").record.id
    assert target in find_ids(at)
    click(at, f"find_rev_{target}")
    assert at.title[0].value == "Data Analyst Intern"
    body = texts(at).replace("\\", "")                                     # drop markdown escapes
    assert "Marina Analytics (fictional)" in body and "Stipend" in body and "Chennai, Tamil Nadu" in body
    assert "₹15,000-₹20,000 a month" in body and "Hybrid" in body
    assert at.button(key="r_back").label == "Back to results"
    links = [b.proto.label for b in at.get("link_button")]
    assert "Apply on employer site" in links

    click(at, "r_save")
    assert interns.saved_ids() == [target] and scholarships.saved_ids() == [scholarship]
    goto(at, "saved")
    assert [t.value for t in at.title] == ["Saved internships"] and "Data Analyst Intern" in texts(at)
    click(at, f"saved_remove_{target}")
    assert interns.saved_ids() == [] and "Undo" in [b.label for b in at.button]
    click(at, "saved_undo_btn")
    assert interns.saved_ids() == [target]
    click(at, f"saved_remove_{target}")
    assert interns.saved_ids() == []

    goto(at, "find")
    assert headers(at)[0] == "4 internships"                                # the search was kept
    click(at, f"find_rev_{target}")
    click(at, "r_mark")
    assert interns.applications() == []                                     # nothing until confirmed
    click(at, "r_confirm")
    assert [a.status for a in interns.applications()] == ["applied"]
    assert "Application added. It is now in Applications." in texts(at)
    click(at, "r_confirm") if any(b.key == "r_confirm" for b in at.button) else None
    assert len(interns.applications()) == 1
    click(at, "r_view_app")
    assert [t.value for t in at.title] == ["Applications"] and "Data Analyst Intern" in texts(at)
    assert "View internship" in [b.label for b in at.button]
    history = interns.application_history(target)
    assert [h["note"] for h in history] == ["Marked as applied"]

    switch(at, "scholarship")                                               # scholarship data untouched
    goto(at, "saved")
    assert scholarships.saved_ids() == [scholarship] and "Saved scholarships" in texts(at)
    goto(at, "applications")
    assert [a.item_id for a in scholarships.applications()] == [example_records[1]["id"]]
    assert example_records[1]["name"] in texts(at)


def test_application_status_updates_keep_history_for_internships(seeded):
    _, interns = seeded
    rec = interns.search()[0].record.id
    interns.mark_applied(rec, FIXED_TODAY)
    at = choose(fresh(), "internship")
    at.session_state["tracker_pick"] = rec
    goto(at, "applications")
    at.selectbox(key=f"t_status_{rec}").set_value("result_received").run()
    at.selectbox(key=f"t_out_{rec}").set_value("awarded").run()
    click(at, f"t_save_{rec}")
    assert interns.get_application(rec).outcome == "awarded"
    assert [h["status"] for h in interns.application_history(rec)] == ["result_received", "applied"]


# --- every other internship page ----------------------------------------------------------------

def test_internship_filters_table_csv_and_empty_state(seeded):
    at = choose(fresh(), "internship")
    at.multiselect(key="i_disc").set_value(["legal"]).run()
    assert headers(at)[0] == "1 internship" and "Discipline: Legal" in texts(at)
    at.text_input(key="i_text").set_value("nothing like this").run()
    assert "No internships match" in texts(at)
    click(at, "clear_filters_empty")
    assert headers(at)[0] == "15 internships" and at.multiselect(key="i_disc").value == []
    at.toggle(key="i_table").set_value(True).run()
    assert not at.exception and at.dataframe
    assert any(b.label.startswith("Download 15 results") for b in at.get("download_button"))


def test_check_my_fit_insights_and_data_pages_for_internships(seeded):
    at = choose(fresh(), "internship")
    goto(at, "fit")
    at.selectbox(key="im_degree").set_value("bachelor").run()
    at.selectbox(key="im_disc").set_value("data").run()
    at.button[[b.label for b in at.button].index("Check my fit")].click().run()
    assert not at.exception and "Your results" in texts(at)
    goto(at, "insights")
    assert "Where you can intern" in headers(at) and "Counting **15 internships**" in texts(at)
    goto(at, "data")
    assert "Sixteen invented internships" in texts(at) and "No longer listed" in [m.label for m in at.metric]


def test_the_assistant_talks_about_internships(seeded):
    at = choose(fresh(), "internship")
    click(at, "chat_open_btn")
    assert "Talking about: all internships in Example data (fictional)" in texts(at).replace("\\", "")
    assert "Which internships fit me?" in [b.label for b in at.button]
