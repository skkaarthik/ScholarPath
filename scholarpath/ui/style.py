"""Visual layer: one stylesheet injected once per page run.

Only static, trusted CSS lives here - never data. Hover and press feedback
uses short transitions (150-200 ms) and is switched off for people who ask
their system to reduce motion. Cards are targeted through the `card_*`
container keys so the effect applies only to interactive result cards.
"""

from __future__ import annotations

import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

:root {
  --sp-ink: #14213D;
  --sp-teal: #0E7C7B;
  --sp-teal-soft: #E3F2F1;
  --sp-marigold: #F2B632;
  --sp-text: #1B2233;
  --sp-muted: #5B6478;
  --sp-line: #DCE2EC;
  --sp-ease: cubic-bezier(.2, .7, .2, 1);
}

/* Page rhythm */
.block-container { padding-top: 3.6rem; max-width: 1200px; }
h1 { letter-spacing: -0.02em; }
h2, h3 { letter-spacing: -0.01em; }

/* Sidebar: the passport cover. The page menu (key "page") is styled as a nav list. */
.st-key-page, .st-key-page [data-testid="stRadio"], .st-key-page [data-testid="stRadio"] > div { width: 100% !important; }
.st-key-page [role="radiogroup"] { gap: 2px; width: 100%; display: flex; flex-direction: column; }
.st-key-page [role="radiogroup"] > div, .st-key-page [role="radiogroup"] > div > label { width: 100% !important; max-width: none !important; }
.st-key-page label[data-testid="stRadioOption"] {
  width: 100%; padding: .55rem .75rem; border-radius: .6rem; margin: 0; cursor: pointer;
  transition: background-color .18s var(--sp-ease), box-shadow .18s var(--sp-ease), transform .18s var(--sp-ease);
}
.st-key-page label[data-testid="stRadioOption"] > div > div:first-child { display: none; }
.st-key-page label[data-testid="stRadioOption"] p { font-size: .97rem; font-weight: 500; color: #D5DCEB; }
.st-key-page label[data-testid="stRadioOption"]:hover { background: rgba(255, 255, 255, .07) !important; transform: translateX(2px); }
.st-key-page label[data-testid="stRadioOption"][data-selected="true"],
.st-key-page label[data-testid="stRadioOption"][data-selected="true"]:hover {
  background: rgba(255, 255, 255, .12) !important; box-shadow: inset 3px 0 0 var(--sp-marigold);
}
.st-key-page label[data-testid="stRadioOption"][data-selected="true"] p { color: #FFFFFF; font-weight: 650; }
.st-key-page label[data-testid="stRadioOption"][data-focus-visible="true"] { outline: 3px solid var(--sp-marigold); outline-offset: 1px; }
.sp-brand { font-size: 1.35rem; font-weight: 800; letter-spacing: -0.02em; color: #FFFFFF; margin: .2rem 0 .1rem; }
.sp-brand-sub { color: #AEB9D1; font-size: .85rem; margin-bottom: 1rem; }

/* Interactive cards (containers with key card_*) */
div[class*="st-key-card_"] {
  background: #FFFFFF;
  border: 1px solid var(--sp-line) !important;
  border-radius: .9rem !important;
  box-shadow: 0 1px 2px rgba(20, 33, 61, .04);
  transition: transform .2s var(--sp-ease), box-shadow .2s var(--sp-ease), border-color .2s var(--sp-ease);
}
div[class*="st-key-card_"]:hover {
  transform: translateY(-2px);
  border-color: rgba(14, 124, 123, .55) !important;
  box-shadow: 0 10px 24px -12px rgba(20, 33, 61, .28);
}
div[class*="st-key-card_"]:focus-within { border-color: var(--sp-teal) !important; }
div[class*="st-key-card_urgent_"] { border-left: 4px solid var(--sp-marigold) !important; }

/* Metric tiles */
div[data-testid="stMetric"] {
  background: #FFFFFF; border: 1px solid var(--sp-line); border-radius: .9rem;
  padding: .9rem 1.1rem;
  transition: border-color .2s var(--sp-ease), box-shadow .2s var(--sp-ease);
}
div[data-testid="stMetric"]:hover { border-color: rgba(14, 124, 123, .45); box-shadow: 0 8px 20px -14px rgba(20, 33, 61, .35); }
div[data-testid="stMetricValue"] { font-weight: 750; letter-spacing: -0.02em; }

/* Buttons: smooth colour change and a gentle press */
.stButton > button, .stDownloadButton > button, .stLinkButton > a, .stFormSubmitButton > button {
  font-weight: 600;
  transition: background-color .16s var(--sp-ease), border-color .16s var(--sp-ease),
              color .16s var(--sp-ease), transform .12s var(--sp-ease), box-shadow .16s var(--sp-ease);
}
.stButton > button:hover, .stDownloadButton > button:hover, .stLinkButton > a:hover, .stFormSubmitButton > button:hover {
  box-shadow: 0 4px 12px -6px rgba(14, 124, 123, .55);
}
.stButton > button:active, .stDownloadButton > button:active, .stFormSubmitButton > button:active { transform: scale(.98); }
button:focus-visible, a:focus-visible, [role="radio"]:focus-visible {
  outline: 3px solid var(--sp-marigold) !important; outline-offset: 2px;
}

/* Expanders, tabs, tables */
details[data-testid="stExpander"] { border-radius: .8rem; transition: border-color .2s var(--sp-ease); }
details[data-testid="stExpander"]:hover { border-color: rgba(14, 124, 123, .45); }
details[data-testid="stExpander"] summary:hover p { color: var(--sp-teal); }
.stTabs [data-baseweb="tab"] { transition: color .16s var(--sp-ease); }
.stTabs [data-baseweb="tab"]:hover { color: var(--sp-teal); }
div[data-testid="stDataFrame"] { border-radius: .7rem; overflow: hidden; }

/* Small type helpers used by cards */
.sp-card-title { font-weight: 700; font-size: 1.05rem; line-height: 1.3; color: var(--sp-text); }
.sp-card-title.sp-small { font-size: .95rem; }
.sp-provider { color: var(--sp-muted); font-size: .88rem; margin-top: .15rem; }
.sp-hero-sub { color: var(--sp-muted); font-size: 1.05rem; max-width: 64ch; margin-top: -.4rem; line-height: 1.55; }

/* Dataset banner: clear but calm */
.sp-banner {
  border-radius: .8rem; padding: .7rem 1rem; margin-bottom: 1rem; font-size: .92rem; line-height: 1.45;
  border: 1px solid transparent;
}
.sp-banner-example { background: #EEF0FF; border-color: #D3D7FA; color: #2E3170; }
.sp-banner-real { background: #E6F4F3; border-color: #C3E3E1; color: #0B4F4E; }

/* Progress bars in match cards */
div[data-testid="stProgress"] > div > div > div > div { background-color: var(--sp-teal); }


/* Sidebar depth: a quiet gradient like a passport cover */
section[data-testid="stSidebar"] > div:first-child {
  background: linear-gradient(180deg, #14213D 0%, #182A4E 55%, #1B3159 100%);
}
.sp-brand { display: flex; align-items: center; gap: .55rem; }
.sp-brand svg { flex: none; }

/* Overview hero: the one bold element. A dotted flight path crosses the panel. */
.st-key-hero {
  position: relative; overflow: hidden;
  background:
    url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 600 260'><path d='M20 230 C 180 40, 400 20, 580 70' fill='none' stroke='%23F2B632' stroke-opacity='.55' stroke-width='2.5' stroke-dasharray='2 10' stroke-linecap='round'/><circle cx='20' cy='230' r='6' fill='%23F2B632'/><circle cx='580' cy='70' r='7' fill='none' stroke='%23F2B632' stroke-width='2.5'/><circle cx='580' cy='70' r='2.5' fill='%23F2B632'/></svg>") right 0 top 18px / 40% auto no-repeat,
    radial-gradient(120% 140% at 100% 0%, #1F6F78 0%, rgba(31, 111, 120, 0) 55%),
    linear-gradient(135deg, #14213D 0%, #1B2F5A 70%);
  border: none !important; border-radius: 1.25rem !important;
  padding: 2.2rem 2.4rem 2rem !important;
  box-shadow: 0 18px 40px -24px rgba(20, 33, 61, .65);
}
.st-key-hero h1 { color: #FFFFFF; font-size: 2.5rem; line-height: 1.12; max-width: 16ch; padding-top: 0; }
@media (max-width: 900px) { .st-key-hero { background-size: 0 0, auto, auto !important; } .st-key-hero h1 { font-size: 1.9rem; } }
.st-key-hero .sp-hero-sub { color: #C9D3E8; margin-top: .25rem; max-width: 52ch; }
.st-key-hero .stButton > button { border-radius: .7rem; padding: .55rem 1rem; }
.st-key-hero .stButton > button[kind="primary"] { background: var(--sp-marigold); border-color: var(--sp-marigold); color: #14213D; }
.st-key-hero .stButton > button[kind="primary"]:hover { background: #F5C451; border-color: #F5C451; box-shadow: 0 6px 18px -8px rgba(242, 182, 50, .8); }
.st-key-hero .stButton > button[kind="secondary"] { background: rgba(255, 255, 255, .06); border-color: rgba(255, 255, 255, .35); color: #FFFFFF; }
.st-key-hero .stButton > button[kind="secondary"]:hover { background: rgba(255, 255, 255, .14); border-color: rgba(255, 255, 255, .6); color: #FFFFFF; box-shadow: none; }
.sp-today { display: inline-block; color: #F2D58B; font-size: .85rem; font-weight: 600; margin-bottom: .35rem; }

/* Match result groups: three calm tiles */
.sp-tile { border-radius: .9rem; padding: .85rem 1rem; border: 1px solid; height: 100%; margin-bottom: .6rem; }
.sp-tile strong { display: block; font-weight: 700; margin-top: .1rem; }
.sp-tile b { display: block; font-size: 1.7rem; font-weight: 780; letter-spacing: -0.02em; line-height: 1.1; }
.sp-tile span { font-size: .9rem; }
.sp-tile-fit { background: #E7F5EE; border-color: #BFE3CF; color: #14532D; }
.sp-tile-missing { background: #EAF1FB; border-color: #C9DAF3; color: #1E3A6E; }
.sp-tile-no { background: #F1F3F6; border-color: #DDE2E9; color: #3F4859; }
.sp-why { color: var(--sp-muted); font-size: .92rem; margin: .1rem 0 .2rem; }
.sp-rule { display: flex; gap: .55rem; align-items: flex-start; font-size: .86rem; line-height: 1.4;
           color: #3F4859; padding: .2rem 0; }
.sp-rule > span { flex: none; width: 1.15rem; height: 1.15rem; border-radius: 50%; font-size: .72rem; font-weight: 800;
                  display: inline-flex; align-items: center; justify-content: center; margin-top: .08rem; }
.sp-rule b { color: var(--sp-text); font-weight: 650; margin-right: .2rem; }
.sp-rule-no > span { background: #F3E1E1; color: #9B2C2C; }
.sp-rule-open > span { background: #E3ECF8; color: #1E3A6E; }
.sp-rule:last-of-type { margin-bottom: .4rem; }

/* Section headings inside cards stay compact */
div[data-testid="stVerticalBlockBorderWrapper"] h4 { font-size: 1.05rem; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; animation: none !important; }
  div[class*="st-key-card_"]:hover { transform: none; }
}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def brand() -> None:
    """Static sidebar title (no user data)."""
    st.markdown(
        '<div class="sp-brand">'
        '<svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true">'
        '<rect x="1" y="1" width="30" height="30" rx="9" fill="#F2B632"/>'
        '<path d="M8 21 C 12 12, 19 10, 25 11" fill="none" stroke="#14213D" stroke-width="2.2" '
        'stroke-linecap="round" stroke-dasharray="1.5 3.5"/>'
        '<circle cx="8" cy="21" r="2.4" fill="#14213D"/><circle cx="25" cy="11" r="2.6" fill="#14213D"/>'
        '</svg>ScholarPath</div>'
        '<div class="sp-brand-sub">Find, check and track scholarships</div>', unsafe_allow_html=True)
