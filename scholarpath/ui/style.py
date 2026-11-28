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

/* --- Opportunity type (v2) ----------------------------------------------------------
   "kind_bar" is the labelled Internships / Scholarships switch just under the menu: a quiet
   row on wide screens, at the top of the page on phones (the bottom bar keeps its four entries).
   "nav_switch_kind" is the same switch inside the More menu. "choose_page" and "card_choose_*"
   are the first screen: two equal white cards, one primary action each. */
.st-key-kind_bar { margin-bottom: 0.25rem; }
.st-key-kind_bar label p { color: var(--sp-ink-2); font-size: 0.875rem; }
.st-key-kind_pick button { min-height: 2.75rem; }
.st-key-nav_switch_kind { border-top: 1px solid var(--sp-line); padding-top: 0.25rem; margin-top: 0.25rem; }
.st-key-nav_switch_kind button { justify-content: flex-start; min-height: 2.75rem; color: var(--sp-ink-2); }
.st-key-choose_page { max-width: 52rem; margin: 2.5rem auto 0; }
/* Equal cards side by side; each card's button sits at its foot so the two line up. */
.st-key-choose_cards { flex-wrap: wrap; align-items: stretch !important; }
.st-key-choose_cards > * { flex: 1 1 18rem; min-width: 0; }
[class*="st-key-card_choose_"] { padding: 0.5rem 0.25rem; }
[class*="st-key-card_choose_"] > :last-child { margin-top: auto; }
[class*="st-key-card_choose_"] h3 { font-size: 1.45rem; }
@media (max-width: 40rem) {
  .st-key-choose_page { margin-top: 1rem; }
}

/* --- Assistant ---------------------------------------------------------------------
   ui/chatbot.py. "chat_fab" is the Ask ScholarPath button; "chat_panel" the chat window that
   replaces it in the bottom-right corner (a sheet above the menu bar on phones). Colours and
   hover follow the menu: idle ink-2, hover 8 % indigo tint with indigo text, highlight lavender. */
.st-key-chat_fab { position: fixed; right: 1.5rem; bottom: 1.5rem; z-index: 101; width: auto !important; }
.st-key-chat_fab button {
  min-height: 3rem; padding: 0 1.125rem; border-radius: 999px; border: 1px solid var(--sp-primary);
  background: var(--sp-primary); color: #FFFFFF; box-shadow: 0 4px 14px rgba(52, 58, 140, 0.28);
  transition: background-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
}
.st-key-chat_fab button * { color: #FFFFFF !important; }
@media (hover: hover) {
  .st-key-chat_fab button:hover {
    background: #2A2F75; border-color: #2A2F75; box-shadow: 0 6px 18px rgba(52, 58, 140, 0.36); transform: translateY(-1px);
  }
}

/* The window. */
.st-key-chat_panel {
  position: fixed; right: 1.5rem; bottom: 1.5rem; z-index: 101;
  width: min(25rem, calc(100vw - 3rem)) !important; max-height: min(42rem, calc(100vh - 3rem));
  gap: 0 !important; overflow: hidden;
  background: var(--sp-paper); border: 1px solid var(--sp-line); border-radius: 1rem;
  box-shadow: 0 16px 40px rgba(18, 17, 24, 0.16), 0 2px 6px rgba(18, 17, 24, 0.06);
}
.st-key-chat_panel > * { flex-shrink: 0; }
/* Streamlit pulls every text block up by 1rem (a negative bottom margin); inside the compact
   window that makes lines overlap, so text blocks keep their natural height here. */
.st-key-chat_panel div:has(> p) { margin-bottom: 0 !important; }
.st-key-chat_status { padding: 0.5rem 1rem 0; }
.st-key-chat_status p { margin: 0; font-size: 0.8125rem; }

/* Header: icon tile, title and context, Clear and Close as round icon buttons. */
.st-key-chat_head {
  padding: 0.75rem 0.75rem 0.75rem 1rem; background: var(--sp-sheet); border-bottom: 1px solid var(--sp-line);
}
.st-key-chat_icon {
  display: flex; align-items: center; justify-content: center; flex: 0 0 auto;
  width: 2.5rem !important; height: 2.5rem; border-radius: 0.75rem; background: var(--sp-tint);
}
.st-key-chat_icon p { margin: 0; color: var(--sp-primary); font-size: 1.25rem; line-height: 1; }
.st-key-chat_title { flex: 1 1 auto; min-width: 0; }
.st-key-chat_title p { margin: 0; line-height: 1.3; }
.st-key-chat_title { gap: 0.125rem; }
.st-key-chat_title > :last-child p {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--sp-ink-2); font-size: 0.8125rem;
}
:is(.st-key-chat_clear, .st-key-chat_close) { width: auto !important; }
:is(.st-key-chat_clear, .st-key-chat_close) button {
  width: 2.5rem; min-width: 2.5rem; min-height: 2.5rem; padding: 0; justify-content: center;
  border-radius: 0.75rem; color: var(--sp-ink-2); transition: background-color 0.15s ease, color 0.15s ease;
}
:is(.st-key-chat_clear, .st-key-chat_close, .st-key-chat_fab) button p {
  position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap;
}
.st-key-chat_fab button p { position: static; width: auto; height: auto; overflow: visible; clip: auto; }

/* Messages: scroll inside the window, newest at the bottom (column-reverse keeps it in view). */
.st-key-chat_msgs {
  display: flex; flex-direction: column-reverse; justify-content: flex-start !important;
  overflow-y: auto; overscroll-behavior: contain;
  flex: 1 1 auto !important; min-height: 8rem; max-height: 26rem; padding: 0.75rem 1rem;
}
.st-key-chat_msgs > * { flex-shrink: 0; }                 /* the content scrolls instead of shrinking */
.st-key-chat_msgs_inner { gap: 0.625rem; }
[class*="st-key-chat_user_"], [class*="st-key-chat_bot_"] { padding: 0.5rem 0.875rem; gap: 0.25rem; }
[class*="st-key-chat_user_"] p, [class*="st-key-chat_bot_"] p, [class*="st-key-chat_bot_"] li { font-size: 0.9375rem; }
[class*="st-key-chat_user_"] p:last-child, [class*="st-key-chat_bot_"] p:last-child { margin-bottom: 0; }
/* The student's messages: lavender bubbles on the right. */
[class*="st-key-chat_user_"] {
  width: fit-content !important; max-width: 85%; margin-left: auto;
  background: var(--sp-tint); color: #121118; border-radius: 1rem 1rem 0.25rem 1rem;
}
/* The assistant's answers: white sheets on the left, like the site's cards. */
[class*="st-key-chat_bot_"] {
  max-width: 94%; margin-right: auto; background: var(--sp-sheet);
  border: 1px solid var(--sp-line); border-radius: 1rem 1rem 1rem 0.25rem; box-shadow: var(--sp-shadow);
}
.st-key-chat_thinking { padding: 0.25rem 0.25rem; color: var(--sp-ink-2); }

/* Starter questions: outlined chips that take the menu's hover. */
.st-key-chat_starters button {
  justify-content: flex-start; text-align: left; min-height: 2.5rem; padding: 0.5rem 0.875rem;
  background: var(--sp-sheet); border: 1px solid var(--sp-line); border-radius: 0.75rem; color: var(--sp-ink-2);
  transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}
.st-key-chat_starters button > div { justify-content: flex-start; }
/* Links under an answer: indigo, compact. */
[class*="st-key-chat_ref_"] { flex-wrap: wrap; row-gap: 0; }
[class*="st-key-chat_ref_"] button, [class*="st-key-chat_ref_"] a {
  min-height: 2.25rem; padding: 0 0.5rem; border-radius: 0.5rem; color: var(--sp-primary) !important;
  transition: background-color 0.15s ease;
}
[class*="st-key-chat_ref_"] :is(button, a) p { font-size: 0.875rem; font-weight: 600; text-align: left; }

@media (hover: hover) {
  :is(.st-key-chat_clear, .st-key-chat_close, .st-key-chat_starters, [class*="st-key-chat_ref_"]) :is(button, a):hover {
    background-color: rgba(52, 58, 140, 0.08) !important; color: var(--sp-primary) !important;
  }
  .st-key-chat_starters button:hover { border-color: var(--sp-tint-strong); }
  .st-key-chat_starters button:hover * { color: var(--sp-primary) !important; }
}

/* Question field and Send. */
.st-key-chat_foot {
  padding: 0.75rem 1rem 1rem; background: var(--sp-sheet); border-top: 1px solid var(--sp-line);
}
.st-key-chat_input_row { flex-wrap: nowrap !important; }
.st-key-chat_input_row > :first-child { flex: 1 1 0; width: auto !important; min-width: 0; }
.st-key-chat_input_row > :last-child { flex: 0 0 auto; width: auto !important; }
.st-key-chat_input_row button { min-height: 2.5rem; border-radius: 0.75rem; }
/* Streamlit's "Press Enter to submit form" hint sits right after the field's box and covers the
   text in this narrow field; the Send button next to it already says what to do. */
.st-key-chat_input_row div:has(> div > input) + div { display: none; }

/* Phones: a sheet above the menu bar, the full width of the screen. */
@media (max-width: 40rem) {
  .st-key-chat_fab { right: 0.75rem; bottom: calc(5.25rem + env(safe-area-inset-bottom, 0px)); }
  .st-key-chat_fab button { width: 3.25rem; min-height: 3.25rem; padding: 0; justify-content: center; }
  .st-key-chat_fab button p {
    position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap;
  }
  .st-key-chat_panel {
    left: 0.5rem; right: 0.5rem; width: auto !important;
    bottom: calc(4.75rem + env(safe-area-inset-bottom, 0px)); max-height: calc(100vh - 6.5rem);
  }
  .st-key-chat_msgs { max-height: 52vh; }
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
