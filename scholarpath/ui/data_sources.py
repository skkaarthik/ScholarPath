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

from .. import config, refresh
from ..collectors import runner
from . import common

EXPLAIN = {
    config.MODE_EXAMPLE: "Fifteen invented scholarships with deadlines generated around a fixed date, so every "
                         "part of the app can be tried safely. None of them exist.",
    config.MODE_REAL: "Records read from official scholarship pages by ScholarPath's collectors. Each record "
                      "keeps the page it came from and the time it was read.",
}
COMMANDS = {
    config.MODE_EXAMPLE: "python -m scholarpath init-examples",
    config.MODE_REAL: "python -m scholarpath refresh --force   # collect live, validate, publish\n"
                      "python -m scholarpath refresh --dry-run # check the sources without writing anything",
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
        st.markdown((I_EXPLAIN if common.is_internship(svc) else EXPLAIN)[svc.mode])
        st.button(f"Switch to {config.MODE_LABELS[other]}", key="data_switch", on_click=common.switch_mode,
                  args=(other,), icon=":material/swap_horiz:")
        st.caption("Each dataset has its own database, saved list and applications. Nothing is shared "
                   "between them, and switching never changes either one.")


I_EXPLAIN = {
    config.MODE_EXAMPLE: "Sixteen invented internships with deadlines generated around a fixed date, so every part "
                         "of the app can be tried safely. None of them exist.",
    config.MODE_REAL: "Internships read live from employers' public job boards (Greenhouse and Lever) by "
                      "ScholarPath's internship finder. Each record keeps the board it came from and when it was "
                      "last checked.",
}
I_COMMANDS = {
    config.MODE_EXAMPLE: "python -m scholarpath init-examples",
    config.MODE_REAL: "python -m scholarpath find-internships --import   # read every job board live, publish, import\n"
                      "python -m scholarpath find-internships --dry-run  # read and report coverage, write nothing",
}


def _finder_status(svc, info: dict) -> None:
    """The live finder's latest run: every board, whether it was read, what it gave, when it last worked."""
    st.header("Live internship finder", anchor=False)
    sources = info.get("sources") or []
    if not sources:
        st.markdown("The live finder has not been run for this dataset yet.")
        st.code(I_COMMANDS[config.MODE_REAL], language=None)
        return
    failed = [s for s in sources if s.get("status") != "ok"]
    st.markdown(f"**Latest run:** {common.fmt_ts(info.get('newest_fetched'))} · "
                f"{len(sources) - len(failed)} of {len(sources)} job boards read")
    if failed:
        st.warning(f"{common.plural(len(failed), 'job board')} could not be read in the latest run. Their "
                   "internships from the last successful run are still shown.", icon=":material/warning:")
    st.dataframe(pd.DataFrame([{
        "Job board": s["source_name"],
        "Latest run": "Read" if s.get("status") == "ok" else "Failed",
        "Postings on the board": s.get("listed") if s.get("listed") is not None else "-",
        "Internships in India": s.get("internships", 0),
        "Last success": _when(s.get("last_success_at")),
        "Problem": s.get("error") or "",
    } for s in sources]), hide_index=True, key="data_finder_sources")
    cover = svc.coverage()
    with st.container(horizontal=True, key="facts_coverage"):
        st.metric("Chennai", cover["chennai"], border=True)
        st.metric("Bengaluru", cover["bengaluru"], border=True)
        st.metric("Rest of India", cover["rest_of_india"], border=True)
        st.metric("Remote", cover["remote"], border=True)
    st.caption("Open internships by place. One internship in several places counts in each. Postings a job board "
               "no longer lists are marked closed at the next run and stay in Saved and Applications.")


def _sources(views) -> None:
    st.header("Sources", anchor=False)
    by_source = defaultdict(list)
    for view in views:
        by_source[view.record.source_name].append(view.record)
    internship = bool(views) and hasattr(views[0].record, "employer")
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
                ("Internship" if internship else "Scholarship"): v.record.name,
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


@st.cache_data(show_spinner=False)
def _refresh_state(path: str, modified_ns: int) -> dict:
    return refresh.load_state(path)


def _when(ts: str | None) -> str:
    return common.fmt_ts(ts) if ts else "Never"


def _refresh_status(svc) -> None:
    """When the published real data was last refreshed, when the next refresh is due, and how the
    latest attempt went. Read from data/refresh/state.json, written only by the refresh command."""
    st.header("Data refresh", anchor=False)
    path = refresh.STATE_FILE
    state = _refresh_state(str(path), path.stat().st_mtime_ns) if path.exists() else refresh.load_state(path)
    last, attempt = state.get("last_success_at"), state.get("latest_attempt") or {}
    if not last and not attempt:
        st.markdown("No automatic refresh has run yet. The records below come from the last manual collection; "
                    "the page each was read from and when is listed under Sources.")
        st.caption("Once the GitHub workflow is switched on, ScholarPath checks every day and refreshes the data "
                   "when 15 days have passed since the last successful refresh.")
        return
    due = refresh.next_due(state)
    due_text = ("due now; the next daily check will run it" if due is None or due <= svc.now()
                else common.fmt_ts(due.isoformat()))
    st.markdown(f"**Last successful data refresh:** {_when(last)}  \n**Next refresh due:** {due_text}")
    if attempt.get("status") == "failed":
        st.warning(f"The latest refresh attempt ({_when(attempt.get('at'))}) failed, so the data from the last "
                   "successful refresh is still shown. Nothing was changed.", icon=":material/warning:")
        with st.expander("Why the latest attempt failed", key="data_refresh_problems", icon=":material/info:"):
            st.markdown("\n".join(f"- {common.md_escape(p)}" for p in attempt.get("problems", [])))
    sources = state.get("sources") or {}
    if sources:
        st.dataframe(pd.DataFrame([{
            "Source": getattr(runner.SOURCES.get(sid), "SOURCE_NAME", sid),
            "Latest attempt": "Read without problems" if info.get("status") == "ok" else "Failed",
            "Records read": info.get("accepted", 0),
            "Last success": _when(info.get("last_success_at")),
        } for sid, info in sorted(sources.items())]), hide_index=True, key="data_refresh_sources")
    st.caption("Refreshed data is collected automatically from the official pages; it has not been checked by a "
               "person. Closed scholarships leave Find as soon as their deadline passes, even between refreshes.")


def _trust(svc, info: dict) -> None:
    st.header("How far to trust it", anchor=False)
    checked, total = info["verified_count"], info["scholarships"]
    lines = [
        ("**Last checked** is when ScholarPath last read the employer's job board. Job boards remove postings "
         "when a role is filled, so check the employer's page before applying." if common.is_internship(svc) else
         "**Read** is the day ScholarPath collected a page, not the day the provider published or updated it. "
         "A deadline that was correct then may have changed since."),
        (f"**Checked by a person: {checked} of {total}.** Collecting a page is not verification; a record "
         "counts as checked only after someone compares it with the official page."),
    ]
    if svc.mode == config.MODE_REAL and common.is_internship(svc):
        lines.append("Each internship keeps facts only (role, employer, place, stipend, duration, deadline and the "
                     "requirements it states), never the employer's description text. The discipline is "
                     "ScholarPath's reading of the role title.")
    elif svc.mode == config.MODE_REAL:
        lines.append("Each record says how it was read: from a saved copy of the official page, or downloaded "
                     "directly by the refresh. Either way, it shows the page as it was on that day, not live.")
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
        if common.is_internship(svc) and svc.mode == config.MODE_REAL:
            how = ("Real internships change only through the live finder command, run in Terminal inside the "
                   "ScholarPath folder (or by the daily GitHub workflow, once activated). A new run is picked up "
                   "by the app automatically.")
        elif svc.mode == config.MODE_REAL:
            how = ("The real dataset changes only through the refresh command: on a schedule in GitHub "
                   "Actions (once activated), or when you run it in Terminal inside the ScholarPath folder. "
                   "A successful refresh is picked up by the app automatically.")
        else:
            how = ("The example dataset is rebuilt only by this command, run in Terminal inside the "
                   "ScholarPath folder; reload this page afterwards.")
        st.markdown("Nothing is collected while you browse. " + how)
        st.code((I_COMMANDS if common.is_internship(svc) else COMMANDS)[svc.mode], language=None)
        st.caption(f"Database file: {svc.db_path}")


def render(svc) -> None:
    common.page_header(svc, "Data & sources",
                       "Where this information comes from, when it was read, and what has not been checked.")
    _dataset_card(svc)
    if not common.dataset_ready(svc):
        return
    info = common.cached_overview(str(svc.db_path), svc.today().isoformat(), svc.kind)
    views = common.all_views(svc, "name", include_closed=True)   # this page describes the whole dataset
    w = common.WORDS[svc.kind]

    with st.container(horizontal=True, key="facts_data"):
        st.metric("Open now", info["active"], border=True,
                  help=f"Shown in {w['find']}: not closed (rolling and unconfirmed dates included)")
        st.metric("All records", info["scholarships"], border=True,
                  help="Including closed ones, which are kept for saved items and applications")
        st.metric("Sources", len({v.record.source_name for v in views}), border=True)
        st.metric("Checked by hand", f"{info['verified_count']} of {info['scholarships']}", border=True,
                  help="Records a person has compared with the official page")
        st.metric("No longer listed" if common.is_internship(svc) else "Pages unavailable", info["unavailable_count"],
                  border=True)

    if svc.mode == config.MODE_REAL and common.is_internship(svc):
        _finder_status(svc, info)
    elif svc.mode == config.MODE_REAL:
        _refresh_status(svc)
    _sources(views)
    _trust(svc, info)
    _technical(svc, info)
