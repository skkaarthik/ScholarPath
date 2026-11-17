"""Review a scholarship (step 2) and apply (step 3).

Top of the page: deadline, who can apply, where and funding. Then the Apply
section, which always shows one main action for the scholarship's current state:

  not applied yet  -> "Apply on provider site" (opens the provider's page in a new tab)
  after returning  -> "Mark as applied" asks for the submission date and a confirmation
  confirmed        -> "Application added" with "View application" (opens the tracker entry)

ScholarPath never submits anything itself, so nothing enters Applications
until the user confirms that they submitted. Saving for later is optional.
"""

from __future__ import annotations

import streamlit as st

from .. import config
from ..dates import describe_deadline
from ..models import SCORE_SCALES
from ..services import STORAGE_ERRORS, ServiceError
from . import common


# --- button callbacks ------------------------------------------------------------------

def _ask_to_confirm(scholarship_id: str) -> None:
    st.session_state["confirm_apply"] = scholarship_id


def _not_yet() -> None:
    st.session_state.pop("confirm_apply", None)


def _confirm_applied(svc, scholarship_id: str) -> None:
    """The only place an application is created: after the user confirms their submission."""
    try:
        svc.mark_applied(scholarship_id, st.session_state.get("c_date"))
    except (ServiceError, *STORAGE_ERRORS) as exc:
        st.session_state["flash_error"] = f"Not added: {exc}"
        return
    common.after_write()
    st.session_state.pop("confirm_apply", None)
    st.session_state["just_applied"] = scholarship_id


# --- page sections ---------------------------------------------------------------------

def _who_can_apply(rec) -> list[str]:
    """Short eligibility lines for the top of the page; the full rules are further down."""
    nat = rec.nationalities
    if nat.kind == "list":
        shown = ", ".join(nat.values[:4])
        extra = len(nat.values) - 4
        lines = [f"Citizens of {shown}" + (f" and {extra} more" if extra > 0 else "")]
    elif nat.kind == "unrestricted":
        lines = ["Any citizenship"]
    else:
        lines = ["Citizenship rule not recorded"]
    if rec.subjects.kind == "list":
        lines.append(common.subject_text(rec))
    elif rec.subjects.kind == "unrestricted":
        lines.append("Any subject")
    if rec.min_score is not None:
        lines.append(f"Score of at least {rec.min_score:g} ({SCORE_SCALES[rec.score_scale]['label']})")
    return lines


def _at_a_glance(view) -> None:
    rec = view.record
    with st.container(border=True, key="card_glance"):
        deadline, who, where = st.columns(3, gap="medium")
        with deadline:
            st.markdown(f"**Deadline**  \n{common.deadline_line(view)}")
        with who:
            st.markdown("**Who can apply**  \n" + "  \n".join(common.md_escape(line) for line in _who_can_apply(rec)))
        with where:
            level = common.degree_text(rec) if rec.degrees.kind == "list" else "Level not recorded"
            st.markdown(f"**Where and funding**  \n{common.md_escape(', '.join(rec.host_countries))} · "
                        f"{common.md_escape(level)}  \nFunding: {common.md_escape(common.funding_text(rec))}")


def _save_button(svc, rec, saved: bool) -> None:
    if saved:
        st.button("Saved · remove", key="r_unsave", on_click=common.unsave, args=(svc, rec.id),
                  icon=":material/bookmark_added:")
    else:
        st.button("Save for later", key="r_save", on_click=common.save, args=(svc, rec.id, rec.name),
                  icon=":material/bookmark_add:")


def _apply(svc, view, today) -> None:
    rec = view.record
    app = svc.get_application(rec.id)
    saved = rec.id in svc.saved_ids()
    st.header("Apply", anchor=False)
    common.flash()

    # State 3: the user has confirmed their submission. Next step: the tracker.
    if app and app.status in common.SUBMITTED_STATUSES:
        if st.session_state.pop("just_applied", None) == rec.id:
            st.success("Application added.", icon=":material/check_circle:")
        st.markdown(f"You applied on {common.fmt_date(app.submitted_date)}. "
                    f"Status: **{common.tracker_status(app.status)}**.")
        with st.container(horizontal=True, key="apply_actions"):
            st.button("View application", key="r_view_app", on_click=common.open_application, args=(rec.id,),
                      type="primary", icon=":material/arrow_forward:", icon_position="right")
            common.safe_link_button("Provider site", rec.application_url, key="r_apply",
                                    icon=":material/open_in_new:")
            _save_button(svc, rec, saved)
        return

    # State 2: "Mark as applied" was chosen; ask for the date and a clear confirmation.
    if st.session_state.get("confirm_apply") == rec.id:
        with st.container(border=True, key="card_confirm"):
            st.subheader("Confirm your submission", anchor=False)
            st.markdown("Confirm only after you have submitted the application on the provider's site. "
                        "ScholarPath does not send anything to the provider.")
            st.date_input("Date you submitted it", value=today, max_value=today, key="c_date")
            with st.container(horizontal=True, key="confirm_actions"):
                st.button("Yes, add to Applications", key="r_confirm", on_click=_confirm_applied,
                          args=(svc, rec.id), type="primary", icon=":material/check:")
                st.button("Not yet", key="r_not_yet", on_click=_not_yet)
        return

    # State 1: not applied yet. One main action: go to the provider's site.
    closed = view.status == "expired"
    with st.container(horizontal=True, key="apply_actions"):
        common.safe_link_button("Apply on provider site", rec.application_url, key="r_apply",
                                type="secondary" if closed else "primary", icon=":material/open_in_new:")
        st.button("Mark as applied", key="r_mark", on_click=_ask_to_confirm, args=(rec.id,),
                  icon=":material/check:")
        _save_button(svc, rec, saved)
    if closed:
        st.caption("The published deadline has passed. If you applied before it closed, choose Mark as applied.")
    else:
        st.caption("The application opens on the provider's site in a new tab. After you submit it, "
                   "come back here and choose Mark as applied.")
    if app:  # an earlier Interested/Preparing entry made before the redesign
        st.button(f"In Applications as {common.tracker_status(app.status)} · view", key="r_view_app",
                  on_click=common.open_application, args=(rec.id,), type="tertiary",
                  icon=":material/arrow_forward:", icon_position="right")


def _eligibility(rec) -> None:
    st.header("Eligibility", anchor=False)
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
               "there is none.")
    manual = rec.manual_review_items
    if manual:
        st.subheader(f"Confirm on the provider's page ({len(manual)})", anchor=False)
        st.markdown("Part of the eligibility rules, but ScholarPath can't check them for you.")
        st.markdown("\n".join(f"- {common.md_escape(item.text)}" for item in manual))
    with st.expander("Original eligibility wording", key="r_wording", icon=":material/format_quote:"):
        st.caption("Exactly as collected from the source.")
        st.markdown(common.md_escape(rec.eligibility_text) or "No eligibility text was collected.")


def _deadline_and_funding(view, today) -> None:
    rec = view.record
    st.header("Deadline", anchor=False)
    st.markdown(f"**{describe_deadline(rec.deadline_kind, rec.deadline_date, today)}**")
    if rec.deadline_text:
        st.markdown(f"As published: {common.md_escape(rec.deadline_text)}")
    if rec.award_cycle:
        st.markdown(f"Award cycle: {common.md_escape(rec.award_cycle)}")
    st.caption(f"A date-only deadline counts as open until the end of that day ({config.APP_TIMEZONE_NAME}). "
               "Providers often close at a set time, so check their page.")

    st.header("Funding", anchor=False)
    st.markdown(f"**{common.funding_text(rec)}**")
    st.markdown(common.md_escape(rec.funding_description) if rec.funding_description
                else "The source does not describe the funding in detail.")


def _source(rec) -> None:
    with st.expander("Source and freshness", key="r_source", icon=":material/info:"):
        st.markdown(
            f"- **Source:** {common.md_escape(rec.source_name)}\n"
            f"- **How it was collected:** "
            f"{common.FETCH_LABELS.get(rec.fetch_method, common.md_escape(rec.fetch_method))}\n"
            f"- **Source page read:** "
            f"{common.fmt_ts(rec.source_fetched_at) if rec.source_fetched_at else 'Not applicable'}\n"
            f"- **Record created:** {common.fmt_ts(rec.collected_at)}\n"
            f"- **Checked by a person:** "
            f"{common.fmt_ts(rec.manual_verified_at) if rec.manual_verified_at else 'Not yet'}"
        )
        if rec.source_status == "unavailable":
            st.markdown("The source page could not be reached at the last collection, so this saved copy "
                        "may be out of date.")
        if rec.notes:
            st.caption(common.md_escape(rec.notes))
        common.safe_link_button("Open source page", rec.source_url, key="r_source_link",
                                icon=":material/open_in_new:")
        st.caption(f"Record ID: {rec.id}")


def render(svc) -> None:
    back = st.session_state.get("review_back")
    if back not in common.BACK_LABELS:
        back = "find"
    st.button(common.BACK_LABELS[back], key="r_back", on_click=common.go_to, args=(back,),
              icon=":material/arrow_back:", type="tertiary")
    if not common.dataset_ready(svc):
        return
    sid = st.session_state.get("selected_id")
    view = svc.get(sid) if sid else None
    if view is None:
        common.page_header(svc, "Review scholarship")
        common.empty_state("review", "No scholarship selected",
                           "Choose a scholarship from Find Scholarships or your Saved list to review it here.",
                           "Find scholarships", "find", icon=":material/search:")
        return
    rec = view.record
    today = svc.today()

    st.title(common.md_escape(rec.name), anchor=False)
    st.markdown(common.md_escape(rec.provider))
    common.dataset_notice(svc)
    _at_a_glance(view)
    _apply(svc, view, today)
    _eligibility(rec)
    _deadline_and_funding(view, today)
    _source(rec)
