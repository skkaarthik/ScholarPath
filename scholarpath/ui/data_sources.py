"""Data & sources: where the records come from, how fresh they are and how to refresh them."""

from __future__ import annotations

from collections import defaultdict

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


def render(svc) -> None:
    common.page_header(svc, "Data & sources",
                       "Where this information comes from, how fresh it is, and what has not been checked.")
    st.markdown(EXPLAIN[svc.mode])
    if not common.dataset_ready(svc):
        return
    today = svc.today()
    info = common.cached_overview(str(svc.db_path), today.isoformat())
    views = common.all_views(svc, "name")

    with st.container(horizontal=True, key="data_metrics"):
        st.metric("Records", info["scholarships"], border=True)
        st.metric("Sources", len({v.record.source_name for v in views}), border=True)
        st.metric("Checked by a person", f"{info['verified_count']} of {info['scholarships']}", border=True,
                  help="Compared with the official page by a human. Collecting a page is not verification.")
        st.metric("Source pages unavailable", info["unavailable_count"], border=True,
                  help="Pages that could not be reached at the last collection. Their saved copies are kept.")

    st.header("Sources", anchor=False)
    by_source = defaultdict(list)
    for view in views:
        by_source[view.record.source_name].append(view.record)
    st.dataframe(pd.DataFrame([{
        "Source": name,
        "Records": len(records),
        "Oldest read": common.fmt_ts(min(r.source_fetched_at or r.collected_at for r in records)),
        "Newest read": common.fmt_ts(max(r.source_fetched_at or r.collected_at for r in records)),
        "How it was collected": ", ".join(sorted({common.FETCH_LABELS.get(r.fetch_method, r.fetch_method)
                                                  for r in records})),
    } for name, records in sorted(by_source.items())]), hide_index=True)

    st.header("Freshness", anchor=False)
    run = info["last_import"] or {}
    st.markdown(
        f"- **Last import into this database:** {common.fmt_ts(run.get('finished_at'))}"
        f"{' (' + common.md_escape(run['status']) + ')' if run.get('status') else ''}\n"
        f"- **Records created between:** {common.fmt_ts(info['oldest_collected'])} and "
        f"{common.fmt_ts(info['newest_collected'])}\n"
        f"- **Most recent source page read:** {common.fmt_ts(info['newest_fetched'])}"
    )
    if info.get("example_anchor_date"):
        st.caption(f"Example deadlines were generated relative to {info['example_anchor_date']} "
                   "(fictional data only; real deadlines are never shifted).")
    st.markdown("\"Read\" is when ScholarPath collected a page, not when the provider published or updated it. "
                "A deadline that was correct then may have changed since.")

    st.header("Refreshing this dataset", anchor=False)
    st.markdown("Data changes only when you run these commands in Terminal, inside the ScholarPath folder. "
                "Nothing is collected while you browse, and no automatic schedule is set up.")
    st.code(COMMANDS[svc.mode], language=None)
    st.caption(f"Database file: {svc.db_path}")
