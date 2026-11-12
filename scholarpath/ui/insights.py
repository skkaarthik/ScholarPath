"""Insights: simple descriptive charts with clearly stated scope.

Single-series horizontal bars in one hue; hovering a bar highlights it and
shows a tooltip. Every chart has a table view.
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

BAR_COLOR = "#0E7C7B"  # brand teal; single series, so no legend


def _bar(df: pd.DataFrame, category: str, sort: str | list = "-x") -> alt.Chart:
    hover = alt.selection_point(on="pointerover", clear="pointerout", fields=[category], empty=False)
    return (
        alt.Chart(df)
        .mark_bar(color=BAR_COLOR, cornerRadiusEnd=4, height={"band": 0.72}, cursor="pointer")
        .encode(
            x=alt.X("Scholarships:Q", title="Scholarships", axis=alt.Axis(tickMinStep=1, grid=True)),
            y=alt.Y(f"{category}:N", title=None, sort=sort, axis=alt.Axis(labelLimit=320)),
            opacity=alt.condition(hover, alt.value(1.0), alt.value(0.78)),
            tooltip=[alt.Tooltip(f"{category}:N"), alt.Tooltip("Scholarships:Q")],
        )
        .add_params(hover)
        .properties(height=alt.Step(30))
        .configure_axis(gridColor="#E6EAF1", domainColor="#C9D1DE", labelColor="#4A5468", titleColor="#4A5468",
                        labelFontSize=12, titleFontSize=12)
        .configure_view(strokeWidth=0)
    )


def _chart_card(title: str, df: pd.DataFrame, category: str, note: str, sort: str | list = "-x") -> None:
    with st.container(border=True):
        st.markdown(f"#### {title}")
        st.altair_chart(_bar(df, category, sort))
        st.caption(note)


def render(svc) -> None:
    st.title("Insights", anchor=False)
    if not common.dataset_ready(svc):
        return
    today = svc.today()
    use_filters = st.toggle("Use my Explore filters", key="ins_filters")
    filters = common.explore_filters() if use_filters else SearchFilters()
    views = common.cached_search(str(svc.db_path), today.isoformat(), common.filters_key(filters), "name")
    scope = "your current Explore filters" if use_filters and not filters.is_empty() else "no filters, so every record"
    st.markdown(f"Showing **{len(views)} scholarships** from the *{config.MODE_LABELS[svc.mode]}* dataset, "
                f"with {scope}.")
    if not views:
        st.info("No scholarships match these filters. Turn the filter switch off to see everything.")
        return

    hosts = Counter(c for v in views for c in v.record.host_countries)
    host_df = pd.DataFrame(sorted(hosts.items()), columns=["Host country", "Scholarships"])
    funding = Counter(FUNDING_CATEGORIES[v.record.funding_category] for v in views)
    fund_df = pd.DataFrame(sorted(funding.items()), columns=["Funding category", "Scholarships"])
    dated = [v for v in views if v.record.deadline_kind == "dated"]
    months = Counter(v.record.deadline_date.strftime("%Y-%m") for v in dated)
    month_df = pd.DataFrame(sorted(months.items()), columns=["Deadline month", "Scholarships"])

    left, right = st.columns(2, gap="medium")
    with left:
        _chart_card("Where you can study", host_df, "Host country",
                    "A scholarship hosted in several countries counts once in each, so bars can add up to "
                    "more than the number of scholarships.")
    with right:
        _chart_card("How much is funded", fund_df, "Funding category", "Each scholarship counts once.")
    if months:
        _chart_card("When deadlines fall", month_df, "Deadline month",
                    f"Only the {len(dated)} scholarships with a published date are shown (open or closed). "
                    f"{len(views) - len(dated)} rolling or unpublished deadlines are left out.",
                    sort=sorted(months))

    with st.expander("Table view of these charts", icon=":material/table_rows:"):
        st.dataframe(host_df, hide_index=True)
        st.dataframe(fund_df, hide_index=True)
        if months:
            st.dataframe(month_df, hide_index=True)
