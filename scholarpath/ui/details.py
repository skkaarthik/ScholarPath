"""Scholarship details: funding, requirements, original wording, things to confirm, links, provenance."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from .. import config
from ..dates import describe_deadline
from ..models import SCORE_SCALES, TRACKER_STATUSES
from ..repository import SearchFilters
from . import common

FETCH_LABELS = {
    "fictional": "Fictional example (not collected from any source)",
    "live_http": "Downloaded directly from the official page",
    "browser_snapshot": "Read from a saved copy of the official page",
}


def _save(svc, sid):
    svc.save(sid)
    common.after_write()
    st.session_state["flash"] = "Saved to your shortlist."


def _unsave(svc, sid):
    svc.unsave(sid)
    common.after_write()
    st.session_state["flash"] = "Removed from your shortlist. Your tracker notes and history are kept."


def _track(svc, sid):
    svc.start_tracking(sid)
    common.after_write()
    st.session_state["tracker_pick"] = sid
    st.session_state["flash"] = "Tracking started. Update your progress under My applications."


def render(svc) -> None:
    if not common.dataset_ready(svc):
        return
    today = svc.today()
    views = common.cached_search(str(svc.db_path), today.isoformat(), common.filters_key(SearchFilters()), "name")
    ids = [v.record.id for v in views]
    labels = {v.record.id: f"{v.record.name} ({v.record.provider})" for v in views}
    if st.session_state.get("selected_id") not in ids:
        st.session_state["selected_id"] = ids[0]
    sid = st.selectbox("Scholarship", ids, format_func=labels.get, key="selected_id",
                       label_visibility="collapsed")
    view = svc.get(sid)
    rec = view.record
    common.flash()

    with st.container(border=True, key="detail_header"):
        st.header(rec.name, anchor=False)
        st.markdown(f'<div class="sp-provider">{html.escape(rec.provider)}</div>', unsafe_allow_html=True)
        st.markdown(f"{common.deadline_badge(view)} {common.meta_badges(rec)}")
        if rec.source_status == "unavailable":
            st.caption(":material/link_off: The source page could not be reached at the last collection, "
                       "so this saved copy may be out of date.")
        saved = sid in svc.saved_ids()
        app = svc.get_application(sid)
        a, b, c = st.columns(3)
        if saved:
            a.button("Remove from shortlist", key="d_unsave", on_click=_unsave, args=(svc, sid),
                     icon=":material/bookmark_remove:", width="stretch")
        else:
            a.button("Save to shortlist", key="d_save", on_click=_save, args=(svc, sid), type="primary",
                     icon=":material/bookmark_add:", width="stretch")
        if app:
            b.button(f"Tracking: {TRACKER_STATUSES[app.status]}", key="d_edit", on_click=common.go_to,
                     args=("My applications",), icon=":material/edit_note:", width="stretch")
        else:
            b.button("Start tracking", key="d_track", on_click=_track, args=(svc, sid),
                     icon=":material/playlist_add:", width="stretch")
        with c:
            common.safe_link_button("Official page", rec.application_url, key="d_apply",
                                    icon=":material/open_in_new:", width="stretch")

    summary, wording, source = st.tabs(["Summary", "Original eligibility wording", "Source and verification"])

    with summary:
        left, right = st.columns(2, gap="medium")
        with left, st.container(border=True):
            st.markdown("#### :material/event: Deadline")
            st.markdown(describe_deadline(rec.deadline_kind, rec.deadline_date, today))
            if rec.deadline_text:
                st.caption(f"As published: {common.md_escape(rec.deadline_text)}")
            st.caption(f"A date-only deadline counts as open until the end of that day ({config.APP_TIMEZONE_NAME}). "
                       "Providers often close at a set time, so check the official page.")
            if rec.award_cycle:
                st.markdown(f"**Award cycle:** {common.md_escape(rec.award_cycle)}")
        with right, st.container(border=True):
            st.markdown("#### :material/payments: Funding")
            st.markdown(f"**{common.funding_text(rec)}**")
            st.markdown(common.md_escape(rec.funding_description) if rec.funding_description
                        else "The source does not describe the funding in detail.")

        st.markdown("#### :material/rule: Recorded requirements")
        exc = rec.nationality_exclusions
        exclusions = {"none": "None", "unknown": "Not stated"}.get(exc.kind, ", ".join(exc.values))
        score = (f"At least {rec.min_score:g} ({SCORE_SCALES[rec.score_scale]['label']})"
                 if rec.min_score is not None else "No minimum score published")
        st.dataframe(pd.DataFrame({
            "Requirement": ["Citizenship", "Not open to citizens of", "Degree", "Subject", "Academic score"],
            "What the source says": [
                common.restriction_text(rec.nationalities.kind, rec.nationalities.values),
                exclusions, common.degree_text(rec), common.subject_text(rec), score,
            ],
        }), hide_index=True)

        manual = rec.manual_review_items
        with st.container(border=True, key="confirm_box"):
            st.markdown(f"#### :material/checklist: Confirm on the official page ({len(manual)})")
            if manual:
                st.caption("These are part of the eligibility rules but can't be checked automatically.")
                for item in manual:
                    st.markdown(f"- {common.md_escape(item.text)}")
            else:
                st.caption("Nothing extra recorded for this scholarship.")

    with wording:
        st.caption("Exactly as collected from the source.")
        st.markdown(common.md_escape(rec.eligibility_text))

    with source:
        st.markdown(
            f"- **Source:** {common.md_escape(rec.source_name)}\n"
            f"- **How it was collected:** {FETCH_LABELS.get(rec.fetch_method, rec.fetch_method)}\n"
            f"- **Source page read:** {rec.source_fetched_at or 'Not applicable'}\n"
            f"- **Record created:** {rec.collected_at}\n"
            f"- **Checked by a person against the official page:** {rec.manual_verified_at or 'Not yet'}\n"
            f"- **Record ID:** `{rec.id}`"
        )
        if rec.notes:
            st.caption(common.md_escape(rec.notes))
        common.safe_link_button("Open source page", rec.source_url, key="d_source", icon=":material/link:")
