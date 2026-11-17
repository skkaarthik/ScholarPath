"""Data & sources: which dataset is showing, where its records come from, when they
were read and what has not been checked. Technical details come last.

Every statement on this page is taken from the stored records (how each was
collected, when, whether a person checked it). Nothing here claims the data is
current, verified or live.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import pandas as pd
import streamlit as st

from .. import config
from . import common

EXPLAIN = {
    config.MODE_EXAMPLE: "Fifteen invented scholarships with deadlines generated around a fixed date, so every "
                         "part of the app can be tried safely. None of them exist.",
    config.MODE_REAL: "Records read from official scholarship pages by ScholarPath's collectors. Each record "
                      "keeps the page it came from and the time it was read.",
}
COMMANDS = {
    config.MODE_EXAMPLE: "python -m scholarpath init-examples",
    config.MODE_REAL: "python -m scholarpath collect --from-snapshots\npython -m scholarpath import-real",
}


def _read_day(rec):
    """The day a record's source page was read (falls back to when the record was created)."""
    try:
        return datetime.fromisoformat(rec.source_fetched_at or rec.collected_at).date()
    except ValueError:
        return None


def _day_range(days: list) -> str:
    """'12 Nov 2026', or '10 Nov 2026 to 12 Nov 2026' when the pages were read on different days."""
    days = sorted(d for d in days if d)
    if not days:
        return "Not recorded"
    first, last = common.fmt_date(days[0]), common.fmt_date(days[-1])
    return first if first == last else f"{first} to {last}"


def _dataset_card(svc) -> None:
    """Which dataset is showing, with a switch that also works on a phone (no sidebar needed)."""
    other = config.MODE_REAL if svc.mode == config.MODE_EXAMPLE else config.MODE_EXAMPLE
    with st.container(border=True, key="card_dataset"):
        st.subheader(f"Showing: {config.MODE_LABELS[svc.mode]}", anchor=False)
        st.markdown(EXPLAIN[svc.mode])
        st.button(f"Switch to {config.MODE_LABELS[other]}", key="data_switch", on_click=common.switch_mode,
                  args=(other,), icon=":material/swap_horiz:")
        st.caption("Each dataset has its own database, saved list and applications. Nothing is shared "
                   "between them, and switching never changes either one.")


def _sources(views) -> None:
    st.header("Sources", anchor=False)
    by_source = defaultdict(list)
    for view in views:
        by_source[view.record.source_name].append(view.record)
    st.dataframe(pd.DataFrame([{
        "Source": name,
        "Records": len(records),
        "Pages read on": _day_range([_read_day(r) for r in records]),
        "How it was collected": ", ".join(sorted({common.FETCH_LABELS.get(r.fetch_method, r.fetch_method)
                                                  for r in records})),
        "Checked by a person": f"{sum(1 for r in records if r.manual_verified_at)} of {len(records)}",
    } for name, records in sorted(by_source.items())]), hide_index=True)

    with st.expander(f"Every record and its source page ({len(views)})", key="data_records",
                     icon=":material/link:"):
        st.dataframe(
            pd.DataFrame([{
                "Scholarship": v.record.name,
                "Source page": v.record.source_url,
                "Page read on": common.fmt_date(_read_day(v.record)),
                "Checked by a person": "Yes" if v.record.manual_verified_at else "Not yet",
            } for v in views]),
            hide_index=True,
            column_config={"Source page": st.column_config.LinkColumn(
                "Source page", help="Opens the page this record was read from, in a new tab",
                display_text=r"https?://(?:www\.)?([^/]+)")},
        )
        if views and views[0].record.fetch_method == "fictional":
            st.caption("Example data: these addresses are placeholders on example.org, not real pages.")


def _trust(svc, info: dict) -> None:
    st.header("How far to trust it", anchor=False)
    checked, total = info["verified_count"], info["scholarships"]
    lines = [
        "**Read** is the day ScholarPath collected a page, not the day the provider published or updated it. "
        "A deadline that was correct then may have changed since.",
        (f"**Checked by a person: {checked} of {total}.** Collecting a page is not verification; a record "
         "counts as checked only after someone compares it with the official page."),
    ]
    if svc.mode == config.MODE_REAL:
        lines.append("These records were read from saved copies of the official pages. Downloading the pages "
                     "directly (live collection) exists as a command, but it has not been verified in this "
                     "project, so no record here should be treated as live.")
    else:
        lines.append("Example records are invented. Their deadlines are generated around "
                     f"{common.fmt_iso_date(info.get('example_anchor_date'))} so the list always has open, "
                     "closing and closed examples; real deadlines are never shifted.")
    if info["unavailable_count"]:
        lines.append(f"**{common.plural(info['unavailable_count'], 'source page')} could not be reached** at the "
                     "last collection. Their saved copies are kept and may be out of date.")
    st.markdown("\n".join(f"- {line}" for line in lines))


def _technical(svc, info: dict) -> None:
    with st.expander("Technical details and refreshing this dataset", key="data_technical",
                     icon=":material/terminal:"):
        run = info["last_import"] or {}
        st.markdown(
            f"- **Last import into this database:** {common.fmt_ts(run.get('finished_at'))}"
            f"{' (' + common.md_escape(run['status']) + ')' if run.get('status') else ''}\n"
            f"- **Records created between:** {common.fmt_ts(info['oldest_collected'])} and "
            f"{common.fmt_ts(info['newest_collected'])}\n"
            f"- **Source pages read between:** {common.fmt_ts(info['oldest_fetched'])} and "
            f"{common.fmt_ts(info['newest_fetched'])}"
        )
        st.markdown("Data changes only when you run these commands in Terminal, inside the ScholarPath folder. "
                    "Nothing is collected while you browse, and no automatic schedule is set up. "
                    "After running them, reload this page.")
        st.code(COMMANDS[svc.mode], language=None)
        st.caption(f"Database file: {svc.db_path}")


def render(svc) -> None:
    common.page_header(svc, "Data & sources",
                       "Where this information comes from, when it was read, and what has not been checked.")
    _dataset_card(svc)
    if not common.dataset_ready(svc):
        return
    info = common.cached_overview(str(svc.db_path), svc.today().isoformat())
    views = common.all_views(svc, "name")

    with st.container(horizontal=True, key="facts_data"):
        st.metric("Records", info["scholarships"], border=True)
        st.metric("Sources", len({v.record.source_name for v in views}), border=True)
        st.metric("Checked by hand", f"{info['verified_count']} of {info['scholarships']}", border=True,
                  help="Records a person has compared with the official page")
        st.metric("Pages unavailable", info["unavailable_count"], border=True)

    _sources(views)
    _trust(svc, info)
    _technical(svc, info)
