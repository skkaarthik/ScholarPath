"""Applications (step 4): every application the user confirmed, with its status at a glance.

Each entry shows scholarship, provider and status. "Update status" opens the
edit fields for that entry; saving writes to SQLite and confirms in the entry.
Rules (checked in services.validate_application): Applied needs a submission
date, Result received needs an outcome.
"""

from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from ..models import TRACKER_OUTCOMES, TRACKER_STATUSES
from ..services import STORAGE_ERRORS, ServiceError
from . import common


def _save(svc, app, name: str) -> None:
    """Button callback: store the edit fields of one entry and leave a confirmation for it."""
    ss, sid = st.session_state, app.scholarship_id
    status = ss[f"t_status_{sid}"]
    # Fields that are hidden for the chosen status are stored as empty.
    submitted = ss.get(f"t_sub_{sid}") if status in common.SUBMITTED_STATUSES else None
    outcome = (ss.get(f"t_out_{sid}") or None) if status == "result_received" else None
    target = ss.get(f"t_target_{sid}") or None
    notes = (ss.get(f"t_notes_{sid}") or "").strip()
    note = (ss.get(f"t_hist_{sid}") or "").strip()
    ss["tracker_pick"] = sid  # keep this entry open and first
    ss.pop("app_saved", None)
    ss.pop("app_error", None)
    unchanged = (status == app.status and target == app.target_date and submitted == app.submitted_date
                 and outcome == app.outcome and notes == app.notes and not note)
    if unchanged:
        ss["app_error"] = (sid, "Nothing to save: no field was changed.")
        return
    try:
        svc.update_application(sid, status, target_date=target, submitted_date=submitted, outcome=outcome,
                               notes=notes, history_note=note)
    except (ServiceError, *STORAGE_ERRORS) as exc:
        ss["app_error"] = (sid, f"Not saved yet: {exc}")
        return
    common.after_write()
    ss[f"t_hist_{sid}"] = ""
    ss["app_saved"] = sid
    ss["flash"] = f"Saved your changes to “{name}”."


def _status_line(app) -> str:
    line = f"**{common.tracker_status(app.status)}**"
    if app.status == "result_received" and app.outcome:
        line += f" · {TRACKER_OUTCOMES[app.outcome]}"
    if app.submitted_date:
        line += f" · submitted {common.fmt_date(app.submitted_date)}"
    return line


def _edit_fields(svc, app, view, today) -> None:
    sid = app.scholarship_id
    statuses = list(TRACKER_STATUSES)
    status = st.selectbox("Status", statuses, index=statuses.index(app.status),
                          format_func=common.tracker_status, key=f"t_status_{sid}")
    if status in common.SUBMITTED_STATUSES:
        st.date_input("Date you submitted it", value=app.submitted_date or today, max_value=today,
                      key=f"t_sub_{sid}")
    if status == "result_received":
        outcomes = [""] + list(TRACKER_OUTCOMES)
        st.selectbox("Outcome", outcomes, index=outcomes.index(app.outcome or ""), key=f"t_out_{sid}",
                     format_func=lambda v: TRACKER_OUTCOMES.get(v, "Choose the outcome"))
    st.date_input("My target date (optional)", value=app.target_date, key=f"t_target_{sid}",
                  help="Your own planning date. The official deadline is shown above.")
    st.text_area("Notes", value=app.notes, key=f"t_notes_{sid}",
                 placeholder="e.g. Ask Prof. X for a reference letter by Friday")
    st.text_input("What changed? (optional, kept in history)", key=f"t_hist_{sid}")
    st.button("Save changes", key=f"t_save_{sid}", on_click=_save, args=(svc, app, view.record.name),
              type="primary", icon=":material/save:")

    history = svc.application_history(sid)
    st.caption(f"History ({len(history)})")
    st.dataframe(pd.DataFrame([{
        "When": common.fmt_ts(h["changed_at"]),
        "Status": common.tracker_status(h["status"]),
        "Target": h["target_date"] or "-", "Submitted": h["submitted_date"] or "-",
        "Outcome": TRACKER_OUTCOMES.get(h["outcome"], "-") if h["outcome"] else "-",
        "Note": h["note"],
    } for h in history]), hide_index=True, key=f"t_history_{sid}")


def _entry(svc, app, view, today, opened: bool) -> None:
    rec, sid = view.record, app.scholarship_id
    with st.container(border=True, key=f"card_app_{sid}"):
        text, action = st.columns([4, 1], vertical_alignment="center")
        with text:
            st.subheader(common.md_escape(rec.name), anchor=False)
            st.markdown(f"{common.md_escape(rec.provider)}  \n{_status_line(app)}")
            st.caption(f"Official deadline: {common.deadline_line(view).replace('**', '')}")
        with action:
            common.review_button(view, "app", back="applications", label="Scholarship", type="tertiary",
                                 width="stretch")
        if st.session_state.get("app_saved") == sid:
            st.session_state.pop("app_saved")
            st.success(f"Saved. Status: {common.tracker_status(app.status)}.", icon=":material/check_circle:")
        problem = st.session_state.get("app_error")
        if problem and problem[0] == sid:
            st.session_state.pop("app_error")
            st.error(problem[1], icon=":material/error:")
        with st.expander("Update status", expanded=opened, key=f"app_edit_{sid}", icon=":material/edit:"):
            _edit_fields(svc, app, view, today)


def render(svc) -> None:
    common.page_header(svc, "Applications")
    if not common.dataset_ready(svc):
        return
    common.flash()
    apps = svc.applications()
    if not apps:
        common.empty_state("applications", "No applications yet",
                           "When you have applied for a scholarship, choose **Mark as applied** on its page "
                           "and it appears here.", "Find scholarships", "find", icon=":material/search:")
        return
    today = svc.today()
    records = {v.record.id: v for v in common.all_views(svc)}
    counts = Counter(a.status for a in apps)
    st.caption(common.plural(len(apps), "application") + ": "
               + ", ".join(f"{counts[s]} {common.tracker_status(s).lower()}" for s in TRACKER_STATUSES if counts[s]))

    pick = st.session_state.get("tracker_pick")
    apps.sort(key=lambda a: a.scholarship_id != pick)  # the entry just opened or saved comes first
    for app in apps:
        _entry(svc, app, records[app.scholarship_id], today, opened=app.scholarship_id == pick)
