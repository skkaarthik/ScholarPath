"""ScholarPath Streamlit entry point: `streamlit run app.py`.

This file only sets up the page, the dataset-mode switch and navigation.
Each page lives in scholarpath/ui/ and talks to the database only through
ScholarPathService. No scraping happens here.
"""

from __future__ import annotations

import streamlit as st

from scholarpath import config
from scholarpath.ui import applications, common, details, explore, insights, overview, profile_match

st.set_page_config(page_title="ScholarPath", page_icon="🎓", layout="wide")

RENDERERS = {
    "Overview": overview.render,
    "Explore": explore.render,
    "Profile matching": profile_match.render,
    "Scholarship details": details.render,
    "My applications": applications.render,
    "Insights": insights.render,
}

with st.sidebar:
    st.markdown("## 🎓 ScholarPath")
    st.radio("Dataset", list(config.MODES), format_func=config.MODE_LABELS.get, key="mode",
             on_change=common.on_mode_change,
             help="Each dataset has its own database, saved items and tracker.")
    st.radio("Go to", common.PAGES, key="page")
    st.caption("Single-user local app. Nothing is submitted to any scholarship provider.")

svc = common.service()
common.mode_banner(svc)
RENDERERS[st.session_state.get("page", "Overview")](svc)
