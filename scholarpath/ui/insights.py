"""Insights: simple descriptive charts with clearly stated scope.

Counts only: nothing is predicted or estimated. The three counting functions
below are pure (no Streamlit), so tests can compare them with the stored data.
Single-series horizontal bars in one hue with the number written on each bar;
every chart also has a table view.
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


def count_by_country(views) -> Counter:
    """Scholarships per host country. One hosted in two countries counts once in each."""
    return Counter(country for v in views for country in v.record.host_countries)


def count_by_funding(views) -> Counter:
    """Scholarships per funding category. Each scholarship counts once."""
    return Counter(FUNDING_CATEGORIES[v.record.funding_category] for v in views)


def count_by_month(views) -> list[tuple[str, int]]:
    """(month label, count) in calendar order, for scholarships with a published date only."""
    months = Counter(v.record.deadline_date.replace(day=1) for v in views if v.record.deadline_kind == "dated")
    return [(month.strftime("%b %Y"), count) for month, count in sorted(months.items())]


def _frame(pairs, category: str) -> pd.DataFrame:
    return pd.DataFrame(list(pairs), columns=[category, "Scholarships"])


def _bar(df: pd.DataFrame, category: str, sort: str | list = "-x") -> alt.LayerChart:
    base = alt.Chart(df).encode(
        x=alt.X("Scholarships:Q", title="Scholarships", axis=alt.Axis(tickMinStep=1, grid=True, format="d")),
        y=alt.Y(f"{category}:N", title=None, sort=sort, axis=alt.Axis(labelLimit=170)),
        tooltip=[alt.Tooltip(f"{category}:N"), alt.Tooltip("Scholarships:Q")],
    )
    bars = base.mark_bar(color=BAR_COLOR, cornerRadiusEnd=4, height={"band": 0.72})
    numbers = base.mark_text(align="left", dx=5, color="#121118", fontSize=13).encode(text="Scholarships:Q")
    return (
        alt.layer(bars, numbers)
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
    use_filters = st.toggle("Only count scholarships that match my Find Scholarships filters", key="ins_filters")
    filters = common.find_filters() if use_filters else SearchFilters()
    views = common.cached_search(str(svc.db_path), common.time_key(svc), common.filters_key(filters), "name")
    if use_filters and filters.is_empty():
        scope = "no filters set on Find Scholarships, so every open record"
    elif use_filters:
        scope = "your current Find Scholarships filters"
    else:
        scope = "no filters, so every open record (closed ones are left out)"
    st.markdown(f"Counting **{common.plural(len(views), 'scholarship')}** from the "
                f"*{config.MODE_LABELS[svc.mode]}* dataset, with {scope}.")
    if not views:
        common.empty_state("insights", "No scholarships match your Find Scholarships filters",
                           "Turn the switch above off to chart the whole dataset, or change the filters.",
                           "Change filters", "find", icon=":material/tune:")
        return

    host_df = _frame(sorted(count_by_country(views).items()), "Host country")
    fund_df = _frame(sorted(count_by_funding(views).items()), "Funding category")
    months = count_by_month(views)
    month_df = _frame(months, "Deadline month")
    dated = sum(count for _, count in months)

    left, right = st.columns(2, gap="medium")
    with left:
        _chart_card("Where you can study", host_df, "Host country",
                    "A scholarship hosted in several countries counts once in each, so bars can add up to "
                    "more than the number of scholarships.")
    with right:
        _chart_card("How much is funded", fund_df, "Funding category", "Each scholarship counts once.")
    if months:
        _chart_card("When deadlines fall", month_df, "Deadline month",
                    f"Only the {common.plural(dated, 'scholarship')} with a published closing date "
                    f"(open or closed). {len(views) - dated} with a rolling or unconfirmed deadline are left out.",
                    sort=[label for label, _ in months])

    with st.expander("The same numbers as tables", key="ins_tables", icon=":material/table_rows:"):
        for column, frame in zip(st.columns(3), [host_df, fund_df, month_df if months else None]):
            if frame is not None:
                column.dataframe(frame, hide_index=True)
