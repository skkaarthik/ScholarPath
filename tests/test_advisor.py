"""AI advisor: grounding, settings, error handling and the Review-page section.

The network call (advisor._post) is always replaced by a fake, so these tests run offline.
"""

import pytest
import requests
from streamlit.testing.v1 import AppTest

from scholarpath import advisor, config
from scholarpath.services import ScholarPathService, ServiceError

from .conftest import by_key
from .test_ui import APP, click, goto, run_app, texts


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
def service(example_records):
    svc = ScholarPathService(config.MODE_EXAMPLE)
    svc.import_records(example_records, source_file="test")
    return svc


@pytest.fixture
def ai_on(monkeypatch):
    """Switch the advisor on and record what would have been sent."""
    monkeypatch.setenv("SCHOLARPATH_AI_API_KEY", "test-key")
    sent = []

    def fake_post(settings, payload):
        sent.append((settings, payload))
        return reply("Prepare a CV and two references. The record does not state an IELTS score.")

    monkeypatch.setattr(advisor, "_post", fake_post)
    return sent


def record(service, example_records, key="vega-cs-masters"):
    return service.get(by_key(example_records, key)["id"]).record


# --- settings and prompt (pure) ------------------------------------------------------

def test_advisor_is_off_without_a_key_and_uses_groq_by_default(monkeypatch):
    assert advisor.settings_from_env() is None
    monkeypatch.setenv("SCHOLARPATH_AI_API_KEY", " k ")
    s = advisor.settings_from_env()
    assert (s.api_key, s.base_url, s.model) == ("k", advisor.DEFAULT_BASE_URL, advisor.DEFAULT_MODEL)
    monkeypatch.setenv("SCHOLARPATH_AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    monkeypatch.setenv("SCHOLARPATH_AI_MODEL", "gemini-flash")
    s = advisor.settings_from_env()
    assert s.base_url.endswith("/openai") and s.model == "gemini-flash"


def test_prompt_is_grounded_in_the_record_and_admits_gaps(service, example_records):
    rec = record(service, example_records)
    context = advisor.record_context(rec)
    assert rec.name in context and rec.provider in context
    assert (rec.deadline_date.isoformat() if rec.deadline_date else "Deadline:") in context
    assert "fictional example record" in context            # example data is never passed off as real
    messages = advisor.build_messages(rec, "Am I eligible?", [])
    assert messages[0]["role"] == "system" and "Never guess or invent" in messages[0]["content"]
    assert "RECORD:" in messages[0]["content"] and messages[-1] == {"role": "user", "content": "Am I eligible?"}


def test_only_recent_history_is_sent(service, example_records):
    history = [(f"q{i}", f"a{i}") for i in range(10)]
    messages = advisor.build_messages(record(service, example_records), "now?", history)
    sent_questions = [m["content"] for m in messages if m["role"] == "user"]
    assert sent_questions == [f"q{i}" for i in range(4, 10)] + ["now?"]


# --- the call and its failures -------------------------------------------------------

@pytest.mark.parametrize("response, message", [
    (FakeResponse(429, {}), "busy or its daily limit"),
    (FakeResponse(401, {}), "API key was refused"),
    (FakeResponse(500, {}), r"returned an error \(500\)"),
    (FakeResponse(200, ValueError("not json")), "could not read"),
    (FakeResponse(200, {"choices": []}), "could not read"),
    (reply("   "), "empty answer"),
])
def test_provider_failures_become_plain_messages(service, example_records, monkeypatch, response, message):
    monkeypatch.setattr(advisor, "_post", lambda s, p: response)
    settings = advisor.AdvisorSettings(api_key="secret-key")
    with pytest.raises(advisor.AdvisorError, match=message) as err:
        advisor.ask(settings, record(service, example_records), "Hi", [])
    assert "secret-key" not in str(err.value)


def test_network_failure_and_bad_questions(service, example_records, monkeypatch):
    def down(s, p):
        raise requests.ConnectionError("dns")

    monkeypatch.setattr(advisor, "_post", down)
    settings, rec = advisor.AdvisorSettings(api_key="k"), record(service, example_records)
    with pytest.raises(advisor.AdvisorError, match="could not be reached"):
        advisor.ask(settings, rec, "Hi", [])
    with pytest.raises(advisor.AdvisorError, match="Type a question"):
        advisor.ask(settings, rec, "   ", [])
    with pytest.raises(advisor.AdvisorError, match="under 1000"):
        advisor.ask(settings, rec, "x" * 1001, [])


def test_service_answers_from_the_stored_record(service, example_records, ai_on):
    sid = by_key(example_records, "vega-cs-masters")["id"]
    answer = service.ask_advisor(sid, "What should I prepare?", [])
    assert answer.startswith("Prepare a CV")
    settings, payload = ai_on[0]
    assert settings.api_key == "test-key" and payload["model"] == advisor.DEFAULT_MODEL
    assert "Vega Computer Science Master's Award" in payload["messages"][0]["content"]
    with pytest.raises(ServiceError, match="no longer in the current dataset"):
        service.ask_advisor("sp-missing", "Hi", [])


def test_service_refuses_when_not_set_up(service, example_records):
    assert service.advisor_available() is False
    with pytest.raises(ServiceError, match="not set up"):
        service.ask_advisor(by_key(example_records, "vega-cs-masters")["id"], "Hi", [])


# --- Review page ---------------------------------------------------------------------

def open_review(sid):
    at = run_app()
    at.session_state["selected_id"] = sid
    return goto(at, "review")


def ask_in_ui(at, sid, question):
    at.text_area(key=f"adv_q_{sid}").input(question)
    at.button[[b.label for b in at.button].index("Ask")].click().run()
    assert not at.exception, at.exception
    return at


def test_review_hides_the_advisor_when_no_key_is_set(service, example_records):
    at = open_review(by_key(example_records, "vega-cs-masters")["id"])
    assert "Ask the AI advisor" not in [e.label for e in at.expander]


def test_review_shows_the_answer_and_keeps_the_conversation(service, example_records, ai_on):
    sid = by_key(example_records, "vega-cs-masters")["id"]
    at = open_review(sid)
    assert "Ask the AI advisor" in [e.label for e in at.expander]
    assert "can be wrong" in texts(at)
    ask_in_ui(at, sid, "What should I prepare?")
    ask_in_ui(at, sid, "And the deadline?")
    assert len(ai_on) == 2 and at.session_state["advisor_count"] == 2
    assert [q for q, _ in at.session_state["advisor_chat"][sid]] == ["What should I prepare?", "And the deadline?"]
    assert len(ai_on[1][1]["messages"]) == 4            # system, first Q, first answer, new Q
    assert "The record does not state an IELTS score" in texts(at)


def test_review_shows_failures_and_the_per_visit_limit(service, example_records, ai_on, monkeypatch):
    sid = by_key(example_records, "vega-cs-masters")["id"]
    at = open_review(sid)
    monkeypatch.setattr(advisor, "_post", lambda s, p: FakeResponse(429, {}))
    ask_in_ui(at, sid, "Hi")
    assert "daily limit is used up" in texts(at) and "advisor_count" not in at.session_state
    at.session_state["advisor_count"] = 15
    at.run()
    ask_in_ui(at, sid, "One more?")
    assert "limit for the free service" in texts(at)
