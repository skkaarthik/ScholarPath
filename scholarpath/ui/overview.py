"""Overview page: purpose, dataset mode, database-backed counts, upcoming saved deadlines, freshness."""

from __future__ import annotations

import streamlit as st

from .. import config
from ..dates import GROUPS
from ..repository import SearchFilters
from . import common


def _fmt(ts: str | None) -> str:
    return ts.replace("T", " ").replace("+00:00", " UTC") if ts else "-"


def render(svc) -> None:
    st.title("ScholarPath")
    st.write(
        "Find international scholarships, understand their recorded requirements, save the ones you like "
        "and track your own application preparation and deadlines. Single-user and local: your data stays "
        "in a SQLite file on this computer."
    )
    st.markdown(f"**Dataset in use:** {config.MODE_LABELS[svc.mode]}")
    if not common.dataset_ready(svc):
        return
    today = svc.today()
    info = common.cached_overview(str(svc.db_path), today.isoformat())
    views = common.cached_search(str(svc.db_path), today.isoformat(), common.filters_key(SearchFilters()), "deadline")
    open_count = sum(1 for v in views if v.status == "open")

    cols = st.columns(4)
    cols[0].metric("Scholarships in dataset", info["scholarships"])
    cols[1].metric("Open dated deadlines", open_count)
    cols[2].metric("Saved", info["saved"])
    cols[3].metric("Tracked applications", info["tracked"])

    st.subheader("Upcoming deadlines for saved and tracked scholarships")
    groups = svc.dashboard()
    upcoming = [v for key in ("due_7", "due_30", "later") for v in groups.get(key, [])]
    if not upcoming:
        st.caption("Nothing saved with an upcoming dated deadline yet. Use **Explore** to save scholarships.")
    for view in upcoming[:5]:
        st.markdown(f"- **{common.md_escape(view.record.name)}** - {common.deadline_text(view, today)} "
                    f"({GROUPS[view.group]})")
        st.button("Open details", key=f"ov_open_{view.record.id}", on_click=common.go_to,
                  args=("Scholarship details", view.record.id))

    st.subheader("Data freshness")
    st.markdown(
        f"- Records collected: {_fmt(info['oldest_collected'])} to {_fmt(info['newest_collected'])}\n"
        f"- Latest source fetch: {_fmt(info['newest_fetched'])}\n"
        f"- Manually verified records: {info['verified_count']} of {info['scholarships']}\n"
        f"- Records whose source page was reported unavailable: {info['unavailable_count']}\n"
        f"- Last successful import: {_fmt((info['last_import'] or {}).get('finished_at'))}"
    )
    if info.get("example_anchor_date"):
        st.caption(f"Example deadlines were generated relative to {info['example_anchor_date']} "
                   "(fictional data only; real deadlines are never shifted).")
    st.caption(f"Dates are evaluated for today = {today.isoformat()} in {config.APP_TIMEZONE_NAME}.")
