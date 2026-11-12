"""Shared Streamlit helpers: dataset mode, service access, cached reads, safe rendering.

UI modules call services only; no SQL, HTTP or JSON reads happen here.
Cached reads are keyed by database path (so modes never share cache entries)
and are cleared after every successful write.
"""

from __future__ import annotations

import re

import streamlit as st

from .. import config
from ..cleaning import is_http_url
from ..dates import STATUS_LABELS, describe_deadline
from ..models import DEGREES, FUNDING_CATEGORIES, SUBJECTS, ScholarshipRecord
from ..repository import SearchFilters
from ..services import ScholarPathService

PAGES = ["Overview", "Explore", "Profile matching", "Scholarship details", "My applications", "Insights"]

STATUS_BADGES = {
    "open": "🟢 Open",
    "expired": "⛔ Expired",
    "rolling": "🔄 Rolling",
    "unknown": "❓ Unknown",
}
RULE_BADGES = {"satisfied": "✅ Satisfied", "failed": "❌ Failed", "unknown": "⚠️ Unknown"}
OVERALL_BADGES = {
    "Matches recorded requirements": "✅ Matches recorded requirements",
    "Needs manual verification": "⚠️ Needs manual verification",
    "Does not match recorded requirements": "❌ Does not match recorded requirements",
}

# Keys of temporary selections that must not survive a dataset switch.
MODE_SCOPED_KEYS = ("selected_id", "match_results", "match_profile", "explore_open_id", "tracker_pick",
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


def service() -> ScholarPathService:
    return ScholarPathService(current_mode())


def dataset_ready(svc: ScholarPathService) -> bool:
    """Show a clear message (never a silent fallback) when the selected DB is not initialised."""
    if svc.database_exists():
        svc.ensure_schema()
        if cached_overview(str(svc.db_path), svc.today().isoformat())["scholarships"] > 0:
            return True
    command = ("python -m scholarpath init-examples" if svc.mode == config.MODE_EXAMPLE
               else "python -m scholarpath import-real")
    st.error(
        f"The **{config.MODE_LABELS[svc.mode]}** database has no scholarships yet "
        f"({svc.db_path}). Run `{command}` from the project folder, then reload. "
        "ScholarPath does not switch to the other dataset automatically."
    )
    return False


def mode_banner(svc: ScholarPathService) -> None:
    if svc.mode == config.MODE_EXAMPLE:
        st.warning("**EXAMPLE DATA - all scholarships shown are fictional** and exist only for demonstration. "
                   "Do not apply to them.", icon="🧪")
    else:
        st.info("**Real-source data** parsed from official pages on the collection date shown. "
                "Not manually verified - always confirm details on the official page.", icon="🌐")


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

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$])")


def md_escape(text: str) -> str:
    """Show untrusted text literally inside st.markdown (no links, emphasis or LaTeX)."""
    return _MD_SPECIAL.sub(r"\\\1", text or "")


def safe_link_button(label: str, url: str, key: str) -> None:
    if is_http_url(url):
        st.link_button(label, url, key=key)
    else:
        st.caption(f"{label}: link not shown (not a valid http/https URL).")


def restriction_text(kind: str, values: list[str], labels: dict | None = None) -> str:
    if kind == "unrestricted":
        return "Any (explicitly unrestricted)"
    if kind == "unknown":
        return "Unknown - not recorded in structured form"
    return ", ".join(labels.get(v, v) if labels else v for v in values)


def degree_text(rec: ScholarshipRecord) -> str:
    return restriction_text(rec.degrees.kind, rec.degrees.values, DEGREES)


def subject_text(rec: ScholarshipRecord) -> str:
    return restriction_text(rec.subjects.kind, rec.subjects.values, SUBJECTS)


def funding_text(rec: ScholarshipRecord) -> str:
    return FUNDING_CATEGORIES.get(rec.funding_category, rec.funding_category)


def deadline_text(view, today) -> str:
    return f"{STATUS_BADGES[view.status]} · " + describe_deadline(
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
