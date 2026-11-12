"""Profile matching: a submitted form with friendly, explainable results.

Presentation only - the verdicts come unchanged from ``matching.evaluate``:
unknown information is never counted as met. Requirements ScholarPath cannot
check (language tests, residence, ...) are gathered into one checklist per
scholarship instead of a warning per line. The profile lives only in this
browser session and is never saved.
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from ..matching import DISCLAIMER, FAILED, SATISFIED, UNKNOWN, StudentProfile, validate_profile
from ..models import DEGREES, SCORE_SCALES, SUBJECTS
from . import common

NOT_SET = ""
OTHER = "__other__"


GROUPS = {
    "fit": {"title": "Good fits", "tile": "sp-tile-fit", "icon": ":material/verified:",
            "blurb": "Pass every check ScholarPath can run"},
    "missing": {"title": "Need more info", "tile": "sp-tile-missing", "icon": ":material/help_center:",
                "blurb": "Nothing failed, but some rules couldn't be checked yet"},
    "no_fit": {"title": "Not a fit", "tile": "sp-tile-no", "icon": ":material/block:",
               "blurb": "At least one recorded requirement isn't met"},
}
EMPTY_GROUP = {
    "fit": "No full fits yet. Filling in more of the form often moves scholarships here.",
    "missing": "Every scholarship could be checked with what you entered.",
    "no_fit": "Nothing ruled out by the recorded requirements.",
}
FIELD_NAMES = {"Nationality": "citizenship", "Nationality exclusions": "citizenship", "Degree": "degree",
               "Subject": "subject", "Academic score": "score"}


def _join(words: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _summary_line(match) -> str:
    """One encouraging, accurate sentence for the card."""
    auto = match.automatic
    passed = sum(1 for r in auto if r.status == SATISFIED)
    if match.group == "no_fit":
        first = next(r for r in match.rules if r.status == FAILED)
        return f"{first.reason}"
    if match.group == "fit":
        if match.manual:
            return (f"You meet all {passed} recorded requirements ScholarPath can check. "
                    f"Confirm {len(match.manual)} more on the official page.")
        return f"You meet all {passed} recorded requirements."
    blanks = sorted({FIELD_NAMES.get(r.rule, r.rule.lower()) for r in match.missing_inputs})
    source_gaps = any(r.status == UNKNOWN and not r.missing_input for r in auto)
    if blanks and source_gaps:
        return (f"Add your {_join(blanks)} above to check more. Some rules also aren't published in a form "
                "ScholarPath can check.")
    if blanks:
        return f"Add your {_join(blanks)} above to check the rest."
    return "The source doesn't publish some rules in a form ScholarPath can check, so read them on the official page."


def _result_card(view, match, today) -> None:
    rec = view.record
    style = common.OVERALL_STYLE[match.overall]
    auto = match.automatic
    met = [r for r in auto if r.status == SATISFIED]
    failed = [r for r in auto if r.status == FAILED]
    open_auto = [r for r in auto if r.status == UNKNOWN]

    with common.card("m", view):
        common.card_header(view, today, show_date=False)
        st.markdown(f":{style['badge']}-badge[{style['icon']} {match.overall}]")
        st.markdown(f'<p class="sp-why">{html.escape(_summary_line(match))}</p>', unsafe_allow_html=True)
        if auto:
            st.progress(len(met) / len(auto), text=f"{len(met)} of {len(auto)} automatic checks passed")
        lines = [("sp-rule-no", "✕", r) for r in failed] + [("sp-rule-open", "?", r) for r in open_auto]
        if lines:
            st.markdown("".join(
                f'<div class="sp-rule {cls}"><span aria-hidden="true">{mark}</span>'
                f'<div><b>{html.escape(r.rule)}</b> {html.escape(r.reason)}</div></div>'
                for cls, mark, r in lines), unsafe_allow_html=True)
        if match.manual:
            with st.expander(f"Confirm on the official page ({len(match.manual)})", icon=":material/checklist:"):
                st.caption("Part of the eligibility rules, but written in a way only you can check.")
                for r in match.manual:
                    st.markdown(f"- {common.md_escape(r.requirement)}")
        with st.expander("Every rule, explained", icon=":material/list_alt:"):
            st.dataframe(pd.DataFrame([{
                "Rule": r.rule, "You": r.student_value, "Recorded requirement": r.requirement,
                "Result": common.RULE_TEXT[r.status], "Why": r.reason,
            } for r in match.rules]), hide_index=True)
        st.button("Open details", key=f"m_open_{rec.id}", on_click=common.go_to,
                  args=("Scholarship details", rec.id), icon=":material/visibility:")


def render(svc) -> None:
    st.title("Check your fit", anchor=False)
    st.markdown('<p class="sp-hero-sub">Tell ScholarPath what you know. It compares your answers with the '
                'requirements recorded for each scholarship and shows exactly why. Your answers stay in this '
                'browser tab and are not saved.</p>', unsafe_allow_html=True)
    if not common.dataset_ready(svc):
        return
    options = common.cached_options(str(svc.db_path))
    nationality_options = [NOT_SET] + options["nationalities"] + [OTHER]

    with st.form("profile_form", border=True):
        c1, c2 = st.columns(2, gap="large")
        nat = c1.selectbox("Your citizenship", nationality_options, key="m_nat",
                           format_func=lambda v: {NOT_SET: "Choose a country", OTHER: "Another country (type it below)"}.get(v, v))
        other_nat = c1.text_input("Another country", key="m_nat_other", placeholder="e.g. Brazil",
                                  help="Used only when you choose 'Another country'. Matched by exact country name.")
        dest = c1.selectbox("Where would you like to study? (optional)", [NOT_SET] + options["host_countries"],
                            key="m_dest", format_func=lambda v: v or "Anywhere",
                            help="Only narrows the list. It is not an eligibility rule.")
        degree = c2.selectbox("Degree you want to study", [NOT_SET] + list(DEGREES), key="m_degree",
                              format_func=lambda v: DEGREES.get(v, "Choose a degree"))
        subject = c2.selectbox("Subject area", [NOT_SET] + list(SUBJECTS), key="m_subject",
                               format_func=lambda v: SUBJECTS.get(v, "Choose a subject"))
        s1, s2 = c2.columns(2)
        score = s1.number_input("Academic score (optional)", min_value=0.0, max_value=100.0, value=None,
                                step=0.1, key="m_score", placeholder="e.g. 8.2")
        scale = s2.selectbox("Score scale", [NOT_SET] + list(SCORE_SCALES), key="m_scale",
                             format_func=lambda v: SCORE_SCALES[v]["label"] if v else "Choose a scale")
        submitted = st.form_submit_button("Check my fit", type="primary", icon=":material/fact_check:")

    if submitted:
        nationality = other_nat.strip() if nat == OTHER else (nat or None)
        profile = StudentProfile(
            nationality=nationality or None, degree=degree or None, subject=subject or None,
            score=float(score) if score is not None else None, score_scale=scale or None,
            preferred_destination=dest or None,
        )
        errors = validate_profile(profile)
        if errors:
            st.session_state.pop("match_results", None)
            for error in errors:
                st.error(error, icon=":material/error:")
            return
        st.session_state["match_profile"] = profile
        st.session_state["match_results"] = svc.match(profile)

    results = st.session_state.get("match_results")
    if results is None:
        st.info("Fill in what you know and choose **Check my fit**. Anything you leave blank is shown as "
                "*not enough information*, never as a match.", icon=":material/lightbulb:")
        return
    profile = st.session_state["match_profile"]
    if not results:
        st.info("No scholarships in this dataset are hosted in that destination. Try *Anywhere*.")
        return

    groups: dict[str, list] = {key: [] for key in GROUPS}
    for view, match in results:
        groups[match.group].append((view, match))
    for items in groups.values():  # full matches first inside "Good fits", then by name
        items.sort(key=lambda pair: (pair[1].overall != "Matches recorded requirements", pair[0].record.name))

    cols = st.columns(3, gap="medium")
    for col, (key, meta) in zip(cols, GROUPS.items()):
        col.markdown(f'<div class="sp-tile {meta["tile"]}"><b>{len(groups[key])}</b>'
                     f'<strong>{meta["title"]}</strong><span>{meta["blurb"]}</span></div>', unsafe_allow_html=True)

    blanks = sorted({FIELD_NAMES[f] for f, v in (("Nationality", profile.nationality), ("Degree", profile.degree),
                                                    ("Subject", profile.subject), ("Academic score", profile.score))
                     if v in (None, "")})
    if blanks:
        st.info(f"Tip: add your {_join(blanks)} to move more scholarships out of *Need more info*.",
                icon=":material/lightbulb:")
    if profile.preferred_destination:
        st.caption(f"Showing scholarships hosted in {profile.preferred_destination} only.")
    st.caption(DISCLAIMER)

    today = svc.today()
    labels = {key: f"{meta['icon']} {meta['title']} ({len(groups[key])})" for key, meta in GROUPS.items()}
    first_with_results = next((key for key in GROUPS if groups[key]), "fit")
    tabs = st.tabs(list(labels.values()), default=labels[first_with_results])
    for tab, (key, meta) in zip(tabs, GROUPS.items()):
        with tab:
            items = groups[key]
            if not items:
                st.caption(EMPTY_GROUP[key])
                continue
            columns = st.columns(2, gap="medium")
            for index, (view, match) in enumerate(items):
                with columns[index % 2]:
                    _result_card(view, match, today)
