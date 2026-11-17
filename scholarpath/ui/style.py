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

/* --- Navigation ---------------------------------------------------------------------
   Streamlit's top menu has no `key=`, so it is reached through its accessibility markup:
   nav[aria-label="App pages"], aria-current="page" on the open page, aria-expanded on "More".
   The phone row reuses the same look. Palette: primary #343A8C on soft lavender #E9E8F7
   (about 8:1), idle text #4B4955 on paper (about 8:1). */
.stAppHeader { box-shadow: 0 1px 0 #E7E4DB; }
nav[aria-label="App pages"] { gap: 0.25rem; align-items: center; padding-left: 1.125rem; }

:is(nav[aria-label="App pages"] a, nav[aria-label="App pages"] button[aria-haspopup="menu"], .st-key-mobile_nav a) {
  display: inline-flex; align-items: center; gap: 0.5rem; box-sizing: border-box;
  min-height: 2.5rem; padding: 0 0.875rem; border: 0; border-radius: 0.75rem;
  background-color: transparent !important; color: #4B4955 !important;
  font-weight: 500; line-height: 1.25; text-decoration: none; white-space: nowrap;
  transition: background-color 0.15s ease, color 0.15s ease;
}
/* Same size, weight and colour for every icon, label and the "More" chevron. */
:is(nav[aria-label="App pages"], .st-key-mobile_nav) :is(a, button) :is(span, p, div, svg) { color: inherit !important; }
:is(nav[aria-label="App pages"], .st-key-mobile_nav) :is(a, button) p {
  margin: 0; line-height: 1.25; font-weight: 500 !important;   /* constant weight: the open tab never shifts its neighbours */
}
:is(nav[aria-label="App pages"], .st-key-mobile_nav) span[translate="no"] {
  font-size: 1.25rem; width: 1.25rem; height: 1.25rem; line-height: 1; font-weight: 400 !important;
  font-variation-settings: "FILL" 0, "wght" 400, "GRAD" 0, "opsz" 20;
}
nav[aria-label="App pages"] button[aria-haspopup="menu"] { gap: 0.125rem; padding-right: 0.625rem; }
nav[aria-label="App pages"] button[aria-haspopup="menu"] > div { display: flex; margin: 0; padding: 0; }
nav[aria-label="App pages"] button[aria-haspopup="menu"] svg { width: 1.25rem; height: 1.25rem; }

/* Open page and open "More" menu: lavender pill, purple text and icon. */
:is(nav[aria-label="App pages"] a[aria-current="page"], nav[aria-label="App pages"] button[aria-expanded="true"],
    [class*="st-key-mobile_nav_"][class*="_current"] a) {
  background-color: #E9E8F7 !important; color: #343A8C !important;
}
@media (hover: hover) {
  :is(nav[aria-label="App pages"] a, nav[aria-label="App pages"] button[aria-haspopup="menu"], .st-key-mobile_nav a):hover {
    background-color: rgba(52, 58, 140, 0.08) !important; color: #343A8C !important;
  }
  :is(nav[aria-label="App pages"] a[aria-current="page"], [class*="st-key-mobile_nav_"][class*="_current"] a):hover {
    background-color: #E1E0F3 !important;
  }
}
/* Comfortable touch targets, and a row that wraps instead of overflowing on very narrow phones. */
@media (max-width: 767.98px), (pointer: coarse) {
  :is(nav[aria-label="App pages"] a, nav[aria-label="App pages"] button[aria-haspopup="menu"], .st-key-mobile_nav a) {
    min-height: 2.75rem;
  }
}
.st-key-mobile_nav { gap: 0.25rem; }

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
