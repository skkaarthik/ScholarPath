"""Find scholarships (step 1): search first, results below, advanced filters behind one control.

Choosing a result opens the Review page. The search text, filters, sort order
and page number are kept (common.keep_state), so Back returns to the same list.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..exports import to_csv
from ..models import DEGREES, FUNDING_CATEGORIES, SUBJECTS
from . import common

SORT_LABELS = {"deadline": "Deadline (soonest first)", "name": "Scholarship name", "provider": "Provider"}
STATUS_OPTIONS = {"open": "Open", "rolling": "Rolling", "unknown": "Not published", "expired": "Closed"}
# Advanced filters: session key -> (label in the summary line, value -> readable name).
ADVANCED = {
    "f_hosts": ("Country", {}), "f_degrees": ("Level", DEGREES), "f_subjects": ("Subject", SUBJECTS),
    "f_funding": ("Funding", FUNDING_CATEGORIES), "f_status": ("Deadline", STATUS_OPTIONS),
}


def _first_page() -> None:
    st.session_state["f_page"] = 1


def _clear_filters() -> None:
    for key in common.FILTER_KEYS:
        st.session_state.pop(key, None)
    _first_page()


def _active_filters() -> list[str]:
    """Readable summary of what is narrowing the list, e.g. 'Country: Canada or Ireland'."""
    ss = st.session_state
    parts = []
    if (ss.get("f_text") or "").strip():
        parts.append(f"Search: “{common.md_escape(ss['f_text'].strip())}”")
    for key, (label, names) in ADVANCED.items():
        chosen = ss.get(key) or []
        if chosen:
            parts.append(f"{label}: " + " or ".join(common.md_escape(names.get(v, v)) for v in chosen))
    return parts


def _search_and_filters(options: dict) -> None:
    st.text_input("Search by scholarship or provider", key="f_text", on_change=_first_page,
                  placeholder="e.g. Commonwealth", icon=":material/search:")
    in_use = sum(1 for key in ADVANCED if st.session_state.get(key))
    label = "Filters and sorting" + (f" · {in_use} in use" if in_use else "")
    with st.expander(label, key="find_filters", icon=":material/tune:"):
        c1, c2 = st.columns(2)
        c1.multiselect("Country", options["host_countries"], key="f_hosts", on_change=_first_page,
                       placeholder="Any country")
        c2.multiselect("Level of study", list(DEGREES), format_func=DEGREES.get, key="f_degrees",
                       on_change=_first_page, placeholder="Any level")
        c1.multiselect("Subject", list(SUBJECTS), format_func=SUBJECTS.get, key="f_subjects",
                       on_change=_first_page, placeholder="Any subject")
        c2.multiselect("Funding", list(FUNDING_CATEGORIES), format_func=FUNDING_CATEGORIES.get, key="f_funding",
                       on_change=_first_page, placeholder="Any funding")
        st.pills("Deadline", list(STATUS_OPTIONS), format_func=STATUS_OPTIONS.get, key="f_status",
                 selection_mode="multi", on_change=_first_page)
        st.selectbox("Sort by", list(SORT_LABELS), format_func=SORT_LABELS.get, key="f_sort",
                     on_change=_first_page)
        st.caption("Several values in one filter match any of them; different filters must all match. "
                   "A scholarship whose level or subject is not recorded never matches those filters.")


def _progress_note(rec_id: str, saved: set, applications: dict) -> str:
    """Tell a returning user what they already did with this scholarship."""
    app = applications.get(rec_id)
    if app:
        return f"In Applications: {common.tracker_status(app.status)}"
    return "Saved" if rec_id in saved else ""


def _table_and_download(svc, views, today) -> None:
    with st.expander("Table view and download", key="find_more", icon=":material/table:"):
        st.toggle("Show results as a table", key="f_table")
        st.download_button(
            "Download these results (CSV)", data=to_csv([v.record for v in views], today),
            file_name=f"scholarpath_{svc.mode}_{today.isoformat()}.csv", mime="text/csv", key="find_csv",
            icon=":material/download:",
            help="Exactly the filtered results, all pages, with source and deadline status.")


def render(svc) -> None:
    common.page_header(svc, "Find scholarships")
    if not common.dataset_ready(svc):
        return
    today = svc.today()
    _search_and_filters(common.cached_options(str(svc.db_path)))

    sort = st.session_state.get("f_sort") or "deadline"
    views = common.cached_search(str(svc.db_path), today.isoformat(), common.filters_key(common.find_filters()),
                                 sort)
    active = _active_filters()

    st.header(common.plural(len(views), "scholarship"), anchor=False)
    if active:
        st.markdown("Filtered by " + " · ".join(active))
        if views:
            st.button("Clear filters", on_click=_clear_filters, key="clear_filters", type="tertiary",
                      icon=":material/filter_alt_off:")
    common.flash()

    if not views:
        total = common.cached_overview(str(svc.db_path), today.isoformat())["scholarships"]
        with st.container(border=True, key="card_empty_find"):
            st.subheader("No scholarships match", anchor=False)
            st.markdown(f"This dataset has {total} scholarships, but none meet your search and every filter. "
                        "Clear them to see the full list again.")
            st.button("Clear filters", on_click=_clear_filters, key="clear_filters_empty", type="primary",
                      icon=":material/filter_alt_off:")
        return

    if st.session_state.get("f_table"):
        st.dataframe(pd.DataFrame(common.results_table(views, today)), hide_index=True)
        _table_and_download(svc, views, today)
        return

    page_views, page, pages = common.paginate(views, "f_page")
    if pages > 1:
        first = (page - 1) * common.PAGE_SIZE + 1
        st.caption(f"Showing {first} to {first + len(page_views) - 1} of {len(views)}")
    saved = set(svc.saved_ids())
    applications = {a.scholarship_id: a for a in svc.applications()}
    for view in page_views:
        with common.card("find", view):
            text, action = st.columns([4, 1], vertical_alignment="center")
            with text:
                common.card_summary(view)
                note = _progress_note(view.record.id, saved, applications)
                if note:
                    st.caption(note)
            with action:
                common.review_button(view, "find", back="find", width="stretch")
    common.pager("f_page", page, pages)
    _table_and_download(svc, views, today)
