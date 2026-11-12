"""Scholarship details: funding, requirements, original wording, manual-review items, links, provenance."""

from __future__ import annotations

import streamlit as st

from .. import config
from ..models import SCORE_SCALES
from ..repository import SearchFilters
from . import common

FETCH_LABELS = {
    "fictional": "Fictional example (not collected from any source)",
    "live_http": "Fetched directly over HTTP by the collector",
    "browser_snapshot": "Parsed from a browser-captured snapshot of the official page",
}


def _save(svc, sid):
    svc.save(sid)
    common.after_write()
    st.session_state["flash"] = "Saved to your shortlist."


def _unsave(svc, sid):
    svc.unsave(sid)
    common.after_write()
    st.session_state["flash"] = "Removed from your shortlist. Any tracker entry and its history were kept."


def _track(svc, sid):
    svc.start_tracking(sid)
    common.after_write()
    st.session_state["tracker_pick"] = sid
    st.session_state["flash"] = "Tracking started with status Interested. Edit it under My applications."


def render(svc) -> None:
    st.title("Scholarship details")
    if not common.dataset_ready(svc):
        return
    today = svc.today()
    views = common.cached_search(str(svc.db_path), today.isoformat(), common.filters_key(SearchFilters()), "name")
    ids = [v.record.id for v in views]
    labels = {v.record.id: f"{v.record.name} - {v.record.provider}" for v in views}
    if st.session_state.get("selected_id") not in ids:
        st.session_state["selected_id"] = ids[0]
    sid = st.selectbox("Scholarship", ids, format_func=labels.get, key="selected_id")
    view = svc.get(sid)
    rec = view.record

    if flash := st.session_state.pop("flash", None):
        st.success(flash)

    st.header(rec.name)
    st.markdown(f"**Provider:** {common.md_escape(rec.provider)}  \n"
                f"**Host countries:** {common.md_escape(', '.join(rec.host_countries))}")
    if rec.dataset_origin == "example":
        st.warning("Fictional example record - not a real scholarship.", icon="🧪")
    if rec.source_status == "unavailable":
        st.error("The source page was reported unavailable at the last collection. "
                 "This saved information may be out of date.", icon="⚠️")

    saved = sid in svc.saved_ids()
    app = svc.get_application(sid)
    a, b, c = st.columns(3)
    if saved:
        a.button("Remove from shortlist", key="d_unsave", on_click=_unsave, args=(svc, sid))
    else:
        a.button("Save to shortlist", key="d_save", on_click=_save, args=(svc, sid))
    if app:
        b.button(f"Tracking: {app.status.replace('_', ' ')} - edit", key="d_edit",
                 on_click=common.go_to, args=("My applications",))
    else:
        b.button("Start tracking", key="d_track", on_click=_track, args=(svc, sid))
    with c:
        common.safe_link_button("Official application page", rec.application_url, key="d_apply")

    st.subheader("Deadline")
    st.markdown(common.deadline_text(view, today))
    if rec.deadline_text:
        st.markdown(f"Source wording: *{common.md_escape(rec.deadline_text)}*")
    st.caption(f"Date basis: a date-only deadline is treated as open through that calendar day in "
               f"{config.APP_TIMEZONE_NAME}. Providers often close at a specific time and timezone - "
               "check the official page.")
    if rec.award_cycle:
        st.markdown(f"**Award cycle:** {common.md_escape(rec.award_cycle)}")

    st.subheader("Funding")
    st.markdown(f"**Category:** {common.funding_text(rec)}")
    st.markdown(common.md_escape(rec.funding_description) if rec.funding_description else "_No funding description recorded._")

    st.subheader("Recorded requirements")
    exc = rec.nationality_exclusions
    exclusions = {"none": "None recorded", "unknown": "Unknown"}.get(exc.kind, ", ".join(exc.values))
    score = (f"At least {rec.min_score:g} ({SCORE_SCALES[rec.score_scale]['label']})"
             if rec.min_score is not None else "No numeric threshold recorded")
    st.table({
        "Criterion": ["Nationality", "Excluded nationalities", "Degree", "Subject", "Academic score"],
        "Recorded requirement": [
            common.restriction_text(rec.nationalities.kind, rec.nationalities.values),
            exclusions, common.degree_text(rec), common.subject_text(rec), score,
        ],
    })
    manual = rec.manual_review_items
    st.markdown(f"**Manual-review items ({len(manual)})** - ScholarPath cannot check these automatically:")
    if manual:
        for item in manual:
            st.markdown(f"- *{item.category.replace('_', ' ')}*: {common.md_escape(item.text)}")
    else:
        st.caption("None recorded.")
    with st.expander("Original eligibility wording from the source"):
        st.markdown(common.md_escape(rec.eligibility_text))

    st.subheader("Source and verification")
    st.markdown(
        f"- Source: {common.md_escape(rec.source_name)}\n"
        f"- How collected: {FETCH_LABELS.get(rec.fetch_method, rec.fetch_method)}\n"
        f"- Source fetched: {rec.source_fetched_at or '-'}\n"
        f"- Record collected: {rec.collected_at}\n"
        f"- Manually verified against the official source: {rec.manual_verified_at or 'No'}\n"
        f"- Stable ID: `{rec.id}`"
    )
    if rec.notes:
        st.caption(common.md_escape(rec.notes))
    common.safe_link_button("Open source page", rec.source_url, key="d_source")
