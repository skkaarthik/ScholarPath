"""Saved & applications: deadline board, saved list and tracker (all persisted in SQLite)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..dates import GROUPS
from ..models import TRACKER_OUTCOMES, TRACKER_STATUSES
from ..services import STORAGE_ERRORS, ServiceError
from . import common

BOARD = [("due_7", ":material/alarm:"), ("due_30", ":material/event_upcoming:"), ("later", ":material/calendar_month:")]
OTHER_GROUPS = [("rolling", ":material/autorenew:"), ("unknown", ":material/event_note:"), ("expired", ":material/event_busy:")]
TABS = {"deadlines": ":material/event: Deadlines", "saved": ":material/bookmark: Saved",
        "tracker": ":material/task_alt: Tracker"}


def _short(status: str) -> str:
    return TRACKER_STATUSES[status].replace(" (recorded by you)", "")


def _board_column(key: str, icon: str, items, today) -> None:
    st.subheader(f"{icon} {GROUPS[key]} ({len(items)})", anchor=False)
    if not items:
        st.caption("Nothing here.")
    for view in items:
        with common.card(f"b{key}", view):
            st.markdown(f"**{common.md_escape(view.record.name)}**  \n{common.md_escape(view.record.provider)}")
            st.markdown(common.deadline_badge(view))
            if view.record.deadline_date:
                st.caption(f"Official deadline {common.fmt_date(view.record.deadline_date)}")
            common.details_button(view, f"b{key}", back="applications", label="Details", type="tertiary")


def _deadlines(svc, today) -> None:
    groups = svc.dashboard()
    if not groups:
        common.empty_state("deadlines", "Nothing saved or tracked yet",
                           "Save scholarships in Discover and their official deadlines appear here, "
                           "grouped by how soon they close.", "Find scholarships", "discover",
                           icon=":material/search:")
        return
    st.markdown("Saved and tracked scholarships by **official** deadline. Days are counted from today, and "
                "each scholarship appears in exactly one group.")
    for row in (BOARD, OTHER_GROUPS):
        for column, (key, icon) in zip(st.columns(3, gap="medium"), row):
            with column:
                _board_column(key, icon, groups.get(key, []), today)


def _saved(svc, today) -> None:
    views = svc.shortlist()
    if not views:
        common.empty_state("saved", "Your saved list is empty",
                           "Choose **Save** on any scholarship in Discover to keep it here.",
                           "Find scholarships", "discover", icon=":material/search:")
        return
    tracked = {a.scholarship_id for a in svc.applications()}
    for view in views:
        rec = view.record
        with common.card("s", view):
            text, actions = st.columns([4, 1.3], vertical_alignment="center")
            with text:
                common.card_summary(view, today)
            with actions:
                common.details_button(view, "s", back="applications", width="stretch")
                if rec.id in tracked:
                    st.markdown(":green-badge[:material/task_alt: In your tracker]")
                else:
                    st.button("Track", key=f"s_track_{rec.id}", on_click=common.track, args=(svc, rec.id),
                              icon=":material/playlist_add:", type="primary", width="stretch")
                st.button("Remove", key=f"s_remove_{rec.id}", on_click=common.unsave, args=(svc, rec.id),
                          icon=":material/bookmark_remove:", width="stretch")


def _edit_form(svc, app, view, today) -> None:
    sid = app.scholarship_id
    with st.form(f"tracker_form_{sid}", border=False):
        st.caption("This records your own progress. ScholarPath never submits anything, so choose "
                   "*Applied* only after you've submitted on the official site.")
        status = st.radio("Status", list(TRACKER_STATUSES), index=list(TRACKER_STATUSES).index(app.status),
                          format_func=_short, key=f"t_status_{sid}", horizontal=True)
        c1, c2, c3 = st.columns(3)
        target = c1.date_input("My target date (optional)", value=app.target_date, key=f"t_target_{sid}",
                               help="Your own planning date. The official deadline is shown separately.")
        submitted = c2.date_input("Date I submitted it", value=app.submitted_date, key=f"t_sub_{sid}",
                                  max_value=today, help="Needed for Applied and Result received.")
        outcome_keys = [""] + list(TRACKER_OUTCOMES)
        outcome = c3.selectbox("Outcome", outcome_keys, index=outcome_keys.index(app.outcome or ""),
                               key=f"t_out_{sid}", format_func=lambda v: TRACKER_OUTCOMES.get(v, "No result yet"),
                               help="Only for Result received.")
        notes = st.text_area("Notes", value=app.notes, key=f"t_notes_{sid}",
                             placeholder="e.g. Ask Prof. X for a reference letter by Friday")
        note = st.text_input("What changed? (optional, kept in history)", key=f"t_hist_{sid}")
        if not st.form_submit_button("Save changes", type="primary", icon=":material/save:"):
            return
        unchanged = (status == app.status and (target or None) == app.target_date
                     and (submitted or None) == app.submitted_date and (outcome or None) == app.outcome
                     and notes.strip() == app.notes and not note.strip())
        if unchanged:
            st.info("No changes to save.", icon=":material/info:")
            return
        try:
            svc.update_application(sid, status, target_date=target or None, submitted_date=submitted or None,
                                   outcome=outcome or None, notes=notes, history_note=note)
        except (ServiceError, *STORAGE_ERRORS) as exc:
            st.error(f"Not saved yet: {exc}", icon=":material/error:")
            return
        common.after_write()
        st.session_state["tracker_pick"] = sid
        st.session_state["flash"] = f"Saved your changes to “{view.record.name}”."
        st.rerun()  # redraw the summary table above with the stored values


def _tracker(svc, today) -> None:
    apps = svc.applications()
    if not apps:
        common.empty_state("tracker", "You're not tracking any applications yet",
                           "Choose **Track** on a saved scholarship, or **Start tracking my application** on "
                           "its details page.")
        return
    records = {v.record.id: v for v in common.all_views(svc)}
    with st.container(horizontal=True, key="tracker_metrics"):
        for status in TRACKER_STATUSES:
            st.metric(_short(status), sum(1 for a in apps if a.status == status), border=True)

    st.dataframe(pd.DataFrame([{
        "Scholarship": records[a.scholarship_id].record.name,
        "My status": _short(a.status),
        "My target date": common.fmt_date(a.target_date),
        "Official deadline": common.deadline_text(records[a.scholarship_id], today),
        "Last updated": common.fmt_ts(a.updated_at),
    } for a in apps]), hide_index=True)

    st.header("Update an application", anchor=False)
    pick = st.session_state.get("tracker_pick")
    if pick not in records or len(apps) == 1:
        pick = apps[0].scholarship_id
    for app in apps:
        view = records[app.scholarship_id]
        label = f"{common.md_escape(view.record.name)} · {_short(app.status)}"
        with st.expander(label, expanded=app.scholarship_id == pick, icon=":material/edit_note:"):
            st.markdown(f"{common.deadline_badge(view)} Official deadline: "
                        f"{common.fmt_date(view.record.deadline_date) if view.record.deadline_date else 'not published'}")
            _edit_form(svc, app, view, today)
            history = svc.application_history(app.scholarship_id)
            st.markdown(f"**Change history ({len(history)})**")
            st.dataframe(pd.DataFrame([{
                "When": common.fmt_ts(h["changed_at"]),
                "Status": _short(h["status"]) if h["status"] in TRACKER_STATUSES else h["status"],
                "Target": h["target_date"] or "-", "Submitted": h["submitted_date"] or "-",
                "Outcome": TRACKER_OUTCOMES.get(h["outcome"], "-") if h["outcome"] else "-",
                "Note": h["note"],
            } for h in history]), hide_index=True, key=f"t_history_{app.scholarship_id}")
            common.details_button(view, "t", back="applications", label="Scholarship details", type="tertiary")


def render(svc) -> None:
    common.page_header(svc, "Saved & applications",
                       "Your saved scholarships, their deadlines and your own progress. Stored on this computer.")
    if not common.dataset_ready(svc):
        return
    common.flash()
    today = svc.today()
    wanted = TABS.get(st.session_state.pop("apps_tab", None), TABS["deadlines"])
    tab_deadlines, tab_saved, tab_tracker = st.tabs(list(TABS.values()), default=wanted)
    with tab_deadlines:
        _deadlines(svc, today)
    with tab_saved:
        _saved(svc, today)
    with tab_tracker:
        _tracker(svc, today)
