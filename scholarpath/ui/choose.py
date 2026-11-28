"""The first screen (v2): choose internships or scholarships.

Shown once per visit, before anything else. Choosing opens that type's Find page at once.
The choice is kept for the session (and in the address, so a reload keeps it), and the
switch under the menu changes it at any time. Built only from the shared design: white
cards on paper, the serif headings, one primary action per card.
"""

from __future__ import annotations

import streamlit as st

from .. import config
from . import common

CHOICES = (
    (config.KIND_INTERNSHIP, ":material/work:", "Find internships",
     "Internships across India, with Chennai and Bengaluru first, plus remote roles. See stipend, duration, "
     "work arrangement and deadline, then save them and track your applications."),
    (config.KIND_SCHOLARSHIP, ":material/school:", "Find scholarships",
     "International scholarships from official pages. Check who can apply, funding and deadlines, then save "
     "them and track your applications."),
)


def render() -> None:
    with st.container(key="choose_page"):
        st.title("What are you looking for?", anchor=False)
        st.markdown("ScholarPath helps you find, review, save and track opportunities. Choose one to start; "
                    "you can switch at any time from the menu.")
        # A row of two equal cards that wraps to one per line on a phone (style.py: choose_cards).
        with st.container(horizontal=True, gap="medium", key="choose_cards"):
            for kind, icon, label, text in CHOICES:
                _choice(kind, icon, label, text)
        st.caption("Runs only on this computer. ScholarPath never submits anything to an employer or a provider.")


def _choice(kind: str, icon: str, label: str, text: str) -> None:
    with st.container(border=True, key=f"card_choose_{kind}"):
        st.subheader(f"{icon} {label[5:].capitalize()}", anchor=False)
        st.markdown(text)
        st.button(label, key=f"choose_{kind}", on_click=common.choose_kind, args=(kind,), type="primary",
                  icon=":material/arrow_forward:", icon_position="right", width="stretch")
