"""Explore page: search, combined filters, result cards, save/details actions and filtered CSV export."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..dates import STATUS_LABELS
from ..exports import to_csv
from ..models import DEGREES, FUNDING_CATEGORIES, SUBJECTS
from . import common

SORT_LABELS = {"deadline": "Deadline (open soonest first)", "name": "Scholarship name", "provider": "Provider"}
FILTER_KEYS = ("f_text", "f_hosts", "f_degrees", "f_subjects", "f_funding", "f_status")


def _clear_filters() -> None:
    for key in FILTER_KEYS:
        st.session_state.pop(key, None)


def _save(svc, scholarship_id: str, name: str) -> None:
    created = svc.save(scholarship_id)
    common.after_write()
    st.session_state["flash"] = f"Saved “{name}” to your shortlist." if created else "Already in your shortlist."


def _active_filter_count() -> int:
    ss = st.session_state
    return int(bool(ss.get("f_text", "").strip())) + sum(bool(ss.get(k)) for k in FILTER_KEYS[1:])


def render(svc) -> None:
    st.title("Explore scholarships", anchor=False)
    if not common.dataset_ready(svc):
        return
    today = svc.today()
    options = common.cached_options(str(svc.db_path))

    st.text_input("Search", key="f_text", placeholder="Scholarship or provider name, e.g. Commonwealth",
                  label_visibility="collapsed")
    active = _active_filter_count()
    with st.expander(f"Filters{f' ({active} active)' if active else ''}", expanded=active > 0, icon=":material/tune:"):
        c1, c2, c3 = st.columns(3)
        c1.multiselect("Host country", options["host_countries"], key="f_hosts")
        c2.multiselect("Degree", list(DEGREES), format_func=DEGREES.get, key="f_degrees")
        c3.multiselect("Subject", list(SUBJECTS), format_func=SUBJECTS.get, key="f_subjects")
        c4, c5, c6 = st.columns(3)
        c4.multiselect("Funding", list(FUNDING_CATEGORIES), format_func=FUNDING_CATEGORIES.get, key="f_funding")
        c5.multiselect("Deadline status", list(STATUS_LABELS), format_func=STATUS_LABELS.get, key="f_status")
        c6.selectbox("Sort by", list(SORT_LABELS), format_func=SORT_LABELS.get, key="f_sort")
        st.caption("Several values in one filter match any of them; different filters must all match. "
                   "A record whose degree or subject is unknown never matches those filters; one that is "
                   "explicitly open to any subject does.")
        st.button("Clear filters", on_click=_clear_filters, key="clear_filters", icon=":material/filter_alt_off:")

    filters = common.explore_filters()
    sort = st.session_state.get("f_sort", "deadline")
    views = common.cached_search(str(svc.db_path), today.isoformat(), common.filters_key(filters), sort)

    head, download = st.columns([3, 1], vertical_alignment="center")
    head.subheader(f"{len(views)} result{'s' if len(views) != 1 else ''}")
    if views:
        download.download_button(
            "Download CSV", data=to_csv([v.record for v in views], today),
            file_name=f"scholarpath_{svc.mode}_{today.isoformat()}.csv", mime="text/csv", key="explore_csv",
            icon=":material/download:", help="Exactly the filtered results below, with provenance and deadline status.",
        )

    common.flash()

    if not views:
        st.info("No scholarships match these filters. Remove a filter or choose **Clear filters**.")
        return

    saved = set(svc.saved_ids())
    columns = st.columns(2, gap="medium")
    for index, view in enumerate(views):
        rec = view.record
        with columns[index % 2], common.card("ex", view):
            common.card_header(view, today)
            a, b = st.columns(2)
            a.button("View details", key=f"ex_det_{rec.id}", on_click=common.go_to,
                     args=("Scholarship details", rec.id), icon=":material/visibility:", width="stretch")
            if rec.id in saved:
                b.button("Saved", key=f"ex_saved_{rec.id}", disabled=True, icon=":material/bookmark_added:",
                         width="stretch")
            else:
                b.button("Save", key=f"ex_save_{rec.id}", on_click=_save, args=(svc, rec.id, rec.name),
                         type="primary", icon=":material/bookmark_add:", width="stretch")

    with st.expander("Table view", icon=":material/table_rows:"):
        st.dataframe(pd.DataFrame(common.results_table(views, today)), hide_index=True)
