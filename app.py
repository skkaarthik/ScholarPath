"""ScholarPath Streamlit entry point: `streamlit run app.py`.

This file only sets up the page, Streamlit's built-in navigation and the
dataset switch. Each page lives in scholarpath/ui/ and talks to the database
only through ScholarPathService. No scraping happens here.
"""

from __future__ import annotations

import streamlit as st

from scholarpath import config
from scholarpath.ui import (applications, common, data_sources, details, discover, home, insights,
                            profile_match, style)

st.set_page_config(page_title="ScholarPath", page_icon=":material/school:", layout="wide")
style.inject()
common.keep_state()

RENDERERS = {
    "home": home.render,
    "discover": discover.render,
    "fit": profile_match.render,
    "applications": applications.render,
    "insights": insights.render,
    "data": data_sources.render,
    "details": details.render,
}


def _page(slug: str) -> st.Page:
    title, icon = common.PAGE_INFO[slug]

    def show() -> None:
        common.run_page(RENDERERS[slug])

    return st.Page(show, title=title, icon=icon, url_path=slug, default=slug == "home",
                   visibility="hidden" if slug == "details" else "visible")


PAGES = {slug: _page(slug) for slug in RENDERERS}
current = st.navigation(list(PAGES.values()))

# Buttons ask for another page through common.go_to(); the switch happens here.
target = st.session_state.pop("_goto", None)
if target in PAGES:
    st.switch_page(PAGES[target])

with st.sidebar:
    st.radio("Dataset", list(config.MODES), format_func=config.MODE_LABELS.get, key="mode",
             on_change=common.on_mode_change,
             help="Each dataset has its own database, saved list and tracker. Nothing is shared between them.")
    st.caption("Runs only on this computer. ScholarPath never submits anything to a scholarship provider.")

current.run()
