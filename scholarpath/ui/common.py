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
from ..locations import place_text
from ..models import (DEGREES, DISCIPLINES, FUNDING_CATEGORIES, INTERN_DEGREES, STIPEND_KINDS, STUDY_YEARS, SUBJECTS,
                      TRACKER_OUTCOMES, TRACKER_STATUSES, WORK_ARRANGEMENTS, InternshipRecord, ScholarshipRecord)
from ..repository import InternshipFilters, SearchFilters
from ..services import STORAGE_ERRORS, ImportFailed, InternshipService, ScholarPathService, ServiceError, service_for

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
# v2: the same pages serve internships. Only these titles change with the opportunity type.
INTERNSHIP_TITLES = {"find": "Find Internships", "review": "Review internship"}
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

# Words that change with the opportunity type. Everything else on the pages is shared.
WORDS = {
    config.KIND_SCHOLARSHIP: {
        "noun": "scholarship", "nouns": "scholarships", "Noun": "Scholarship", "Nouns": "Scholarships",
        "a": "a scholarship", "find": "Find Scholarships", "find_button": "Find scholarships",
        "provider_site": "provider's site", "provider": "provider", "other": config.KIND_INTERNSHIP,
        "switch_label": "Switch to internships", "chooser": "Find scholarships",
    },
    config.KIND_INTERNSHIP: {
        "noun": "internship", "nouns": "internships", "Noun": "Internship", "Nouns": "Internships",
        "a": "an internship", "find": "Find Internships", "find_button": "Find internships",
        "provider_site": "employer's site", "provider": "employer", "other": config.KIND_SCHOLARSHIP,
        "switch_label": "Switch to scholarships", "chooser": "Find internships",
    },
}
KIND_LABELS = {config.KIND_INTERNSHIP: "Internships", config.KIND_SCHOLARSHIP: "Scholarships"}

# Empty values of the Find filters and the Check my fit form. To clear a widget its key is
# set to one of these, never deleted: the browser keeps its own copy of every widget value
# and would send the old one back on the next click (see reset_widgets).
FILTER_DEFAULTS = {"f_text": "", "f_hosts": [], "f_degrees": [], "f_subjects": [], "f_funding": [], "f_status": []}
FIT_DEFAULTS = {"m_nat": "", "m_nat_other": "", "m_dest": "", "m_degree": "", "m_subject": "", "m_score": None,
                "m_scale": ""}
# The same for internships (their own keys, so each type keeps its own search when switching).
I_FILTER_DEFAULTS = {"i_text": "", "i_place": "all_india", "i_cities": [], "i_states": [], "i_arr": [], "i_disc": [],
                     "i_stipend": [], "i_status": []}
I_FIT_DEFAULTS = {"im_degree": "", "im_year": "", "im_final": False, "im_disc": "", "im_place": ""}
FILTER_KEYS = tuple(FILTER_DEFAULTS)
FIT_KEYS = tuple(FIT_DEFAULTS)
# Widget values that should survive a visit to another page. Streamlit forgets the
# value of any widget that is not drawn on the current page unless we keep it alive.
PERSIST_KEYS = FILTER_KEYS + FIT_KEYS + ("f_sort", "f_page", "f_table", "ins_filters", "mode") + \
    tuple(I_FILTER_DEFAULTS) + tuple(I_FIT_DEFAULTS) + ("i_sort", "i_page", "i_table", "i_ins_filters")
# Temporary selections (not widgets) that must not survive a dataset switch. They belong to one
# opportunity type, so switching type puts them aside and brings them back on the way back.
MODE_SCOPED_KEYS = ("selected_id", "review_back", "match_results", "match_profile", "tracker_pick",
                    "confirm_apply", "confirm_error", "just_applied", "app_message", "saved_undo",
                    "app_remove", "app_removed", "chat_log", "chat_pending", "chat_context_id")
KIND_SCOPED_KEYS = MODE_SCOPED_KEYS
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


def current_kind() -> str | None:
    """The opportunity type chosen on the first screen (None until the student chooses)."""
    kind = st.session_state.get("kind")
    return kind if kind in config.KINDS else None


def kind_or_default() -> str:
    return current_kind() or config.KIND_SCHOLARSHIP


def words() -> dict:
    return WORDS[kind_or_default()]


def page_title(slug: str) -> str:
    """Menu and heading title of a page for the current opportunity type."""
    if kind_or_default() == config.KIND_INTERNSHIP and slug in INTERNSHIP_TITLES:
        return INTERNSHIP_TITLES[slug]
    return PAGE_INFO[slug][0]


def remember_kind_in_url() -> None:
    """Keep the choice in the address (?for=internships) so a reload does not ask again."""
    kind = current_kind()
    if kind:
        wanted = "internships" if kind == config.KIND_INTERNSHIP else "scholarships"
        if st.query_params.get("for") != wanted:
            st.query_params["for"] = wanted


def restore_kind_from_url() -> None:
    """A reload starts a new session; the address still says which type was chosen."""
    if current_kind() is None:
        chosen = {"internships": config.KIND_INTERNSHIP, "scholarships": config.KIND_SCHOLARSHIP}.get(
            st.query_params.get("for", ""))
        if chosen:
            st.session_state["kind"] = chosen


def choose_kind(kind: str) -> None:
    """Button callback on the first screen: open that type's Find page straight away."""
    st.session_state["kind"] = kind
    st.session_state["_goto"] = "find"


def switch_kind(kind: str) -> None:
    """Button/segment callback: change the opportunity type and return to where the student was.

    Each type keeps its own search, filters, sort, page and form answers (different widget keys,
    kept alive by keep_state). Its open selections (the record on Review, an unfinished
    confirmation, the assistant's conversation) are put aside and brought back on return.
    """
    ss = st.session_state
    old = current_kind()
    if kind not in config.KINDS or kind == old:
        return
    if old:
        ss[f"_kept_{old}"] = {key: ss[key] for key in KIND_SCOPED_KEYS if key in ss}
    for key in KIND_SCOPED_KEYS:
        ss.pop(key, None)
    ss.update(ss.pop(f"_kept_{kind}", {}))
    ss["kind"] = kind
    page = ss.get("_page")
    if page == "review" and not ss.get("selected_id"):
        ss["_goto"] = "find"


def on_kind_segment() -> None:
    """The type switch under the menu (a segmented control keyed "kind_pick")."""
    chosen = st.session_state.get("kind_pick")
    if chosen:
        switch_kind(chosen)
    st.session_state["kind_pick"] = current_kind()


def reset_widgets(defaults: dict) -> None:
    """Clear widgets by assigning their empty values, so the cleared state also reaches the browser."""
    for key, value in defaults.items():
        st.session_state[key] = list(value) if isinstance(value, list) else value


def on_mode_change() -> None:
    """A dataset switch starts clean: no filters, form answers or selections from the other dataset
    (for either opportunity type)."""
    reset_widgets({**FILTER_DEFAULTS, **FIT_DEFAULTS, "f_sort": "deadline", "f_page": 1,
                   **I_FILTER_DEFAULTS, **I_FIT_DEFAULTS, "i_sort": "deadline", "i_page": 1})
    for key in MODE_SCOPED_KEYS:
        st.session_state.pop(key, None)
    for kind in config.KINDS:
        st.session_state.pop(f"_kept_{kind}", None)


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
    """The service for the chosen opportunity type in the chosen dataset."""
    return service_for(kind_or_default(), current_mode())


def is_internship(svc) -> bool:
    return isinstance(svc, InternshipService)


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
    w = WORDS[svc.kind]
    if svc.mode == config.MODE_EXAMPLE:
        st.caption(":orange-badge[Example data] Invented for practice, so don't apply to these. "
                   f"To see collected {w['nouns']}, change the dataset on Data & sources.")
    elif is_internship(svc):
        st.caption(":blue-badge[Real sources] Collected from employers' public job boards. Details can change, "
                   "so confirm on the employer's page before you apply.")
    else:
        st.caption(":blue-badge[Real sources] Collected from official pages. Details can change, so "
                   "confirm on the provider's page before you apply.")


def dataset_ready(svc: ScholarPathService) -> bool:
    """Explain how to set up an empty dataset (never a silent fallback to the other one)."""
    w = WORDS[svc.kind]
    if svc.database_exists():
        svc.ensure_schema()
        if cached_overview(str(svc.db_path), time_key(svc), svc.kind)["scholarships"] > 0:
            return True
    real_command = ("python -m scholarpath find-internships --import" if is_internship(svc)
                    else "python -m scholarpath import-real")
    command = "python -m scholarpath init-examples" if svc.mode == config.MODE_EXAMPLE else real_command
    with st.container(border=True, key="card_setup_needed"):
        st.subheader(f"Set up the {config.MODE_LABELS[svc.mode].lower()}", anchor=False)
        if svc.mode == config.MODE_EXAMPLE:
            # The fictional dataset can be built from inside the app, so a hosted copy (where
            # nobody has a terminal) can still show it. Real data is never created this way.
            st.markdown(f"This dataset has no {w['nouns']} yet. Create the fictional practice data here, "
                        "or run this in Terminal inside the ScholarPath folder:")
            st.code(command, language=None)
            st.button("Create the example data", key="setup_create_examples", icon=":material/add:",
                      on_click=create_example_data, type="primary")
        else:
            st.markdown(f"This dataset has no {w['nouns']} yet. In Terminal, inside the ScholarPath folder, run:")
            st.code(command, language=None)
            st.markdown("Then choose **Check again**. ScholarPath never swaps in the other dataset by itself.")
            st.button("Check again", key="setup_retry", icon=":material/refresh:", on_click=after_write,
                      type="primary")
        st.caption(f"Database file: {svc.db_path}")
    return False


def create_example_data() -> None:
    """Button callback: build and import the FICTIONAL example dataset (same as `init-examples`),
    with deadlines relative to today."""
    from ..examples import write_example_dataset, write_example_internships

    try:
        svc = ScholarPathService(config.MODE_EXAMPLE)
        today = config.Clock().today()
        path = write_example_dataset(today)
        svc.ensure_schema()
        svc.import_file(path)
        InternshipService(config.MODE_EXAMPLE).import_file(write_example_internships(today))
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

def _svc_for(db_path: str, kind: str = config.KIND_SCHOLARSHIP) -> ScholarPathService:
    mode = config.MODE_EXAMPLE if db_path == str(config.db_path(config.MODE_EXAMPLE)) else config.MODE_REAL
    return service_for(kind, mode, db_path=db_path)


S_FILTER_FIELDS = ("text", "host_countries", "degrees", "subjects", "funding", "deadline_statuses", "include_closed")
I_FILTER_FIELDS = ("text", "place", "cities", "states", "arrangements", "disciplines", "stipends", "deadline_statuses",
                   "include_closed")


@st.cache_data(show_spinner=False)
def cached_search(db_path: str, when: str, filters: tuple, sort: str, kind: str = config.KIND_SCHOLARSHIP):
    """Cached search for either type; ``filters`` is filters_key() of that type's filters."""
    internship = kind == config.KIND_INTERNSHIP
    values = dict(zip(I_FILTER_FIELDS if internship else S_FILTER_FIELDS, filters))
    values = {k: (list(v) if isinstance(v, tuple) else v) for k, v in values.items()}
    chosen = InternshipFilters(**values) if internship else SearchFilters(**values)
    return _svc_for(db_path, kind).search(chosen, sort)


@st.cache_data(show_spinner=False)
def cached_overview(db_path: str, when: str, kind: str = config.KIND_SCHOLARSHIP) -> dict:
    return _svc_for(db_path, kind).overview()


@st.cache_data(show_spinner=False)
def cached_options(db_path: str, kind: str = config.KIND_SCHOLARSHIP) -> dict:
    return _svc_for(db_path, kind).filter_options()


# --- the published real dataset reaches the running app ------------------------------------

@st.cache_data(show_spinner=False)
def _published_version(path: str, modified_ns: int) -> str | None:
    """The published dataset's version; re-read only when the file itself changes."""
    from ..refresh import load_published

    return load_published(Path(path))["dataset_version"]


@st.cache_resource(show_spinner=False)
def _sync_internships_once(db_path: str, version: str, db_existed: bool) -> str:
    """The same for the live internship finder's dataset (its own version, its own tables)."""
    result = _svc_for(db_path, config.KIND_INTERNSHIP).sync_published(config.REAL_INTERNSHIPS_FILE)
    if result == "imported":
        st.cache_data.clear()
    return result


@st.cache_data(show_spinner=False)
def _internships_version(path: str, modified_ns: int) -> str | None:
    import json

    return json.loads(Path(path).read_text(encoding="utf-8")).get("dataset_version")


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
    """Called by app.py on every run; cheap unless a published dataset changed."""
    real_db = config.db_path(config.MODE_REAL)
    path = Path(config.REAL_DATASET_FILE)
    if path.exists():
        try:
            version = _published_version(str(path), path.stat().st_mtime_ns)
            if version:
                _sync_once(str(real_db), version, real_db.exists())
        except (ImportFailed, ValueError, OSError, *STORAGE_ERRORS):
            pass   # the last imported data stays usable; the next run tries again (failures are not cached)
    path = Path(config.REAL_INTERNSHIPS_FILE)
    if path.exists():
        try:
            version = _internships_version(str(path), path.stat().st_mtime_ns)
            if version:
                _sync_internships_once(str(real_db), version, real_db.exists())
        except (ImportFailed, ValueError, OSError, *STORAGE_ERRORS):
            pass


def all_views(svc: ScholarPathService, sort: str = "deadline", include_closed: bool = False):
    """Every open opportunity; with include_closed, also closed ones (for pages that must reach
    a saved or tracked record whatever its state, and for Data & sources)."""
    empty = (InternshipFilters if is_internship(svc) else SearchFilters)(include_closed=include_closed)
    return cached_search(str(svc.db_path), time_key(svc), filters_key(empty), sort, svc.kind)


def filters_key(f) -> tuple:
    if isinstance(f, InternshipFilters):
        return (f.text, f.place, tuple(f.cities), tuple(f.states), tuple(f.arrangements), tuple(f.disciplines),
                tuple(f.stipends), tuple(f.deadline_statuses), f.include_closed)
    return (f.text, tuple(f.host_countries), tuple(f.degrees), tuple(f.subjects), tuple(f.funding),
            tuple(f.deadline_statuses), f.include_closed)


def internship_filters() -> InternshipFilters:
    """Current Find Internships selections (temporary UI state only)."""
    ss = st.session_state
    return InternshipFilters(
        text=ss.get("i_text") or "", place=ss.get("i_place") or "all_india",
        cities=list(ss.get("i_cities") or []), states=list(ss.get("i_states") or []),
        arrangements=list(ss.get("i_arr") or []), disciplines=list(ss.get("i_disc") or []),
        stipends=list(ss.get("i_stipend") or []), deadline_statuses=list(ss.get("i_status") or []),
    )


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


def rupees(value: int) -> str:
    """Indian digit grouping: 150000 -> '₹1,50,000'."""
    digits = str(int(value))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        digits = f"{head},{tail}"
    return f"₹{digits}"


def stipend_text(rec: InternshipRecord) -> str:
    """'₹15,000-₹20,000 a month', 'Unpaid', 'Paid (amount not stated)' or 'Stipend not stated'."""
    if rec.stipend_kind == "paid":
        low, high = rec.stipend_min, rec.stipend_max
        if low is not None and high not in (None, low):
            return f"{rupees(low)}-{rupees(high)} a month"
        return f"{rupees(low if low is not None else high)} a month" if low is not None else f"Up to {rupees(high)} a month"
    return {"unpaid": "Unpaid", "paid_unstated": "Paid (amount not stated)"}.get(rec.stipend_kind, "Stipend not stated")


def internship_place(rec: InternshipRecord) -> str:
    return place_text(rec.cities, rec.states, rec.work_arrangement)


def arrangement_text(rec: InternshipRecord) -> str:
    return WORK_ARRANGEMENTS.get(rec.work_arrangement, rec.work_arrangement) if rec.work_arrangement != "unknown" \
        else "Work arrangement not stated"


def duration_text(rec: InternshipRecord) -> str:
    return rec.duration_text or "Duration not stated"


def discipline_text(rec: InternshipRecord) -> str:
    return restriction_text(rec.disciplines.kind, rec.disciplines.values, DISCIPLINES)


def intern_degree_text(rec: InternshipRecord) -> str:
    return restriction_text(rec.degrees.kind, rec.degrees.values, {k: v.split(" (")[0] for k, v in INTERN_DEGREES.items()})


def year_text(rec: InternshipRecord) -> str:
    return restriction_text(rec.study_years.kind, rec.study_years.values, STUDY_YEARS)


def level_text(rec: ScholarshipRecord) -> str:
    """Level of study in a few words, or '' when the source does not give one."""
    if rec.degrees.kind == "list":
        return degree_text(rec)
    return "Any level" if rec.degrees.kind == "unrestricted" else ""


def where_text(rec) -> str:
    """Country, level of study and funding in one plain line (only what the source states).
    For an internship: place, work arrangement, stipend and duration."""
    if isinstance(rec, InternshipRecord):
        parts = [internship_place(rec)]
        if rec.work_arrangement != "unknown" and not (rec.work_arrangement == "remote" and not rec.cities):
            parts.append(WORK_ARRANGEMENTS[rec.work_arrangement])
        parts.append(stipend_text(rec) if rec.stipend_kind != "unknown" else "Stipend not stated")
        if rec.duration_text:
            parts.append(rec.duration_text)
        return " · ".join(parts)
    funding = "Funding not stated" if rec.funding_category == "unknown" else f"Funding: {funding_text(rec)}"
    return " · ".join(p for p in (", ".join(rec.host_countries), level_text(rec), funding) if p)


def freshness_text(rec: ScholarshipRecord, today: date) -> str:
    """When the information was read from its source, and whether a person has checked it."""
    if rec.fetch_method == "fictional":
        return "Fictional example record"
    parts = []
    checked_word = "checked" if isinstance(rec, InternshipRecord) else "read"
    try:
        read_on = datetime.fromisoformat(rec.source_fetched_at or rec.collected_at).date()
        age = (today - read_on).days
        ago = "today" if age <= 0 else f"{plural(age, 'day')} ago"
        parts.append(f"Source {checked_word} {fmt_date(read_on)} ({ago})")
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
    if views and isinstance(views[0].record, InternshipRecord):
        return [{
            "Internship": v.record.title,
            "Employer": v.record.employer,
            "Where": internship_place(v.record),
            "Arrangement": WORK_ARRANGEMENTS.get(v.record.work_arrangement, "Not stated"),
            "Stipend": stipend_text(v.record),
            "Duration": duration_text(v.record),
            "Deadline": deadline_plain(v),
            "Information": freshness_text(v.record, today),
        } for v in views]
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
