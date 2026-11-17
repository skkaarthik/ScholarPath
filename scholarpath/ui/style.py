"""Visual layer.

Almost all styling comes from Streamlit's own theme in .streamlit/config.toml
(colours, fonts, radius, semantic badge/message colours, page padding).
This file adds only what the theme cannot express.

Stable hooks only. Rules start from one of:
* a ``st-key-*`` class, which Streamlit creates from the ``key=`` we give a
  container or widget (a documented feature);
* Streamlit's public element classes (``stMainBlockContainer``, ``stButton`` ...);
* plain elements and states (``h1``, ``:focus-visible``, ``aria-expanded``).
Never generated class names (``st-emotion-cache-*``) or element positions.

Only static, trusted CSS lives here - never data. Keep "<" out of the CSS
comments: Streamlit's HTML sanitiser drops a style block that looks like it
contains a tag, and then none of these rules apply.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).parent / "assets"

CSS = """
<style>
/* --- Tokens (the rest are in .streamlit/config.toml) -------------------------------- */
:root {
  --sp-paper: #FBFAF6;        /* page */
  --sp-sheet: #FFFFFF;        /* cards */
  --sp-line: #E2DED3;         /* hairline around cards and under the menu */
  --sp-ink-2: #4B4955;        /* secondary text and idle menu entries (8.4:1 on paper) */
  --sp-primary: #343A8C;
  --sp-tint: #E9E8F7;         /* soft lavender: highlighted menu entry */
  --sp-tint-strong: #DDDBF2;  /* the same, hovered */
  --sp-focus: #1D4ED8;
  --sp-shadow: 0 1px 2px rgba(18, 17, 24, 0.05);
}

/* --- Page ------------------------------------------------------------------------- */
/* Readable content width on large screens (Streamlit's documented main-container class). */
.stMainBlockContainer { max-width: 70rem; }
h1, h2, h3 { overflow-wrap: anywhere; }             /* very long titles wrap instead of overflowing */
@media (max-width: 40rem) {
  h1 { font-size: 1.75rem !important; }
  .stMainBlockContainer { padding-bottom: 7rem; }   /* room for the menu bar along the bottom */
}

/* --- Cards ------------------------------------------------------------------------
   Any container whose key starts with "card_" is a white sheet on the paper background,
   with a lighter hairline than the input border and a barely visible shadow. */
[class*="st-key-card_"] {
  background: var(--sp-sheet); border-color: var(--sp-line); box-shadow: var(--sp-shadow);
}
/* Rows of metrics: equal white tiles that wrap two-by-two on a phone. */
[class*="st-key-facts_"] > * { flex: 1 1 9rem; min-width: 0; }
[class*="st-key-facts_"] .stMetric {
  background: var(--sp-sheet); border-color: var(--sp-line); box-shadow: var(--sp-shadow);
}

/* --- Buttons ----------------------------------------------------------------------- */
/* Comfortable targets on touch screens and phones (44 CSS px). */
@media (pointer: coarse), (max-width: 40rem) {
  .stButton button, .stLinkButton a, .stDownloadButton button, .stFormSubmitButton button { min-height: 2.75rem; }
}

/* --- Menu ---------------------------------------------------------------------------
   Drawn in app.py from st.page_link and st.popover inside containers keyed by us:
   "app_nav" is the row, "nav_find" (and so on) one entry, "nav_find_current" the
   highlighted entry. Every rule starts from one of those keys. Idle text #4B4955 on paper is 8.4:1;
   highlighted text #343A8C on lavender #E9E8F7 is 8.2:1. */
.st-key-app_nav {
  gap: 0.25rem; padding-bottom: 0.625rem; margin-bottom: 0.25rem; border-bottom: 1px solid var(--sp-line);
}
[class*="st-key-nav_"] :is(a, button) {
  display: flex; align-items: center; gap: 0.5rem; box-sizing: border-box;
  min-height: 2.75rem; min-width: 2.75rem; padding: 0 0.875rem; margin: 0;
  border: 0; border-radius: 0.75rem; text-decoration: none; white-space: nowrap;
  background-color: transparent !important; color: var(--sp-ink-2) !important;
  font-size: 0.9375rem; font-weight: 500; line-height: 1.25;
  transition: background-color 0.15s ease, color 0.15s ease;
}
/* Icon, label and the More chevron take their colour, size and weight from the entry. */
[class*="st-key-nav_"] :is(a, button) * { color: inherit !important; font-weight: inherit !important; }
[class*="st-key-nav_"] :is(a, button) p { margin: 0; font-size: 0.9375rem; line-height: 1.25; }
[class*="st-key-nav_"] button { padding-right: 0.5rem; }             /* the chevron sits closer to the edge */

/* Highlighted entry: lavender pill, purple icon and label, heavier label, filled icon
   (so the state does not depend on colour alone). */
[class*="st-key-nav_"][class*="_current"] :is(a, button) {
  background-color: var(--sp-tint) !important; color: var(--sp-primary) !important;
  font-weight: 650; font-variation-settings: "FILL" 1;
}
@media (hover: hover) {
  [class*="st-key-nav_"] :is(a, button):hover {
    background-color: rgba(52, 58, 140, 0.08) !important; color: var(--sp-primary) !important;
  }
  [class*="st-key-nav_"][class*="_current"] :is(a, button):hover { background-color: var(--sp-tint-strong) !important; }
}
/* The More button while its menu is open. */
[class*="st-key-nav_"] button[aria-expanded="true"] {
  background-color: rgba(52, 58, 140, 0.08) !important; color: var(--sp-primary) !important;
}

/* Phones: the same four entries become a bar along the bottom edge, icon above label,
   so every destination stays one tap away and nothing hides behind the sidebar arrow. */
@media (max-width: 40rem) {
  .st-key-app_nav {
    position: fixed; left: 0; right: 0; bottom: 0; z-index: 100;
    display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); justify-items: center; gap: 0;
    margin: 0; padding: 0.375rem 0.25rem calc(0.375rem + env(safe-area-inset-bottom, 0px));
    background: var(--sp-paper); border-top: 1px solid var(--sp-line); border-bottom: 0;
    box-shadow: 0 -2px 8px rgba(18, 17, 24, 0.04);
  }
  .st-key-app_nav [class*="st-key-nav_"] :is(a, button),
  .st-key-app_nav [class*="st-key-nav_"] button :is(div, span) {
    flex-direction: column; align-items: center; gap: 0.125rem;
  }
  .st-key-app_nav [class*="st-key-nav_"] :is(a, button) {
    justify-content: flex-start; width: 5.25rem; max-width: 100%; min-height: 3.5rem;
    padding: 0.375rem 0.125rem; text-align: center;
  }
  /* Labels may wrap onto two lines ("Find Scholarships"); the icon glyphs must not. */
  .st-key-app_nav [class*="st-key-nav_"] :is(a, button) :not([aria-hidden="true"]) { white-space: normal !important; }
  .st-key-app_nav [class*="st-key-nav_"] :is(a, button) p { font-size: 0.75rem; line-height: 1.15; }
  .st-key-app_nav [class*="st-key-nav_"] button div[aria-hidden="true"] { display: none; }   /* no chevron in the bar */
}

/* --- Focus and motion --------------------------------------------------------------- */
/* One clear keyboard-focus ring everywhere (WCAG 2.4.7 / 2.4.11). */
:focus-visible { outline: 3px solid var(--sp-focus) !important; outline-offset: 2px !important; }

/* Respect "reduce motion". */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; animation: none !important; scroll-behavior: auto !important; }
}
</style>
"""


def inject() -> None:
    st.html(CSS)
    st.logo(str(ASSETS / "logo.svg"), size="large", icon_image=str(ASSETS / "icon.svg"))
