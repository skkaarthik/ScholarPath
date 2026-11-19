"""ScholarPath Streamlit entry point: `streamlit run app.py`.

This file only sets up the page, the menu and the dataset switch. Each page
lives in scholarpath/ui/ and talks to the database only through
ScholarPathService. No scraping happens here.
"""

from __future__ import annotations

import os

import streamlit as st

from scholarpath import advisor, config
from scholarpath.ui import (applications, chatbot, common, data_sources, find, insights, profile_match, review,
                            saved, style)

st.set_page_config(page_title="ScholarPath", page_icon=str(style.ASSETS / "icon.svg"), layout="wide")
style.inject()
common.keep_state()


@st.cache_resource
def _assistant_settings() -> bool:
    """Load the assistant's settings once per server process: Streamlit secrets when hosted,
    otherwise .env or .streamlit/secrets.toml. Without a key the assistant runs in demonstration mode."""
    try:
        for name in advisor.SETTING_NAMES:
            if name in st.secrets and not os.environ.get(name):
                os.environ[name] = str(st.secrets[name])
    except Exception:  # no secrets.toml, or an unreadable one
        pass
    advisor.load_local_settings()
    advisor.reset_limiter()
    return True


_assistant_settings()

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

    return st.Page(show, title=title, icon=icon, url_path=slug, default=slug == "find")


def _menu_link(slug: str, active: bool, width: str = "content") -> None:
    """One menu entry. The container key ends in "_current" for the highlighted entry,
    which is what style.py uses to draw the lavender pill (st.page_link has no key of its own)."""
    title, icon = common.PAGE_INFO[slug]
    with st.container(key=f"nav_{slug}" + ("_current" if active else ""), width=width):
        st.page_link(PAGES[slug], label=title, icon=icon, width=width)


def _menu(page: str) -> None:
    """Find Scholarships, Saved, Applications and a More menu. One menu for every screen
    size: a row above the page on wide screens, a bar along the bottom on phones (style.py)."""
    active = common.menu_item(page, st.session_state.get("review_back"))
    with st.container(horizontal=True, key="app_nav", gap="small", vertical_alignment="center"):
        for slug in common.MAIN_PAGES:
            _menu_link(slug, active == slug)
        with st.container(key="nav_more" + ("_current" if active == common.MORE else ""), width="content"):
            # The key includes the open page, so after a page is chosen Streamlit draws a new,
            # closed menu. (A menu left open would swallow the next click on the page.)
            with st.popover("More", icon=":material/more_horiz:", type="tertiary", key=f"nav_more_menu_{page}"):
                for slug in common.MORE_PAGES:
                    _menu_link(slug, page == slug, width="stretch")   # full-width rows inside the menu


PAGES = {slug: _page(slug) for slug in RENDERERS}
# Streamlit only does the routing (position="hidden"); _menu() draws the menu itself.
current = st.navigation(list(PAGES.values()), position="hidden")

# Buttons ask for another page through common.go_to(); the switch happens here.
target = st.session_state.pop("_goto", None)
if target in PAGES:
    st.switch_page(PAGES[target])

page = current.url_path or "find"   # the default page has an empty url_path
common.enter_page(page)

with st.sidebar:
    st.radio("Dataset", list(config.MODES), format_func=config.MODE_LABELS.get, key="mode",
             on_change=common.on_mode_change,
             help="Each dataset has its own database, saved list and tracker. Nothing is shared between them.")
    st.caption("Runs only on this computer. ScholarPath never submits anything to a scholarship provider.")

_menu(page)
chatbot.entry(page)       # "Ask ScholarPath": the assistant panel, available on every page
current.run()
