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
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

from .. import config
from ..cleaning import is_http_url
from ..dates import STATUS_LABELS
from ..models import DEGREES, FUNDING_CATEGORIES, SUBJECTS, TRACKER_OUTCOMES, TRACKER_STATUSES, ScholarshipRecord
from ..repository import SearchFilters
from ..services import STORAGE_ERRORS, ImportFailed, ScholarPathService, ServiceError

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
MORE_PAGES = ("fit", "insights", "data")         # listed under "More"
MORE = "more"                                    # menu_item() value for the "More" button
# Label of the Back button on the Review page, by the page the user came from.
BACK_LABELS = {"find": "Back to results", "saved": "Back to Saved", "applications": "Back to Applications",
               "fit": "Back to Check my fit"}
FETCH_LABELS = {
    "fictional": "Fictional example (not collected from any source)",
    "live_http": "Downloaded directly from the official page",
    "browser_snapshot": "Read from a saved copy of the official page",
}
SUBMITTED_STATUSES = ("applied", "result_received")  # statuses that mean "the user has applied"

# Badge colours for the states a student has to tell apart. The words always carry the
# meaning; colour only supports them. The colours themselves are set in .streamlit/config.toml.
RULE_TEXT = {"satisfied": "✓ Met", "failed": "✕ Not met", "unknown": "? To confirm"}
OVERALL_STYLE = {
    "Matches recorded requirements": {"badge": "green", "icon": ":material/verified:"},
    "Needs manual verification": {"badge": "blue", "icon": ":material/help:"},
    "Does not match recorded requirements": {"badge": "gray", "icon": ":material/block:"},
}
TRACKER_BADGES = {"interested": "gray", "preparing": "gray", "applied": "blue", "result_received": "green"}
OUTCOME_BADGES = {"awarded": "green", "waitlisted": "orange", "not_selected": "gray", "withdrawn": "gray",
                  "other": "gray"}

# Empty values of the Find filters and the Check my fit form. To clear a widget its key is
# set to one of these, never deleted: the browser keeps its own copy of every widget value
# and would send the old one back on the next click (see reset_widgets).
FILTER_DEFAULTS = {"f_text": "", "f_hosts": [], "f_degrees": [], "f_subjects": [], "f_funding": [], "f_status": []}
FIT_DEFAULTS = {"m_nat": "", "m_nat_other": "", "m_dest": "", "m_degree": "", "m_subject": "", "m_score": None,
                "m_scale": ""}
FILTER_KEYS = tuple(FILTER_DEFAULTS)
FIT_KEYS = tuple(FIT_DEFAULTS)
# Widget values that should survive a visit to another page. Streamlit forgets the
# value of any widget that is not drawn on the current page unless we keep it alive.
PERSIST_KEYS = FILTER_KEYS + FIT_KEYS + ("f_sort", "f_page", "f_table", "ins_filters", "mode")
# Temporary selections (not widgets) that must not survive a dataset switch.
MODE_SCOPED_KEYS = ("selected_id", "review_back", "match_results", "match_profile", "tracker_pick",
                    "confirm_apply", "confirm_error", "just_applied", "app_message", "saved_undo",
                    "app_remove", "app_removed", "chat_log", "chat_pending", "chat_context_id")
PAGE_SIZE = 10


# --- navigation and state -----------------------------------------------------------

def keep_state() -> None:
    """Called once at the top of app.py: keep filter/form values while other pages are open."""
    for key in PERSIST_KEYS:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


def menu_item(page: str, review_back: str | None = None) -> str:
    """The menu item to highlight for a page: one of MAIN_PAGES, or MORE.

    Review is not in the menu, so it highlights the page it was opened from
    (the same page its Back button returns to).
    """
    if page == "review":
        page = review_back if review_back in BACK_LABELS else "find"
    return page if page in MAIN_PAGES else MORE


def enter_page(page: str) -> None:
    """Called by app.py on every run. When the user has moved to another page, forget
    steps that were only half done on the page they left."""
    ss = st.session_state
    if ss.get("_page") != page:
        ss.pop("saved_undo", None)                  # the offer to undo a removal from Saved
        if page != "review":
            ss.pop("confirm_apply", None)           # "Mark as applied" was opened but not confirmed
            ss.pop("confirm_error", None)
        if page != "applications":
            ss.pop("tracker_pick", None)
            ss.pop("app_remove", None)              # "Remove" was chosen but not confirmed
            ss.pop("app_removed", None)             # the note that an entry was removed
    ss["_page"] = page


def current_mode() -> str:
    return st.session_state.setdefault("mode", config.MODE_EXAMPLE)


def reset_widgets(defaults: dict) -> None:
    """Clear widgets by assigning their empty values, so the cleared state also reaches the browser."""
    for key, value in defaults.items():
        st.session_state[key] = list(value) if isinstance(value, list) else value


def on_mode_change() -> None:
    """A dataset switch starts clean: no filters, form answers or selections from the other dataset."""
    reset_widgets({**FILTER_DEFAULTS, **FIT_DEFAULTS, "f_sort": "deadline", "f_page": 1})
    for key in MODE_SCOPED_KEYS:
        st.session_state.pop(key, None)


def switch_mode(mode: str) -> None:
    """Button callback: change the dataset from a page (same effect as the sidebar switch)."""
    st.session_state["mode"] = mode
    on_mode_change()


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
        with st.container(border=True, key="card_page_error"):
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
    """One line saying which dataset is showing and how far to trust it."""
    if svc.mode == config.MODE_EXAMPLE:
        st.caption(":orange-badge[Example data] Invented for practice, so don't apply to these. "
                   "To see collected scholarships, change the dataset on Data & sources.")
    else:
        st.caption(":blue-badge[Real sources] Collected from official pages. Details can change, so "
                   "confirm on the provider's page before you apply.")


def dataset_ready(svc: ScholarPathService) -> bool:
    """Explain how to set up an empty dataset (never a silent fallback to the other one)."""
    if svc.database_exists():
        svc.ensure_schema()
        if cached_overview(str(svc.db_path), time_key(svc))["scholarships"] > 0:
            return True
    command = ("python -m scholarpath init-examples" if svc.mode == config.MODE_EXAMPLE
               else "python -m scholarpath import-real")
    with st.container(border=True, key="card_setup_needed"):
        st.subheader(f"Set up the {config.MODE_LABELS[svc.mode].lower()}", anchor=False)
        if svc.mode == config.MODE_EXAMPLE:
            # The fictional dataset can be built from inside the app, so a hosted copy (where
            # nobody has a terminal) can still show it. Real data is never created this way.
            st.markdown("This dataset has no scholarships yet. Create the fictional practice data here, "
                        "or run this in Terminal inside the ScholarPath folder:")
            st.code(command, language=None)
            st.button("Create the example data", key="setup_create_examples", icon=":material/add:",
                      on_click=create_example_data, type="primary")
        else:
            st.markdown("This dataset has no scholarships yet. In Terminal, inside the ScholarPath folder, run:")
            st.code(command, language=None)
            st.markdown("Then choose **Check again**. ScholarPath never swaps in the other dataset by itself.")
            st.button("Check again", key="setup_retry", icon=":material/refresh:", on_click=after_write,
                      type="primary")
        st.caption(f"Database file: {svc.db_path}")
    return False


def create_example_data() -> None:
    """Button callback: build and import the FICTIONAL example dataset (same as `init-examples`),
    with deadlines relative to today."""
    from ..examples import write_example_dataset

    try:
        svc = ScholarPathService(config.MODE_EXAMPLE)
        path = write_example_dataset(config.Clock().today())
        svc.ensure_schema()
        svc.import_file(path)
    except (ServiceError, ImportFailed, ValueError, *STORAGE_ERRORS) as exc:
        st.session_state["flash_error"] = f"The example data could not be created: {exc}"
        return
    after_write()


def after_write() -> None:
    """Refresh cached reads after a committed write."""
    st.cache_data.clear()


def flash() -> None:
    """Show a problem reported by a write callback. Successful writes need no pop-up: every page
    shows the new state in place (a Saved badge, an updated list, a message inside the entry).
    Pop-up toasts were dropped because on phones they covered the buttons and the menu bar."""
    problem = st.session_state.pop("flash_error", None)
    if problem:
        st.error(problem, icon=":material/error:")


# --- write actions shared by several pages (success is reported only after the commit) ----

def _write(action) -> bool:
    """Run one service write; on failure leave the reason for flash() and report False."""
    try:
        action()
    except (ServiceError, *STORAGE_ERRORS) as exc:
        st.session_state["flash_error"] = f"Not saved: {exc}"
        return False
    after_write()
    return True


def save(svc: ScholarPathService, scholarship_id: str, name: str = "") -> bool:
    return _write(lambda: svc.save(scholarship_id))


def unsave(svc: ScholarPathService, scholarship_id: str) -> bool:
    """Remove from Saved. Any application entry for the scholarship is kept."""
    return _write(lambda: svc.unsave(scholarship_id))


def open_application(scholarship_id: str) -> None:
    """Button callback: open Applications with this scholarship's entry first and expanded."""
    st.session_state["tracker_pick"] = scholarship_id
    go_to("applications")


# --- cached reads (keyed by DB path + a 5-minute time window, so modes never mix and a
# deadline that passes mid-day leaves discovery within minutes) -------------------------

CACHE_WINDOW_MINUTES = 5


def time_key(svc: ScholarPathService) -> str:
    """'Now', rounded down to the cache window. Part of every cached read's key."""
    now = svc.now()
    return now.replace(minute=now.minute - now.minute % CACHE_WINDOW_MINUTES, second=0).isoformat()

def _svc_for(db_path: str) -> ScholarPathService:
    mode = config.MODE_EXAMPLE if db_path == str(config.db_path(config.MODE_EXAMPLE)) else config.MODE_REAL
    return ScholarPathService(mode, db_path=db_path)


@st.cache_data(show_spinner=False)
def cached_search(db_path: str, when: str, filters: tuple, sort: str):
    keys = ("text", "host_countries", "degrees", "subjects", "funding", "deadline_statuses", "include_closed")
    values = dict(zip(keys, filters))
    values = {k: (list(v) if isinstance(v, tuple) else v) for k, v in values.items()}
    return _svc_for(db_path).search(SearchFilters(**values), sort)


@st.cache_data(show_spinner=False)
def cached_overview(db_path: str, when: str) -> dict:
    return _svc_for(db_path).overview()


@st.cache_data(show_spinner=False)
def cached_options(db_path: str) -> dict:
    return _svc_for(db_path).filter_options()


# --- the published real dataset reaches the running app ------------------------------------

@st.cache_data(show_spinner=False)
def _published_version(path: str, modified_ns: int) -> str | None:
    """The published dataset's version; re-read only when the file itself changes."""
    from ..refresh import load_published

    return load_published(Path(path))["dataset_version"]


@st.cache_resource(show_spinner=False)
def _sync_once(db_path: str, version: str, db_existed: bool) -> str:
    """Import a published version into the Real database once per server process.

    cache_resource is shared by every session, so concurrent visitors trigger one import;
    the import itself is transactional and idempotent. After an import every cached read
    is dropped, so no session keeps showing the previous dataset."""
    result = _svc_for(db_path).sync_published(config.REAL_DATASET_FILE)
    if result == "imported":
        st.cache_data.clear()
    return result


def sync_published_data() -> None:
    """Called by app.py on every run; cheap unless the published dataset changed."""
    path = Path(config.REAL_DATASET_FILE)
    if not path.exists():
        return
    real_db = config.db_path(config.MODE_REAL)
    try:
        version = _published_version(str(path), path.stat().st_mtime_ns)
        if version:
            _sync_once(str(real_db), version, real_db.exists())
    except (ImportFailed, ValueError, OSError, *STORAGE_ERRORS):
        pass   # the last imported data stays usable; the next run tries again (failures are not cached)


def all_views(svc: ScholarPathService, sort: str = "deadline", include_closed: bool = False):
    """Every open opportunity; with include_closed, also closed ones (for pages that must reach
    a saved or tracked record whatever its state, and for Data & sources)."""
    return cached_search(str(svc.db_path), time_key(svc), filters_key(SearchFilters(include_closed=include_closed)),
                         sort)


def filters_key(f: SearchFilters) -> tuple:
    return (f.text, tuple(f.host_countries), tuple(f.degrees), tuple(f.subjects), tuple(f.funding),
            tuple(f.deadline_statuses), f.include_closed)


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


def badge(colour: str, text: str) -> str:
    """Markdown for one badge. Colours: green, orange, yellow, red, blue, gray (see config.toml)."""
    return f":{colour}-badge[{badge_text(text)}]"


def fmt_date(value: date | None) -> str:
    """One date format for the whole app: 8 Dec 2026."""
    return f"{value.day} {value.strftime('%b %Y')}" if value else "-"


def fmt_iso_date(value: str | None) -> str:
    """Stored ISO date ('2026-12-08') -> '8 Dec 2026'; anything else is shown unchanged."""
    if not value:
        return "-"
    try:
        return fmt_date(date.fromisoformat(value))
    except ValueError:
        return value


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


def site_name(url: str) -> str:
    """'https://www.example.ac.uk/apply' -> 'example.ac.uk', to name the website a link opens."""
    host = urlparse(url).netloc if is_http_url(url) else ""
    return host[4:] if host.startswith("www.") else host


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


def level_text(rec: ScholarshipRecord) -> str:
    """Level of study in a few words, or '' when the source does not give one."""
    if rec.degrees.kind == "list":
        return degree_text(rec)
    return "Any level" if rec.degrees.kind == "unrestricted" else ""


def where_text(rec: ScholarshipRecord) -> str:
    """Country, level of study and funding in one plain line (only what the source states)."""
    funding = "Funding not stated" if rec.funding_category == "unknown" else f"Funding: {funding_text(rec)}"
    return " · ".join(p for p in (", ".join(rec.host_countries), level_text(rec), funding) if p)


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


def tracker_status(status: str) -> str:
    """'Applied (recorded by you)' -> 'Applied' for headings and lists."""
    return TRACKER_STATUSES.get(status, status).replace(" (recorded by you)", "")


# --- deadlines: one wording for cards, tables and pages ---------------------------------

def deadline_state(view) -> tuple[str, str, str]:
    """(badge colour, short label, detail) for a scholarship's deadline.

    Six states are kept apart: closing within 7 days, open, closed, rolling,
    "date not confirmed" (the provider published wording but no exact date)
    and "no deadline published" (nothing was collected at all).
    """
    rec, status, days = view.record, view.status, view.days_left
    when = fmt_date(rec.deadline_date)
    if status == "open" and days == 0:
        return "orange", "Closes today", when
    if status == "open" and days <= 7:
        return "orange", f"Closes in {plural(days, 'day')}", when
    if status == "open":
        return "green", STATUS_LABELS["open"], f"closes {when} · {days} days left"
    if status == "expired":
        if rec.deadline_date is None:
            return "gray", STATUS_LABELS["expired"], "the official page says applications are closed"
        return "gray", STATUS_LABELS["expired"], f"deadline was {when}"
    if status == "rolling":
        return "blue", STATUS_LABELS["rolling"], "no fixed closing date"
    if rec.deadline_text.strip():
        return "yellow", STATUS_LABELS["unknown"], "see the provider's wording"
    return "gray", "No deadline published", ""


def deadline_line(view) -> str:
    """Markdown for cards and page tops: a badge with the state, then the date in words."""
    colour, label, detail = deadline_state(view)
    return badge(colour, label) + (f" {detail}" if detail else "")


def deadline_plain(view) -> str:
    """The same wording without a badge, for tables and captions."""
    _, label, detail = deadline_state(view)
    return f"{label} · {detail}" if detail else label


def application_line(app) -> str:
    """Markdown for an application's status: badge, outcome and the submission date."""
    line = badge(TRACKER_BADGES.get(app.status, "gray"), tracker_status(app.status))
    if app.status == "result_received" and app.outcome:
        line += " " + badge(OUTCOME_BADGES.get(app.outcome, "gray"), TRACKER_OUTCOMES[app.outcome])
    if app.submitted_date:
        line += f" submitted {fmt_date(app.submitted_date)}"
    return line


def results_table(views, today) -> list[dict]:
    return [{
        "Scholarship": v.record.name,
        "Provider": v.record.provider,
        "Where": ", ".join(v.record.host_countries),
        "Level": level_text(v.record) or "Not recorded",
        "Funding": funding_text(v.record),
        "Deadline": deadline_plain(v),
        "Information": freshness_text(v.record, today),
    } for v in views]


# --- components --------------------------------------------------------------------------

def card(prefix: str, view):
    """White bordered container keyed by the stable record ID."""
    return st.container(border=True, key=f"card_{prefix}_{view.record.id}")


def card_summary(view, note: str = "") -> None:
    """One list row: scholarship, provider, where/level/funding, deadline (all text escaped).

    ``note`` is one optional status line, e.g. "Saved" or the application status.
    """
    rec = view.record
    st.subheader(md_escape(rec.name), anchor=False)
    st.markdown(f"{md_escape(rec.provider)}  \n{md_escape(where_text(rec))}")
    st.markdown(deadline_line(view) + (f"  \n{note}" if note else ""))


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


def safe_link_button(label: str, url: str, key: str, **kwargs) -> bool:
    """A button that opens an outside website in a new tab. Returns False if the address is unusable."""
    if not is_http_url(url):
        return False
    st.link_button(label, url, key=key, help=f"Opens {site_name(url)} in a new tab", **kwargs)
    return True


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
