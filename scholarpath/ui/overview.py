"""Overview page: purpose, dataset mode, database-backed counts, deadlines, freshness."""

from __future__ import annotations

import streamlit as st

from .. import config
from ..repository import SearchFilters
from . import common


def _fmt(ts: str | None) -> str:
    return ts.replace("T", " ").replace("+00:00", " UTC") if ts else "-"


def _hero(today) -> None:
    with st.container(key="hero"):
        st.markdown(f'<span class="sp-today">Today is {today.strftime("%A, %d %B %Y").replace(" 0", " ")}</span>',
                    unsafe_allow_html=True)
        st.title("Your path to studying abroad, one deadline at a time", anchor=False)
        st.markdown('<p class="sp-hero-sub">Find scholarships, see what each one asks for, save the ones that fit '
                    'and keep every deadline in view. Everything stays on this computer.</p>',
                    unsafe_allow_html=True)
        a, b, c, _ = st.columns([1.15, 1.05, 1.1, 1.4])
        a.button("Find scholarships", key="hero_explore", on_click=common.go_to, args=("Explore",),
                 type="primary", icon=":material/travel_explore:", width="stretch")
        b.button("Check my fit", key="hero_match", on_click=common.go_to, args=("Profile matching",),
                 icon=":material/fact_check:", width="stretch")
        c.button("My applications", key="hero_apps", on_click=common.go_to, args=("My applications",),
                 icon=":material/assignment:", width="stretch")


def _deadline_cards(views, today, prefix: str) -> None:
    columns = st.columns(3, gap="medium")
    for index, view in enumerate(views):
        with columns[index % 3], common.card(prefix, view):
            common.card_header(view, today)
            st.button("Open details", key=f"{prefix}_open_{view.record.id}", on_click=common.go_to,
                      args=("Scholarship details", view.record.id), icon=":material/visibility:", width="stretch")


def render(svc) -> None:
    today = svc.today()
    _hero(today)
    if not common.dataset_ready(svc):
        return
    info = common.cached_overview(str(svc.db_path), today.isoformat())
    views = common.cached_search(str(svc.db_path), today.isoformat(), common.filters_key(SearchFilters()), "deadline")
    open_views = [v for v in views if v.status == "open"]

    cols = st.columns(4)
    cols[0].metric("Scholarships", info["scholarships"], help="Records in the dataset you selected in the sidebar.")
    cols[1].metric("Still open", len(open_views), help="Published deadline is today or later.")
    cols[2].metric("Saved by you", info["saved"])
    cols[3].metric("Being tracked", info["tracked"])

    groups = svc.dashboard()
    upcoming = [v for key in ("due_7", "due_30", "later") for v in groups.get(key, [])]
    st.subheader("Your next deadlines")
    if upcoming:
        _deadline_cards(upcoming[:6], today, "ov")
    else:
        with st.container(border=True, key="ov_empty"):
            st.markdown("**Nothing saved yet.** Save a scholarship in Explore and its deadline shows up here, "
                        "counted down for you.")

    if open_views:
        st.subheader("Closing soon in this dataset")
        _deadline_cards(open_views[:3], today, "soon")

    with st.expander("About this data", icon=":material/history:"):
        st.markdown(
            f"- Dataset: **{config.MODE_LABELS[svc.mode]}**\n"
            f"- Records collected: {_fmt(info['oldest_collected'])} to {_fmt(info['newest_collected'])}\n"
            f"- Latest source fetch: {_fmt(info['newest_fetched'])}\n"
            f"- Checked by a person against the official page: {info['verified_count']} of {info['scholarships']}\n"
            f"- Source pages reported unavailable: {info['unavailable_count']}\n"
            f"- Last successful import: {_fmt((info['last_import'] or {}).get('finished_at'))}"
        )
        if info.get("example_anchor_date"):
            st.caption(f"Example deadlines were generated relative to {info['example_anchor_date']} "
                       "(fictional data only; real deadlines are never shifted).")
        st.caption(f"Dates are counted for today, {today.isoformat()}, in {config.APP_TIMEZONE_NAME}.")
