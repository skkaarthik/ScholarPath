"""Saved: scholarships kept for later, grouped by how soon they close.

Saving is optional. Each row reopens the Review page, so the user picks up
where they left off (apply, or mark as applied).
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from ..dates import GROUPS
from . import common

# Soonest first; closed scholarships last.
GROUP_ORDER = ("due_7", "due_30", "later", "rolling", "unknown", "expired")


def render(svc) -> None:
    common.page_header(svc, "Saved scholarships")
    if not common.dataset_ready(svc):
        return
    common.flash()
    views = svc.shortlist()
    if not views:
        common.empty_state("saved", "Nothing saved yet",
                           "Saving is optional. Choose **Save for later** on a scholarship to keep it here "
                           "and come back to it.", "Find scholarships", "find", icon=":material/search:")
        return
    applications = {a.scholarship_id: a for a in svc.applications()}
    for group in GROUP_ORDER:
        items = sorted((v for v in views if v.group == group),
                       key=lambda v: (v.record.deadline_date or date.max, v.record.name))
        if not items:
            continue
        st.header(f"{GROUPS[group]} ({len(items)})", anchor=False)
        for view in items:
            rec = view.record
            with common.card("saved", view):
                text, actions = st.columns([4, 1], vertical_alignment="center")
                with text:
                    common.card_summary(view)
                    app = applications.get(rec.id)
                    if app:
                        st.caption(f"In Applications: {common.tracker_status(app.status)}")
                with actions:
                    common.review_button(view, "saved", back="saved", width="stretch")
                    st.button("Remove", key=f"saved_remove_{rec.id}", on_click=common.unsave, args=(svc, rec.id),
                              icon=":material/bookmark_remove:", type="tertiary", width="stretch")
