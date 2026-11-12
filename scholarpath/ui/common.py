"""Shared Streamlit helpers: dataset mode, service access, cached reads, safe rendering, cards.

UI modules call services only; no SQL, HTTP or JSON reads happen here.
Cached reads are keyed by database path (so modes never share cache entries)
and are cleared after every successful write.

Rendering safety: untrusted text goes through ``md_escape`` (Markdown) or
``html.escape`` (the few HTML snippets). Raw HTML from sources is never shown.
"""

from __future__ import annotations

import html
import re

import streamlit as st

from .. import config
from ..cleaning import is_http_url
from ..dates import STATUS_LABELS, describe_deadline
from ..models import DEGREES, FUNDING_CATEGORIES, SUBJECTS, ScholarshipRecord
from ..repository import SearchFilters
from ..services import ScholarPathService

PAGES = ["Overview", "Explore", "Profile matching", "Scholarship details", "My applications", "Insights"]
PAGE_ICONS = {
    "Overview": ":material/home:",
    "Explore": ":material/travel_explore:",
    "Profile matching": ":material/fact_check:",
    "Scholarship details": ":material/description:",
    "My applications": ":material/assignment:",
    "Insights": ":material/insights:",
}

# Plain-text status labels (tables, CSV-like views). Words carry the meaning.
STATUS_TEXT = {"open": "Open", "expired": "Expired", "rolling": "Rolling", "unknown": "Unknown"}
RULE_TEXT = {"satisfied": "✓ Met", "failed": "✕ Not met", "unknown": "? To confirm"}

# Overall verdicts keep the exact wording from matching.py; only the presentation differs.
OVERALL_STYLE = {
    "Matches recorded requirements": {"badge": "green", "icon": ":material/verified:", "group": "Good fits"},
    "Needs manual verification": {"badge": "blue", "icon": ":material/checklist:", "group": "Check a few details"},
    "Does not match recorded requirements": {"badge": "gray", "icon": ":material/block:", "group": "Not eligible"},
}

# Keys of temporary selections that must not survive a dataset switch.
MODE_SCOPED_KEYS = ("selected_id", "match_results", "match_profile", "tracker_pick",
                    "f_text", "f_hosts", "f_degrees", "f_subjects", "f_funding", "f_status", "f_sort")


# --- mode & navigation ----------------------------------------------------------

def current_mode() -> str:
    return st.session_state.setdefault("mode", config.MODE_EXAMPLE)


def on_mode_change() -> None:
    for key in MODE_SCOPED_KEYS:
        st.session_state.pop(key, None)


def go_to(page: str, scholarship_id: str | None = None) -> None:
    """Button callback: switch page (and optionally the selected scholarship)."""
    st.session_state["page"] = page
    if scholarship_id:
        st.session_state["selected_id"] = scholarship_id


def page_label(page: str) -> str:
    return f"{PAGE_ICONS[page]} {page}"


def service() -> ScholarPathService:
    return ScholarPathService(current_mode())


def dataset_ready(svc: ScholarPathService) -> bool:
    """Explain how to set up an empty dataset (never a silent fallback to the other one)."""
    if svc.database_exists():
        svc.ensure_schema()
        if cached_overview(str(svc.db_path), svc.today().isoformat())["scholarships"] > 0:
            return True
    command = ("python -m scholarpath init-examples" if svc.mode == config.MODE_EXAMPLE
               else "python -m scholarpath import-real")
    with st.container(border=True, key="setup_needed"):
        st.markdown(f"#### :material/database: Set up the {config.MODE_LABELS[svc.mode].lower()}")
        st.markdown("This dataset has no scholarships yet. In Terminal, inside the ScholarPath folder, run:")
        st.code(command, language="bash")
        st.markdown("Then reload this page. ScholarPath never swaps in the other dataset by itself.")
        st.caption(f"Database file: {svc.db_path}")
    return False


def mode_banner(svc: ScholarPathService) -> None:
    """Clear, calm dataset label (static text only)."""
    if svc.mode == config.MODE_EXAMPLE:
        st.markdown(
            '<div class="sp-banner sp-banner-example"><strong>Example data.</strong> Every scholarship here '
            "is invented for practice, so don't apply to them. Switch to <em>Real sources</em> in the "
            "sidebar for collected scholarships.</div>", unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="sp-banner sp-banner-real"><strong>Real sources.</strong> Collected from official '
            "pages on the date shown in each record. Details can change, so confirm on the official page "
            "before you apply.</div>", unsafe_allow_html=True)


def after_write() -> None:
    """Refresh cached reads after a committed write."""
    st.cache_data.clear()


# --- cached reads (keyed by DB path + date, so modes and days never mix) ---------

def _svc_for(db_path: str) -> ScholarPathService:
    mode = config.MODE_EXAMPLE if db_path == str(config.db_path(config.MODE_EXAMPLE)) else config.MODE_REAL
    return ScholarPathService(mode, db_path=db_path)


@st.cache_data(show_spinner=False)
def cached_search(db_path: str, today: str, filters: tuple, sort: str):
    keys = ("text", "host_countries", "degrees", "subjects", "funding", "deadline_statuses")
    values = dict(zip(keys, filters))
    values = {k: (list(v) if isinstance(v, tuple) else v) for k, v in values.items()}
    return _svc_for(db_path).search(SearchFilters(**values), sort)


@st.cache_data(show_spinner=False)
def cached_overview(db_path: str, today: str) -> dict:
    return _svc_for(db_path).overview()


@st.cache_data(show_spinner=False)
def cached_options(db_path: str) -> dict:
    return _svc_for(db_path).filter_options()


def filters_key(f: SearchFilters) -> tuple:
    return (f.text, tuple(f.host_countries), tuple(f.degrees), tuple(f.subjects), tuple(f.funding),
            tuple(f.deadline_statuses))


def explore_filters() -> SearchFilters:
    """Current Explore selections (temporary UI state only)."""
    ss = st.session_state
    return SearchFilters(
        text=ss.get("f_text", ""), host_countries=list(ss.get("f_hosts", [])), degrees=list(ss.get("f_degrees", [])),
        subjects=list(ss.get("f_subjects", [])), funding=list(ss.get("f_funding", [])),
        deadline_statuses=list(ss.get("f_status", [])),
    )


# --- safe rendering ----------------------------------------------------------------

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:])")


def md_escape(text: str) -> str:
    """Show untrusted text literally inside st.markdown (no links, emphasis, icons or LaTeX)."""
    return _MD_SPECIAL.sub(r"\\\1", text or "")


def badge_text(text: str) -> str:
    """Text safe to place inside a :color-badge[...] directive (brackets would end it early)."""
    return re.sub(r"[\[\]\\`*_$:<>|]", " ", text or "").strip()


def safe_link_button(label: str, url: str, key: str, **kwargs) -> None:
    if is_http_url(url):
        st.link_button(label, url, key=key, **kwargs)
    else:
        st.caption(f"{label}: link not shown (not a valid http/https address).")


def restriction_text(kind: str, values: list[str], labels: dict | None = None) -> str:
    if kind == "unrestricted":
        return "Any (explicitly open to all)"
    if kind == "unknown":
        return "Not listed in a structured form"
    return ", ".join(labels.get(v, v) if labels else v for v in values)


def degree_text(rec: ScholarshipRecord) -> str:
    return restriction_text(rec.degrees.kind, rec.degrees.values, DEGREES)


def subject_text(rec: ScholarshipRecord) -> str:
    return restriction_text(rec.subjects.kind, rec.subjects.values, SUBJECTS)


def funding_text(rec: ScholarshipRecord) -> str:
    return FUNDING_CATEGORIES.get(rec.funding_category, rec.funding_category)


def deadline_text(view, today) -> str:
    """Plain words for tables: status plus the date description."""
    return f"{STATUS_TEXT[view.status]}: " + describe_deadline(
        view.record.deadline_kind, view.record.deadline_date, today)


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def results_table(views, today) -> list[dict]:
    return [{
        "Scholarship": v.record.name,
        "Provider": v.record.provider,
        "Host countries": ", ".join(v.record.host_countries),
        "Degree": degree_text(v.record),
        "Funding": funding_text(v.record),
        "Deadline": deadline_text(v, today),
    } for v in views]


# --- cards and badges ------------------------------------------------------------

def deadline_badge(view) -> str:
    """Badge whose words carry the meaning; colour and icon only reinforce it."""
    status, days = view.status, view.days_left
    if status == "open" and days is not None and days <= 7:
        text = "Closes today" if days == 0 else f"Closes in {days} day{'s' if days != 1 else ''}"
        return f":orange-badge[:material/alarm: {text}]"
    if status == "open":
        return f":green-badge[:material/event_available: {days} days left]"
    if status == "expired":
        return ":gray-badge[:material/event_busy: Closed]"
    if status == "rolling":
        return ":blue-badge[:material/autorenew: Rolling deadline]"
    return ":gray-badge[:material/event_note: Deadline not published]"


def is_urgent(view) -> bool:
    return view.status == "open" and view.days_left is not None and view.days_left <= 7


def meta_badges(rec: ScholarshipRecord) -> str:
    parts = [f":gray-badge[:material/public: {badge_text(', '.join(rec.host_countries))}]"]
    if rec.degrees.kind == "list":
        parts.append(f":gray-badge[:material/school: {badge_text(degree_text(rec))}]")
    if rec.funding_category == "unknown":
        parts.append(":gray-badge[:material/payments: Funding not stated]")
    else:
        parts.append(f":violet-badge[:material/payments: {badge_text(funding_text(rec))}]")
    return " ".join(parts)


def card_header(view, today, show_date: bool = True) -> None:
    """Name, provider and badges for a scholarship card (all text escaped)."""
    rec = view.record
    st.markdown(f'<div class="sp-card-title">{html.escape(rec.name)}</div>'
                f'<div class="sp-provider">{html.escape(rec.provider)}</div>', unsafe_allow_html=True)
    st.markdown(f"{deadline_badge(view)} {meta_badges(rec)}")
    if show_date and rec.deadline_date:
        prefix = "Closed on" if view.status == "expired" else "Deadline"
        st.caption(f"{prefix} {rec.deadline_date.strftime('%d %b %Y').lstrip('0')}")


def card(prefix: str, view):
    """Bordered, hoverable container keyed by the stable record ID."""
    key = f"card_{prefix}_{view.record.id}"
    if is_urgent(view):
        key = f"card_urgent_{prefix}_{view.record.id}"
    return st.container(border=True, key=key)


def flash() -> None:
    """Show a one-off confirmation set by a callback (after the write committed)."""
    message = st.session_state.pop("flash", None)
    if message:
        st.toast(message, icon=":material/check_circle:")
