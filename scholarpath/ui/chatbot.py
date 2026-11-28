"""The ScholarPath assistant: an "Ask ScholarPath" button that opens a chat window in the
bottom-right corner of every page (a sheet above the menu bar on phones).

The window shows what the assistant is talking about (the scholarship open on Review, or the
whole dataset), up to three starter questions, the conversation, a question field with Send,
and Clear chat / Close in its header. It is not a modal: the page stays visible and usable.
Answers come from ScholarPathService.chat(), which runs on the server; the browser never sees
the API key. The assistant is read-only: scholarship links open the Review page, where the
student uses the normal buttons to save or mark as applied.

Every part is drawn inside containers keyed "chat_*", which style.py uses for the layout and
the site's colours (lavender highlight, indigo text, white sheet, hairline border).
"""

from __future__ import annotations

import time

import streamlit as st

from .. import config
from ..advisor import AdvisorError, provider_name, settings_from_env
from ..services import STORAGE_ERRORS, ServiceError
from . import common

SESSION_LIMIT = 20          # questions per browser session (the server also limits the shared key)
MIN_GAP_SECONDS = 2         # between two questions from one session

STARTERS = {
    "review": ("Am I eligible for this scholarship?", "What documents should I prepare for this one?",
               "What should I do next before the deadline?"),
    "applications": ("Where do my applications stand?", "What should I do next for my applications?",
                     "Which scholarships close soonest?"),
    "default": ("Which scholarships fit me?", "Which scholarships close soonest?",
                "How do I prepare a strong application?"),
}
I_STARTERS = {
    "review": ("Do I meet what this internship asks for?", "How should I prepare for this internship?",
               "What should I do next before applying?"),
    "applications": ("Where do my applications stand?", "What should I do next for my applications?",
                     "Which internships close soonest?"),
    "default": ("Which internships fit me?", "Which paid internships are in Chennai?",
                "How do I prepare a strong internship application?"),
}
ERROR_STYLE = {"quota": st.warning, "input": st.warning, "config": st.error, "unavailable": st.error}


def _log() -> list[dict]:
    return st.session_state.setdefault("chat_log", [])


def _pairs() -> list[tuple[str, str]]:
    """(question, answer) pairs for follow-up questions, oldest first."""
    pairs, question = [], None
    for item in _log():
        if item["role"] == "user":
            question = item["text"]
        elif item["role"] == "assistant" and question is not None:
            pairs.append((question, item["text"]))
            question = None
    return pairs


def _ask(text: str) -> None:
    st.session_state["chat_pending"] = text


def _send() -> None:
    _ask(st.session_state.get("chat_input", ""))


def _open() -> None:
    st.session_state["chat_open"] = True


def _close() -> None:
    st.session_state["chat_open"] = False


def _clear() -> None:
    for key in ("chat_log", "chat_pending", "chat_context_id"):
        st.session_state.pop(key, None)


def _context(svc, page: str) -> tuple[str | None, str]:
    """(scholarship id or None, plain description) of what the assistant is talking about."""
    sid = st.session_state.get("selected_id") if page == "review" else None
    view = svc.get(sid) if sid else None
    if view is not None:
        return view.record.id, view.record.name
    return None, f"all {common.WORDS[svc.kind]['nouns']} in {config.MODE_LABELS.get(svc.mode, 'this dataset')}"


def _note_context_change(sid: str | None, label: str) -> None:
    """When the student opens another scholarship mid-conversation, say so in the chat."""
    ss = st.session_state
    if ss.get("chat_context_id", "unset") != sid:
        if _log():
            _log().append({"role": "note", "text": f"Now talking about: {label}"})
        ss["chat_context_id"] = sid


def _references(item: dict, index: int, page: str) -> None:
    back = page if page in common.BACK_LABELS else "find"
    for n, ref in enumerate(item.get("refs", [])):
        with st.container(horizontal=True, key=f"chat_ref_{index}_{n}", gap="small"):
            if st.button(ref["name"], key=f"chat_review_{index}_{n}", icon=":material/arrow_forward:",
                         icon_position="right", type="tertiary"):
                common.go_to("review", ref["id"], back=back)
                st.rerun()                       # full rerun: opens the page, the window stays open
            common.safe_link_button("Official page", ref["url"], key=f"chat_link_{index}_{n}",
                                    icon=":material/open_in_new:", icon_position="right", type="tertiary")


def _show(item: dict, index: int, page: str) -> None:
    role = item["role"]
    if role == "note":
        st.caption(f":material/swap_horiz: {common.md_escape(item['text'])}")
    elif role == "user":
        with st.container(key=f"chat_user_{index}"):
            st.markdown(common.md_escape(item["text"]))
    elif role == "error":
        ERROR_STYLE.get(item["kind"], st.error)(item["text"], icon=":material/error:")
    else:
        with st.container(key=f"chat_bot_{index}"):
            if item.get("demo"):
                st.caption(":material/science: Demonstration answer: from ScholarPath's records, without AI")
            st.markdown(item["text"])
            if item.get("invented"):
                st.warning("Part of this answer refers to a scholarship that is not in ScholarPath's records. "
                           "Ignore that part; only the scholarships linked below are real records.",
                           icon=":material/warning:")
            if item.get("refs"):
                st.caption(f"{common.words()['Nouns']} in this answer")
                _references(item, index, page)


def _answer(svc, question: str, current_id: str | None, page: str) -> None:
    """Send one question (with a loading indicator) and add the reply or a plain error to the log."""
    ss = st.session_state
    log = _log()
    history = _pairs()
    log.append({"role": "user", "text": question.strip()[:800]})
    _show(log[-1], len(log) - 1, page)
    if ss.get("chat_count", 0) >= SESSION_LIMIT:
        log.append({"role": "error", "kind": "quota",
                    "text": f"You have asked {SESSION_LIMIT} questions in this visit, the limit for the free service."})
        return
    if time.monotonic() - ss.get("chat_last", -MIN_GAP_SECONDS) < MIN_GAP_SECONDS:
        log.append({"role": "error", "kind": "quota", "text": "Please wait a few seconds between questions."})
        return
    with st.container(key="chat_thinking"):
        with st.spinner("Checking ScholarPath's records..."):
            try:
                reply = svc.chat(question, history, current_id, ss.get("match_profile"))
            except AdvisorError as exc:
                if exc.kind == "input":
                    log.pop()                    # an empty or too-long question is not kept
                log.append({"role": "error", "kind": exc.kind, "text": str(exc)})
                return
            except (ServiceError, *STORAGE_ERRORS):
                log.append({"role": "error", "kind": "unavailable",
                            "text": "ScholarPath couldn't read its records just now. Please try again."})
                return
    ss["chat_count"] = ss.get("chat_count", 0) + 1
    ss["chat_last"] = time.monotonic()
    log.append({"role": "assistant", "text": reply.text, "demo": reply.demo, "invented": reply.invented,
                "refs": [{"id": c.view.record.id, "name": c.view.record.name,
                          "url": c.view.record.application_url or c.view.record.source_url}
                         for c in reply.references]})


def _header(page: str, label: str, live: bool) -> None:
    with st.container(key="chat_head", horizontal=True, vertical_alignment="center", gap="small"):
        with st.container(key="chat_icon", width="content"):       # the lavender icon tile (style.py)
            st.markdown(":material/forum:")
        with st.container(key="chat_title"):
            st.markdown("**ScholarPath assistant**")
            st.caption(f"Talking about: {common.md_escape(label)}")
        if _log():
            st.button("Clear chat", key="chat_clear", on_click=_clear, type="tertiary",
                      icon=":material/delete_sweep:")
        if st.button("Close", key="chat_close", type="tertiary", icon=":material/close:"):
            _close()
            st.rerun()                           # full rerun: removes the window, shows the button again
    with st.container(key="chat_status", gap=None):
        _status(live)


def _status(live: bool) -> None:
    if live:
        st.caption(f"AI answers ({provider_name(settings_from_env())}) from ScholarPath's records. They can be "
                   "wrong, so check the official page. Leave out personal details.")
    else:
        st.caption(":material/science: **Demonstration mode**: no AI provider is set up, so answers come "
                   "straight from ScholarPath's records.")
    if st.session_state.get("match_profile") is not None:
        st.caption(":material/fact_check: Using your Check my fit answers.")


def body(page: str, in_fragment: bool = True) -> None:
    """The window's contents. Drawn in a fragment, so sending a question redraws only the window."""
    svc = common.service()
    sid, label = _context(svc, page)
    _note_context_change(sid, label)
    _header(page, label, settings_from_env() is not None)

    log = _log()
    with st.container(key="chat_msgs"):                # scrolls; newest message stays in view
        with st.container(key="chat_msgs_inner"):
            for i, item in enumerate(log):
                _show(item, i, page)
            pending = st.session_state.pop("chat_pending", None)
            if pending is not None:
                _answer(svc, pending, sid, page)
                st.rerun(scope="fragment" if in_fragment else "app")   # redraw with the reply's links
            if not log:
                topic = ("internships, what employers ask for" if common.is_internship(svc)
                         else "scholarships, eligibility")
                st.caption(f"Ask anything about {topic} or your applications. For example:")
                starters = I_STARTERS if common.is_internship(svc) else STARTERS
                with st.container(key="chat_starters", gap="small"):
                    for n, text in enumerate(starters.get(page, starters["default"])[:3]):
                        st.button(text, key=f"chat_starter_{n}", on_click=_ask, args=(text,), width="stretch")

    with st.container(key="chat_foot"):
        with st.form("chat_form", clear_on_submit=True, border=False, enter_to_submit=True):
            with st.container(key="chat_input_row", horizontal=True, vertical_alignment="bottom", gap="small"):
                # No max_chars here (its counter crowds the narrow field); 800 is enforced on the server.
                st.text_input("Your question", key="chat_input", label_visibility="collapsed",
                              placeholder="Ask a question...")
                st.form_submit_button("Send", on_click=_send, type="primary", icon=":material/send:")


@st.fragment
def _window(page: str) -> None:
    with st.container(key="chat_panel"):
        body(page)


def entry(page: str) -> None:
    """The "Ask ScholarPath" button (bottom right), or the open chat window in its place."""
    svc = common.service()
    if not svc.database_exists():
        return
    if st.session_state.get("chat_open"):
        _window(page)
    else:
        with st.container(key="chat_fab"):
            st.button("Ask ScholarPath", key="chat_open_btn", on_click=_open, icon=":material/forum:",
                      help=f"Ask the ScholarPath assistant about {common.words()['nouns']} or your applications")
