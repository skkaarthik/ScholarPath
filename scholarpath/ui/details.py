"""Scholarship details: one scrollable page in a fixed order.

Key facts (dates, funding, where it comes from) sit beside the requirements,
then the original wording. Source facts and ScholarPath's own planning hints
are labelled separately; nothing here is invented beyond what was collected.
"""

from __future__ import annotations

import streamlit as st

from .. import config
from ..dates import describe_deadline
from ..models import SCORE_SCALES, TRACKER_STATUSES
from . import common

FETCH_LABELS = {
    "fictional": "Fictional example (not collected from any source)",
    "live_http": "Downloaded directly from the official page",
    "browser_snapshot": "Read from a saved copy of the official page",
}


def _open_tracker(scholarship_id: str) -> None:
    st.session_state["tracker_pick"] = scholarship_id
    st.session_state["apps_tab"] = "tracker"
    common.go_to("applications")


def _actions(svc, view) -> None:
    rec = view.record
    saved = rec.id in svc.saved_ids()
    app = svc.get_application(rec.id)
    with st.container(horizontal=True, key="detail_actions"):
        if saved:
            st.button("Saved · remove", key="d_unsave", on_click=common.unsave, args=(svc, rec.id),
                      icon=":material/bookmark_added:")
        else:
            st.button("Save", key="d_save", on_click=common.save, args=(svc, rec.id, rec.name), type="primary",
                      icon=":material/bookmark_add:")
        if app:
            st.button(f"My application: {TRACKER_STATUSES[app.status]}", key="d_edit", on_click=_open_tracker,
                      args=(rec.id,), icon=":material/edit_note:")
        else:
            st.button("Start tracking my application", key="d_track", on_click=common.track, args=(svc, rec.id),
                      icon=":material/playlist_add:")
        common.safe_link_button("Official page", rec.application_url, key="d_apply", icon=":material/open_in_new:")


def _facts(view, today) -> None:
    rec = view.record
    with st.container(border=True, key="card_dates"):
        st.header("Dates", anchor=False)
        st.markdown(f"**{describe_deadline(rec.deadline_kind, rec.deadline_date, today)}**")
        if rec.deadline_text:
            st.markdown(f"As published: {common.md_escape(rec.deadline_text)}")
        if rec.award_cycle:
            st.markdown(f"Award cycle: {common.md_escape(rec.award_cycle)}")
        st.caption(f"A date-only deadline counts as open until the end of that day ({config.APP_TIMEZONE_NAME}). "
                   "Providers often close at a set time, so check the official page.")
    with st.container(border=True, key="card_funding"):
        st.header("Funding", anchor=False)
        st.markdown(f"**{common.funding_text(rec)}**")
        st.markdown(common.md_escape(rec.funding_description) if rec.funding_description
                    else "The source does not describe the funding in detail.")
    with st.container(border=True, key="card_source"):
        st.header("Source and freshness", anchor=False)
        st.markdown(
            f"- **Source:** {common.md_escape(rec.source_name)}\n"
            f"- **How it was collected:** {FETCH_LABELS.get(rec.fetch_method, common.md_escape(rec.fetch_method))}\n"
            f"- **Source page read:** {common.fmt_ts(rec.source_fetched_at) if rec.source_fetched_at else 'Not applicable'}\n"
            f"- **Record created:** {common.fmt_ts(rec.collected_at)}\n"
            f"- **Checked by a person:** {common.fmt_ts(rec.manual_verified_at) if rec.manual_verified_at else 'Not yet'}"
        )
        if rec.source_status == "unavailable":
            st.markdown(":orange-badge[:material/link_off: Source page unavailable] It could not be reached at "
                        "the last collection, so this saved copy may be out of date.")
        if rec.notes:
            st.caption(common.md_escape(rec.notes))
        common.safe_link_button("Open source page", rec.source_url, key="d_source", icon=":material/open_in_new:")
        st.caption(f"Record ID: {rec.id}")


def _requirements(rec) -> None:
    st.header("Recorded requirements", anchor=False)
    exc = rec.nationality_exclusions
    exclusions = {"none": "None", "unknown": "Not stated"}.get(exc.kind, ", ".join(exc.values))
    score = (f"At least {rec.min_score:g} ({SCORE_SCALES[rec.score_scale]['label']})"
             if rec.min_score is not None else "No minimum score published")
    rows = [
        ("Citizenship", common.restriction_text(rec.nationalities.kind, rec.nationalities.values)),
        ("Not open to citizens of", exclusions),
        ("Level of study", common.degree_text(rec)),
        ("Subject", common.subject_text(rec)),
        ("Academic score", score),
    ]
    # A list (not a table) so long country lists wrap instead of being cut off.
    st.markdown("\n".join(f"- **{label}:** {common.md_escape(value)}" for label, value in rows))
    st.caption("\"Not listed in a structured form\" means ScholarPath could not record the rule, not that "
               "there is none. Read the original wording below.")

    manual = rec.manual_review_items
    st.header(f"Confirm on the official page ({len(manual)})", anchor=False)
    if manual:
        st.markdown("These are part of the eligibility rules, but ScholarPath can't check them for you.")
        st.markdown("\n".join(f"- {common.md_escape(item.text)}" for item in manual))
    else:
        st.markdown("Nothing extra is recorded for this scholarship.")

    st.header("How to apply", anchor=False)
    st.markdown("ScholarPath has not recorded step-by-step application instructions or a document list for "
                "this scholarship. Follow the instructions on the official page.")

    st.header("Original eligibility wording", anchor=False)
    st.caption("Exactly as collected from the source.")
    with st.container(border=True, key="card_wording"):
        st.markdown(common.md_escape(rec.eligibility_text) or "No eligibility text was collected.")


def render(svc) -> None:
    back = st.session_state.get("details_back") or "discover"
    if back not in common.PAGE_INFO or back == "details":
        back = "discover"
    st.button(f"Back to {common.PAGE_INFO[back][0]}", key="d_back", on_click=common.go_to, args=(back,),
              icon=":material/arrow_back:", type="tertiary")
    if not common.dataset_ready(svc):
        return
    sid = st.session_state.get("selected_id")
    view = svc.get(sid) if sid else None
    if view is None:
        common.page_header(svc, "Scholarship details")
        common.empty_state("details", "No scholarship selected",
                           "Open a scholarship from Discover or your saved list to read its details here.",
                           "Go to Discover", "discover", icon=":material/search:")
        return
    rec = view.record
    today = svc.today()

    st.title(common.md_escape(rec.name), anchor=False)
    st.markdown(common.md_escape(rec.provider))
    st.markdown(f"{common.deadline_badge(view)} {common.meta_badges(rec)}")
    common.dataset_notice(svc)
    _actions(svc, view)
    common.flash()

    facts, body = st.columns([1, 1.5], gap="large")
    with facts:
        _facts(view, today)
    with body:
        _requirements(rec)
