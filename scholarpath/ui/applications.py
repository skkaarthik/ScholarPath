"""Applications (step 4): every application the user confirmed, with its status at a glance.

The same page for scholarships and internships (each type has its own entries).
Each entry shows scholarship (or role), provider (or employer), status and the next step. "Update
status" opens the edit fields for that entry; saving writes to SQLite and the
confirmation appears in the entry only after the write succeeded.
"Remove" asks for confirmation inside the entry, then deletes the entry and its
history; the scholarship itself and the Saved list are not changed.
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

# What the user can do next, by status. Entries made before the redesign can still be
# Interested or Preparing; they are kept and move on through the Review page.
NEXT_STEP = {
    "interested": "Next: apply on the provider's website, then choose Mark as applied on the scholarship's page.",
    "preparing": "Next: apply on the provider's website, then choose Mark as applied on the scholarship's page.",
    "applied": "Next: when the provider replies, open Update status and choose Result received.",
    "result_received": "",
}
I_NEXT_STEP = {
    "interested": "Next: apply on the employer's website, then choose Mark as applied on the internship's page.",
    "preparing": "Next: apply on the employer's website, then choose Mark as applied on the internship's page.",
    "applied": "Next: when the employer replies, open Update status and choose Result received.",
    "result_received": "",
}
MESSAGES = {"success": st.success, "info": st.info, "error": st.error}
MESSAGE_ICONS = {"success": ":material/check_circle:", "info": ":material/info:", "error": ":material/error:"}


def _save(svc, app, name: str) -> None:
    """Button callback: store the edit fields of one entry and leave a message for it."""
    ss, sid = st.session_state, app.scholarship_id
    status = ss[f"t_status_{sid}"]
    # Fields that are hidden for the chosen status are stored as empty.
    submitted = ss.get(f"t_sub_{sid}") if status in common.SUBMITTED_STATUSES else None
    outcome = (ss.get(f"t_out_{sid}") or None) if status == "result_received" else None
    target = ss.get(f"t_target_{sid}") or None
    notes = (ss.get(f"t_notes_{sid}") or "").strip()
    note = (ss.get(f"t_hist_{sid}") or "").strip()
    ss["tracker_pick"] = sid  # keep this entry open and first
    unchanged = (status == app.status and target == app.target_date and submitted == app.submitted_date
                 and outcome == app.outcome and notes == app.notes and not note)
    if unchanged:
        ss["app_message"] = (sid, "info", "Nothing to save: no field was changed.")
        return
    try:
        svc.update_application(sid, status, target_date=target, submitted_date=submitted, outcome=outcome,
                               notes=notes, history_note=note)
    except (ServiceError, *STORAGE_ERRORS) as exc:
        ss["app_message"] = (sid, "error", f"Not saved yet: {exc}")
        return
    common.after_write()
    ss[f"t_hist_{sid}"] = ""
    ss["app_message"] = (sid, "success", f"Saved. Status: {common.tracker_status(status)}.")


def _ask_remove(scholarship_id: str) -> None:
    st.session_state["app_remove"] = scholarship_id


def _cancel_remove() -> None:
    st.session_state.pop("app_remove", None)


def _remove(svc, scholarship_id: str, name: str) -> None:
    """Button callback for "Yes, remove": the note is shown only after the delete committed."""
    ss = st.session_state
    ss.pop("app_remove", None)
    try:
        removed = svc.remove_application(scholarship_id)
    except STORAGE_ERRORS as exc:
        ss["app_message"] = (scholarship_id, "error", f"Not removed: {exc}")
        return
    common.after_write()
    if ss.get("tracker_pick") == scholarship_id:
        ss.pop("tracker_pick")
    if removed:
        ss["app_removed"] = name


def _confirm_remove(svc, app, name: str) -> None:
    sid = app.scholarship_id
    noun = common.WORDS[svc.kind]["noun"]
    with st.container(border=True, key=f"app_confirm_remove_{sid}"):
        st.markdown("**Remove this application?** Its status, notes and history are deleted and can't be "
                    f"restored. The {noun} itself stays in Find (and in Saved, if you saved it).")
        with st.container(horizontal=True):
            st.button("Yes, remove", key=f"app_remove_yes_{sid}", on_click=_remove, args=(svc, sid, name),
                      icon=":material/delete:")
            st.button("Cancel", key=f"app_remove_no_{sid}", on_click=_cancel_remove, type="tertiary")


def _edit_fields(svc, app, view, today) -> None:
    sid = app.scholarship_id
    statuses = list(TRACKER_STATUSES)
    status = st.selectbox("Status", statuses, index=statuses.index(app.status),
                          format_func=common.tracker_status, key=f"t_status_{sid}")
    if status in common.SUBMITTED_STATUSES:
        # No max_value: a later date is refused by the service on Save, with the reason shown in
        # the entry, instead of the field silently keeping its previous value.
        st.date_input("Date you submitted it", value=app.submitted_date or today, key=f"t_sub_{sid}",
                      format="DD/MM/YYYY")
    if status == "result_received":
        outcomes = [""] + list(TRACKER_OUTCOMES)
        st.selectbox("Outcome", outcomes, index=outcomes.index(app.outcome or ""), key=f"t_out_{sid}",
                     format_func=lambda v: TRACKER_OUTCOMES.get(v, "Choose the outcome"))
    st.date_input("My target date (optional)", value=app.target_date, key=f"t_target_{sid}",
                  format="DD/MM/YYYY",
                  help="Your own planning date. The official deadline is shown above.")
    st.text_area("Notes", value=app.notes, key=f"t_notes_{sid}",
                 placeholder="e.g. Ask Prof. X for a reference letter by Friday")
    st.text_input("What changed? (optional, kept in history)", key=f"t_hist_{sid}")
    st.button("Save changes", key=f"t_save_{sid}", on_click=_save, args=(svc, app, view.record.name),
              type="primary", icon=":material/save:")

    history = svc.application_history(sid)
    st.caption(f"History, newest first ({len(history)})")
    st.dataframe(pd.DataFrame([{
        "When": common.fmt_ts(h["changed_at"]),
        "Status": common.tracker_status(h["status"]),
        "Outcome": TRACKER_OUTCOMES.get(h["outcome"], "-") if h["outcome"] else "-",
        "Submitted": common.fmt_iso_date(h["submitted_date"]),
        "Target": common.fmt_iso_date(h["target_date"]),
        "Note": h["note"],
    } for h in history]), hide_index=True, key=f"t_history_{sid}")


def _entry(svc, app, view, today, opened: bool) -> None:
    rec, sid = view.record, app.scholarship_id
    with st.container(border=True, key=f"card_app_{sid}"):
        text, action = st.columns([4, 1], vertical_alignment="center")
        with text:
            st.subheader(common.md_escape(rec.name), anchor=False)
            st.markdown(f"{common.md_escape(rec.provider)}  \n{common.application_line(app)}")
            next_step = (I_NEXT_STEP if svc.kind == "internship" else NEXT_STEP).get(app.status, "")
            st.caption(f"Official deadline: {common.deadline_plain(view)}" + (f"  \n{next_step}" if next_step else ""))
        with action:
            common.review_button(view, "app", back="applications", label=f"View {common.WORDS[svc.kind]['noun']}",
                                 type="tertiary", width="stretch")
            st.button("Remove", key=f"app_remove_{sid}", on_click=_ask_remove, args=(sid,), type="tertiary",
                      icon=":material/delete:", width="stretch")
        if st.session_state.get("app_remove") == sid:
            _confirm_remove(svc, app, rec.name)
        message = st.session_state.get("app_message")
        if message and message[0] == sid:
            st.session_state.pop("app_message")
            MESSAGES[message[1]](message[2], icon=MESSAGE_ICONS[message[1]])
        with st.expander("Update status", expanded=opened, key=f"app_edit_{sid}", icon=":material/edit:"):
            _edit_fields(svc, app, view, today)


def render(svc) -> None:
    common.page_header(svc, "Applications")
    if not common.dataset_ready(svc):
        return
    common.flash()
    removed = st.session_state.get("app_removed")
    if removed:
        st.success(f"Removed “{common.md_escape(removed)}” from Applications.", icon=":material/check_circle:")
    apps = svc.applications()
    if not apps:
        w = common.WORDS[svc.kind]
        common.empty_state("applications", "No applications yet",
                           f"When you have applied for {w['a']}, choose **Mark as applied** on its page "
                           "and it appears here.", w["find_button"], "find", icon=":material/search:")
        return
    today = svc.today()
    records = {v.record.id: v for v in common.all_views(svc, include_closed=True)}   # tracked ones may be closed
    counts = Counter(a.status for a in apps)
    st.caption(common.plural(len(apps), "application") + ": "
               + ", ".join(f"{counts[s]} {common.tracker_status(s).lower()}" for s in TRACKER_STATUSES if counts[s]))

    pick = st.session_state.get("tracker_pick")
    apps.sort(key=lambda a: a.scholarship_id != pick)  # the entry just opened or saved comes first
    for app in apps:
        _entry(svc, app, records[app.scholarship_id], today, opened=app.scholarship_id == pick)
