"""My applications: deadline groups, shortlist and tracker editing (all persisted in SQLite)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..dates import GROUP_ORDER, GROUPS
from ..models import TRACKER_OUTCOMES, TRACKER_STATUSES
from ..services import ServiceError
from . import common


def _unsave(svc, sid):
    svc.unsave(sid)
    common.after_write()
    st.session_state["flash"] = "Removed from shortlist. Tracker history (if any) was kept."


def _track(svc, sid):
    svc.start_tracking(sid)
    common.after_write()
    st.session_state["tracker_pick"] = sid
    st.session_state["flash"] = "Tracking started."


def _dashboard(svc, today) -> None:
    groups = svc.dashboard()
    if not groups:
        st.info("Nothing saved or tracked yet. Save scholarships from **Explore** or **Scholarship details**.")
        return
    st.caption("Groups do not overlap. Days are counted from today in the app timezone; "
               "rolling and unknown deadlines are listed separately.")
    for key in GROUP_ORDER:
        items = groups.get(key, [])
        st.markdown(f"**{GROUPS[key]}** ({len(items)})")
        if not items:
            st.caption("None.")
            continue
        for view in items:
            st.markdown(f"- {common.md_escape(view.record.name)} - {common.deadline_text(view, today)}")


def _shortlist(svc, today) -> None:
    views = svc.shortlist()
    if not views:
        st.info("Your shortlist is empty.")
        return
    tracked = {a.scholarship_id for a in svc.applications()}
    for view in views:
        rec = view.record
        with st.container(border=True):
            st.markdown(f"**{common.md_escape(rec.name)}** - {common.md_escape(rec.provider)}  \n"
                        f"{common.deadline_text(view, today)}")
            if rec.source_status == "unavailable":
                st.caption("⚠️ Source page reported unavailable; retained record shown.")
            a, b, c = st.columns(3)
            a.button("Details", key=f"s_open_{rec.id}", on_click=common.go_to, args=("Scholarship details", rec.id))
            if rec.id in tracked:
                b.button("Tracking ✓", key=f"s_tracked_{rec.id}", disabled=True)
            else:
                b.button("Start tracking", key=f"s_track_{rec.id}", on_click=_track, args=(svc, rec.id))
            c.button("Remove", key=f"s_remove_{rec.id}", on_click=_unsave, args=(svc, rec.id))


def _tracker(svc, today) -> None:
    apps = svc.applications()
    if not apps:
        st.info("No applications tracked yet. Use **Start tracking** on a saved scholarship.")
        return
    records = {v.record.id: v for v in svc.search()}
    ids = [a.scholarship_id for a in apps]
    if st.session_state.get("tracker_pick") not in ids:
        st.session_state["tracker_pick"] = ids[0]

    st.dataframe(pd.DataFrame([{
        "Scholarship": records[a.scholarship_id].record.name,
        "Status": TRACKER_STATUSES[a.status],
        "My target date": a.target_date.isoformat() if a.target_date else "-",
        "Source deadline": common.deadline_text(records[a.scholarship_id], today),
        "Updated": a.updated_at.replace("T", " ").replace("+00:00", " UTC"),
    } for a in apps]), hide_index=True)

    sid = st.selectbox("Edit application", ids, key="tracker_pick",
                       format_func=lambda i: records[i].record.name)
    app = next(a for a in apps if a.scholarship_id == sid)
    st.caption("Statuses only record your own progress. ScholarPath never submits anything; choose "
               "*Applied* only after you have submitted the application yourself on the official site.")
    with st.form(f"tracker_form_{sid}"):
        status = st.selectbox("Status", list(TRACKER_STATUSES), index=list(TRACKER_STATUSES).index(app.status),
                              format_func=TRACKER_STATUSES.get, key=f"t_status_{sid}")
        c1, c2 = st.columns(2)
        target = c1.date_input("My personal target date (optional)", value=app.target_date, key=f"t_target_{sid}",
                               help="Your own planning date - separate from the official deadline.")
        submitted = c2.date_input("Date I submitted it (Applied / Result received only)",
                                  value=app.submitted_date, key=f"t_sub_{sid}", max_value=today)
        outcome_keys = [""] + list(TRACKER_OUTCOMES)
        outcome = st.selectbox("Outcome (Result received only)", outcome_keys,
                               index=outcome_keys.index(app.outcome or ""), key=f"t_out_{sid}",
                               format_func=lambda v: TRACKER_OUTCOMES.get(v, "- none -"))
        notes = st.text_area("Notes", value=app.notes, key=f"t_notes_{sid}")
        note = st.text_input("Reason for this change (optional, kept in history)", key=f"t_hist_{sid}")
        if st.form_submit_button("Save changes"):
            try:
                svc.update_application(sid, status, target_date=target or None, submitted_date=submitted or None,
                                       outcome=outcome or None, notes=notes, history_note=note)
            except ServiceError as exc:
                st.error(f"Not saved: {exc}")
            else:
                common.after_write()
                st.success("Saved. The change is stored in the database.")

    history = svc.application_history(sid)
    with st.expander(f"Change history ({len(history)})"):
        st.dataframe(pd.DataFrame([{
            "When (UTC)": h["changed_at"].replace("T", " ").replace("+00:00", ""),
            "Status": TRACKER_STATUSES.get(h["status"], h["status"]),
            "Target": h["target_date"] or "-", "Submitted": h["submitted_date"] or "-",
            "Outcome": TRACKER_OUTCOMES.get(h["outcome"], "-") if h["outcome"] else "-",
            "Note": h["note"],
        } for h in history]), hide_index=True)


def render(svc) -> None:
    st.title("My applications")
    if not common.dataset_ready(svc):
        return
    if flash := st.session_state.pop("flash", None):
        st.success(flash)
    today = svc.today()
    tab_deadlines, tab_shortlist, tab_tracker = st.tabs(["Deadlines", "Shortlist", "Tracker"])
    with tab_deadlines:
        _dashboard(svc, today)
    with tab_shortlist:
        _shortlist(svc, today)
    with tab_tracker:
        _tracker(svc, today)
