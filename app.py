"""ScholarPath Streamlit entry point: `streamlit run app.py`.

This file only sets up the page, the dataset-mode switch and navigation.
Each page lives in scholarpath/ui/ and talks to the database only through
ScholarPathService. No scraping happens here.
"""

from __future__ import annotations

import streamlit as st

from scholarpath import config
from scholarpath.ui import applications, common, details, explore, insights, overview, profile_match, style

st.set_page_config(page_title="ScholarPath", page_icon="🎓", layout="wide")
style.inject()

RENDERERS = {
    "Overview": overview.render,
    "Explore": explore.render,
    "Profile matching": profile_match.render,
    "Scholarship details": details.render,
    "My applications": applications.render,
    "Insights": insights.render,
}

with st.sidebar:
    style.brand()
    st.radio("Menu", common.PAGES, key="page", format_func=common.page_label, label_visibility="collapsed")
    st.divider()
    st.radio("Dataset", list(config.MODES), format_func=config.MODE_LABELS.get, key="mode",
             on_change=common.on_mode_change,
             help="Each dataset has its own database, saved list and tracker.")
    st.caption("Runs only on this computer. ScholarPath never submits anything to a scholarship provider.")

svc = common.service()
common.mode_banner(svc)
RENDERERS[st.session_state.get("page", "Overview")](svc)
