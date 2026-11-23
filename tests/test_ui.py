"""Streamlit AppTest checks.

These drive app.py headlessly against a temporary database and then verify,
through a separate service object, that UI actions reached SQLite.
Workflow covered: Find -> Filter -> Review -> Apply -> Confirm -> Applications,
plus the menu, Saved, Check my fit and the other pages (CSV content is checked
in test_exports_and_tracker.py).
Pages are opened the same way the app's own buttons do it (common.go_to).
"""

from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from scholarpath import config
from scholarpath.matching import StudentProfile
from scholarpath.repository import SearchFilters
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


def menu_keys(at: AppTest) -> list[str]:
    """Keys of the menu's containers as rendered (set in app.py), e.g. 'nav_find_current'."""
    found = []

    def walk(block) -> None:
        key = getattr(getattr(block, "proto", None), "id", "").rpartition("-")[2]
        if key.startswith("nav_"):
            found.append(key)
        for child in getattr(block, "children", {}).values():
            walk(child)

    walk(at.main)
    return found


def highlighted(at: AppTest) -> list[str]:
    """Menu entries drawn as highlighted: 'find', 'saved', 'applications', 'more' or a More page."""
    return [key[len("nav_"):-len("_current")] for key in menu_keys(at) if key.endswith("_current")]


def test_missing_database_shows_setup_steps_without_fallback():
    at = run_app()
    assert "python -m scholarpath init-examples" in texts(at)
    at.sidebar.radio(key="mode").set_value(config.MODE_REAL).run()
    assert "python -m scholarpath import-real" in texts(at) and not at.exception


def test_example_data_can_be_created_from_the_app_but_real_data_cannot():
    at = run_app()
    click(at, "setup_create_examples")
    assert not at.exception and not at.error
    created = ScholarPathService(config.MODE_EXAMPLE).overview()["scholarships"]
    assert created == 15 and "13 scholarships" in texts(at)                 # Find lists the open ones
    at.sidebar.radio(key="mode").set_value(config.MODE_REAL).run()
    assert "python -m scholarpath import-real" in texts(at)                 # real data: terminal only
    assert not [b for b in at.button if b.key == "setup_create_examples"]


def test_app_opens_on_find_scholarships(seeded):
    at = run_app()
    assert [t.value for t in at.title] == ["Find scholarships"]
    assert "Example data" in texts(at) and "13 scholarships" in texts(at)
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
    assert ":blue-badge[Applied] submitted 12 Nov 2026" in texts(at)
    assert "Next: when the provider replies" in texts(at)  # the next available step is spelled out
    assert [e.proto.expanded for e in at.expander if e.label == "Update status"] == [True]

    at = goto(at, "find")  # the search is still as the user left it
    assert list(at.multiselect(key="f_hosts").value) == ["United Kingdom"]
    assert "In Applications: Applied" in texts(at)
    click(at, "clear_filters")
    assert "13 scholarships" in texts(at)


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
    assert ":green-badge[Result received] :orange-badge[Waitlisted / reserve] submitted 10 Nov 2026" in texts(at)

    reopened = ScholarPathService(config.MODE_EXAMPLE).get_application(sid)
    assert reopened.status == "result_received" and reopened.outcome == "waitlisted"
    assert reopened.target_date == date(2026, 11, 18) and reopened.notes == "Uploaded transcript"

    history = at.dataframe[0].value  # the only table on the page: newest first, one date format
    assert list(history["Status"]) == ["Result received", "Applied"]
    assert list(history["Submitted"]) == ["10 Nov 2026", "10 Nov 2026"] and history["Target"][0] == "18 Nov 2026"

    click(at, f"t_save_{sid}")  # a second save with nothing changed writes nothing
    assert any("Nothing to save" in i.value for i in at.info) and not at.error
    assert len(ScholarPathService(config.MODE_EXAMPLE).application_history(sid)) == 2


def test_earlier_tracker_entries_are_kept_and_can_be_marked_applied(seeded, example_records):
    """Entries created before the redesign (Interested/Preparing) still show and move on normally."""
    sid = by_key(example_records, "vega-cs-masters")["id"]
    seeded.start_tracking(sid)
    seeded.update_application(sid, "preparing", notes="Draft essay")
    at = goto(run_app(), "applications")
    assert ":gray-badge[Preparing]" in texts(at) and "Next: apply on the provider's website" in texts(at)
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
    assert "Closing in 8 to 30 days (1)" in texts(at)
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
    assert _tab_counts(at) == {"Good fits": 0, "Need more info": 13, "Not a fit": 0}
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
    assert "Real sources" in texts(at) and "Example data" not in texts(at)
    assert "selected_id" not in at.session_state and "No scholarship selected" in texts(at)
    at = goto(at, "saved")
    assert "Nothing saved yet" in texts(at)
    at = goto(at, "applications")
    assert "No applications yet" in texts(at)


def test_insights_states_scope_and_draws_charts(seeded):
    at = goto(run_app(), "insights")
    assert "13 scholarships" in texts(at) and "no filters" in texts(at)
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
    assert len(first) == 10 and "Showing 1 to 10 of 13" in texts(at)
    assert at.button(key="f_page_prev").disabled
    click(at, "f_page_next")
    second = card_ids(at)
    assert len(second) == 3 and not set(first) & set(second)
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
    assert "13 scholarships" in texts(at)


def test_review_without_a_selection_points_back_to_find(seeded):
    at = goto(run_app(), "review")
    assert "No scholarship selected" in texts(at)
    click(at, "empty_review_go")
    assert "13 scholarships" in texts(at)


def test_data_page_reports_sources_and_honest_freshness(seeded):
    at = goto(run_app(), "data")
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Open now"] == "13" and metrics["All records"] == "15"   # 2 closed records are kept
    assert metrics["Checked by hand"] == "0 of 15"
    assert "Nothing is collected while you browse" in texts(at) and "python -m scholarpath init-examples" in texts(at)
    assert "Data refresh" not in [h.value for h in at.header]                # refresh concerns real data only


def test_database_failure_shows_recovery_message_not_a_traceback(seeded, monkeypatch):
    import sqlite3

    def broken(self, *args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ScholarPathService, "shortlist", broken)
    at = goto(run_app(), "saved")
    assert not at.exception
    assert any("couldn't read or write its database" in e.value for e in at.error)
    assert at.button(key="retry_page") is not None


# --- menu: one highlighted entry on every page, including the hidden Review page ------------

def test_menu_item_names_the_entry_to_highlight():
    from scholarpath.ui import common

    assert [common.menu_item(p) for p in ("find", "saved", "applications")] == ["find", "saved", "applications"]
    assert {common.menu_item(p) for p in ("fit", "insights", "data")} == {common.MORE}
    # Review is not in the menu: it highlights the page it was opened from.
    assert common.menu_item("review", "saved") == "saved"
    assert common.menu_item("review", "applications") == "applications"
    assert common.menu_item("review", "fit") == common.MORE
    assert common.menu_item("review", None) == common.menu_item("review", "nonsense") == "find"


def test_menu_highlights_the_open_page_on_every_page(seeded):
    at = run_app()
    assert highlighted(at) == ["find"]  # the opening page, whose URL path is empty
    for page, expected in [("saved", ["saved"]), ("applications", ["applications"]), ("fit", ["more", "fit"]),
                           ("insights", ["more", "insights"]), ("data", ["more", "data"]), ("find", ["find"])]:
        assert highlighted(goto(at, page)) == expected
        at.run()  # a rerun on the same page keeps the same entry highlighted
        assert highlighted(at) == expected


def test_review_highlights_the_page_it_was_opened_from_and_back_returns_there(seeded, example_records):
    sid = example_records[0]["id"]
    seeded.save(sid)
    seeded.mark_applied(sid, FIXED_TODAY)
    at = run_app()
    click(at, f"find_rev_{sid}")
    assert highlighted(at) == ["find"] and at.button(key="r_back").label == "Back to results"

    at = goto(at, "saved")
    click(at, f"saved_rev_{sid}")
    assert highlighted(at) == ["saved"]
    click(at, "r_back")
    assert [t.value for t in at.title] == ["Saved scholarships"] and highlighted(at) == ["saved"]

    at = goto(at, "applications")
    click(at, f"app_rev_{sid}")
    assert highlighted(at) == ["applications"] and at.button(key="r_back").label == "Back to Applications"

    at = open_review(at, sid, back="fit")
    assert highlighted(at) == ["more"] and at.button(key="r_back").label == "Back to Check my fit"
    click(at, "r_back")
    assert [t.value for t in at.title] == ["Check my fit"]


def test_more_menu_is_drawn_fresh_for_each_page_so_it_closes_after_a_choice(seeded):
    """An open menu would swallow the next click. Its key includes the open page, so choosing
    a page makes Streamlit draw a new, closed menu; a rerun on the same page keeps the same one."""
    at = run_app()
    assert "nav_more_menu_find" in menu_keys(at)
    goto(at, "insights")
    assert "nav_more_menu_insights" in menu_keys(at) and "nav_more_menu_find" not in menu_keys(at)
    at.toggle(key="ins_filters").set_value(True).run()   # using the page does not replace the menu
    assert "nav_more_menu_insights" in menu_keys(at)
    assert [k for k in menu_keys(at) if k.startswith(("nav_fit", "nav_insights", "nav_data"))] == [
        "nav_fit", "nav_insights_current", "nav_data"]   # all three destinations are inside it


# --- Find: state kept across Review, paging, deadline wording --------------------------------

def test_sort_and_page_are_restored_after_review(seeded):
    at = run_app()
    at.selectbox(key="f_sort").set_value("name").run()
    click(at, "f_page_next")
    shown = card_ids(at)
    assert at.session_state["f_page"] == 2 and len(shown) == 3
    click(at, f"find_rev_{shown[0]}")
    click(at, "r_back")
    assert at.selectbox(key="f_sort").value == "name" and at.session_state["f_page"] == 2
    assert card_ids(at) == shown and "Showing 11 to 13 of 13" in texts(at)


def test_changing_search_filter_or_sort_on_a_later_page_returns_to_page_one(seeded):
    at = run_app()
    for change in (lambda: at.selectbox(key="f_sort").set_value("provider"),
                   lambda: at.text_input(key="f_text").input("a"),
                   lambda: at.pills(key="f_status").set_value(["open"])):
        click(at, "f_page_next") if at.session_state["f_page"] == 1 else None
        assert at.session_state["f_page"] == 2
        change().run()
        assert at.session_state["f_page"] == 1 and not at.exception


def test_clearing_filters_is_sent_to_the_browser_not_only_forgotten_by_the_server(seeded):
    """The browser keeps its own copy of each widget value. Deleting the session key left that
    copy in place, so the old search and filters came back on the next click. Clearing therefore
    assigns the empty value, which Streamlit marks with ``set_value`` and sends to the browser."""
    real = ScholarPathService(config.MODE_REAL)
    real.import_records([real_record()])
    at = run_app()
    at.text_input(key="f_text").input("aurora").run()
    at.multiselect(key="f_hosts").set_value(["Canada"]).run()
    assert "2 scholarships" in texts(at)
    click(at, "clear_filters")
    assert "13 scholarships" in texts(at) and "Filtered by" not in texts(at)
    assert at.text_input(key="f_text").value == "" and at.text_input(key="f_text").proto.set_value
    assert list(at.multiselect(key="f_hosts").value) == [] and at.multiselect(key="f_hosts").proto.set_value

    at.text_input(key="f_text").input("vega").run()     # the same holds for a dataset switch
    at.sidebar.radio(key="mode").set_value(config.MODE_REAL).run()
    assert "1 scholarship" in texts(at) and "Filtered by" not in texts(at)
    assert at.text_input(key="f_text").value == "" and at.text_input(key="f_text").proto.set_value


def test_download_button_covers_all_filtered_results_not_only_the_page(seeded):
    at = run_app()
    assert len(card_ids(at)) == 10  # page 1 of 2
    labels = [b.proto.label for b in at.get("download_button")]
    assert labels == ["Download 13 results as CSV"]
    at.multiselect(key="f_hosts").set_value(["United Kingdom"]).run()
    assert [b.proto.label for b in at.get("download_button")] == ["Download 2 results as CSV"]


def test_deadline_states_are_told_apart(seeded, example_records):
    """Closing soon, open, closed, rolling, 'date not confirmed' and 'nothing published' never share a label."""
    from scholarpath.ui import common

    labels = {v.record.source_key: common.deadline_state(v)[1]
              for v in seeded.search(SearchFilters(include_closed=True))}
    assert labels["aurora-global-masters-southgate"] == "Closes today"
    assert labels["cedar-public-health"] == "Closes in 3 days"
    assert labels["lakeshore-stem-excellence"] == "Open"
    assert labels["orion-undergraduate-access"] == "Closed"
    assert labels["harbourview-business-leaders"] == "Rolling"

    real = ScholarPathService(config.MODE_REAL)
    real.import_records([
        real_record(source_key="no-year", name="No Year Award", deadline_kind="unknown", deadline_date=None,
                    deadline_text="The closing date for applications was 16:00 BST on Tuesday 20 October."),
        real_record(source_key="silent", name="Silent Award", deadline_kind="unknown", deadline_date=None,
                    deadline_text=""),
    ])
    states = {v.record.name: common.deadline_state(v) for v in real.search()}
    assert states["No Year Award"][1] == "Date not confirmed"      # the provider did publish wording
    assert states["Silent Award"][1] == "No deadline published"    # nothing was collected at all

    at = run_app()
    at.sidebar.radio(key="mode").set_value(config.MODE_REAL).run()
    at = open_review(at, real_record(source_key="no-year")["id"])
    body = texts(at)
    assert "Date not confirmed" in body and "No deadline published" not in body
    assert "Provider's wording: “The closing date for applications was 16" in body
    assert "never guesses a missing year" in body


# --- Review and the Apply flow ------------------------------------------------------------------

def test_review_of_a_record_that_no_longer_exists_explains_and_recovers(seeded):
    at = open_review(run_app(), "sp-0000000000000000")
    assert "This scholarship is not in this dataset" in texts(at) and not at.exception
    click(at, "empty_review_missing_go")
    assert [t.value for t in at.title] == ["Find scholarships"]


def test_review_names_the_outside_website_and_never_claims_to_submit(seeded, example_records):
    at = open_review(run_app(), example_records[0]["id"])
    body = texts(at)
    assert "Opens example\\.org, an outside website, in a new tab" in body
    assert "ScholarPath never submits anything for you" in body
    assert "placeholder page, not a real application form" in body  # example data is never passed off as real


def test_closed_scholarship_says_so_and_can_still_be_recorded(seeded, example_records):
    sid = by_key(example_records, "orion-undergraduate-access")["id"]  # closed 10 days before the fixed date
    at = open_review(run_app(), sid)
    assert any("The published deadline has passed (2 Nov 2026)" in i.value for i in at.info)
    assert "Apply on provider site" in link_labels(at) and at.button(key="r_mark") is not None


def test_mark_as_applied_alone_creates_nothing_and_is_dropped_when_leaving_review(seeded, example_records):
    sid = example_records[0]["id"]
    at = open_review(run_app(), sid)
    click(at, "r_mark")
    assert "Confirm your submission" in texts(at) and seeded.applications() == []
    at = goto(at, "saved")                      # leave through the menu without confirming
    at = open_review(at, sid)
    assert "Confirm your submission" not in texts(at) and at.button(key="r_mark") is not None
    assert seeded.applications() == [] and seeded.saved_ids() == []


def test_confirming_adds_exactly_one_application_however_often_it_is_repeated(seeded, example_records):
    sid = example_records[0]["id"]
    at = open_review(run_app(), sid)
    click(at, "r_mark")
    click(at, "r_confirm")
    at.run()                                    # a rerun after the confirmation
    assert "Application added." not in texts(at)  # the one-off message is not repeated
    # A second confirmation arriving late (double click) has no date field left to read:
    again = seeded.mark_applied(sid, None)
    assert again.status == "applied" and again.submitted_date == FIXED_TODAY
    assert len(seeded.applications()) == 1
    assert [h["note"] for h in seeded.application_history(sid)] == ["Marked as applied"]
    assert seeded.saved_ids() == []             # adding an application never saves the scholarship


def test_a_future_submission_date_is_refused_next_to_the_field_and_saves_nothing(seeded, example_records, monkeypatch):
    from scholarpath.services import ServiceError

    sid = example_records[0]["id"]
    at = open_review(run_app(), sid)
    click(at, "r_mark")
    at.date_input(key="c_date").set_value(date(2026, 11, 13)).run()  # the day after the fixed "today"
    assert [e.value for e in at.error] == ["Choose 12 Nov 2026 or an earlier date. An application cannot have "
                                           "been submitted in the future."]
    assert at.button(key="r_confirm").disabled and seeded.get_application(sid) is None

    # If the service refuses for any other reason, that reason also appears inside the card.
    def refuse(self, scholarship_id, submitted_date):
        raise ServiceError("Enter the date you submitted the application yourself.")

    at.date_input(key="c_date").set_value(date(2026, 11, 11)).run()
    assert not at.error and not at.button(key="r_confirm").disabled
    real_mark_applied = ScholarPathService.mark_applied
    monkeypatch.setattr(ScholarPathService, "mark_applied", refuse)
    click(at, "r_confirm")
    assert [e.value for e in at.error] == ["Not added. Enter the date you submitted the application yourself."]
    assert "Confirm your submission" in texts(at) and seeded.get_application(sid) is None
    monkeypatch.setattr(ScholarPathService, "mark_applied", real_mark_applied)  # only this patch is lifted
    click(at, "r_confirm")
    assert not at.error and seeded.get_application(sid).submitted_date == date(2026, 11, 11)


def test_tracker_refuses_a_future_submission_date_with_the_reason(seeded, example_records):
    sid = example_records[0]["id"]
    seeded.mark_applied(sid, date(2026, 11, 10))
    at = goto(run_app(), "applications")
    at.date_input(key=f"t_sub_{sid}").set_value(date(2026, 12, 1))
    click(at, f"t_save_{sid}")
    assert [e.value for e in at.error] == ["Not saved yet: Submission date cannot be in the future."]
    assert seeded.get_application(sid).submitted_date == date(2026, 11, 10)
    assert len(seeded.application_history(sid)) == 1


def test_save_and_remove_on_review_show_the_state_and_persist(seeded, example_records):
    sid = example_records[0]["id"]
    at = open_review(run_app(), sid)
    assert ":blue-badge[Saved]" not in texts(at)
    click(at, "r_save")
    assert ":blue-badge[Saved]" in texts(at) and seeded.saved_ids() == [sid]
    at = goto(at, "find")                       # the state is read from SQLite again on every page
    assert "Saved" in texts(at)
    at = open_review(at, sid)
    click(at, "r_unsave")
    assert ":blue-badge[Saved]" not in texts(at) and seeded.saved_ids() == []


# --- Saved, Check my fit, Insights, Data & sources ----------------------------------------------

def test_removing_from_saved_can_be_undone(seeded, example_records):
    sid = by_key(example_records, "vega-cs-masters")["id"]
    seeded.save(sid)
    at = goto(run_app(), "saved")
    click(at, f"saved_remove_{sid}")
    assert seeded.saved_ids() == [] and "Nothing saved yet" in texts(at)
    assert "Removed “Vega Computer Science Master's Award” from Saved" in texts(at).replace("\\", "")
    click(at, "saved_undo_btn")
    assert seeded.saved_ids() == [sid] and "Closing in 8 to 30 days (1)" in texts(at)
    click(at, f"saved_remove_{sid}")
    at = goto(goto(at, "find"), "saved")        # the offer to undo ends when the page is left
    assert "saved_undo" not in at.session_state and seeded.saved_ids() == []


def test_removing_an_application_asks_first_and_can_be_cancelled(seeded, example_records):
    sid = by_key(example_records, "vega-cs-masters")["id"]
    seeded.mark_applied(sid, FIXED_TODAY)
    at = goto(run_app(), "applications")
    click(at, f"app_remove_{sid}")
    assert "Remove this application?" in texts(at) and seeded.get_application(sid) is not None
    click(at, f"app_remove_no_{sid}")
    assert "Remove this application?" not in texts(at) and seeded.get_application(sid) is not None
    click(at, f"app_remove_{sid}")
    at = goto(goto(at, "find"), "applications")  # leaving the page drops an unconfirmed removal
    assert "app_remove" not in at.session_state and seeded.get_application(sid) is not None


def test_confirmed_removal_deletes_the_entry_and_shows_the_empty_state(seeded, example_records):
    sid = by_key(example_records, "vega-cs-masters")["id"]
    seeded.save(sid)
    seeded.mark_applied(sid, FIXED_TODAY)
    at = goto(run_app(), "applications")
    click(at, f"app_remove_{sid}")
    click(at, f"app_remove_yes_{sid}")
    assert seeded.get_application(sid) is None and seeded.application_history(sid) == []
    assert "Removed “Vega Computer Science Master's Award” from Applications." in texts(at).replace("\\", "")
    assert "No applications yet" in texts(at)
    assert seeded.saved_ids() == [sid]              # Saved is not touched


def test_fit_form_refuses_another_country_without_a_name(seeded):
    at = goto(run_app(), "fit")
    at.selectbox(key="m_nat").set_value("__other__")
    submit_fit(at)
    assert [e.value for e in at.error] == ["Type your country's name, or choose it from the list."]
    assert not at.tabs  # no results are shown for an invalid form
    at.text_input(key="m_nat_other").input("Brazil")
    submit_fit(at)
    assert not at.error and len(at.tabs) == 3


def test_fit_results_are_never_presented_as_a_guarantee(seeded):
    at = goto(run_app(), "fit")
    assert "How the check works, and its limits" in [e.label for e in at.expander]
    at.selectbox(key="m_nat").set_value("India")
    at.selectbox(key="m_degree").set_value("master")
    at.selectbox(key="m_subject").set_value("computer_science")
    submit_fit(at)
    assert any("does not guarantee official eligibility" in i.value for i in at.info)
    assert _tab_counts(at)["Good fits"] >= 1 and "The provider still decides" in texts(at)


def test_insight_counts_match_the_stored_data(seeded):
    import sqlite3

    from scholarpath.ui import insights

    views = seeded.search()          # Insights counts open opportunities, like every other count
    is_open = "(closed_by_source = 0 AND (closes_at IS NULL OR closes_at > :now))"
    now = {"now": seeded.now_iso()}
    with sqlite3.connect(seeded.db_path) as conn:
        hosts = dict(conn.execute("SELECT country, COUNT(*) FROM scholarship_host_countries h JOIN scholarships s "
                                  f"ON s.id = h.scholarship_id WHERE {is_open} GROUP BY country", now))
        funding = [n for (n,) in conn.execute(f"SELECT COUNT(*) FROM scholarships WHERE {is_open} "
                                              "GROUP BY funding_category", now)]
        months = conn.execute("SELECT substr(deadline_date, 1, 7), COUNT(*) FROM scholarships "
                              f"WHERE deadline_kind = 'dated' AND {is_open} GROUP BY 1 ORDER BY 1", now).fetchall()
    assert dict(insights.count_by_country(views)) == hosts
    assert sorted(insights.count_by_funding(views).values()) == sorted(funding)
    assert sum(insights.count_by_funding(views).values()) == len(views) == 13
    by_month = insights.count_by_month(views)
    assert [count for _, count in by_month] == [count for _, count in months]  # same order: oldest month first
    assert [label for label, _ in by_month] == [date.fromisoformat(m + "-01").strftime("%b %Y") for m, _ in months]


def test_data_page_switches_dataset_and_keeps_the_two_apart(seeded, example_records):
    real = ScholarPathService(config.MODE_REAL)
    real.import_records([real_record()])
    seeded.save(example_records[0]["id"])
    at = goto(run_app(), "data")
    assert "Showing: Example data (fictional)" in texts(at)
    assert "placeholders on example.org" in texts(at)  # fictional records are never shown as real pages
    click(at, "data_switch")
    body = texts(at)
    assert at.session_state["mode"] == config.MODE_REAL and "Showing: Real sources (collected)" in body
    assert {m.label: m.value for m in at.metric}["Checked by hand"] == "0 of 1"
    assert "not live" in body and "No automatic refresh has run yet" in body
    assert real.saved_ids() == [] and seeded.saved_ids() == [example_records[0]["id"]]  # nothing crossed over
    click(at, "data_switch")
    assert at.session_state["mode"] == config.MODE_EXAMPLE
