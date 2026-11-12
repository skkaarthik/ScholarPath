"""Insights: simple descriptive charts with clearly stated scope.

Single-series horizontal bars in one hue with hover tooltips and a table view.
"""

from __future__ import annotations

from collections import Counter

import altair as alt
import pandas as pd
import streamlit as st

from .. import config
from ..models import FUNDING_CATEGORIES
from ..repository import SearchFilters
from . import common

BAR_COLOR = "#2a78d6"


def _bar(df: pd.DataFrame, category: str, title: str, sort: str | list = "-x") -> alt.Chart:
    return (
        alt.Chart(df, title=title)
        .mark_bar(color=BAR_COLOR, cornerRadiusEnd=4, height={"band": 0.75})
        .encode(
            x=alt.X("Scholarships:Q", title="Scholarships", axis=alt.Axis(tickMinStep=1, grid=True)),
            y=alt.Y(f"{category}:N", title=None, sort=sort, axis=alt.Axis(labelLimit=320)),
            tooltip=[alt.Tooltip(f"{category}:N"), alt.Tooltip("Scholarships:Q")],
        )
        .configure_axis(gridColor="#e6e5e1", domainColor="#c3c2b7", labelColor="#52514e", titleColor="#52514e")
        .configure_view(strokeWidth=0)
    )


def render(svc) -> None:
    st.title("Insights")
    if not common.dataset_ready(svc):
        return
    today = svc.today()
    use_filters = st.toggle("Apply my current Explore filters", key="ins_filters")
    filters = common.explore_filters() if use_filters else SearchFilters()
    views = common.cached_search(str(svc.db_path), today.isoformat(), common.filters_key(filters), "name")
    scope = "current Explore filters" if use_filters and not filters.is_empty() else "no filters (all records)"
    st.markdown(f"**Scope:** {len(views)} scholarships from the *{config.MODE_LABELS[svc.mode]}* dataset, "
                f"{scope}.")
    if not views:
        st.info("No scholarships in this scope.")
        return

    hosts = Counter(c for v in views for c in v.record.host_countries)
    host_df = pd.DataFrame(sorted(hosts.items()), columns=["Host country", "Scholarships"])
    st.altair_chart(_bar(host_df, "Host country", "Scholarships by host country"))
    st.caption("A scholarship hosted in several countries counts once in each, so bars can add up to more "
               "than the number of scholarships.")

    funding = Counter(FUNDING_CATEGORIES[v.record.funding_category] for v in views)
    fund_df = pd.DataFrame(sorted(funding.items()), columns=["Funding category", "Scholarships"])
    st.altair_chart(_bar(fund_df, "Funding category", "Scholarships by funding category"))

    dated = [v for v in views if v.record.deadline_kind == "dated"]
    months = Counter(v.record.deadline_date.strftime("%Y-%m") for v in dated)
    if months:
        month_df = pd.DataFrame(sorted(months.items()), columns=["Deadline month", "Scholarships"])
        st.altair_chart(_bar(month_df, "Deadline month", "Known deadlines by month",
                             sort=sorted(months)))
    undated = len(views) - len(dated)
    st.caption(f"Deadline chart includes only the {len(dated)} records with a known date (open or expired). "
               f"{undated} rolling or unknown deadlines are not plotted.")

    with st.expander("Table view of these charts"):
        st.dataframe(host_df, hide_index=True)
        st.dataframe(fund_df, hide_index=True)
        if months:
            st.dataframe(month_df, hide_index=True)
