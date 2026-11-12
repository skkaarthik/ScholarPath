"""Profile matching: a submitted form (no recalculation on every keystroke) with per-rule explanations.

The profile lives only in this browser session; it is not saved to the database.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..matching import DISCLAIMER, StudentProfile, validate_profile
from ..models import DEGREES, SCORE_SCALES, SUBJECTS
from . import common

NOT_SET = ""
OTHER = "__other__"


def render(svc) -> None:
    st.title("Profile matching")
    st.caption("Your answers are used only in this session and are not saved.")
    if not common.dataset_ready(svc):
        return
    options = common.cached_options(str(svc.db_path))
    nationality_options = [NOT_SET] + options["nationalities"] + [OTHER]

    with st.form("profile_form"):
        c1, c2 = st.columns(2)
        nat = c1.selectbox("Nationality (citizenship)", nationality_options, key="m_nat",
                           format_func=lambda v: {NOT_SET: "- not specified -", OTHER: "Other (type below)"}.get(v, v))
        other_nat = c1.text_input("Other nationality", key="m_nat_other",
                                  help="Used only if you chose 'Other'. Matching is by exact country name.")
        degree = c2.selectbox("Intended degree", [NOT_SET] + list(DEGREES), key="m_degree",
                              format_func=lambda v: DEGREES.get(v, "- not specified -"))
        subject = c2.selectbox("Intended subject", [NOT_SET] + list(SUBJECTS), key="m_subject",
                               format_func=lambda v: SUBJECTS.get(v, "- not specified -"))
        c3, c4, c5 = st.columns(3)
        score = c3.number_input("Academic score (optional)", min_value=0.0, max_value=100.0, value=None,
                                step=0.1, key="m_score")
        scale = c4.selectbox("Score scale", [NOT_SET] + list(SCORE_SCALES), key="m_scale",
                             format_func=lambda v: SCORE_SCALES[v]["label"] if v else "- not specified -")
        dest = c5.selectbox("Preferred destination (filter only)", [NOT_SET] + options["host_countries"],
                            key="m_dest", format_func=lambda v: v or "- any -")
        submitted = st.form_submit_button("Check recorded requirements")

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
                st.error(error)
            return
        st.session_state["match_profile"] = profile
        st.session_state["match_results"] = svc.match(profile)

    results = st.session_state.get("match_results")
    if results is None:
        st.info("Fill in what you know and press **Check recorded requirements**. Anything you leave blank "
                "is reported as unknown, never as satisfied.")
        return
    profile = st.session_state["match_profile"]
    st.warning(DISCLAIMER, icon="ℹ️")
    if profile.preferred_destination:
        st.caption(f"Showing only scholarships hosted in {profile.preferred_destination} (a filter, not an "
                   "eligibility rule).")
    if not results:
        st.info("No scholarships in this dataset for the chosen destination.")
        return

    summary = pd.Series([m.overall for _, m in results]).value_counts()
    cols = st.columns(3)
    for col, (overall, badge) in zip(cols, common.OVERALL_BADGES.items()):
        col.metric(badge, int(summary.get(overall, 0)))

    today = svc.today()
    for view, match in results:
        with st.expander(f"{common.OVERALL_BADGES[match.overall]} — {view.record.name} ({view.record.provider})"):
            st.markdown(f"**Deadline (separate from matching):** {common.deadline_text(view, today)}")
            table = pd.DataFrame([{
                "Rule": r.rule, "Your value": r.student_value, "Recorded requirement": r.requirement,
                "Status": common.RULE_BADGES[r.status], "Why": r.reason,
            } for r in match.rules])
            st.dataframe(table, hide_index=True)
            st.button("Open details", key=f"m_open_{view.record.id}", on_click=common.go_to,
                      args=("Scholarship details", view.record.id))
