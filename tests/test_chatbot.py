"""ScholarPath assistant: retrieval, grounding, eligibility, follow-ups, privacy, limits and failures.

The provider call (advisor._post) is always a fake, so everything runs offline. The live
request is checked separately (see README, "Testing a real provider request").
"""

import json
import sqlite3

import pytest
import requests
from streamlit.testing.v1 import AppTest

from scholarpath import advisor, chat_context as cc, config
from scholarpath.matching import StudentProfile
from scholarpath.services import ScholarPathService

from .conftest import FIXED_TODAY, by_key


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def reply(text):
    return FakeResponse(200, {"choices": [{"message": {"content": text}}]})


@pytest.fixture
def svc(example_records):
    service = ScholarPathService(config.MODE_EXAMPLE)
    service.import_records(example_records, source_file="test")
    return service


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch):
    monkeypatch.setattr(advisor, "LIMITER", advisor.RateLimiter(1000, 1000))


@pytest.fixture
def live(monkeypatch):
    """Switch the provider on; every request is recorded and answered by ``live.answer``."""
    monkeypatch.setenv("SCHOLARPATH_AI_API_KEY", "test-key")

    class Live:
        sent: list = []
        answer = "OK"

    Live.sent = []

    def fake_post(settings, payload):
        Live.sent.append(payload)
        return reply(Live.answer)

    monkeypatch.setattr(advisor, "_post", fake_post)
    return Live


@pytest.fixture
def real_records_for_chat(example_records):
    """A second, separate dataset (the Real database) with the same records imported."""
    service = ScholarPathService(config.MODE_REAL)
    service.import_records([dict(r, dataset_origin="real_source", fetch_method="browser_snapshot",
                                 source_fetched_at="2026-11-12T00:00:00+00:00") for r in example_records],
                           source_file="test")
    return service


def sid(records, key):
    return by_key(records, key)["id"]


def context_of(live, n=-1):
    return live.sent[n]["messages"][1]["content"]


# --- configuration -------------------------------------------------------------------

def test_provider_defaults_and_overrides(monkeypatch):
    assert advisor.settings_from_env() is None
    monkeypatch.setenv("SCHOLARPATH_AI_API_KEY", " k ")
    s = advisor.settings_from_env()
    assert (s.api_key, s.base_url, s.model) == ("k", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b")
    assert advisor.provider_name(s) == "Groq"
    monkeypatch.setenv("SCHOLARPATH_AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    monkeypatch.setenv("SCHOLARPATH_AI_MODEL", "gemini-flash-lite")
    s = advisor.settings_from_env()
    assert s.base_url.endswith("/openai") and s.model == "gemini-flash-lite"
    assert advisor.provider_name(s) == "Google Gemini"


def test_without_a_key_answers_are_labelled_demonstrations_from_the_records(svc, example_records):
    assert svc.assistant_mode() == "demo"
    r = svc.chat("Which scholarships close soonest?", [])
    assert r.demo is True and r.references
    names = {v.record.name for v in svc.search()}
    assert all(c.view.record.name in names for c in r.references)


def test_local_settings_load_from_env_file_and_secrets_without_overriding(tmp_path, monkeypatch):
    import os
    monkeypatch.delenv("SCHOLARPATH_AI_NO_LOCAL")
    (tmp_path / ".streamlit").mkdir()
    (tmp_path / ".streamlit" / "secrets.toml").write_text('SCHOLARPATH_AI_MODEL = "from-secrets"\nOTHER = "x"\n')
    (tmp_path / ".env").write_text("# comment\nexport SCHOLARPATH_AI_API_KEY='abc123'  # key\n"
                                   "SCHOLARPATH_AI_BASE_URL=\nPATH=/evil\n")
    monkeypatch.setenv("SCHOLARPATH_AI_MODEL", "already-set")
    loaded = advisor.load_local_settings(tmp_path)
    assert loaded == ["SCHOLARPATH_AI_API_KEY"]
    assert os.environ["SCHOLARPATH_AI_API_KEY"] == "abc123" and os.environ["SCHOLARPATH_AI_MODEL"] == "already-set"
    assert os.environ.get("PATH") != "/evil"


def test_ai_check_command_reports_missing_key_success_and_failure(monkeypatch, capsys):
    from scholarpath.__main__ import main
    assert main(["ai-check"]) == 2 and "No API key found" in capsys.readouterr().out
    monkeypatch.setenv("SCHOLARPATH_AI_API_KEY", "k")
    monkeypatch.setattr(advisor, "_post", lambda s, p: reply("ScholarPath assistant is working."))
    assert main(["ai-check"]) == 0
    out = capsys.readouterr().out
    assert "Provider: Groq" in out and "openai/gpt-oss-120b" in out and "OK - the provider answered" in out
    monkeypatch.setattr(advisor, "_post", lambda s, p: FakeResponse(401, {}))
    assert main(["ai-check"]) == 1 and "FAILED: " in capsys.readouterr().out


# --- recommendations ---------------------------------------------------------------------

def test_recommendations_use_real_records_and_the_profile(svc, example_records, live):
    profile = StudentProfile(nationality="India", degree="master", subject="computer_science")
    live.answer = "Vega Computer Science Master's Award [S1] fits: open to all nationalities. Next step: review it."
    r = svc.chat("Which scholarships fit me?", [], profile=profile)
    ctx = context_of(live)
    assert "Student profile (from Check my fit): nationality India" in ctx
    assert "Vega Computer Science Master's Award" in ctx and "Check against the student's profile:" in ctx
    assert "needs verification: Academic score" in ctx       # a blank answer is never treated as a match
    assert "Cedar Public Health" not in ctx                 # fails the profile: not recommended
    assert [c.view.record.id for c in r.references] == [sid(example_records, "vega-cs-masters")]
    assert "[S1]" not in r.text


def test_recommendation_without_profile_asks_for_the_missing_facts(svc, live):
    svc.chat("Which scholarships fit me?", [])
    assert "Student profile: not provided. Ask for nationality, degree level and subject" in context_of(live)


def test_keyword_questions_pick_matching_records_and_skip_closed_ones(svc, example_records, live):
    svc.chat("Any scholarships in Japan for engineering?", [])
    ctx = context_of(live)
    assert "Sakura Research Scholarship" in ctx
    assert "Orion Undergraduate Access Award" not in ctx    # closed before the fixed test date
    assert ctx.count("\n[S") <= cc.MAX_RECORDS


# --- eligibility and the current scholarship ---------------------------------------------

def test_eligibility_question_on_review_separates_met_not_met_and_to_verify(svc, example_records, live):
    profile = StudentProfile(nationality="India", degree="master", subject="medicine_health")
    cedar = sid(example_records, "cedar-public-health")
    svc.chat("Am I eligible for this scholarship?", [], current_id=cedar, profile=profile)
    ctx = context_of(live)
    assert "(BEING REVIEWED)" in ctx and ctx.count("\n[S") == 1   # only the open scholarship is sent
    assert "Does not match recorded requirements" in ctx
    assert "meets:" in ctx and "does not meet:" in ctx


def test_missing_record_data_is_marked_not_stated(svc, example_records, live):
    meridian = sid(example_records, "meridian-doctoral-fellowship")
    svc.chat("Who can apply?", [], current_id=meridian)
    assert "Nationalities: NOT STATED" in context_of(live)
    assert "Where a record says NOT STATED" in live.sent[-1]["messages"][0]["content"]


def test_follow_up_keeps_history_and_context_switches_with_the_page(svc, example_records, live):
    vega, cedar = sid(example_records, "vega-cs-masters"), sid(example_records, "cedar-public-health")
    history = [("What is the deadline?", "20 Nov 2026."), ("What funding?", "Full tuition.")]
    svc.chat("And documents?", history, current_id=vega)
    msgs = live.sent[-1]["messages"]
    assert [m["content"] for m in msgs if m["role"] == "user"] == ["What is the deadline?", "What funding?",
                                                                    "And documents?"]
    assert "Vega Computer Science" in context_of(live)
    svc.chat("And documents?", history, current_id=cedar)
    assert "Cedar Public Health" in context_of(live) and "Vega Computer Science" not in context_of(live)


def test_history_and_inputs_are_bounded(svc, live):
    history = [(f"q{i}", "a" * 5000) for i in range(20)]
    svc.chat("hi there", history)
    msgs = live.sent[-1]["messages"]
    assert len(msgs) == 2 + 2 * advisor.MAX_HISTORY_TURNS + 1
    assert all(len(m["content"]) <= advisor.MAX_HISTORY_CHARS for m in msgs if m["role"] == "assistant")
    assert live.sent[-1]["max_tokens"] == advisor.MAX_ANSWER_TOKENS
    with pytest.raises(advisor.AdvisorError, match="under 800") as err:
        svc.chat("x" * 801, [])
    assert err.value.kind == "input"
    with pytest.raises(advisor.AdvisorError, match="Type a question"):
        svc.chat(" \x00 ", [])


# --- answers are checked against the records ---------------------------------------------

def test_invented_scholarships_and_links_are_flagged_and_removed(svc, example_records, live):
    vega = by_key(example_records, "vega-cs-masters")
    live.answer = (f"Vega Computer Science Master's Award [S1], see [apply]({vega['application_url']}). "
                   "Also Golden Unicorn Grant [S7] at https://unicorn.example/apply and "
                   "[this page](https://evil.example/x).")
    r = svc.chat("Computer science options in Ireland?", [])
    assert vega["application_url"] in r.text
    assert "unicorn.example" not in r.text and "evil.example" not in r.text
    assert "(not in ScholarPath's records)" in r.text and r.invented is True
    assert [c.view.record.id for c in r.references] == [vega["id"]]


def test_a_tag_next_to_another_name_does_not_create_a_link(svc, example_records, live):
    svc.chat("Which close soonest?", [])                  # learn which record the server tagged S1
    s1 = context_of(live).split("[S1] ")[1].split(" - ")[0]
    assert s1 != "Cedar Public Health Scholarship"
    live.answer = "Cedar Public Health Scholarship [S1] closes soonest."   # the model mixed up the tag
    r = svc.chat("Which close soonest?", [])
    assert [c.view.record.name for c in r.references] == ["Cedar Public Health Scholarship"]


# --- application progress and access -----------------------------------------------------

def test_progress_questions_use_the_tracker_and_send_no_notes(svc, example_records, live):
    vega = sid(example_records, "vega-cs-masters")
    svc.mark_applied(vega, FIXED_TODAY)
    svc.update_application(vega, "applied", submitted_date=FIXED_TODAY, notes="My passport number is X123")
    svc.chat("What is the status of my applications?", [])
    ctx = context_of(live)
    assert "THE STUDENT'S APPLICATION ENTRIES" in ctx and "Vega Computer Science Master's Award" in ctx
    assert "Applied (recorded by you)" in ctx and "passport" not in json.dumps(live.sent[-1])


def test_tracker_entries_are_only_sent_for_progress_questions(svc, example_records, live):
    svc.mark_applied(sid(example_records, "vega-cs-masters"), FIXED_TODAY)
    svc.chat("Scholarships in Japan?", [])
    assert "APPLICATION ENTRIES" not in context_of(live)


def test_assistant_only_sees_the_current_datasets_tracker(svc, example_records, real_records_for_chat, live):
    svc.mark_applied(sid(example_records, "vega-cs-masters"), FIXED_TODAY)
    real = real_records_for_chat
    real.chat("What is the status of my applications?", [])
    assert "Vega" not in context_of(live) and "none recorded" in context_of(live)


def test_the_assistant_never_writes_to_the_database(svc, example_records, live):
    live.answer = "I have saved it and marked it as applied for you."
    def snapshot():
        with sqlite3.connect(svc.db_path) as conn:
            return [conn.execute(f"SELECT COUNT(*), MAX(rowid) FROM {t}").fetchone()
                    for t in ("applications", "application_history", "shortlist")]
    before = snapshot()
    svc.chat("Save Vega and mark it as applied", [], current_id=sid(example_records, "vega-cs-masters"))
    assert snapshot() == before
    assert "cannot save, apply, submit or change anything" in live.sent[-1]["messages"][0]["content"]


# --- provider failures and limits --------------------------------------------------------

@pytest.mark.parametrize("response, kind, message", [
    (FakeResponse(429, {}), "quota", "limit is used up"),
    (FakeResponse(401, {}), "config", "refused the API key"),
    (FakeResponse(404, {}), "config", "model was not found"),
    (FakeResponse(500, {}), "unavailable", r"error \(500\)"),
    (FakeResponse(200, ValueError("bad json")), "unavailable", "could not read"),
    (reply("  "), "unavailable", "empty answer"),
])
def test_provider_failures_become_plain_messages(svc, monkeypatch, response, kind, message):
    monkeypatch.setenv("SCHOLARPATH_AI_API_KEY", "secret-key")
    monkeypatch.setattr(advisor, "_post", lambda s, p: response)
    with pytest.raises(advisor.AdvisorError, match=message) as err:
        svc.chat("Scholarships in Japan?", [])
    assert err.value.kind == kind and "secret-key" not in str(err.value)


@pytest.mark.parametrize("exc, message", [(requests.Timeout(), "took too long"),
                                          (requests.ConnectionError(), "could not be reached")])
def test_network_failures(svc, monkeypatch, exc, message):
    monkeypatch.setenv("SCHOLARPATH_AI_API_KEY", "k")

    def fail(s, p):
        raise exc

    monkeypatch.setattr(advisor, "_post", fail)
    with pytest.raises(advisor.AdvisorError, match=message):
        svc.chat("Scholarships in Japan?", [])


def test_server_rate_limiter_per_minute_and_per_day():
    now = [1_000_000.0]
    lim = advisor.RateLimiter(per_minute=2, per_day=3, clock=lambda: now[0])
    lim.acquire(), lim.acquire()
    with pytest.raises(advisor.AdvisorError, match="busy") as err:
        lim.acquire()
    assert err.value.kind == "quota"
    now[0] += 61
    lim.acquire()
    with pytest.raises(advisor.AdvisorError, match="today's limit"):
        lim.acquire()


def test_rate_limit_is_checked_before_any_request(svc, monkeypatch, live):
    monkeypatch.setattr(advisor, "LIMITER", advisor.RateLimiter(1, 1))
    svc.chat("Scholarships in Japan?", [])
    with pytest.raises(advisor.AdvisorError, match="today's limit"):
        svc.chat("Scholarships in Japan?", [])
    assert len(live.sent) == 1


def test_gpt_oss_models_get_low_reasoning_effort(svc, live, monkeypatch):
    svc.chat("hi", [])
    assert live.sent[-1]["reasoning_effort"] == "low"
    monkeypatch.setenv("SCHOLARPATH_AI_MODEL", "gemini-flash-lite")
    svc.chat("hi again", [])
    assert "reasoning_effort" not in live.sent[-1]


# --- the panel ---------------------------------------------------------------------------

PANEL = """
import streamlit as st
from scholarpath.ui import chatbot
chatbot.body(st.session_state.get("_test_page", "find"), in_dialog=False)
"""


def panel(page="find", **state) -> AppTest:
    at = AppTest.from_string(PANEL, default_timeout=30)
    at.session_state["_test_page"] = page
    for k, v in state.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, at.exception
    return at


def ask(at, text):
    at.text_input(key="chat_input").input(text)
    at.button[[b.label for b in at.button].index("Send")].click().run()
    assert not at.exception, at.exception
    return at


def all_text(at):
    return "\n".join(str(e.value) for coll in (at.markdown, at.caption, at.info, at.warning, at.error)
                     for e in coll)


def test_panel_shows_demo_mode_starters_and_a_labelled_answer(svc):
    at = panel()
    assert "Demonstration mode" in all_text(at)
    starters = [b.label for b in at.button if b.key and b.key.startswith("chat_starter_")]
    assert len(starters) == 3
    at.button(key="chat_starter_1").click().run()
    assert "Demonstration answer" in all_text(at)
    assert any(b.label.startswith("Review: ") for b in at.button)
    assert not [b for b in at.button if b.key and b.key.startswith("chat_starter_")]   # gone once chatting


def test_panel_context_follows_the_reviewed_scholarship(svc, example_records, live):
    vega, cedar = sid(example_records, "vega-cs-masters"), sid(example_records, "cedar-public-health")
    at = panel("review", selected_id=vega)
    assert "Talking about:** Vega Computer Science Master's Award" in all_text(at)
    assert [b.label for b in at.button if b.key and b.key.startswith("chat_starter_")][0] == \
        "Am I eligible for this scholarship?"
    ask(at, "What is the deadline?")
    at.session_state["selected_id"] = cedar
    at.run()
    assert "Now talking about: Cedar Public Health Scholarship" in all_text(at).replace("\\", "")


def test_panel_shows_quota_and_configuration_problems(svc, monkeypatch, live):
    at = panel()
    monkeypatch.setattr(advisor, "_post", lambda s, p: FakeResponse(429, {}))
    ask(at, "Scholarships in Japan?")
    assert "limit is used up" in all_text(at)
    monkeypatch.setattr(advisor, "_post", lambda s, p: FakeResponse(401, {}))
    at.session_state["chat_last"] = -100.0
    ask(at, "Scholarships in Japan?")
    assert "refused the API key" in all_text(at)


def test_panel_session_limit_and_clear_chat(svc, live):
    at = panel(chat_count=20)
    ask(at, "Scholarships in Japan?")
    assert "the limit for the free service" in all_text(at) and live.sent == []
    at.button(key="chat_clear").click().run()
    assert at.session_state["chat_log"] == [] if "chat_log" in at.session_state else True
    assert len([b for b in at.button if b.key and b.key.startswith("chat_starter_")]) == 3


def test_ask_scholarpath_button_is_on_every_main_page(svc):
    from .test_ui import goto, run_app
    at = run_app()
    for page in ("find", "saved", "applications"):
        goto(at, page)
        assert at.button(key="chat_open").label == "Ask ScholarPath"
