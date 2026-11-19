"""Review a scholarship (step 2) and apply (step 3).

Reading order: title and provider, the four facts a student needs first
(deadline, who can apply, where, funding), then Apply, then the detailed
eligibility, deadline, funding and source.

The Apply section always shows one main action for the scholarship's state:

  not applied yet  -> "Apply on provider site" (opens the provider's website in a new tab)
  after returning  -> "Mark as applied" asks for the submission date and a confirmation
  confirmed        -> "Application added" with "View application" (opens the tracker entry)

ScholarPath never submits anything itself, so nothing enters Applications
until the user confirms that they submitted. Saving for later is optional and
separate: adding an application never saves the scholarship.
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
    st.session_state.pop("confirm_error", None)


def _not_yet() -> None:
    """Cancel: leave the confirmation step without saving anything."""
    st.session_state.pop("confirm_apply", None)
    st.session_state.pop("confirm_error", None)


def _confirm_applied(svc, scholarship_id: str) -> None:
    """The only place an application is created: after the user confirms their submission."""
    ss = st.session_state
    ss.pop("confirm_error", None)
    try:
        svc.mark_applied(scholarship_id, ss.get("c_date"))
    except (ServiceError, *STORAGE_ERRORS) as exc:
        ss["confirm_error"] = f"Not added. {exc}"   # shown under the date field; nothing was written
        return
    common.after_write()
    ss.pop("confirm_apply", None)
    ss["just_applied"] = scholarship_id


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


def _fact(column, label: str, lines: list[str]) -> None:
    column.markdown(f"**{label}**  \n" + "  \n".join(lines))


def _at_a_glance(view) -> None:
    """The four facts to read first. Columns stack on a phone."""
    rec = view.record
    colour, label, detail = common.deadline_state(view)
    with st.container(border=True, key="card_glance"):
        deadline, who, where, funding = st.columns(4, gap="medium")
        _fact(deadline, "Deadline", [common.badge(colour, label)] + ([detail] if detail else []))
        _fact(who, "Who can apply", [common.md_escape(line) for line in _who_can_apply(rec)])
        _fact(where, "Where", [common.md_escape(", ".join(rec.host_countries)),
                               common.md_escape(common.level_text(rec) or "Level not recorded")])
        _fact(funding, "Funding", [common.md_escape(common.funding_text(rec))])


def _top_row(svc, rec, back: str, saved: bool) -> None:
    """Back on the left; the optional Save action on the right."""
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                      key="review_top"):
        st.button(common.BACK_LABELS[back], key="r_back", on_click=common.go_to, args=(back,),
                  icon=":material/arrow_back:", type="tertiary")
        if rec is None:
            return
        if saved:
            with st.container(horizontal=True, vertical_alignment="center", key="review_saved", width="content"):
                st.markdown(common.badge("blue", "Saved") + " Find it under Saved")
                st.button("Remove from Saved", key="r_unsave", on_click=common.unsave, args=(svc, rec.id),
                          icon=":material/bookmark_remove:", type="tertiary")
        else:
            st.button("Save for later", key="r_save", on_click=common.save, args=(svc, rec.id, rec.name),
                      icon=":material/bookmark_add:", type="tertiary")


def _confirm_card(svc, rec, today) -> None:
    """Step shown after "Mark as applied": the date, then a clear yes or a cancel."""
    with st.container(border=True, key="card_confirm"):
        st.subheader("Confirm your submission", anchor=False)
        st.markdown("Confirm only after you have submitted the application on the provider's website. "
                    "ScholarPath does not send anything to the provider.")
        # No max_value on purpose: the field would then refuse a later date in the browser but still
        # send its previous value, so a click on "Yes" could record a date the user never chose.
        # The date is checked here as soon as it changes, and again by the service when confirming.
        chosen = st.date_input("Date you submitted it", value=today, key="c_date", format="DD/MM/YYYY")
        in_future = chosen is not None and chosen > today
        problem = st.session_state.get("confirm_error")
        if in_future:
            st.error(f"Choose {common.fmt_date(today)} or an earlier date. An application cannot have been "
                     "submitted in the future.", icon=":material/error:")
        elif problem:
            st.error(problem, icon=":material/error:")
        with st.container(horizontal=True, key="confirm_actions"):
            st.button("Yes, add to Applications", key="r_confirm", on_click=_confirm_applied,
                      args=(svc, rec.id), type="primary", icon=":material/check:", disabled=in_future)
            st.button("Not yet", key="r_not_yet", on_click=_not_yet)


def _apply(svc, view, today) -> None:
    rec = view.record
    app = svc.get_application(rec.id)
    st.header("Apply", anchor=False)
    common.flash()

    # State 3: the user has confirmed their submission. Next step: the tracker.
    if app and app.status in common.SUBMITTED_STATUSES:
        if st.session_state.pop("just_applied", None) == rec.id:
            st.success("Application added. It is now in Applications.", icon=":material/check_circle:")
        st.markdown("You recorded this application: " + common.application_line(app))
        with st.container(horizontal=True, key="apply_actions"):
            st.button("View application", key="r_view_app", on_click=common.open_application, args=(rec.id,),
                      type="primary", icon=":material/arrow_forward:", icon_position="right")
            common.safe_link_button("Provider site", rec.application_url, key="r_apply",
                                    icon=":material/open_in_new:", icon_position="right")
        return

    # State 2: "Mark as applied" was chosen; ask for the date and a clear confirmation.
    if st.session_state.get("confirm_apply") == rec.id:
        _confirm_card(svc, rec, today)
        return

    # State 1: not applied yet. One main action: go to the provider's website.
    closed = view.status == "expired"
    if closed:
        st.info(f"The published deadline has passed ({common.fmt_date(rec.deadline_date)}). You can still open "
                "the provider's website, or record an application you sent before it closed.",
                icon=":material/event_busy:")
    with st.container(horizontal=True, key="apply_actions"):
        linked = common.safe_link_button("Apply on provider site", rec.application_url, key="r_apply",
                                         type="secondary" if closed else "primary",
                                         icon=":material/open_in_new:", icon_position="right")
        st.button("Mark as applied", key="r_mark", on_click=_ask_to_confirm, args=(rec.id,),
                  icon=":material/check:")
    if linked:
        st.caption(f"Opens {common.md_escape(common.site_name(rec.application_url))}, an outside website, in a "
                   "new tab. ScholarPath never submits anything for you: after you apply there, come back "
                   "and choose Mark as applied.")
    else:
        st.caption("No usable application link was collected for this scholarship, so look it up on the "
                   "provider's website. After you apply, come back and choose Mark as applied.")
    if svc.mode == config.MODE_EXAMPLE:
        st.caption("Example data: the link opens a placeholder page, not a real application form.")
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
    st.markdown(f"**{describe_deadline(rec.deadline_kind, rec.deadline_date, today, view.status == 'expired')}**")
    if rec.deadline_text.strip():
        st.markdown(f"Provider's wording: “{common.md_escape(rec.deadline_text.strip())}”")
    if view.status == "unknown":
        if rec.deadline_text.strip():
            st.markdown("ScholarPath never guesses a missing year or date, so this deadline is recorded as "
                        "not confirmed. Check the provider's page for the exact date.")
        else:
            st.markdown("The source does not publish a closing date. Check the provider's page.")
        if rec.notes and rec.fetch_method != "fictional":
            st.caption(f"Note made when the page was collected: {common.md_escape(rec.notes)}")
    if rec.award_cycle:
        st.markdown(f"Award cycle: {common.md_escape(rec.award_cycle)}")
    if view.status in ("open", "expired"):
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
        if not common.safe_link_button("Open source page", rec.source_url, key="r_source_link",
                                       icon=":material/open_in_new:", icon_position="right"):
            st.caption("The source address was not recorded as a valid web link.")
        st.caption(f"Record ID: {rec.id}")


def render(svc) -> None:
    back = st.session_state.get("review_back")
    if back not in common.BACK_LABELS:
        back = "find"
    sid = st.session_state.get("selected_id")
    ready = svc.database_exists() and common.dataset_ready(svc)
    view = svc.get(sid) if ready and sid else None
    _top_row(svc, view.record if view else None, back, bool(view) and view.record.id in svc.saved_ids())
    if not ready:
        if not svc.database_exists():
            common.dataset_ready(svc)     # shows the set-up steps
        return
    if view is None:
        common.page_header(svc, "Review scholarship")
        if sid:   # an ID that is no longer in this dataset (for example after a new import)
            common.empty_state("review_missing", "This scholarship is not in this dataset",
                               "It may have been removed by a later import. Choose a scholarship again "
                               "from Find Scholarships.", "Find scholarships", "find", icon=":material/search:")
        else:
            common.empty_state("review", "No scholarship selected",
                               "Choose a scholarship from Find Scholarships or your Saved list to review it here.",
                               "Find scholarships", "find", icon=":material/search:")
        return
    rec = view.record
    today = svc.today()

    st.title(common.md_escape(rec.name), anchor=False)
    st.markdown(common.md_escape(rec.provider))
    common.dataset_notice(svc)
    if rec.fetch_method != "fictional":
        st.caption(common.freshness_text(rec, today))
    _at_a_glance(view)
    _apply(svc, view, today)
    _eligibility(rec)
    _deadline_and_funding(view, today)
    _source(rec)
