"""Check my fit: a submitted form with friendly, explainable results.

Presentation only - the verdicts come unchanged from ``matching.evaluate``:
unknown information is never counted as met. Requirements ScholarPath cannot
check (language tests, residence, ...) are gathered into one checklist per
scholarship instead of a warning per line. The profile lives only in this
browser session and is never saved. A result compares answers with recorded
rules; it is never shown as a decision about eligibility.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..matching import (DISCLAIMER, FAILED, SATISFIED, UNKNOWN, InternshipProfile, StudentProfile,
                        validate_internship_profile, validate_profile)
from ..models import DEGREES, DISCIPLINES, INTERN_DEGREES, SCORE_SCALES, STUDY_YEARS, SUBJECTS
from . import common

NOT_SET = ""
OTHER = "__other__"


GROUPS = {
    "fit": {"title": "Good fits", "icon": ":material/verified:",
            "blurb": "Your answers meet every rule ScholarPath could check. The provider still decides."},
    "missing": {"title": "Need more info", "icon": ":material/help:",
                "blurb": "Nothing failed, but some rules couldn't be checked yet."},
    "no_fit": {"title": "Not a fit", "icon": ":material/block:",
               "blurb": "At least one recorded requirement isn't met."},
}
EMPTY_GROUP = {
    "fit": "No full fits yet. Filling in more of the form often moves scholarships here.",
    "missing": "Every scholarship could be checked with what you entered.",
    "no_fit": "Nothing ruled out by the recorded requirements.",
}
FIELD_NAMES = {"Nationality": "citizenship", "Nationality exclusions": "citizenship", "Degree": "degree",
               "Subject": "subject", "Academic score": "score", "Year of study": "year of study",
               "Discipline": "discipline"}
I_HOW_IT_WORKS = """
- **Degree** is compared with the degrees the posting mentions (diploma, bachelor's, master's, PhD).
- **Year of study** is compared with the years the posting asks for. "Final year" counts only if you tick that it is your final year: ScholarPath never guesses how long your course is.
- **Discipline** is compared with ScholarPath's reading of the role title and team (for example *Data Analyst Intern* is Data & analytics).
- **Where you would like to work** only narrows the list. It is not a requirement.
- Anything you leave blank, and anything the posting does not state, counts as *not checked*, never as met.
- Skills, documents and experience are listed for you to confirm on the employer's page.
"""
HOW_IT_WORKS = """
- **Citizenship** is compared with each scholarship's lists of eligible and excluded countries, by exact country name.
- **Degree** and **subject** are compared with the levels and subject areas recorded for it. Subject labels are broad and matched exactly.
- **Score** is compared only when the scholarship publishes a minimum on the same scale. Scores are never converted between scales.
- **Where you would like to study** only narrows the list. It is not an eligibility rule.
- Anything you leave blank, and any rule the source does not publish in a checkable form, counts as *not checked*, never as met.
- Rules ScholarPath cannot check at all (language tests, residence, work experience) are listed for you to confirm on the official page.
"""


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


def _result_card(view, match) -> None:
    rec = view.record
    style = common.OVERALL_STYLE[match.overall]
    auto = match.automatic
    met = [r for r in auto if r.status == SATISFIED]
    failed = [r for r in auto if r.status == FAILED]
    # Rules the source does not publish in a checkable form. Blank answers are already
    # covered by the summary sentence, so they are not repeated line by line.
    source_gaps = [r for r in auto if r.status == UNKNOWN and not r.missing_input]

    with common.card("m", view):
        text, actions = st.columns([4, 1], vertical_alignment="top")
        with text:
            common.card_summary(view)
            st.markdown(f":{style['badge']}-badge[{style['icon']} {match.overall}]")
            st.markdown(common.md_escape(_summary_line(match)))
            lines = [f"- ✕ **{common.md_escape(r.rule)}:** {common.md_escape(r.reason)}" for r in failed]
            lines += [f"- ? **{common.md_escape(r.rule)}:** {common.md_escape(r.reason)}" for r in source_gaps]
            if lines:
                st.markdown("\n".join(lines))
            if auto:
                st.caption(f"{len(met)} of {len(auto)} automatic checks passed")
        with actions:
            common.review_button(view, "m", back="fit", width="stretch")
        if match.manual:
            with st.expander(f"Confirm on the official page ({len(match.manual)})", key=f"m_manual_{rec.id}",
                             icon=":material/checklist:"):
                st.caption("Part of the eligibility rules, but written in a way only you can check.")
                st.markdown("\n".join(f"- {common.md_escape(r.requirement)}" for r in match.manual))
        with st.expander("Every rule, explained", key=f"m_rules_{rec.id}", icon=":material/list_alt:"):
            st.dataframe(pd.DataFrame([{
                "Rule": r.rule, "You": r.student_value, "Recorded requirement": r.requirement,
                "Result": common.RULE_TEXT[r.status], "Why": r.reason,
            } for r in match.rules]), hide_index=True)


def _form(options: dict) -> StudentProfile | None:
    """The form. Returns the submitted profile, or None when it was not submitted or is invalid."""
    nationality_options = [NOT_SET] + options["nationalities"] + [OTHER]
    with st.form("profile_form", border=False):
        st.header("About you", anchor=False)
        st.caption("Every field is optional. Anything left blank is treated as not checked, never as a match.")
        c1, c2 = st.columns(2, gap="large")
        nat = c1.selectbox("Your citizenship", nationality_options, key="m_nat",
                           format_func=lambda v: {NOT_SET: "Choose a country",
                                                  OTHER: "Another country (type it below)"}.get(v, v))
        other_nat = c1.text_input("Country name, if it is not in the list", key="m_nat_other",
                                  placeholder="e.g. Brazil",
                                  help="Used only when you choose 'Another country'. Matched by exact country name.")
        dest = c1.selectbox("Where would you like to study?", [NOT_SET] + options["host_countries"],
                            key="m_dest", format_func=lambda v: v or "Anywhere",
                            help="Only narrows the list. It is not an eligibility rule.")
        degree = c2.selectbox("Degree you want to study", [NOT_SET] + list(DEGREES), key="m_degree",
                              format_func=lambda v: DEGREES.get(v, "Choose a degree"))
        subject = c2.selectbox("Subject area", [NOT_SET] + list(SUBJECTS), key="m_subject",
                               format_func=lambda v: SUBJECTS.get(v, "Choose a subject"))
        s1, s2 = c2.columns(2, vertical_alignment="bottom")
        score = s1.number_input("Academic score", min_value=0.0, max_value=100.0, value=None,
                                step=0.1, key="m_score", placeholder="e.g. 8.2")
        scale = s2.selectbox("Score scale", [NOT_SET] + list(SCORE_SCALES), key="m_scale",
                             format_func=lambda v: SCORE_SCALES[v]["label"] if v else "Choose a scale")
        submitted = st.form_submit_button("Check my fit", type="primary", icon=":material/fact_check:")
    if not submitted:
        return None

    nationality = other_nat.strip() if nat == OTHER else (nat or None)
    profile = StudentProfile(
        nationality=nationality or None, degree=degree or None, subject=subject or None,
        score=float(score) if score is not None else None, score_scale=scale or None,
        preferred_destination=dest or None,
    )
    errors = validate_profile(profile)
    if nat == OTHER and not nationality:
        errors.insert(0, "Type your country's name, or choose it from the list.")
    if errors:
        st.session_state.pop("match_results", None)
        for error in errors:
            st.error(error, icon=":material/error:")
        return None
    return profile


def _internship_form(options: dict) -> InternshipProfile | None:
    """The same form card for internships. Returns the submitted profile, or None."""
    places = [NOT_SET, "remote"] + options["cities"]
    with st.form("profile_form", border=False):
        st.header("About you", anchor=False)
        st.caption("Every field is optional. Anything left blank is treated as not checked, never as a match.")
        c1, c2 = st.columns(2, gap="large")
        degree = c1.selectbox("Degree you are studying (or finished)", [NOT_SET] + list(INTERN_DEGREES), key="im_degree",
                              format_func=lambda v: INTERN_DEGREES.get(v, "Choose a degree"))
        year = c1.selectbox("Year of study", [NOT_SET] + [k for k in STUDY_YEARS if k != "final"], key="im_year",
                            format_func=lambda v: STUDY_YEARS.get(v, "Choose a year"))
        final = c1.checkbox("This is the final year of my course", key="im_final")
        discipline = c2.selectbox("Discipline", [NOT_SET] + list(DISCIPLINES), key="im_disc",
                                  format_func=lambda v: DISCIPLINES.get(v, "Choose a discipline"))
        place = c2.selectbox("Where would you like to work?", places, key="im_place",
                             format_func=lambda v: {NOT_SET: "Anywhere in India", "remote": "Remote"}.get(v, v),
                             help="Only narrows the list. It is not a requirement.")
        submitted = st.form_submit_button("Check my fit", type="primary", icon=":material/fact_check:")
    if not submitted:
        return None
    profile = InternshipProfile(degree=degree or None, year=year or None, final_year=bool(final),
                                discipline=discipline or None, preferred_place=place or None)
    errors = validate_internship_profile(profile)
    if errors:
        st.session_state.pop("match_results", None)
        for error in errors:
            st.error(error, icon=":material/error:")
        return None
    return profile


def render(svc) -> None:
    if common.is_internship(svc):
        return _render_internships(svc)
    common.page_header(svc, "Check my fit",
                       "Enter what you know about yourself. ScholarPath compares each answer with the "
                       "requirements it recorded for every scholarship and shows which rules you meet, which "
                       "you don't, and which it could not check. Your answers stay in this browser tab and "
                       "are not saved.")
    if not common.dataset_ready(svc):
        return
    with st.container(border=True, key="card_fit_form"):
        profile = _form(common.cached_options(str(svc.db_path)))
        with st.expander("How the check works, and its limits", key="fit_how", icon=":material/info:"):
            st.markdown(HOW_IT_WORKS)
            st.caption(DISCLAIMER)

    if profile is not None:
        st.session_state["match_profile"] = profile
        with st.spinner("Comparing your answers with each scholarship..."):
            st.session_state["match_results"] = svc.match(profile)

    results = st.session_state.get("match_results")
    if results is None:
        st.info("Fill in what you know and choose **Check my fit**. Anything you leave blank is shown as "
                "*not enough information*, never as a match.", icon=":material/lightbulb:")
        return
    profile = st.session_state["match_profile"]
    if not results:
        common.empty_state("fit_none", "No scholarships in that destination",
                           "Nothing in this dataset is hosted there. Choose *Anywhere* above and check again.")
        return

    groups: dict[str, list] = {key: [] for key in GROUPS}
    for view, match in results:
        groups[match.group].append((view, match))
    for items in groups.values():  # full matches first inside "Good fits", then by name
        items.sort(key=lambda pair: (pair[1].overall != "Matches recorded requirements", pair[0].record.name))

    st.header("Your results", anchor=False)
    st.info(DISCLAIMER, icon=":material/info:")
    blanks = sorted({FIELD_NAMES[f] for f, v in (("Nationality", profile.nationality), ("Degree", profile.degree),
                                                    ("Subject", profile.subject), ("Academic score", profile.score))
                     if v in (None, "")})
    if blanks:
        st.markdown(f"Tip: add your {_join(blanks)} to move more scholarships out of *Need more info*.")
    if profile.preferred_destination:
        st.caption(f"Showing scholarships hosted in {profile.preferred_destination} only.")

    _result_tabs(groups)


def _group(results) -> dict:
    groups: dict[str, list] = {key: [] for key in GROUPS}
    for view, match in results:
        groups[match.group].append((view, match))
    for items in groups.values():  # full matches first inside "Good fits", then by name
        items.sort(key=lambda pair: (pair[1].overall != "Matches recorded requirements", pair[0].record.name))
    return groups


def _render_internships(svc) -> None:
    common.page_header(svc, "Check my fit",
                       "Enter what you know about yourself. ScholarPath compares each answer with what each "
                       "internship's posting states and shows which you meet, which you don't, and which it could "
                       "not check. Your answers stay in this browser tab and are not saved.")
    if not common.dataset_ready(svc):
        return
    with st.container(border=True, key="card_fit_form"):
        profile = _internship_form(common.cached_options(str(svc.db_path), svc.kind))
        with st.expander("How the check works, and its limits", key="fit_how", icon=":material/info:"):
            st.markdown(I_HOW_IT_WORKS)
            st.caption(DISCLAIMER)
    if profile is not None:
        st.session_state["match_profile"] = profile
        with st.spinner("Comparing your answers with each internship..."):
            st.session_state["match_results"] = svc.match(profile)
    results = st.session_state.get("match_results")
    if results is None:
        st.info("Fill in what you know and choose **Check my fit**. Anything you leave blank is shown as "
                "*not enough information*, never as a match.", icon=":material/lightbulb:")
        return
    profile = st.session_state["match_profile"]
    if not results:
        common.empty_state("fit_none", "No internships in that place",
                           "Nothing in this dataset is in that place. Choose *Anywhere in India* above and check again.")
        return
    st.header("Your results", anchor=False)
    st.info(DISCLAIMER, icon=":material/info:")
    blanks = sorted({name for name, value in (("degree", profile.degree), ("year of study", profile.year),
                                              ("discipline", profile.discipline)) if not value})
    if blanks:
        st.markdown(f"Tip: add your {_join(blanks)} to move more internships out of *Need more info*.")
    if profile.preferred_place:
        shown = "remote internships" if profile.preferred_place == "remote" else f"internships in {profile.preferred_place}"
        st.caption(f"Showing {shown} only.")
    _result_tabs(_group(results))


def _result_tabs(groups: dict) -> None:
    labels = {key: f"{meta['icon']} {meta['title']} ({len(groups[key])})" for key, meta in GROUPS.items()}
    first_with_results = next((key for key in GROUPS if groups[key]), "fit")
    tabs = st.tabs(list(labels.values()), default=labels[first_with_results])
    for tab, (key, meta) in zip(tabs, GROUPS.items()):
        with tab:
            items = groups[key]
            if not items:
                st.caption(EMPTY_GROUP[key])
                continue
            st.caption(meta["blurb"])
            for view, match in items:
                _result_card(view, match)
