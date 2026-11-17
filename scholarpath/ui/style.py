"""Visual layer.

Almost all styling comes from Streamlit's own theme in .streamlit/config.toml.
This file adds only what the theme cannot express. Rules deliberately target
either `st-key-*` classes (created by the `key=` we give a container, a
documented Streamlit feature) or plain element states - never generated
class names or internal test IDs, which change between Streamlit versions.

Only static, trusted CSS lives here - never data.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).parent / "assets"

CSS = """
<style>
/* Readable content width on large screens (Streamlit's documented main-container class). */
.stMainBlockContainer { max-width: 70rem; padding-top: 3.5rem; }

/* Cards: any container whose key starts with "card_" is a white sheet on the paper background. */
[class*="st-key-card_"] { background: #FFFFFF; }

/* The row of main-section links (key "mobile_nav" in app.py) is only for phone widths. */
@media (min-width: 768px) { .st-key-mobile_nav { display: none; } }
@media (max-width: 767.98px) { .stMainBlockContainer { padding-top: 4.25rem; } }

/* One clear keyboard-focus ring everywhere (WCAG 2.4.7 / 2.4.11). */
:focus-visible { outline: 3px solid #1D4ED8 !important; outline-offset: 2px !important; }

/* Respect "reduce motion". */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; animation: none !important; scroll-behavior: auto !important; }
}
</style>
"""


def inject() -> None:
    st.html(CSS)
    st.logo(str(ASSETS / "logo.svg"), size="large", icon_image=str(ASSETS / "icon.svg"))
