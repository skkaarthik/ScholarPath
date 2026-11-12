"""Explore page: search, combined filters, results, save/details actions and filtered CSV export."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..dates import STATUS_LABELS
from ..exports import to_csv
from ..models import DEGREES, FUNDING_CATEGORIES, SUBJECTS
from . import common

SORT_LABELS = {"deadline": "Deadline (open soonest, then rolling, unknown, expired)",
               "name": "Scholarship name", "provider": "Provider"}


def _clear_filters() -> None:
    for key in ("f_text", "f_hosts", "f_degrees", "f_subjects", "f_funding", "f_status"):
        st.session_state.pop(key, None)


def _save(svc, scholarship_id: str) -> None:
    created = svc.save(scholarship_id)
    common.after_write()
    st.session_state["flash"] = "Saved to your shortlist." if created else "Already in your shortlist."


def render(svc) -> None:
    st.title("Explore scholarships")
    if not common.dataset_ready(svc):
        return
    today = svc.today()
    options = common.cached_options(str(svc.db_path))

    with st.container(border=True):
        st.text_input("Search scholarship or provider name", key="f_text")
        c1, c2, c3 = st.columns(3)
        c1.multiselect("Host country", options["host_countries"], key="f_hosts")
        c2.multiselect("Degree", list(DEGREES), format_func=DEGREES.get, key="f_degrees")
        c3.multiselect("Subject", list(SUBJECTS), format_func=SUBJECTS.get, key="f_subjects")
        c4, c5, c6 = st.columns(3)
        c4.multiselect("Funding", list(FUNDING_CATEGORIES), format_func=FUNDING_CATEGORIES.get, key="f_funding")
        c5.multiselect("Deadline status", list(STATUS_LABELS), format_func=STATUS_LABELS.get, key="f_status")
        c6.selectbox("Sort by", list(SORT_LABELS), format_func=SORT_LABELS.get, key="f_sort")
        st.button("Clear filters", on_click=_clear_filters, key="clear_filters")
        st.caption("Several values in one filter = any of them (OR). Different filters = all must hold (AND). "
                   "Records whose degree or subject is *unknown* never match those filters; explicitly "
                   "unrestricted ones do.")

    filters = common.explore_filters()
    sort = st.session_state.get("f_sort", "deadline")
    views = common.cached_search(str(svc.db_path), today.isoformat(), common.filters_key(filters), sort)
    st.subheader(f"{len(views)} result{'s' if len(views) != 1 else ''}")

    if flash := st.session_state.pop("flash", None):
        st.success(flash)

    if not views:
        st.info("No scholarships match these filters. Try removing a filter or use **Clear filters**.")
        return

    st.dataframe(pd.DataFrame(common.results_table(views, today)), hide_index=True)

    ids = [v.record.id for v in views]
    labels = {v.record.id: f"{v.record.name} - {v.record.provider}" for v in views}
    if st.session_state.get("explore_open_id") not in ids:
        st.session_state["explore_open_id"] = ids[0]
    pick = st.selectbox("Choose a result", ids, format_func=labels.get, key="explore_open_id")
    saved = set(svc.saved_ids())
    a, b = st.columns(2)
    a.button("View details", key="explore_details", on_click=common.go_to, args=("Scholarship details", pick))
    if pick in saved:
        b.button("Saved ✓", key="explore_saved", disabled=True)
    else:
        b.button("Save to shortlist", key="explore_save", on_click=_save, args=(svc, pick))

    st.download_button(
        "Download these results as CSV",
        data=to_csv([v.record for v in views], today),
        file_name=f"scholarpath_{svc.mode}_{today.isoformat()}.csv",
        mime="text/csv",
        key="explore_csv",
        help="Exports exactly the filtered results above, with provenance and deadline status.",
    )
