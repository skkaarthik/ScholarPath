"""Shared Streamlit helpers: navigation, dataset mode, cached reads, safe rendering
and the small set of reusable components every page is built from.

UI modules call services only; no SQL, HTTP or JSON reads happen here.
Cached reads are keyed by database path (so modes never share cache entries)
and are cleared after every successful write.

Rendering safety: untrusted text always goes through ``md_escape`` before it
reaches ``st.markdown``/headings, or ``badge_text`` inside a badge. No page
renders raw HTML from data.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import streamlit as st

from .. import config
from ..cleaning import is_http_url
from ..dates import STATUS_LABELS, describe_deadline
from ..models import DEGREES, FUNDING_CATEGORIES, SUBJECTS, TRACKER_STATUSES, ScholarshipRecord
from ..repository import SearchFilters
from ..services import STORAGE_ERRORS, ScholarPathService, ServiceError

# slug -> (title in the menu, icon). The app follows one sequence:
# Find a scholarship -> Review it -> Apply on the provider's site -> Track the application.
# "review" is not in the menu; it opens when a scholarship is chosen from a list.
PAGE_INFO = {
    "find": ("Find Scholarships", ":material/search:"),
    "saved": ("Saved", ":material/bookmark:"),
    "applications": ("Applications", ":material/task_alt:"),
    "fit": ("Check my fit", ":material/fact_check:"),
    "insights": ("Insights", ":material/bar_chart:"),
    "data": ("Data & sources", ":material/database:"),
    "review": ("Review scholarship", ":material/description:"),
}
MAIN_PAGES = ("find", "saved", "applications")   # the three main menu items
MORE_PAGES = ("fit", "insights", "data")         # quieter "More" group
# Label of the Back button on the Review page, by the page the user came from.
BACK_LABELS = {"find": "Back to results", "saved": "Back to Saved", "applications": "Back to Applications",
               "fit": "Back to Check my fit"}
FETCH_LABELS = {
    "fictional": "Fictional example (not collected from any source)",
    "live_http": "Downloaded directly from the official page",
    "browser_snapshot": "Read from a saved copy of the official page",
}
SUBMITTED_STATUSES = ("applied", "result_received")  # statuses that mean "the user has applied"

# Plain-text labels (tables). Words carry the meaning, never colour alone.
STATUS_TEXT = {"open": "Open", "expired": "Closed", "rolling": "Rolling", "unknown": "Not published"}
RULE_TEXT = {"satisfied": "✓ Met", "failed": "✕ Not met", "unknown": "? To confirm"}

OVERALL_STYLE = {
    "Matches recorded requirements": {"badge": "green", "icon": ":material/verified:"},
    "Needs manual verification": {"badge": "blue", "icon": ":material/help:"},
    "Does not match recorded requirements": {"badge": "gray", "icon": ":material/block:"},
}

FILTER_KEYS = ("f_text", "f_hosts", "f_degrees", "f_subjects", "f_funding", "f_status")
FIT_KEYS = ("m_nat", "m_nat_other", "m_dest", "m_degree", "m_subject", "m_score", "m_scale")
# Widget values that should survive a visit to another page. Streamlit forgets the
# value of any widget that is not drawn on the current page unless we keep it alive.
PERSIST_KEYS = FILTER_KEYS + FIT_KEYS + ("f_sort", "f_page", "f_table", "ins_filters", "mode")
# Temporary selections that must not survive a dataset switch.
MODE_SCOPED_KEYS = FILTER_KEYS + FIT_KEYS + ("selected_id", "review_back", "match_results", "match_profile",
                                             "tracker_pick", "f_sort", "f_page", "confirm_apply", "just_applied",
                                             "app_saved", "app_error")
PAGE_SIZE = 10


# --- navigation and state -----------------------------------------------------------

def keep_state() -> None:
    """Called once at the top of app.py: keep filter/form values while other pages are open."""
    for key in PERSIST_KEYS:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


def current_mode() -> str:
    return st.session_state.setdefault("mode", config.MODE_EXAMPLE)


def on_mode_change() -> None:
    for key in MODE_SCOPED_KEYS:
        st.session_state.pop(key, None)


def go_to(page: str, scholarship_id: str | None = None, back: str | None = None) -> None:
    """Button callback: ask app.py to open another page (optionally a specific scholarship)."""
    st.session_state["_goto"] = page
    if scholarship_id:
        st.session_state["selected_id"] = scholarship_id
        st.session_state["review_back"] = back or "find"


def service() -> ScholarPathService:
    return ScholarPathService(current_mode())


def run_page(render) -> None:
    """Draw one page; turn storage problems into a calm message with a way to recover."""
    svc = service()
    try:
        render(svc)
    except STORAGE_ERRORS as exc:
        with st.container(border=True, key="page_error"):
            st.error("ScholarPath couldn't read or write its database just now. Nothing was changed.",
                     icon=":material/error:")
            st.markdown("This usually means another ScholarPath window or command is using the database. "
                        "Close it, then try again.")
            st.caption(f"Technical detail: {md_escape(str(exc))}")
            st.button("Try again", key="retry_page", icon=":material/refresh:", type="primary")


def page_header(svc: ScholarPathService, title: str, intro: str = "") -> None:
    """Same top of page everywhere: title, one-sentence purpose, which dataset is showing."""
    st.title(title, anchor=False)
    if intro:
        st.markdown(intro)
    dataset_notice(svc)


def dataset_notice(svc: ScholarPathService) -> None:
    """One quiet line saying which dataset is showing (the switch is in the sidebar)."""
    if svc.mode == config.MODE_EXAMPLE:
        st.caption("Example data: invented for practice, so don't apply to these. "
                   "Switch to Real sources in the sidebar for collected scholarships.")
    else:
        st.caption("Real sources: collected from official pages. Details can change, so confirm on the "
                   "provider's page before you apply.")


def dataset_ready(svc: ScholarPathService) -> bool:
    """Explain how to set up an empty dataset (never a silent fallback to the other one)."""
    if svc.database_exists():
        svc.ensure_schema()
        if cached_overview(str(svc.db_path), svc.today().isoformat())["scholarships"] > 0:
            return True
    command = ("python -m scholarpath init-examples" if svc.mode == config.MODE_EXAMPLE
               else "python -m scholarpath import-real")
    with st.container(border=True, key="card_setup_needed"):
        st.header(f"Set up the {config.MODE_LABELS[svc.mode].lower()}", anchor=False)
        st.markdown("This dataset has no scholarships yet. In Terminal, inside the ScholarPath folder, run:")
        st.code(command, language=None)
        st.markdown("Then choose **Check again**. ScholarPath never swaps in the other dataset by itself.")
        st.button("Check again", key="setup_retry", icon=":material/refresh:", on_click=after_write)
        st.caption(f"Database file: {svc.db_path}")
    return False


def after_write() -> None:
    """Refresh cached reads after a committed write."""
    st.cache_data.clear()


def flash() -> None:
    """Show a one-off confirmation set by a callback (after the write committed)."""
    message = st.session_state.pop("flash", None)
    if message:
        st.toast(message, icon=":material/check_circle:")
    problem = st.session_state.pop("flash_error", None)
    if problem:
        st.error(problem, icon=":material/error:")


# --- write actions shared by several pages (success is reported only after the commit) ----

def _write(action, success: str) -> None:
    try:
        action()
    except (ServiceError, *STORAGE_ERRORS) as exc:
        st.session_state["flash_error"] = f"Not saved: {exc}"
    else:
        after_write()
        st.session_state["flash"] = success


def save(svc: ScholarPathService, scholarship_id: str, name: str) -> None:
    _write(lambda: svc.save(scholarship_id), f"Saved “{name}”. Find it under Saved.")


def unsave(svc: ScholarPathService, scholarship_id: str) -> None:
    _write(lambda: svc.unsave(scholarship_id), "Removed from Saved. Any application entry is kept.")


def open_application(scholarship_id: str) -> None:
    """Button callback: open Applications with this scholarship's entry first and expanded."""
    st.session_state["tracker_pick"] = scholarship_id
    go_to("applications")


# --- cached reads (keyed by DB path + date, so modes and days never mix) -------------

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


def all_views(svc: ScholarPathService, sort: str = "deadline"):
    return cached_search(str(svc.db_path), svc.today().isoformat(), filters_key(SearchFilters()), sort)


def filters_key(f: SearchFilters) -> tuple:
    return (f.text, tuple(f.host_countries), tuple(f.degrees), tuple(f.subjects), tuple(f.funding),
            tuple(f.deadline_statuses))


def find_filters() -> SearchFilters:
    """Current Find Scholarships selections (temporary UI state only)."""
    ss = st.session_state
    return SearchFilters(
        text=ss.get("f_text") or "", host_countries=list(ss.get("f_hosts") or []),
        degrees=list(ss.get("f_degrees") or []), subjects=list(ss.get("f_subjects") or []),
        funding=list(ss.get("f_funding") or []), deadline_statuses=list(ss.get("f_status") or []),
    )


# --- safe text -------------------------------------------------------------------------

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:])")


def md_escape(text: str) -> str:
    """Show untrusted text literally inside st.markdown (no links, emphasis, icons, HTML or LaTeX)."""
    return _MD_SPECIAL.sub(r"\\\1", text or "")


def badge_text(text: str) -> str:
    """Text safe to place inside a :color-badge[...] directive (brackets would end it early)."""
    return re.sub(r"[\[\]\\`*_$:<>|]", " ", text or "").strip()


def fmt_date(value: date | None) -> str:
    return f"{value.day} {value.strftime('%b %Y')}" if value else "-"


def fmt_ts(value: str | None) -> str:
    """ISO timestamp -> '12 Nov 2026, 10:00 UTC' (stored timestamps are UTC)."""
    if not value:
        return "-"
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return value
    return f"{fmt_date(stamp.date())}, {stamp.strftime('%H:%M')} UTC"


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


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


def freshness_text(rec: ScholarshipRecord, today: date) -> str:
    """When the information was read from its source, and whether a person has checked it."""
    if rec.fetch_method == "fictional":
        return "Fictional example record"
    parts = []
    try:
        read_on = datetime.fromisoformat(rec.source_fetched_at or rec.collected_at).date()
        age = (today - read_on).days
        ago = "today" if age <= 0 else f"{plural(age, 'day')} ago"
        parts.append(f"Source read {fmt_date(read_on)} ({ago})")
    except ValueError:
        parts.append("Source read date not recorded")
    parts.append("checked by a person" if rec.manual_verified_at else "not yet checked by a person")
    if rec.source_status == "unavailable":
        parts.append("source page unavailable at last collection")
    return " · ".join(parts)


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def tracker_status(status: str) -> str:
    """'Applied (recorded by you)' -> 'Applied' for headings and lists."""
    return TRACKER_STATUSES.get(status, status).replace(" (recorded by you)", "")


def where_text(rec: ScholarshipRecord) -> str:
    """Country, level of study and funding in one plain line (only what the source states)."""
    parts = [", ".join(rec.host_countries)]
    if rec.degrees.kind == "list":
        parts.append(degree_text(rec))
    if rec.funding_category != "unknown":
        parts.append(f"Funding: {funding_text(rec)}")
    return " · ".join(p for p in parts if p)


def deadline_line(view) -> str:
    """The deadline in words. Bold only when it closes within 7 days."""
    status, days, when = view.status, view.days_left, fmt_date(view.record.deadline_date)
    if status == "open" and days == 0:
        return f"**Closes today** · {when}"
    if status == "open" and days <= 7:
        return f"**Closes in {plural(days, 'day')}** · {when}"
    if status == "open":
        return f"Deadline {when} · {days} days left"
    if status == "expired":
        return f"Closed on {when}"
    if status == "rolling":
        return "Rolling deadline"
    return "Deadline not published"


def results_table(views, today) -> list[dict]:
    return [{
        "Scholarship": v.record.name,
        "Provider": v.record.provider,
        "Where": ", ".join(v.record.host_countries),
        "Level": degree_text(v.record),
        "Funding": funding_text(v.record),
        "Deadline": deadline_text(v, today),
        "Information": freshness_text(v.record, today),
    } for v in views]


# --- components --------------------------------------------------------------------------

def card(prefix: str, view):
    """White bordered container keyed by the stable record ID."""
    return st.container(border=True, key=f"card_{prefix}_{view.record.id}")


def card_summary(view, today=None) -> None:
    """One list row: scholarship, provider, where/level/funding, deadline (all text escaped)."""
    rec = view.record
    st.subheader(md_escape(rec.name), anchor=False)
    st.markdown(f"{md_escape(rec.provider)}  \n{md_escape(where_text(rec))}")
    st.markdown(deadline_line(view))


def review_button(view, prefix: str, back: str, label: str = "Review", **kwargs) -> None:
    """Open the Review page for this scholarship; ``back`` is the page its Back button returns to."""
    st.button(label, key=f"{prefix}_rev_{view.record.id}", on_click=go_to,
              args=("review", view.record.id, back), icon=":material/arrow_forward:", icon_position="right",
              **kwargs)


def empty_state(key: str, title: str, body: str, action: str | None = None, target: str | None = None,
                icon: str = ":material/arrow_forward:") -> None:
    """Explain why a list is empty and offer the next step."""
    with st.container(border=True, key=f"card_empty_{key}"):
        st.subheader(title, anchor=False)
        st.markdown(body)
        if action and target:
            st.button(action, key=f"empty_{key}_go", on_click=go_to, args=(target,), type="primary", icon=icon)


def safe_link_button(label: str, url: str, key: str, **kwargs) -> None:
    if is_http_url(url):
        st.link_button(label, url, key=key, help="Opens the official website in a new tab", **kwargs)
    else:
        st.caption(f"{label}: link not shown (not a valid http/https address).")


def paginate(items: list, key: str, size: int = PAGE_SIZE) -> tuple[list, int, int]:
    """Slice ``items`` for the current page. Returns (page_items, page, page_count)."""
    pages = max(1, -(-len(items) // size))
    page = min(max(1, int(st.session_state.get(key, 1))), pages)
    st.session_state[key] = page
    return items[(page - 1) * size: page * size], page, pages


def _turn(key: str, step: int) -> None:
    st.session_state[key] = int(st.session_state.get(key, 1)) + step


def pager(key: str, page: int, pages: int) -> None:
    if pages <= 1:
        return
    with st.container(horizontal=True, vertical_alignment="center", horizontal_alignment="center", key=f"{key}_pager"):
        st.button("Previous", key=f"{key}_prev", on_click=_turn, args=(key, -1), disabled=page <= 1,
                  icon=":material/chevron_left:")
        st.markdown(f"Page **{page}** of **{pages}**")
        st.button("Next", key=f"{key}_next", on_click=_turn, args=(key, 1), disabled=page >= pages,
                  icon=":material/chevron_right:", icon_position="right")
