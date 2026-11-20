"""Saved: scholarships kept for later, grouped by how soon they close.

Saving is optional. Each row reopens the Review page, so the user picks up
where they left off (apply, or mark as applied). Removing a row only changes
the Saved list; an application entry for the same scholarship is kept, and the
removal can be undone while the page is open.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from ..dates import GROUPS
from . import common

# Soonest first; closed scholarships last.
GROUP_ORDER = ("due_7", "due_30", "later", "rolling", "unknown", "expired")


def _remove(svc, scholarship_id: str, name: str) -> None:
    """Button callback: remove one row and remember it so the page can offer Undo."""
    if common.unsave(svc, scholarship_id):
        st.session_state["saved_undo"] = (scholarship_id, name)


def _undo(svc) -> None:
    scholarship_id, name = st.session_state.pop("saved_undo")
    common.save(svc, scholarship_id, name)


def _undo_notice(svc) -> None:
    """Shown after a removal (the write has already committed) until the user leaves the page."""
    removed = st.session_state.get("saved_undo")
    if not removed:
        return
    with st.container(border=True, horizontal=True, vertical_alignment="center", key="card_saved_undo"):
        st.markdown(f"Removed “{common.md_escape(removed[1])}” from Saved. Any application entry is kept.")
        st.button("Undo", key="saved_undo_btn", on_click=_undo, args=(svc,), icon=":material/undo:")


def render(svc) -> None:
    common.page_header(svc, "Saved scholarships")
    if not common.dataset_ready(svc):
        return
    common.flash()
    _undo_notice(svc)
    views = svc.shortlist()
    if not views:
        common.empty_state("saved", "Nothing saved yet",
                           "Saving is optional. Choose **Save for later** on a scholarship to keep it here "
                           "and come back to it.", "Find scholarships", "find", icon=":material/search:")
        return
    st.caption(f"{common.plural(len(views), 'scholarship')} saved, soonest deadline first.")
    applications = {a.scholarship_id: a for a in svc.applications()}
    for group in GROUP_ORDER:
        items = sorted((v for v in views if v.group == group),
                       key=lambda v: (v.record.deadline_date or date.max, v.record.name))
        if not items:
            continue
        st.header(f"{GROUPS[group]} ({len(items)})", anchor=False)
        for view in items:
            rec = view.record
            app = applications.get(rec.id)
            note = f":material/task_alt: In Applications: {common.tracker_status(app.status)}" if app else ""
            with common.card("saved", view):
                text, actions = st.columns([4, 1], vertical_alignment="center")
                with text:
                    common.card_summary(view, note)
                with actions:
                    common.review_button(view, "saved", back="saved", width="stretch")
                    st.button("Remove", key=f"saved_remove_{rec.id}", on_click=_remove,
                              args=(svc, rec.id, rec.name), icon=":material/bookmark_remove:", type="tertiary",
                              width="stretch")
