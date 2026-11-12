"""My applications: deadline board, shortlist and tracker editing (all persisted in SQLite)."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from ..dates import GROUPS
from ..models import TRACKER_OUTCOMES, TRACKER_STATUSES
from ..services import ServiceError
from . import common

BOARD = [("due_7", ":material/alarm:"), ("due_30", ":material/event_upcoming:"), ("later", ":material/calendar_month:")]
OTHER_GROUPS = [("rolling", ":material/autorenew:"), ("unknown", ":material/event_note:"), ("expired", ":material/event_busy:")]
STATUS_ICONS = {"interested": ":material/star:", "preparing": ":material/edit_note:",
                "applied": ":material/send:", "result_received": ":material/flag:"}


def _unsave(svc, sid):
    svc.unsave(sid)
    common.after_write()
    st.session_state["flash"] = "Removed from your shortlist. Tracker notes and history are kept."


def _track(svc, sid):
    svc.start_tracking(sid)
    common.after_write()
    st.session_state["tracker_pick"] = sid
    st.session_state["flash"] = "Tracking started. Open the Tracker tab to update it."


def _mini(view, today, prefix: str) -> None:
    with common.card(prefix, view):
        st.markdown(f'<div class="sp-card-title sp-small">{html.escape(view.record.name)}</div>'
                    f'<div class="sp-provider">{html.escape(view.record.provider)}</div>', unsafe_allow_html=True)
        st.markdown(common.deadline_badge(view))
        st.button("Details", key=f"{prefix}_open_{view.record.id}", on_click=common.go_to,
                  args=("Scholarship details", view.record.id), icon=":material/visibility:", type="tertiary")


def _dashboard(svc, today) -> None:
    groups = svc.dashboard()
    if not groups:
        st.info("Nothing saved or tracked yet. Save scholarships from **Explore** and their deadlines appear here.",
                icon=":material/bookmark_add:")
        st.button("Explore scholarships", key="dash_explore", on_click=common.go_to, args=("Explore",),
                  type="primary", icon=":material/travel_explore:")
        return
    st.caption("Saved and tracked scholarships, by official deadline. Days are counted from today; "
               "each scholarship appears in exactly one group.")
    columns = st.columns(3, gap="medium")
    for column, (key, icon) in zip(columns, BOARD):
        items = groups.get(key, [])
        with column:
            st.markdown(f"##### {icon} {GROUPS[key]} ({len(items)})")
            if not items:
                st.caption("Nothing here.")
            for view in items:
                _mini(view, today, f"b{key}")
    others = [(key, icon, groups.get(key, [])) for key, icon in OTHER_GROUPS]
    if any(items for _, _, items in others):
        st.markdown("##### Other deadlines")
        columns = st.columns(3, gap="medium")
        for column, (key, icon, items) in zip(columns, others):
            with column:
                st.markdown(f"**{icon} {GROUPS[key]} ({len(items)})**")
                for view in items:
                    st.markdown(f"- {common.md_escape(view.record.name)}")


def _shortlist(svc, today) -> None:
    views = svc.shortlist()
    if not views:
        st.info("Your shortlist is empty. Choose **Save** on any scholarship in Explore.", icon=":material/bookmark:")
        return
    tracked = {a.scholarship_id for a in svc.applications()}
    columns = st.columns(2, gap="medium")
    for index, view in enumerate(views):
        rec = view.record
        with columns[index % 2], common.card("s", view):
            common.card_header(view, today)
            if rec.source_status == "unavailable":
                st.caption(":material/link_off: Source page unavailable at last collection; saved copy shown.")
            a, b, c = st.columns(3)
            a.button("Details", key=f"s_open_{rec.id}", on_click=common.go_to, args=("Scholarship details", rec.id),
                     icon=":material/visibility:", width="stretch")
            if rec.id in tracked:
                b.button("Tracking", key=f"s_tracked_{rec.id}", disabled=True, icon=":material/check:", width="stretch")
            else:
                b.button("Track", key=f"s_track_{rec.id}", on_click=_track, args=(svc, rec.id),
                         icon=":material/playlist_add:", type="primary", width="stretch")
            c.button("Remove", key=f"s_remove_{rec.id}", on_click=_unsave, args=(svc, rec.id),
                     icon=":material/bookmark_remove:", width="stretch")


def _tracker(svc, today) -> None:
    apps = svc.applications()
    if not apps:
        st.info("You're not tracking anything yet. Choose **Track** on a saved scholarship.",
                icon=":material/playlist_add:")
        return
    records = {v.record.id: v for v in svc.search()}
    ids = [a.scholarship_id for a in apps]
    if st.session_state.get("tracker_pick") not in ids:
        st.session_state["tracker_pick"] = ids[0]

    counts = {status: sum(1 for a in apps if a.status == status) for status in TRACKER_STATUSES}
    cols = st.columns(4)
    for col, (status, label) in zip(cols, TRACKER_STATUSES.items()):
        col.metric(label.replace(" (recorded by you)", ""), counts[status])

    st.dataframe(pd.DataFrame([{
        "Scholarship": records[a.scholarship_id].record.name,
        "My status": TRACKER_STATUSES[a.status],
        "My target date": a.target_date.isoformat() if a.target_date else "-",
        "Official deadline": common.deadline_text(records[a.scholarship_id], today),
        "Last updated": a.updated_at.replace("T", " ").replace("+00:00", " UTC"),
    } for a in apps]), hide_index=True)

    sid = st.selectbox("Update an application", ids, key="tracker_pick",
                       format_func=lambda i: records[i].record.name)
    app = next(a for a in apps if a.scholarship_id == sid)
    with st.form(f"tracker_form_{sid}", border=True):
        st.markdown(f"#### {STATUS_ICONS[app.status]} {html.escape(records[sid].record.name)}")
        st.caption("This records your own progress. ScholarPath never submits anything, so choose "
                   "*Applied* only after you've submitted on the official site.")
        status = st.radio("Status", list(TRACKER_STATUSES), index=list(TRACKER_STATUSES).index(app.status),
                          format_func=lambda s: TRACKER_STATUSES[s].replace(" (recorded by you)", ""),
                          key=f"t_status_{sid}", horizontal=True)
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
        if st.form_submit_button("Save changes", type="primary", icon=":material/save:"):
            unchanged = (status == app.status and (target or None) == app.target_date
                         and (submitted or None) == app.submitted_date and (outcome or None) == app.outcome
                         and notes.strip() == app.notes and not note.strip())
            if unchanged:
                st.info("No changes to save.", icon=":material/info:")
            else:
                try:
                    svc.update_application(sid, status, target_date=target or None,
                                           submitted_date=submitted or None, outcome=outcome or None,
                                           notes=notes, history_note=note)
                except ServiceError as exc:
                    st.error(f"Not saved yet: {exc}", icon=":material/error:")
                else:
                    common.after_write()
                    st.success("Saved.", icon=":material/check_circle:")

    history = svc.application_history(sid)
    with st.expander(f"Change history ({len(history)})", icon=":material/history:"):
        st.dataframe(pd.DataFrame([{
            "When (UTC)": h["changed_at"].replace("T", " ").replace("+00:00", ""),
            "Status": TRACKER_STATUSES.get(h["status"], h["status"]),
            "Target": h["target_date"] or "-", "Submitted": h["submitted_date"] or "-",
            "Outcome": TRACKER_OUTCOMES.get(h["outcome"], "-") if h["outcome"] else "-",
            "Note": h["note"],
        } for h in history]), hide_index=True)


def render(svc) -> None:
    st.title("My applications", anchor=False)
    if not common.dataset_ready(svc):
        return
    common.flash()
    today = svc.today()
    tab_deadlines, tab_shortlist, tab_tracker = st.tabs([":material/event: Deadlines", ":material/bookmark: Shortlist",
                                                         ":material/task_alt: Tracker"])
    with tab_deadlines:
        _dashboard(svc, today)
    with tab_shortlist:
        _shortlist(svc, today)
    with tab_tracker:
        _tracker(svc, today)
