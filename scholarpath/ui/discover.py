"""Discover: search, combined filters, paged result cards, save/details actions, filtered CSV export."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..exports import to_csv
from ..models import DEGREES, FUNDING_CATEGORIES, SUBJECTS
from . import common

SORT_LABELS = {"deadline": "Deadline (soonest first)", "name": "Scholarship name", "provider": "Provider"}
STATUS_OPTIONS = {"open": "Open", "rolling": "Rolling", "unknown": "Not published", "expired": "Closed"}


def _first_page() -> None:
    st.session_state["f_page"] = 1


def _clear_filters() -> None:
    for key in common.FILTER_KEYS:
        st.session_state.pop(key, None)
    _first_page()


def _active_filters(options_labels: dict) -> list[str]:
    """Readable summary of what is narrowing the list, e.g. 'Country: Canada or Ireland'."""
    ss = st.session_state
    parts = []
    if (ss.get("f_text") or "").strip():
        parts.append(f"Search: “{common.md_escape(ss['f_text'].strip())}”")
    for key, (label, names) in options_labels.items():
        chosen = ss.get(key) or []
        if chosen:
            parts.append(f"{label}: " + " or ".join(common.md_escape(names.get(v, v)) for v in chosen))
    return parts


def _filters(options: dict) -> None:
    with st.container(border=True, key="card_filters"):
        search, sort = st.columns([3, 1.2])
        search.text_input("Search by scholarship or provider name", key="f_text", on_change=_first_page,
                          placeholder="e.g. Commonwealth", icon=":material/search:")
        sort.selectbox("Sort by", list(SORT_LABELS), format_func=SORT_LABELS.get, key="f_sort",
                       on_change=_first_page)
        c1, c2, c3, c4 = st.columns(4)
        c1.multiselect("Country", options["host_countries"], key="f_hosts", on_change=_first_page,
                       placeholder="Any country")
        c2.multiselect("Level of study", list(DEGREES), format_func=DEGREES.get, key="f_degrees",
                       on_change=_first_page, placeholder="Any level")
        c3.multiselect("Subject", list(SUBJECTS), format_func=SUBJECTS.get, key="f_subjects",
                       on_change=_first_page, placeholder="Any subject")
        c4.multiselect("Funding", list(FUNDING_CATEGORIES), format_func=FUNDING_CATEGORIES.get, key="f_funding",
                       on_change=_first_page, placeholder="Any funding")
        st.pills("Deadline", list(STATUS_OPTIONS), format_func=STATUS_OPTIONS.get, key="f_status",
                 selection_mode="multi", on_change=_first_page,
                 help="Choose one or more. With none chosen, every deadline status is shown.")
        with st.expander("How filters combine", icon=":material/help:"):
            st.markdown("- Several values in one filter match **any** of them.\n"
                        "- Different filters must **all** match.\n"
                        "- A scholarship whose level or subject is unknown never matches those filters. "
                        "One that is explicitly open to any subject does.")


def render(svc) -> None:
    common.page_header(svc, "Discover scholarships")
    if not common.dataset_ready(svc):
        return
    today = svc.today()
    options = common.cached_options(str(svc.db_path))
    _filters(options)

    filters = common.discover_filters()
    sort = st.session_state.get("f_sort") or "deadline"
    views = common.cached_search(str(svc.db_path), today.isoformat(), common.filters_key(filters), sort)
    active = _active_filters({
        "f_hosts": ("Country", {}), "f_degrees": ("Level", DEGREES), "f_subjects": ("Subject", SUBJECTS),
        "f_funding": ("Funding", FUNDING_CATEGORIES), "f_status": ("Deadline", STATUS_OPTIONS),
    })

    st.header(common.plural(len(views), "result"), anchor=False)
    if active:
        st.markdown("Filtered by " + " · ".join(active))
    with st.container(horizontal=True, vertical_alignment="center", key="result_tools"):
        if active:
            st.button("Clear all filters", on_click=_clear_filters, key="clear_filters",
                      icon=":material/filter_alt_off:")
        if views:
            st.download_button(
                "Download these results (CSV)", data=to_csv([v.record for v in views], today),
                file_name=f"scholarpath_{svc.mode}_{today.isoformat()}.csv", mime="text/csv", key="discover_csv",
                icon=":material/download:",
                help="Exactly the filtered results, all pages, with source and deadline status.")
            st.toggle("Show as a table", key="f_table")
    common.flash()

    if not views:
        common_total = common.cached_overview(str(svc.db_path), today.isoformat())["scholarships"]
        with st.container(border=True, key="card_empty_discover"):
            st.subheader("No scholarships match these filters", anchor=False)
            st.markdown(f"The dataset has {common_total} scholarships, but none meet every filter above. "
                        "Remove one filter at a time, or start again.")
            st.button("Clear all filters", on_click=_clear_filters, key="clear_filters_empty", type="primary",
                      icon=":material/filter_alt_off:")
        return

    if st.session_state.get("f_table"):
        st.dataframe(pd.DataFrame(common.results_table(views, today)), hide_index=True)
        st.caption("Switch the table off to save scholarships or open their details.")
        return

    page_views, page, pages = common.paginate(views, "f_page")
    if pages > 1:
        first = (page - 1) * common.PAGE_SIZE + 1
        st.caption(f"Showing {first} to {first + len(page_views) - 1} of {len(views)}")
    saved = set(svc.saved_ids())
    for view in page_views:
        rec = view.record
        with common.card("ex", view):
            text, actions = st.columns([4, 1.3], vertical_alignment="center")
            with text:
                common.card_summary(view, today)
            with actions:
                common.details_button(view, "ex", back="discover", width="stretch")
                if rec.id in saved:
                    st.button("Saved · remove", key=f"ex_unsave_{rec.id}", on_click=common.unsave,
                              args=(svc, rec.id), icon=":material/bookmark_added:", width="stretch",
                              help="This is in your saved list. Choose to remove it.")
                else:
                    st.button("Save", key=f"ex_save_{rec.id}", on_click=common.save, args=(svc, rec.id, rec.name),
                              type="primary", icon=":material/bookmark_add:", width="stretch")
    common.pager("f_page", page, pages)
