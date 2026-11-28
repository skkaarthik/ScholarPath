"""Find (step 1): search first, filters behind one control, results below.

One template for both opportunity types. Choosing a result opens the Review page. The
search text, filters, sort order and page number are kept (common.keep_state), so Back
returns to the same list. Changing the search, a filter or the sort order always returns
to page 1. Scholarships and internships use their own widget keys ("f_*" and "i_*"), so
each keeps its own search when the student switches type.

Internships add one control scholarships do not need: the quick location choice
(Chennai, Bengaluru, All India, Remote), above the filters.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from .. import config
from ..dates import STATUS_LABELS
from ..exports import internships_to_csv, to_csv
from ..locations import QUICK_PLACES
from ..models import DEGREES, DISCIPLINES, FUNDING_CATEGORIES, STIPEND_KINDS, SUBJECTS, WORK_ARRANGEMENTS
from . import common

SORT_LABELS = {"deadline": "Deadline (soonest first)", "name": "Scholarship name (A to Z)",
               "provider": "Provider (A to Z)"}
I_SORT_LABELS = {"deadline": "Deadline (soonest first)", "stipend": "Stipend (highest first)",
                 "name": "Role (A to Z)", "provider": "Employer (A to Z)"}
# Closed opportunities never appear in Find (they stay reachable from Saved and Applications).
STATUS_OPTIONS = {key: STATUS_LABELS[key] for key in ("open", "rolling", "unknown")}
# Filters: session key -> (label in the summary line, value -> readable name).
ADVANCED = {
    "f_hosts": ("Country", {}), "f_degrees": ("Level", DEGREES), "f_subjects": ("Subject", SUBJECTS),
    "f_funding": ("Funding", FUNDING_CATEGORIES), "f_status": ("Deadline", STATUS_OPTIONS),
}
I_ADVANCED = {
    "i_cities": ("City", {}), "i_states": ("State", {}), "i_arr": ("Arrangement", WORK_ARRANGEMENTS),
    "i_disc": ("Discipline", DISCIPLINES), "i_stipend": ("Stipend", STIPEND_KINDS), "i_status": ("Deadline", STATUS_OPTIONS),
}


@dataclass(frozen=True)
class Spec:
    """What differs between the two types on this page; the layout is the same."""

    prefix: str                     # widget key prefix: "f" or "i"
    defaults: dict                  # common.FILTER_DEFAULTS or I_FILTER_DEFAULTS
    advanced: dict
    sorts: dict
    title: str
    noun: str
    search_label: str
    placeholder: str


SPECS = {
    config.KIND_SCHOLARSHIP: Spec("f", common.FILTER_DEFAULTS, ADVANCED, SORT_LABELS, "Find scholarships", "scholarship",
                                  "Search by scholarship or provider", "e.g. Commonwealth"),
    config.KIND_INTERNSHIP: Spec("i", common.I_FILTER_DEFAULTS, I_ADVANCED, I_SORT_LABELS, "Find internships",
                                 "internship", "Search by role or employer", "e.g. Data analyst"),
}


def _first_page(spec: Spec) -> None:
    st.session_state[f"{spec.prefix}_page"] = 1


def _clear_filters(spec: Spec) -> None:
    common.reset_widgets(spec.defaults)
    _first_page(spec)


def _active_filters(spec: Spec) -> list[str]:
    """Readable summary of what is narrowing the list, e.g. 'Country: Canada or Ireland'."""
    ss = st.session_state
    parts = []
    text_key = f"{spec.prefix}_text"
    if (ss.get(text_key) or "").strip():
        parts.append(f"Search: “{common.md_escape(ss[text_key].strip())}”")
    if spec.prefix == "i" and ss.get("i_place") not in (None, "", "all_india"):
        parts.append(f"Location: {QUICK_PLACES[ss['i_place']]}")
    for key, (label, names) in spec.advanced.items():
        chosen = ss.get(key) or []
        if chosen:
            parts.append(f"{label}: " + " or ".join(common.md_escape(names.get(v, v)) for v in chosen))
    return parts


def _scholarship_filters(spec: Spec, options: dict) -> None:
    c1, c2 = st.columns(2)
    c1.multiselect("Country", options["host_countries"], key="f_hosts", on_change=_first_page, args=(spec,),
                   placeholder="Any country")
    c2.multiselect("Level of study", list(DEGREES), format_func=DEGREES.get, key="f_degrees",
                   on_change=_first_page, args=(spec,), placeholder="Any level")
    c1.multiselect("Subject", list(SUBJECTS), format_func=SUBJECTS.get, key="f_subjects",
                   on_change=_first_page, args=(spec,), placeholder="Any subject")
    c2.multiselect("Funding", list(FUNDING_CATEGORIES), format_func=FUNDING_CATEGORIES.get, key="f_funding",
                   on_change=_first_page, args=(spec,), placeholder="Any funding")
    st.pills("Deadline", list(STATUS_OPTIONS), format_func=STATUS_OPTIONS.get, key="f_status",
             selection_mode="multi", on_change=_first_page, args=(spec,))
    st.caption("Several values in one filter match any of them; different filters must all match. "
               "A scholarship whose level or subject is not recorded never matches those filters.")


def _internship_filters(spec: Spec, options: dict) -> None:
    c1, c2 = st.columns(2)
    c1.multiselect("City", options["cities"], key="i_cities", on_change=_first_page, args=(spec,),
                   placeholder="Any city")
    c2.multiselect("State or union territory", options["states"], key="i_states", on_change=_first_page,
                   args=(spec,), placeholder="Any state")
    c1.multiselect("Discipline", list(DISCIPLINES), format_func=DISCIPLINES.get, key="i_disc",
                   on_change=_first_page, args=(spec,), placeholder="Any discipline")
    c2.multiselect("Stipend", list(STIPEND_KINDS), format_func=STIPEND_KINDS.get, key="i_stipend",
                   on_change=_first_page, args=(spec,), placeholder="Paid or unpaid")
    st.pills("Work arrangement", [k for k in WORK_ARRANGEMENTS if k != "unknown"], format_func=WORK_ARRANGEMENTS.get,
             key="i_arr", selection_mode="multi", on_change=_first_page, args=(spec,))
    st.pills("Deadline", list(STATUS_OPTIONS), format_func=STATUS_OPTIONS.get, key="i_status",
             selection_mode="multi", on_change=_first_page, args=(spec,))
    st.caption("Several values in one filter match any of them; different filters must all match. An internship "
               "whose discipline or work arrangement is not stated never matches those filters. Bangalore, "
               "Madras and other spellings are matched to one city name.")


def _search_and_filters(spec: Spec, options: dict) -> None:
    status_key = f"{spec.prefix}_status"
    # A "Closed" filter kept from an earlier version or visit is dropped: Find shows only open ones.
    if any(v not in STATUS_OPTIONS for v in st.session_state.get(status_key) or []):
        st.session_state[status_key] = [v for v in st.session_state[status_key] if v in STATUS_OPTIONS]
    st.text_input(spec.search_label, key=f"{spec.prefix}_text", on_change=_first_page, args=(spec,),
                  placeholder=spec.placeholder, icon=":material/search:")
    if spec.prefix == "i":
        if st.session_state.get("i_place") not in QUICK_PLACES:
            st.session_state["i_place"] = "all_india"
        st.segmented_control("Location", list(QUICK_PLACES), format_func=QUICK_PLACES.get, key="i_place",
                             on_change=_place_changed, args=(spec,), width="stretch")
    in_use = sum(1 for key in spec.advanced if st.session_state.get(key))
    label = "Filters" + (f" · {in_use} in use" if in_use else "")
    with st.expander(label, key="find_filters", icon=":material/tune:"):
        (_internship_filters if spec.prefix == "i" else _scholarship_filters)(spec, options)


def _place_changed(spec: Spec) -> None:
    """The quick location is a single choice that is never empty (clicking it again keeps it)."""
    if not st.session_state.get("i_place"):
        st.session_state["i_place"] = "all_india"
    _first_page(spec)


def _progress_note(rec_id: str, saved: set, applications: dict) -> str:
    """Tell a returning user what they already did with this record."""
    app = applications.get(rec_id)
    if app:
        return f":material/task_alt: In Applications: {common.tracker_status(app.status)}"
    return ":material/bookmark: Saved" if rec_id in saved else ""


def _table_and_download(svc, spec: Spec, views, today) -> None:
    with st.expander("Table view and CSV download", key="find_more", icon=":material/table:"):
        st.toggle("Show results as a table", key=f"{spec.prefix}_table")
        if spec.prefix == "i":
            data = internships_to_csv([v.record for v in views], today, svc.now())
            name = f"scholarpath_internships_{svc.mode}_{today.isoformat()}.csv"
        else:
            data = to_csv([v.record for v in views], today, svc.now())
            name = f"scholarpath_{svc.mode}_{today.isoformat()}.csv"
        st.download_button(
            f"Download {common.plural(len(views), 'result')} as CSV", data=data, file_name=name, mime="text/csv",
            key="find_csv", icon=":material/download:", on_click="ignore")
        st.caption("The file holds every result that matches the search and filters above (all pages), "
                   "with each record's source and deadline status.")


def _no_results(svc, spec: Spec) -> None:
    total = common.cached_overview(str(svc.db_path), common.time_key(svc), svc.kind)["active"]
    with st.container(border=True, key="card_empty_find"):
        st.subheader(f"No {spec.noun}s match", anchor=False)
        st.markdown(f"This dataset has {common.plural(total, 'open ' + spec.noun)}, but none meet your search and "
                    "every filter at once. Remove a filter above, or clear them all to see the full list.")
        st.button("Clear search and filters", on_click=_clear_filters, args=(spec,), key="clear_filters_empty",
                  type="primary", icon=":material/filter_alt_off:")


def render(svc) -> None:
    spec = SPECS[svc.kind]
    p = spec.prefix
    common.page_header(svc, spec.title)
    if not common.dataset_ready(svc):
        return
    today = svc.today()
    _search_and_filters(spec, common.cached_options(str(svc.db_path), svc.kind))

    sort = st.session_state.get(f"{p}_sort") or "deadline"
    if sort not in spec.sorts:
        sort = st.session_state[f"{p}_sort"] = "deadline"
    current = common.internship_filters() if p == "i" else common.find_filters()
    views = common.cached_search(str(svc.db_path), common.time_key(svc), common.filters_key(current), sort, svc.kind)
    active = _active_filters(spec)

    count, sort_box = st.columns([3, 2], vertical_alignment="bottom")
    count.header(common.plural(len(views), spec.noun), anchor=False)
    if views:
        sort_box.selectbox("Sort results by", list(spec.sorts), format_func=lambda k: f"Sort: {spec.sorts[k]}",
                           key=f"{p}_sort", on_change=_first_page, args=(spec,), label_visibility="collapsed")
    if active:
        with st.container(horizontal=True, vertical_alignment="center", key="find_active"):
            st.markdown("Filtered by " + " · ".join(active))
            if views:
                st.button("Clear search and filters", on_click=_clear_filters, args=(spec,), key="clear_filters",
                          type="tertiary", icon=":material/filter_alt_off:")
    common.flash()

    if not views:
        _no_results(svc, spec)
        return

    if st.session_state.get(f"{p}_table"):
        st.dataframe(pd.DataFrame(common.results_table(views, today)), hide_index=True)
        _table_and_download(svc, spec, views, today)
        return

    page_views, page, pages = common.paginate(views, f"{p}_page")
    if pages > 1:
        first = (page - 1) * common.PAGE_SIZE + 1
        st.caption(f"Showing {first} to {first + len(page_views) - 1} of {len(views)}")
    saved = set(svc.saved_ids())
    applications = {a.item_id: a for a in svc.applications()}
    for view in page_views:
        with common.card("find", view):
            text, action = st.columns([4, 1], vertical_alignment="center")
            with text:
                common.card_summary(view, _progress_note(view.record.id, saved, applications))
            with action:
                common.review_button(view, "find", back="find", width="stretch")
    common.pager(f"{p}_page", page, pages)
    _table_and_download(svc, spec, views, today)
