"""The ScholarPath assistant: a compact "Ask ScholarPath" button on every page that opens a chat panel.

The panel shows what the assistant is talking about (the scholarship open on Review, or the
whole dataset), up to three starter questions, the conversation, a question field with Send
and a Clear chat action. Answers come from ScholarPathService.chat(), which runs on the server;
the browser never sees the API key. The assistant is read-only: scholarship links open the
Review page, where the student uses the normal buttons to save or mark as applied.
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


def _clear() -> None:
    for key in ("chat_log", "chat_pending", "chat_context_id"):
        st.session_state.pop(key, None)


def _context(svc, page: str) -> tuple[str | None, str]:
    """(scholarship id or None, plain description) of what the assistant is talking about."""
    sid = st.session_state.get("selected_id") if page == "review" else None
    view = svc.get(sid) if sid else None
    if view is not None:
        return view.record.id, view.record.name
    return None, f"all scholarships in {config.MODE_LABELS.get(svc.mode, 'this dataset')}"


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
        with st.container(horizontal=True, key=f"chat_ref_row_{index}_{n}"):
            if st.button(f"Review: {ref['name']}", key=f"chat_ref_{index}_{n}", icon=":material/arrow_forward:",
                         icon_position="right", type="tertiary"):
                common.go_to("review", ref["id"], back=back)
                st.rerun()                       # leaves the panel and opens the page
            common.safe_link_button("Official page", ref["url"], key=f"chat_link_{index}_{n}",
                                    icon=":material/open_in_new:", icon_position="right", type="tertiary")


def _show(item: dict, index: int, page: str) -> None:
    role = item["role"]
    if role == "note":
        st.caption(f":material/swap_horiz: {common.md_escape(item['text'])}")
    elif role == "user":
        with st.chat_message("user", avatar=":material/person:"):
            st.markdown(common.md_escape(item["text"]))
    elif role == "error":
        ERROR_STYLE.get(item["kind"], st.error)(item["text"], icon=":material/error:")
    else:
        with st.chat_message("assistant", avatar=":material/school:"):
            if item.get("demo"):
                st.caption(":material/science: **Demonstration answer**: built directly from ScholarPath's "
                           "records, without AI.")
            st.markdown(item["text"])
            if item.get("invented"):
                st.warning("Part of this answer refers to a scholarship that is not in ScholarPath's records. "
                           "Ignore that part; only the scholarships linked below are real records.",
                           icon=":material/warning:")
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
    with st.chat_message("assistant", avatar=":material/school:"):
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


def body(page: str, in_dialog: bool = True) -> None:
    """The panel's contents. Drawn inside the dialog; tests draw it directly (in_dialog=False)."""
    svc = common.service()
    sid, label = _context(svc, page)
    _note_context_change(sid, label)
    live = settings_from_env() is not None

    with st.container(key="chat_head"):
        st.markdown(f":material/target: **Talking about:** {common.md_escape(label)}")
        if st.session_state.get("match_profile") is not None:
            st.caption("Using your Check my fit answers for eligibility.")
        if live:
            st.caption(f"Answers are written by AI ({provider_name(settings_from_env())}) from ScholarPath's records "
                       "and can be wrong: check facts on the official page. Your question is sent to the provider, "
                       "so leave out personal details.")
        else:
            st.info("**Demonstration mode.** No AI provider is configured, so answers are built directly from "
                    "ScholarPath's records. Set up an API key to get full answers (see README).",
                    icon=":material/science:")

    log = _log()
    for i, item in enumerate(log):
        _show(item, i, page)
    pending = st.session_state.pop("chat_pending", None)
    if pending is not None:
        _answer(svc, pending, sid, page)
        st.rerun(scope="fragment" if in_dialog else "app")   # redraw so the reply's buttons are in the log

    if not log:
        st.caption("Try one of these:")
        with st.container(key="chat_starters"):
            for n, text in enumerate(STARTERS.get(page, STARTERS["default"])[:3]):
                st.button(text, key=f"chat_starter_{n}", on_click=_ask, args=(text,), width="stretch")

    with st.form("chat_form", clear_on_submit=True, border=False, enter_to_submit=True):
        st.text_input("Your question", key="chat_input", max_chars=800, label_visibility="collapsed",
                      placeholder="Ask about scholarships, eligibility or your applications")
        with st.container(horizontal=True, key="chat_actions"):
            st.form_submit_button("Send", on_click=_send, type="primary", icon=":material/send:")
    if log:
        st.button("Clear chat", key="chat_clear", on_click=_clear, type="tertiary", icon=":material/delete_sweep:")


_panel = st.dialog("ScholarPath assistant", width="large")(body)


def entry(page: str) -> None:
    """The compact entry point, fixed at the bottom-right corner by style.py (key "chat_fab")."""
    svc = common.service()
    if not svc.database_exists():
        return
    with st.container(key="chat_fab"):
        if st.button("Ask ScholarPath", key="chat_open", icon=":material/forum:",
                     help="Ask the ScholarPath assistant about scholarships, eligibility or your applications"):
            _panel(page)
