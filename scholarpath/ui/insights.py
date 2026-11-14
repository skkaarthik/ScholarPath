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

BAR_COLOR = "#343A8C"  # theme primary (ink indigo); single series, so no legend


def _bar(df: pd.DataFrame, category: str, sort: str | list = "-x") -> alt.Chart:
    hover = alt.selection_point(on="pointerover", clear="pointerout", fields=[category], empty=False)
    return (
        alt.Chart(df)
        .mark_bar(color=BAR_COLOR, cornerRadiusEnd=4, height={"band": 0.72}, cursor="pointer")
        .encode(
            x=alt.X("Scholarships:Q", title="Scholarships", axis=alt.Axis(tickMinStep=1, grid=True)),
            y=alt.Y(f"{category}:N", title=None, sort=sort, axis=alt.Axis(labelLimit=320)),
            opacity=alt.condition(hover, alt.value(1.0), alt.value(0.9)),
            tooltip=[alt.Tooltip(f"{category}:N"), alt.Tooltip("Scholarships:Q")],
        )
        .add_params(hover)
        .properties(height=alt.Step(30))
        .configure_axis(gridColor="#E4E1D8", domainColor="#A8A397", labelColor="#3D3B47", titleColor="#3D3B47",
                        labelFontSize=13, titleFontSize=13)
        .configure_view(strokeWidth=0)
        .configure(background="#FFFFFF")
    )


def _chart_card(title: str, df: pd.DataFrame, category: str, note: str, sort: str | list = "-x") -> None:
    with st.container(border=True, key=f"card_chart_{category.lower().replace(' ', '_')}"):
        st.header(title, anchor=False)
        st.altair_chart(_bar(df, category, sort))
        st.caption(note)


def render(svc) -> None:
    common.page_header(svc, "Insights", "A simple picture of what is in this dataset. Counts only, no predictions.")
    if not common.dataset_ready(svc):
        return
    today = svc.today()
    use_filters = st.toggle("Only count scholarships that match my Discover filters", key="ins_filters")
    filters = common.discover_filters() if use_filters else SearchFilters()
    views = common.cached_search(str(svc.db_path), today.isoformat(), common.filters_key(filters), "name")
    scope = "your current Discover filters" if use_filters and not filters.is_empty() else "no filters, so every record"
    st.markdown(f"Showing **{len(views)} scholarships** from the *{config.MODE_LABELS[svc.mode]}* dataset, "
                f"with {scope}.")
    if not views:
        common.empty_state("insights", "No scholarships match your Discover filters",
                           "Turn the switch above off to chart the whole dataset, or change the filters.",
                           "Change filters in Discover", "discover", icon=":material/tune:")
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

    with st.expander("The same numbers as tables", icon=":material/table_rows:"):
        for column, frame in zip(st.columns(3), [host_df, fund_df, month_df if months else None]):
            if frame is not None:
                column.dataframe(frame, hide_index=True)
