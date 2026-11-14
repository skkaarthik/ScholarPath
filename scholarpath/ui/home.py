"""Home: what needs attention today, and the shortest way into each task."""

from __future__ import annotations

import streamlit as st

from .. import config
from . import common

STEPS = [
    ("discover", "1. Discover", "Search and filter scholarships, and see who offers them, what they fund "
     "and when they close.", "Find scholarships", ":material/search:"),
    ("fit", "2. Check your fit", "Compare your citizenship, degree, subject and score with the recorded "
     "requirements. Unknowns are never counted as a match.", "Check my fit", ":material/fact_check:"),
    ("applications", "3. Save and track", "Keep a shortlist, see deadlines grouped by urgency and record "
     "your own progress.", "Open my list", ":material/bookmarks:"),
]


def _rows(views, today, prefix: str) -> None:
    for view in views:
        with common.card(prefix, view):
            text, action = st.columns([4, 1.2], vertical_alignment="center")
            with text:
                common.card_summary(view, today, compact=True)
            with action:
                common.details_button(view, prefix, back="home", width="stretch")


def render(svc) -> None:
    today = svc.today()
    common.page_header(svc, "Home", f"Today is {today.strftime('%A')}, {common.fmt_date(today)}. "
                       "Find scholarships, see what each one asks for, and keep every deadline in view.")
    if not common.dataset_ready(svc):
        return
    common.flash()
    info = common.cached_overview(str(svc.db_path), today.isoformat())
    views = common.all_views(svc)
    open_views = [v for v in views if v.status == "open"]

    with st.container(horizontal=True, key="home_metrics"):
        st.metric("Scholarships in this dataset", info["scholarships"], border=True)
        st.metric("Open now", len(open_views), border=True, help="Published deadline is today or later.")
        st.metric("Saved by you", info["saved"], border=True)
        st.metric("Applications tracked", info["tracked"], border=True)

    groups = svc.dashboard()
    upcoming = [v for key in ("due_7", "due_30", "later") for v in groups.get(key, [])]
    st.header("Your next deadlines", anchor=False)
    if upcoming:
        _rows(upcoming[:5], today, "home")
        if len(upcoming) > 5:
            st.button(f"See all {len(upcoming)} in Saved & applications", key="home_all", on_click=common.go_to,
                      args=("applications",), icon=":material/arrow_forward:")
    else:
        common.empty_state("home", "Nothing saved yet",
                           "Save a scholarship in Discover and its deadline appears here, counted down for you.",
                           "Find scholarships", "discover", icon=":material/search:")

    st.header("How ScholarPath works", anchor=False)
    for column, (slug, title, body, label, icon) in zip(st.columns(3, gap="medium"), STEPS):
        with column, st.container(border=True, key=f"card_step_{slug}", height="stretch"):
            st.subheader(title, anchor=False)
            st.markdown(body)
            st.button(label, key=f"step_{slug}", on_click=common.go_to, args=(slug,), icon=icon,
                      type="primary" if slug == "discover" and not upcoming else "secondary")

    if open_views:
        st.header("Closing soon in this dataset", anchor=False)
        _rows(open_views[:3], today, "soon")

    st.caption(f"Days are counted for {today.isoformat()} in {config.APP_TIMEZONE_NAME}. "
               "See Data & sources for where this information comes from and how fresh it is.")
