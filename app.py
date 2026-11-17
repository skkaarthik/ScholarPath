"""ScholarPath Streamlit entry point: `streamlit run app.py`.

This file only sets up the page, Streamlit's built-in navigation and the
dataset switch. Each page lives in scholarpath/ui/ and talks to the database
only through ScholarPathService. No scraping happens here.
"""

from __future__ import annotations

import streamlit as st

from scholarpath import config
from scholarpath.ui import (applications, common, data_sources, find, insights, profile_match, review, saved,
                            style)

st.set_page_config(page_title="ScholarPath", page_icon=":material/school:", layout="wide")
style.inject()
common.keep_state()

# The app follows one sequence: Find -> Review -> Apply -> Track.
RENDERERS = {
    "find": find.render,                  # 1. search and results
    "review": review.render,              # 2. review a scholarship, 3. apply and confirm
    "saved": saved.render,                # optional shortlist; each row reopens Review
    "applications": applications.render,  # 4. track confirmed applications
    "fit": profile_match.render,
    "insights": insights.render,
    "data": data_sources.render,
}


def _page(slug: str) -> st.Page:
    title, icon = common.PAGE_INFO[slug]

    def show() -> None:
        common.run_page(RENDERERS[slug])

    return st.Page(show, title=title, icon=icon, url_path=slug, default=slug == "find",
                   visibility="hidden" if slug == "review" else "visible")


PAGES = {slug: _page(slug) for slug in RENDERERS}
# Three main menu items, then a quieter "More" group. Review is opened from a list, not the menu.
current = st.navigation({
    "": [PAGES[slug] for slug in common.MAIN_PAGES],
    "More": [PAGES[slug] for slug in common.MORE_PAGES] + [PAGES["review"]],
}, position="top")

# Buttons ask for another page through common.go_to(); the switch happens here.
target = st.session_state.pop("_goto", None)
if target in PAGES:
    st.switch_page(PAGES[target])

with st.sidebar:
    st.radio("Dataset", list(config.MODES), format_func=config.MODE_LABELS.get, key="mode",
             on_change=common.on_mode_change,
             help="Each dataset has its own database, saved list and tracker. Nothing is shared between them.")
    st.caption("Runs only on this computer. ScholarPath never submits anything to a scholarship provider.")

# On a phone Streamlit folds the top menu into the sidebar, so the three main sections are
# repeated as a row of links. style.py hides this row on wider screens, where the top menu shows.
with st.container(horizontal=True, key="mobile_nav"):
    for slug in common.MAIN_PAGES:
        st.page_link(PAGES[slug], label="Find" if slug == "find" else common.PAGE_INFO[slug][0])

current.run()
